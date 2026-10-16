#!/usr/bin/env python3
"""Fail closed on contract drift and missing cross-repository product wiring.

Default mode inventories all existing debt. --baseline-ref origin/main (used by
manual comparisons) reports only NEW wiring/orphan findings; Stop instead
uses immutable SessionStart SHAs via --baseline-file; contract and type freshness are
ALWAYS checked in full. This is static evidence, not a substitute for browser
or recovery drills. Only the repository's generated, block-style OpenAPI YAML
and literal/templated TS client conventions are supported; unsupported requests
are reported rather than guessed. No third-party Python packages are needed.
"""
import argparse
import ast
import copy
from dataclasses import dataclass
import io
import hashlib
import json
from functools import lru_cache
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile

# Exact normalized operations only. Never exempt /me/* or /admin/* wholesale.
# These routes are consumed by protocols, browser navigation or media elements,
# not JSON SPA requests. Every exemption states the external consumer.
BACKEND_ONLY_PATHS = {
    ('GET', '/healthz'): 'load balancer liveness',
    ('GET', '/readyz'): 'deployment readiness probe',
    ('GET', '/version'): 'operator version probe',
    ('GET', '/schemaz'): 'deployment migration-ledger probe',
    ('GET', '/api/v1/nodeinfo'): 'federation NodeInfo discovery',
    ('GET', '/api/v1/auth/oauth/{}'): 'top-level OIDC browser redirect',
    ('GET', '/api/v1/auth/oauth/{}/callback'): 'OIDC provider redirect target',
    ('GET', '/api/v1/auth/atproto/callback'): 'ATProto authorization redirect target',
    ('GET', '/api/v1/auth/atproto/client-metadata.json'): 'ATProto authorization-server metadata',
    ('POST', '/api/v1/live/ingest/start'): 'nginx-rtmp publisher authorization',
    ('POST', '/api/v1/live/ingest/stop'): 'nginx-rtmp publisher teardown',
    ('GET', '/api/v1/ipfs/gateway/authorize'): 'Caddy forward-auth subrequest',
}
# Media streams are fetched by the player/HTML elements after a JSON API request
# authorizes them; requiring a JSON wrapper for segment bytes would be wrong.
for _path in (
    '/api/v1/videos/{}/original', '/api/v1/videos/{}/webm',
    '/api/v1/videos/{}/download/audio', '/api/v1/videos/{}/download/hls/{}',
    '/api/v1/videos/{}/download/original', '/api/v1/videos/{}/download/subtitles/{}',
    '/api/v1/videos/{}/download/webm', '/api/v1/videos/{}/hls/master.m3u8',
    '/api/v1/videos/{}/hls/{}/index.m3u8', '/api/v1/videos/{}/hls/{}/{}',
    '/api/v1/live/{}/hls/master.m3u8', '/api/v1/live/{}/hls/{}',
):
    BACKEND_ONLY_PATHS[('GET', _path)] = 'HTML media element / HLS player / direct anchor byte transport'
for _path in (
    '/api/v1/channels/{}/avatar', '/api/v1/channels/{}/banner',
    '/api/v1/instance/avatar', '/api/v1/instance/banner', '/api/v1/instance/logo/{}',
    '/api/v1/remote-videos/{}/thumbnail', '/api/v1/users/{}/avatar',
    '/api/v1/users/{}/banner', '/api/v1/videos/{}/thumbnail',
    '/api/v1/videos/{}/storyboard.jpg', '/api/v1/videos/{}/storyboard.vtt',
    '/api/v1/instance/custom.css', '/api/v1/instance/custom.js',
):
    BACKEND_ONLY_PATHS[('GET', _path)] = 'HTML img/link/script or player preview asset request'


@dataclass(frozen=True)
class Finding:
    key: str
    message: str


@dataclass(frozen=True)
class Token:
    value: str
    string: bool = False


@lru_cache(maxsize=1024)
def tokens(source):
    """Lex strings/templates atomically, discarding comments (not quoted prose)."""
    pattern = r'''//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|=>|[^\s]'''
    return [Token(m[0][1:-1], True) if m[0][0] in '\'"`' else Token(m[0])
            for m in re.finditer(pattern, source)
            if not m[0].startswith(('//', '/*'))]


