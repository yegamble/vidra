#!/usr/bin/env python3
"""Freeze an existing release and prove its source/image/asset/contract boundary.

Read-only network operations; writes only a NEW output directory. Requires git,
gh authentication, Docker buildx, Node >=24 and npm. Does not boot images.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile


REPOS = ('vidra', 'vidra-core', 'vidra-user', 'vidra-search')

# Platform release records name components by ROLE; this script works in
# repository names. The meta repository is the release itself, so it is never
# in a record's components and is always frozen at --tag.
RECORD_COMPONENT = {'vidra-core': 'core', 'vidra-user': 'user', 'vidra-search': 'search'}
RELEASE_TAG = re.compile(r'v([0-9]+)\.([0-9]+)\.([0-9]+)')
RELEASES = Path(__file__).resolve().parent.parent / 'releases'


def release_order(tag, what='tag'):
    """(major, minor, patch), so v0.7.10 is correctly NEWER than v0.7.9. A
    lexical comparison inverts that and would wave through a component built
    from a later release than the one being frozen."""
    match = RELEASE_TAG.fullmatch(tag or '')
    if not match:
        raise ValueError(f'{what}: expected a vX.Y.Z release tag, got {tag!r}')
    return tuple(int(part) for part in match.groups())


def parse_component_tags(values):
    """`--component-tag <repo>=<tag>`, repeatable, as {repo: tag}.

    WHY IT EXISTS. A core-only release (v0.7.4, v0.7.5) pairs vidra-user and
    vidra-search at an OLDER tag, and the record that says so lands in the same
    PR as this preflight's own evidence. This flag covers that window; once the
    record is on the tree it is redundant.
    """
    overrides = {}
    for value in values or ():
        repo, sep, tag = value.partition('=')
        if not sep or repo not in RECORD_COMPONENT:
            raise ValueError(f'--component-tag {value!r}: expected <repo>=<tag> where repo is '
                             f'one of {", ".join(sorted(RECORD_COMPONENT))}')
        release_order(tag, f'--component-tag {repo}')
        if overrides.setdefault(repo, tag) != tag:
            raise ValueError(f'--component-tag names {repo} twice, as {overrides[repo]} and '
                             f'{tag}; one of them is wrong and guessing which is not this '
                             'script\'s job')
    return overrides


def record_component_tags(releases, tag):
    """Component tags from releases/<tag>.json, or {} when no record exists.

    A record that exists but cannot be read is NOT treated as absent: falling
    back to a uniform tag there would freeze the wrong bytes for exactly the
    releases this lookup exists to serve.
    """
    path = Path(releases) / f'{tag}.json'
    if not path.is_file():
        return {}
    try:
        components = json.loads(path.read_text())['components']
        return {repo: components[name]['tag'] for repo, name in RECORD_COMPONENT.items()
                if name in components}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'releases/{path.name}: unusable release record ({error})') from None


def resolve_component_tags(tag, overrides, releases=RELEASES):
    """({repo: tag}, {repo: where it came from}, [warnings]) for every REPO.

    Precedence: an explicit --component-tag, then the platform release record,
    then --tag for everything (byte-for-byte the behaviour before records were
    consulted). Raises ValueError on anything nonsensical, and the caller runs
    this BEFORE the first clone so no network or output directory is touched.
    """
    release_order(tag, '--tag')
    recorded = record_component_tags(releases, tag)
    tags, sources, warnings = {}, {}, []
    for repo in REPOS:
        if repo in overrides:
            tags[repo] = overrides[repo]
            sources[repo] = '--component-tag'
            if repo in recorded and recorded[repo] != overrides[repo]:
                # The operator may be correcting a bad record, so the flag wins
                # -- but never quietly: the wrong choice freezes the wrong bytes.
                sources[repo] = (f'--component-tag (overrides releases/{tag}.json '
                                 f'{recorded[repo]})')
                warnings.append(
                    f'--component-tag {repo}={overrides[repo]} contradicts '
                    f'releases/{tag}.json, which pairs {repo} at {recorded[repo]}. '
                    f'Freezing {overrides[repo]} because the flag wins; if the record is '
                    'right, this candidate is not the release.')
        elif repo in recorded:
            tags[repo] = recorded[repo]
            sources[repo] = f'releases/{tag}.json'
        else:
            tags[repo] = tag
            sources[repo] = '--tag'
        if release_order(tags[repo], repo) > release_order(tag):
            raise ValueError(f'{repo}: {tags[repo]} is newer than the release {tag} being '
                             f'frozen ({sources[repo]}); a release cannot contain a component '
                             'built after it')
    return tags, sources, warnings


def image_pin(data, repo, revision, platform):
    digest = data['manifest']['digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('registry did not return an immutable digest')
    images = data['image']
    image = images if 'os' in images else images.get(platform, {})
    if f"{image.get('os')}/{image.get('architecture')}" != platform:
        raise ValueError(f'{repo}: image lacks {platform}')
    labels = image.get('config', {}).get('Labels', {})
    if labels.get('org.opencontainers.image.revision') != revision:
        raise ValueError(f'{repo}: image revision does not match frozen source {revision}')
    if labels.get('org.opencontainers.image.source') != f'https://github.com/{repo}':
        raise ValueError(f'{repo}: image source label does not match repository')
    return {'digest': digest, 'reference': f'ghcr.io/{repo}@{digest}',
            'platform': platform, 'revision': revision}


def verify_checksum(path, sums):
    entries = [line.split() for line in sums.splitlines()]
    matches = [entry[0] for entry in entries if len(entry) == 2 and entry[1] == path.name]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if matches != [actual]:
        raise ValueError(f'{path.name}: missing, duplicate or mismatched SHA256SUMS entry')
    return actual


def without_resolver(spec):
    result, count = re.subn(r'^  /api/v1/videos/resolve:\n.*?(?=^  /|^\S|\Z)', '', spec,
                            flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise ValueError('expected exactly one resolver path')
    return result


def asset_names(tag, platform):
    return [f'vidra-bundle_{tag}.tar.gz', f'vidra_{tag}_{platform.replace("/", "_")}']


def run(args, cwd=None, env=None, expected=0):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=900)
    print(f'$ {" ".join(map(str, args))}\n{result.stdout}', flush=True)
    if result.returncode != expected:
        raise RuntimeError(f'{args[0]} exited {result.returncode}; expected {expected}')
    return result.stdout


def freeze(args, out, manifest):
    node = run(['node', '--version']).strip()
    if int(node.lstrip('v').split('.')[0]) < 24:
        raise ValueError('Node >=24 is required; unsupported toolchains cannot certify the candidate')
    manifest['tools'] = {'node': node, 'npm': run(['npm', '--version']).strip(),
                         'buildx': run(['docker', 'buildx', 'version']).strip()}
    source = out / 'source'
    source.mkdir()
    for repo in REPOS:
        # Not every component moves in every release: a core-only release pairs
        # the others at an older tag, and cloning those at --tag finds no ref.
        component_tag = args.component_tags[repo]
        remote = f'https://github.com/{args.owner}/{repo}.git'
        dest = source / repo
        # A private detached checkout avoids moving operator release pins or
        # silently reading ignored/uncommitted files from nested workspaces.
        run(['git', 'clone', '--quiet', '--depth', '1', '--branch', component_tag, remote, str(dest)])
        revision = run(['git', 'rev-parse', '--verify', f'refs/tags/{component_tag}^{{commit}}'], cwd=dest).strip()
        run(['git', 'checkout', '--quiet', '--detach', revision], cwd=dest)
        manifest['repositories'][repo] = {'remote': remote, 'tag': component_tag,
                                          'tag_source': args.component_tag_sources[repo],
                                          'revision': revision}
        save(out, manifest)
    for repo in REPOS[1:]:
        name = f'{args.owner}/{repo}'
        # The image must be the one THIS component's tag published, or the
        # digest would belong to bytes the frozen source never built.
        tagged = f'ghcr.io/{name}:{manifest["repositories"][repo]["tag"]}'
        resolved = json.loads(run(['docker', 'buildx', 'imagetools', 'inspect', tagged,
                                   '--format', '{{json .}}']))
        digest = resolved['manifest']['digest']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError(f'{repo}: invalid registry digest')
        # Inspect again BY DIGEST: a mutable tag must not supply provenance for
        # bytes different from those the next acceptance will actually pull.
        pinned = json.loads(run(['docker', 'buildx', 'imagetools', 'inspect',
                                 f'ghcr.io/{name}@{digest}', '--format', '{{json .}}']))
        manifest['images'][repo] = image_pin(pinned, name,
            manifest['repositories'][repo]['revision'], args.platform)
        if manifest['images'][repo]['digest'] != digest:
            raise ValueError(f'{repo}: registry returned a different digest')
        save(out, manifest)

    assets = out / 'assets'
    assets.mkdir()
    release = json.loads(run(['gh', 'release', 'view', args.tag, '-R', f'{args.owner}/vidra-core',
                              '--json', 'assets,tagName,isDraft,isPrerelease,url']))
    if release['isDraft'] or release['isPrerelease'] or release['tagName'] != args.tag:
        raise ValueError('candidate must be an existing stable release')
    names = ['SHA256SUMS'] + asset_names(args.tag, args.platform)
    for name in names:
        metadata = [a for a in release['assets'] if a['name'] == name]
        if len(metadata) != 1:
            raise ValueError(f'missing or duplicate release asset: {name}')
        run(['gh', 'release', 'download', args.tag, '-R', f'{args.owner}/vidra-core',
             '--pattern', name, '--dir', str(assets)])
        manifest['assets'][name] = {'url': metadata[0]['url'],
            'sha256': hashlib.sha256((assets / name).read_bytes()).hexdigest()}
    sums = (assets / 'SHA256SUMS').read_text()
    for name in names[1:]:
        verify_checksum(assets / name, sums)
    # Read just the manifest, never extract or execute the downloaded bundle.
    with tarfile.open(assets / names[1]) as archive:
        members = [m for m in archive.getmembers() if m.name.removeprefix('./') == 'vidra-bundle.manifest']
        if len(members) != 1 or not members[0].isfile():
            raise ValueError('bundle must contain one regular provenance manifest')
        provenance = archive.extractfile(members[0]).read().decode()
    (out / 'bundle-provenance.txt').write_text(provenance)
    for key, repo in [('meta_commit', 'vidra'), ('core_commit', 'vidra-core')]:
        if not re.search(rf'^{key}={manifest["repositories"][repo]["revision"]}$', provenance, re.MULTILINE):
            raise ValueError(f'bundle {key} does not match frozen source')
    manifest['checks']['assets'] = 'PASS'
    save(out, manifest)

    user = source / 'vidra-user'
    spec = source / 'vidra-core/api/openapi.yaml'
    env = dict(os.environ, OPENAPI_PATH=str(spec))
    run(['node', 'scripts/check-contract.mjs'], cwd=user, env=env)
    manifest['checks']['paths'] = 'PASS'
    # Install exactly the frozen lockfile, without project lifecycle scripts.
    run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=user)
    before = (user / 'lib/api/generated.ts').read_bytes()
    run(['node', 'scripts/codegen.mjs'], cwd=user, env=env)
    if before != (user / 'lib/api/generated.ts').read_bytes():
        raise ValueError('generated API types drift from frozen core spec')
    manifest['checks']['generated_types'] = 'PASS'

    regression = out / 'resolver-regression'
    (regression / 'scripts').mkdir(parents=True)
    (regression / 'lib/api').mkdir(parents=True)
    shutil.copyfile(user / 'scripts/check-contract.mjs', regression / 'scripts/check-contract.mjs')
    (regression / 'lib/api/probe.ts').write_text('apiRequest("/api/v1/videos/resolve");\n')
    yaml = spec.read_text()
    (regression / 'old-core.yaml').write_text(without_resolver(yaml) if '  /api/v1/videos/resolve:\n' in yaml else yaml)
    (regression / 'compatible.yaml').write_text('paths:\n  /api/v1/videos/resolve:\n    get:\n      responses: {}\n')
    run(['node', 'scripts/check-contract.mjs'], cwd=regression,
        env=dict(os.environ, OPENAPI_PATH=str(regression / 'compatible.yaml')))
    rejected = run(['node', 'scripts/check-contract.mjs'], cwd=regression,
                   env=dict(os.environ, OPENAPI_PATH=str(regression / 'old-core.yaml')), expected=1)
    if '/api/v1/videos/resolve' not in rejected or 'do NOT exist' not in rejected:
        raise ValueError('skew regression did not fail for the missing resolver')
    manifest['checks']['resolver_skew_rejected'] = 'PASS'


def save(out, manifest):
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--owner', default='yegamble')
    parser.add_argument('--platform', choices=['linux/amd64', 'linux/arm64'], default='linux/amd64')
    parser.add_argument('--out', required=True, type=Path, help='new disposable directory (must not exist)')
    parser.add_argument('--component-tag', action='append', metavar='REPO=TAG', default=[],
                        help='freeze one component at its own tag, for a release whose '
                             'releases/<tag>.json has not landed yet (repeatable)')
    args = parser.parse_args()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.tag) or not re.fullmatch(r'[A-Za-z0-9-]+', args.owner):
        parser.error('expected vX.Y.Z tag and GitHub owner name')
    # Resolved BEFORE the output directory exists: a nonsensical pairing must
    # cost nothing, not half an evidence tree and a cloned repository.
    try:
        args.component_tags, args.component_tag_sources, warnings = resolve_component_tags(
            args.tag, parse_component_tags(args.component_tag))
    except ValueError as error:
        parser.error(str(error))
    for warning in warnings:
        print(f'[preflight] WARNING: {warning}', file=sys.stderr, flush=True)
    for repo in REPOS:
        print(f'[preflight] {repo}: {args.component_tags[repo]} '
              f'(from {args.component_tag_sources[repo]})', flush=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version': 1, 'status': 'UNVERIFIED', 'tag': args.tag, 'platform': args.platform,
                'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'repositories': {}, 'images': {}, 'assets': {}, 'checks': {},
                'verifier_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    save(out, manifest)
    try:
        freeze(args, out, manifest)
        manifest['status'] = 'PASS'
    except (ValueError, RuntimeError, OSError, KeyError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        manifest['status'] = 'FAIL'
        manifest['error'] = str(error)
        print(f'[preflight] ERROR: {error}', file=sys.stderr)
    finally:
        save(out, manifest)
    return 0 if manifest['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