def normalize(path):
    path = re.sub(r'\$\{[^}]*\}', '{}', path)
    path = re.sub(r'\{[^}]*\}', '{}', path)
    return path.split('?', 1)[0].rstrip('/')


def groups(ts, start):
    """Return balanced argument/property groups and the closing token index."""
    closing = {'(': ')', '{': '}', '[': ']'}
    stack, parts, last = [closing[ts[start].value]], [], start + 1
    for i in range(start + 1, len(ts)):
        t = ts[i]
        if t.string:
            continue
        if t.value in closing:
            stack.append(closing[t.value])
        elif t.value in (')', '}', ']'):
            if not stack or t.value != stack.pop():
                raise ValueError('unbalanced TypeScript delimiter')
            if not stack:
                return parts + [ts[last:i]], i
        elif t.value == ',' and len(stack) == 1:
            parts.append(ts[last:i])
            last = i + 1
    raise ValueError('unterminated TypeScript expression')


def openapi_operations(yaml):
    """Use the generated spec's indentation contract; reject unparsed path keys."""
    operations, blocks, current, active = set(), {}, None, False
    for line in yaml.splitlines():
        if line == 'paths:':
            active = True
            continue
        if not active:
            continue
        if line and not line[0].isspace() and not line.startswith('#'):
            break
        match = re.match(r'^  (/\S+):\s*$', line)
        if match:
            current = match[1]
            blocks[current] = []
        elif re.match(r'^  \S', line) and not line.lstrip().startswith('#'):
            raise ValueError(f'unsupported OpenAPI path syntax: {line}')
        elif current:
            blocks[current].append(line)
            verb = re.match(r'^    (get|post|put|patch|delete|head|options):\s*$', line)
            if verb:
                operations.add((verb[1].upper(), normalize(current)))
    if not operations:
        raise ValueError('no OpenAPI operations found')
    return operations, {p: '\n'.join(b) for p, b in blocks.items()}


def oauth_findings(blocks, source):
    codes = set()
    for path in ('/api/v1/auth/oauth/{provider}/callback', '/api/v1/auth/atproto/callback'):
        if path not in blocks:
            raise ValueError(f'missing callback contract {path}')
        # Backtick identifiers in these two callback descriptions are stable
        # errors, except the documented success/cookie/parameter names below.
        for quoted in re.findall(r'`([^`]+)`', blocks[path]):
            if re.fullmatch(r'[a-z]+(?:_[a-z]+)+', quoted):
                if quoted not in {'return_to', 'id_token', 'vidra_refresh', 'vidra_mfa_pending',
                                  'vidra_atproto_state', 'link_error', 'oauth_error'}:
                    codes.add(quoted)
            codes.update(re.findall(r'(?:oauth_error|link_error)=([a-z][a-z_]+)', quoted))
    ts = tokens(source)
    for i in range(len(ts) - 2):
        if ts[i].value == 'function' and ts[i + 1].value == 'oauthErrorMessage':
            _, end = groups(ts, i + 2)
            start = next(j for j in range(end + 1, len(ts)) if ts[j].value == '{')
            _, end = groups(ts, start)
            ts = ts[start:end + 1]
            break
    else:
        ts = []
    cases = {ts[i + 1].value for i, t in enumerate(ts[:-2])
             if t.value == 'case' and ts[i + 1].string and ts[i + 2].value == ':'}
    return [Finding(f'oauth:{c}', f'OAuthButtons.oauthErrorMessage lacks case "{c}"')
            for c in sorted(codes - cases)]


def is_source(name):
    return name.endswith(('.ts', '.tsx', '.js', '.jsx', '.mjs')) and not re.search(
        r'(?:\.test\.|\.spec\.|(?:^|/)(?:__tests__|__mocks__)/)', name)


def sources(repo, ref=None):
    if ref:
        # Read only tracked content at the explicit baseline, without checking
        # out files or mutating a sibling working tree.
        data = subprocess.run(['git', '-C', str(repo), 'archive', ref, 'app', 'components', 'lib'],
                              check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            return {m.name: archive.extractfile(m).read().decode() for m in archive.getmembers()
                    if m.isfile() and is_source(m.name)}
    return {p.relative_to(repo).as_posix(): p.read_text() for d in ('app', 'components', 'lib')
            for p in sorted((repo / d).rglob('*')) if p.is_file() and is_source(p.relative_to(repo).as_posix())}


def resolve_import(file, module, files):
    if module.startswith('@/'):
        path = module[2:]
    elif module.startswith('.'):
        path = os.path.normpath(str(PurePosixPath(file).parent / module))
    else:
        return None
    return next((p for p in [path, *(path + e for e in ('.ts', '.tsx', '.js', '.jsx')),
                            *(path + '/index' + e for e in ('.ts', '.tsx', '.js'))] if p in files), None)


def imports(ts):
    """Real import/export module edges, including dynamic import; skip type-only."""
    result = []
    for i, t in enumerate(ts[:-1]):
        if t.string or t.value not in ('import', 'export') or ts[i + 1].value == 'type':
            continue
        if t.value == 'import' and ts[i + 1].value == '(':
            if i + 2 < len(ts) and ts[i + 2].string:
                result.append((ts[i + 2].value, []))
            continue
        for j in range(i + 1, len(ts)):
            if ts[j].value == ';':
                break
            if ts[j].string and (j == i + 1 or ts[j - 1].value == 'from'):
                result.append((ts[j].value, ts[i + 1:j - 1]))
                break
    return result


def mounted_sources(files):
    graph = {f: {r for module, _ in imports(tokens(s))
                 if (r := resolve_import(f, module, files))} for f, s in files.items()}
    reachable, queue = set(), [f for f in files if f.startswith('app/')]
    while queue:
        f = queue.pop()
        if f not in reachable:
            reachable.add(f)
            queue.extend(graph[f] - reachable)
    return reachable


def template(value, bindings):
    def substitute(match):
        expression = match[1].strip()
        return bindings.get(expression, '{}')
    return re.sub(r'\$\{([^}]*)\}', substitute, value)


def expression_path(ts, bindings):
    if not ts:
        return None
    if ts[0].string:
        value = template(ts[0].value, bindings)
    elif ts[0].value in bindings:
        value = bindings[ts[0].value]
        if len(ts) > 1 and ts[1].value == '(':
            # one(id) helper: its template was resolved with a placeholder.
            value = template(value, bindings)
    else:
        return None
    hit = re.search(r'/api/v1/[^\s\'"`]*', value)
    return normalize(hit[0]) if hit else None


def request_calls(ts, bindings=None):
    bindings = dict(bindings or {})
    # Local URL aliases (also the watched-word factory's one(id) template).
    for i in range(len(ts) - 3):
        if ts[i].value == 'const' and ts[i + 2].value == '=':
            name = ts[i + 1].value
            for j in range(i + 3, len(ts)):
                if ts[j].value == ';':
                    break
                if ts[j].string:
                    bindings[name] = template(ts[j].value, bindings)
                    break
    calls = []
    for i, t in enumerate(ts):
        if t.string or t.value not in ('apiRequest', 'fetch', 'uploadWithProgress', 'doRequest', 'serverJson', 'subscribeEventStream'):
            continue
        j = i + 1
        if j < len(ts) and ts[j].value == '<':
            depth = 1
            j += 1
            while j < len(ts) and depth:
                if ts[j].value == '<':
                    depth += 1
                elif ts[j].value == '>':
                    depth -= 1
                j += 1
        if j >= len(ts) or ts[j].value != '(':
            continue
        args, _ = groups(ts, j)
        path = expression_path(args[0], bindings)
        method = 'POST' if t.value == 'uploadWithProgress' else 'GET'
        options = args[1] if len(args) > 1 else []
        for k in range(len(options) - 2):
            if options[k].value == 'method' and options[k + 1].value == ':':
                method = options[k + 2].value.upper() if options[k + 2].string else None
        if path and method:
            calls.append((method, path))
    return calls


def wrappers(files):
    """Map exact method/path to (module, export, member) wrapper identities."""
    result = {}
    for file, source in files.items():
        if not file.startswith('lib/api/') or file.endswith(('generated.ts', 'types.ts')):
            continue
        ts = tokens(source)
        global_bindings = {}
        for k in range(len(ts) - 3):
            if ts[k].value == 'const' and ts[k + 2].value == '=' and ts[k + 3].string:
                global_bindings[ts[k + 1].value] = template(ts[k + 3].value, global_bindings)
        for k in range(len(ts) - 3):
            if ts[k].value != 'function' or ts[k + 1].string:
                continue
            name = ts[k + 1].value
            j = k + 2
            while j < len(ts) and ts[j].value != '(':
                j += 1
            if j == len(ts):
                continue
            _, end = groups(ts, j)
            depth, body_start = 0, None
            for q in range(end + 1, len(ts)):
                if ts[q].value == '<':
                    depth += 1
                elif ts[q].value == '>':
                    depth -= 1
                elif ts[q].value == '{' and depth == 0:
                    body_start = q
                    break
                elif ts[q].value == ';' and depth == 0:
                    break
            if body_start is not None and any(t.value == 'export' for t in ts[max(0, k - 2):k]):
                _, body_end = groups(ts, body_start)
                for op in request_calls(ts[body_start:body_end + 1], global_bindings):
                    result.setdefault(op, []).append((file, name, None))
        for i in range(len(ts) - 4):
            if [t.value for t in ts[i:i + 2]] != ['export', 'const']:
                continue
            name = ts[i + 2].value
            if ts[i + 3].value != '=':
                continue
            start = i + 4
            if ts[start].value == '{':
                members, _ = groups(ts, start)
                for member in members:
                    if len(member) > 2 and member[1].value == ':':
                        for op in request_calls(member[2:]):
                            result.setdefault(op, []).append((file, name, member[0].value))
            elif start + 1 < len(ts) and ts[start + 1].value == '(':
                # Resolve exported instances of a local endpoint factory.
                args, _ = groups(ts, start + 1)
                if not args or not args[0] or not args[0][0].string:
                    continue
                factory = ts[start].value
                for k in range(len(ts) - 4):
                    if ts[k].value == 'function' and ts[k + 1].value == factory:
                        params, end = groups(ts, k + 2)
                        body_start = end + 1
                        if ts[body_start].value != '{':
                            continue
                        body, _ = groups(ts, body_start)
                        body_ts = [t for group in body for t in group]
                        base = {params[0][0].value: args[0][0].value}
                        # The factory returns an object; retain per-member identity.
                        for q in range(len(body_ts) - 1):
                            if body_ts[q].value == 'return' and body_ts[q + 1].value == '{':
                                members, _ = groups(body_ts, q + 1)
                                aliases = dict(base)
                                for z in range(q - 3):
                                    if body_ts[z].value == 'const' and body_ts[z + 2].value == '=':
                                        for a in body_ts[z + 3:q]:
                                            if a.string:
                                                aliases[body_ts[z + 1].value] = template(a.value, base)
                                                break
                                for member in members:
                                    if len(member) > 2 and member[1].value == ':':
                                        for op in request_calls(member[2:], aliases):
                                            result.setdefault(op, []).append((file, name, member[0].value))
    return result


def imported_origins(module, name, files, seen=None):
    """Follow named barrel re-exports without treating unused exports as callers."""
    seen = set(seen or ())
    if (module, name) in seen:
        return set()
    seen.add((module, name))
    origins = {(module, name)}
    for specifier, binding in imports(tokens(files[module])):
        target = resolve_import(module, specifier, files)
        if target is None:
            continue
        names = [t.value for t in binding]
        if name in names or '*' in names:
            original = names[names.index(name) - 2] if name in names and names[names.index(name) - 1:names.index(name)] == ['as'] else name
            origins.update(imported_origins(target, original, files, seen))
    return origins


def consumed_wrappers(files, reachable):
    consumed = set()
    for file in sorted(reachable):
        ts = tokens(files[file])
        symbols = {}
        for specifier, binding in imports(ts):
            module = resolve_import(file, specifier, files)
            if module is None:
                continue
            names = [t.value for t in binding]
            for i, name in enumerate(names):
                if not re.fullmatch(r'[A-Za-z_$][\w$]*', name) or name in ('as', 'type'):
                    continue
                if i and names[i - 1] == 'as':
                    continue
                local = names[i + 2] if names[i + 1:i + 2] == ['as'] else name
                symbols[local] = imported_origins(module, name, files)
        # Resolve local const aliases and shared scope dispatch tables. Import
        # presence alone is never sufficient: an actual member access is needed.
        for _ in range(3):
            for i in range(len(ts) - 3):
                if ts[i].value != 'const' or ts[i + 2].value != '=':
                    continue
                end = next((j for j in range(i + 3, len(ts)) if ts[j].value == ';'), len(ts))
                origins = set().union(*(symbols.get(t.value, set()) for t in ts[i + 3:end] if not t.string))
                if origins:
                    symbols[ts[i + 1].value] = origins
        for i in range(len(ts) - 2):
            if ts[i].string or ts[i].value not in symbols:
                continue
            if ts[i + 1].value == '.' and not ts[i + 2].string:
                for module, export in symbols[ts[i].value]:
                    consumed.add((module, export, ts[i + 2].value))
            elif ts[i + 1].value == '(':
                for module, export in symbols[ts[i].value]:
                    consumed.add((module, export, None))
    return consumed


def static_findings(yaml, files):
    operations, blocks = openapi_operations(yaml)
    reachable = mounted_sources(files)
    findings = oauth_findings(blocks, files.get('components/auth/OAuthButtons.tsx', ''))
    for file in sorted(files):
        if file.startswith('components/') and file.endswith('.tsx') and file not in reachable:
            findings.append(Finding(f'orphan:{file}', f'unmounted React component: {file}'))
    clients = wrappers(files)
    consumed = consumed_wrappers(files, reachable)
    for method, path in sorted(operations):
        if not path.startswith('/api/v1/') or (method, path) in BACKEND_ONLY_PATHS:
            continue
        identities = clients.get((method, path), [])
        if not any(w in consumed for w in identities):
            reason = 'no statically resolved client wrapper' if not identities else 'wrapper has no mounted consumer'
            findings.append(Finding(f'endpoint:{method}:{path}', f'{method} {path}: {reason}'))
    return findings


def migration_findings(core, catalogue):
    tree = ast.parse(catalogue.read_text())
    values = {}
    class Constants(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in values and isinstance(values[node.id], (int, str)):
                return ast.copy_location(ast.Constant(values[node.id]), node)
            return node
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(Constants().visit(copy.deepcopy(node.value)))
            except (ValueError, TypeError):
                pass
    added = values['TABLES_ADDED']
    ceiling = values.get('CATALOGUE_AUDITED_THROUGH', max(added))
    classified = values['CATALOGUE'] | values['EXCLUDED_TABLES']
    problems = []
    for migration in sorted((core / 'migrations').glob('*.up.sql')):
        version = int(migration.name.split('_', 1)[0])
        if version > ceiling or version not in added and version >= values.get('CATALOGUE_AUDIT_FLOOR', min(added)):
            problems.append(f'{migration.name}: schema {version} exceeds or has a gap in recovery audit {ceiling}')
            continue
        if version in added:
            sql = re.sub(r'--[^\n]*|/\*[\s\S]*?\*/', '', migration.read_text())
            created = set(re.findall(r'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?"?([a-z_][a-z_0-9]*)', sql, re.I))
            if created != set(added[version]):
                problems.append(f'{migration.name}: CREATE TABLE inventory differs from TABLES_ADDED')
            for table in sorted(created - classified.keys()):
                problems.append(f'{migration.name}: {table} is absent from CATALOGUE / EXCLUDED_TABLES')
    if not list((core / 'migrations').glob('*.up.sql')):
        raise ValueError('no core migrations found')
    return problems


def contract_findings(core, user):
    env = os.environ | {'OPENAPI_PATH': str((core / 'api/openapi.yaml').resolve())}
    problems = []
    result = subprocess.run(['node', 'scripts/check-contract.mjs'], cwd=user, env=env,
                            text=True, capture_output=True, timeout=120)
    if result.returncode:
        problems.append('frontend path/verb contract failed:\n' + result.stdout + result.stderr)
    generator = user / 'node_modules/.bin/openapi-typescript'
    if not generator.is_file():
        problems.append('type freshness unavailable: run npm ci in vidra-user (pinned openapi-typescript required)')
    else:
        with tempfile.TemporaryDirectory(prefix='vidra-contract-') as tmp:
            out = Path(tmp) / 'generated.ts'
            result = subprocess.run([str(generator), env['OPENAPI_PATH'], '-o', str(out)], cwd=user,
                                    text=True, capture_output=True, timeout=120)
            if result.returncode:
                problems.append('API type generation failed:\n' + result.stdout + result.stderr)
            elif out.read_bytes() != (user / 'lib/api/generated.ts').read_bytes():
                problems.append('lib/api/generated.ts is stale; run OPENAPI_PATH=<core>/api/openapi.yaml npm run codegen in vidra-user')
    return problems


def component_repo(root, name, explicit=None):
    explicit = explicit or os.environ.get('VIDRA_' + name.removeprefix('vidra-').upper() + '_ROOT')
    if explicit:
        return Path(explicit).resolve()
    for path in (root / name, root.parent / name):
        if (path / '.git').exists():
            return path
    raise ValueError(f'{name} not found; use --{name.removeprefix("vidra-")}-root for a separate worktree')


def record_session_baseline(root):
    """Immutable per-session refs; restarting/resuming must not forgive new debt."""
    payload = json.load(sys.stdin)
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        raise ValueError('SessionStart requires session_id; no baseline recorded')
    key = hashlib.sha256(session.encode()).hexdigest()
    directory = root / '.claude/hooks/.state'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (key + '.baseline.json')
    if path.exists():
        return 0
    repos = {}
    for name in ('core', 'user'):
        repo = component_repo(root, 'vidra-' + name)
        sha = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                             check=True, capture_output=True, text=True).stdout.strip()
        repos[name] = {'path': str(repo.resolve()), 'sha': sha}
    # Exclusive create avoids overwriting a baseline when SessionStart fires on
    # resume/compact, or two launch events race in one session.
    try:
        with path.open('x') as out:
            json.dump({'schema_version': 1, 'repos': repos}, out)
    except FileExistsError:
        pass
    return 0


def baseline_refs(path, core, user):
    document = json.loads(path.read_text())
    if document.get('schema_version') != 1:
        raise ValueError('unsupported session baseline version')
    refs = []
    for name, repo in (('core', core), ('user', user)):
        entry = document['repos'][name]
        if Path(entry['path']).resolve() != repo.resolve() or not re.fullmatch(r'[0-9a-f]{40}', entry['sha']):
            raise ValueError(f'session baseline does not identify this {name} checkout')
        refs.append(entry['sha'])
    return refs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--core-root', type=Path)
    parser.add_argument('--user-root', type=Path)
    parser.add_argument('--strict-migrations', action='store_true')
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument('--baseline-ref', help='manual comparison ref; Stop uses immutable session SHAs instead')
    baseline.add_argument('--baseline-file', type=Path, help='SessionStart snapshot; never advances when PRs merge')
    parser.add_argument('--record-session-baseline', action='store_true', help='SessionStart: read hook JSON on stdin and record immutable refs')
    args = parser.parse_args(argv)
    try:
        if args.record_session_baseline:
            return record_session_baseline(args.root)
        core = component_repo(args.root, 'vidra-core', args.core_root)
        user = component_repo(args.root, 'vidra-user', args.user_root)
        yaml = (core / 'api/openapi.yaml').read_text()
        findings = static_findings(yaml, sources(user))
        if args.baseline_ref or args.baseline_file:
            core_ref, user_ref = baseline_refs(args.baseline_file, core, user) if args.baseline_file else (args.baseline_ref, args.baseline_ref)
            old_yaml = subprocess.run(['git', '-C', str(core), 'show', f'{core_ref}:api/openapi.yaml'],
                                      capture_output=True, text=True, check=True).stdout
            old = {f.key for f in static_findings(old_yaml, sources(user, user_ref))}
            count = len(findings)
            findings = [f for f in findings if f.key not in old]
            print(f'BASELINE {args.baseline_file or args.baseline_ref}: {count - len(findings)} existing static findings remain; full inventory requires no baseline option')
        errors = [f.message for f in findings] + contract_findings(core, user)
        migrations = migration_findings(core, args.root / 'tests/recovery_release_acceptance.py')
        if args.strict_migrations:
            errors.extend(migrations)
        else:
            for message in migrations:
                print('WARN migration: ' + message)
        for message in errors:
            print('FAIL ' + message)
        print(f'vertical-slice: {len(errors)} failure(s), {len(migrations)} migration finding(s)')
        return bool(errors)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'FAIL completeness gate could not verify: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
