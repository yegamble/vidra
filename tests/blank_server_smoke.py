#!/usr/bin/env python3
"""A02 guest assertions. Invoke through blank-server-smoke.sh, never on an operator host."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


REPOS = ('vidra', 'vidra-core', 'vidra-user', 'vidra-search')
# The repositories that ship an image. A release must move at least one of them.
COMPONENTS = ('vidra-core', 'vidra-user', 'vidra-search')
COMPONENT_TAG_KEYS = {'vidra-core': 'VIDRA_CORE_TAG', 'vidra-user': 'VIDRA_USER_TAG',
                      'vidra-search': 'VIDRA_SEARCH_TAG'}
# ASCII digits with no leading zeros: 'v0.07.3' is not the release v0.7.3, and
# unicode \d would admit 'v٦.٥.٤', which names no tag, asset or image anywhere.
RELEASE_TAG = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def release_version(tag):
    """(major, minor, patch) of a strict vX.Y.Z tag; None when it is not one.

    Ordering release tags as STRINGS is wrong in both directions — 'v0.7.10'
    sorts below 'v0.7.9' — so every comparison here goes through these tuples.
    The shape admitted is exactly the shape the release tag itself must have:
    no prerelease or build suffix is a release in this repo.
    """
    match = RELEASE_TAG.fullmatch(tag) if isinstance(tag, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def expected_image(candidate, repo):
    """The image reference the Compose render must pin for `repo`.

    A core-only release ships vidra-core at the release tag while vidra-user and
    vidra-search stay at the older tag they were last cut at, so the pin is the
    COMPONENT's tag. Asserting the release tag for all three passes happily on
    `ghcr.io/yegamble/vidra-user:v0.7.5` — an image that was never published —
    and the digest pulls below cannot contradict it, because they pull by
    digest. That reads as evidence of a deployable pin and is not.
    """
    return f'ghcr.io/yegamble/{repo}:{candidate["repositories"][repo]["tag"]}'


def pin_component_tags(text, candidate):
    """Rewrite the three image tags in an env file to the candidate's own.

    `vidra setup --release-tag` writes ONE tag for all three services, which is
    correct only for a release that moved all three. Each substitution is
    asserted: a renamed or duplicated key fails here rather than silently
    leaving the wrong pin in a render this lane then certifies.
    """
    for repo, key in COMPONENT_TAG_KEYS.items():
        tag = candidate['repositories'][repo]['tag']
        text, count = re.subn(f'(?m)^{key}=.*$', f'{key}={tag}', text)
        require(count == 1, f'{key}: expected exactly one assignment, found {count}')
    return text


def validate_candidate(candidate):
    require(candidate.get('schema_version') == 1 and candidate.get('status') == 'PASS', 'requires PASS A01 manifest')
    tag = candidate.get('tag', '')
    release = release_version(tag)
    require(release is not None, 'invalid release tag')
    for name in ('assets', 'paths', 'generated_types', 'resolver_skew_rejected'):
        require(candidate.get('checks', {}).get(name) == 'PASS', f'A01 {name} not verified')
    # A core-only release (v0.7.4, v0.7.5) pins vidra-user and vidra-search at
    # the older tag they were last cut at, so demanding tag == release tag
    # refused a legitimate manifest and gated every runtime, B2, migration and
    # recovery lane on it. The structural rule that replaces it still refuses
    # nonsense: a tag that is not a release tag at all, a component AHEAD of the
    # release that claims to contain it, and (below) a release nothing shipped
    # in. Image and revision stay bound to the source by the checks that follow.
    shipped = []
    for repo in REPOS:
        source = candidate.get('repositories', {}).get(repo, {})
        # isinstance first: a null or numeric field is a malformed manifest, and
        # must read as a named refusal, not as a TypeError out of re.fullmatch.
        revision = source.get('revision')
        require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision), f'{repo}: missing commit')
        require(source.get('remote') == f'https://github.com/yegamble/{repo}.git', f'{repo}: unexpected source remote')
        component = release_version(source.get('tag'))
        require(component is not None,
                f'{repo}: tag {source.get("tag")!r} is not a release tag (release {tag})')
        require(component <= release, f'{repo}: tag {source["tag"]} is newer than release {tag}')
        if repo == 'vidra':
            # Meta is never a carry-over: the bundle is built from meta AT the
            # release tag, so only the image-bearing components may lag.
            require(source['tag'] == tag, f'vidra: tag {source["tag"]} is not the release tag {tag}')
            continue
        if source['tag'] == tag:
            shipped.append(repo)
        image = candidate.get('images', {}).get(repo, {})
        digest = image.get('digest', '')
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', digest), f'{repo}: missing digest')
        require(image.get('reference') == f'ghcr.io/yegamble/{repo}@{digest}', f'{repo}: mutable image reference')
        require(image.get('revision') == source['revision'], f'{repo}: image/source mismatch')
        require(image.get('platform') == candidate.get('platform') in ('linux/amd64', 'linux/arm64'),
                f'{repo}: unsupported platform')
    # A release in which no shipped component carries the release tag released
    # nothing: every component is a carry-over and the tag names no new image.
    pinned = ', '.join(f'{repo}={candidate["repositories"][repo]["tag"]}' for repo in COMPONENTS)
    require(shipped, f'no component was released at {tag} ({pinned})')
    for name in ('SHA256SUMS', f'vidra-bundle_{tag}.tar.gz', f'vidra_{tag}_{candidate["platform"].replace("/", "_")}'):
        asset = candidate.get('assets', {}).get(name, {})
        require(re.fullmatch(r'[0-9a-f]{64}', asset.get('sha256', '')), f'{name}: missing checksum')
        require(asset.get('url') == f'https://github.com/yegamble/vidra-core/releases/download/{tag}/{name}',
                f'{name}: unexpected asset URL')


def expected_hash(sums, name):
    entries = [line.split() for line in sums.splitlines()]
    matches = [line[0] for line in entries if len(line) == 2 and line[1] == name]
    require(len(matches) == 1 and re.fullmatch(r'[0-9a-f]{64}', matches[0]), f'{name}: missing/duplicate checksum')
    return matches[0]


def check_ports(model):
    services = model.get('services', {})
    for name in ('postgres', 'redis', 'search', 'api', 'frontend'):
        require(name in services, f'missing service {name}; use explicit profiles')
    for name in ('postgres', 'redis', 'search'):
        require(not services[name].get('ports'), f'{name}: datastore port published')
    for name, port in (('api', 8080), ('frontend', 3000)):
        ports = services[name].get('ports', [])
        require(len(ports) == 1 and ports[0].get('host_ip') == '127.0.0.1'
                and str(ports[0].get('published')) == str(port)
                and ports[0].get('target') == port, f'{name}: expected one loopback port {port}')
    return {name: services[name].get('ports', []) for name in ('postgres', 'redis', 'search', 'api', 'frontend')}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(args, private, label, cwd=None, env=None, expected=0):
    # Setup and Compose output may contain newly generated test secrets. Keep
    # every raw subprocess log root-only in the disposable VM, never export it.
    print(f'[a02] {label}', flush=True)
    with (private / f'{label}.log').open('w') as log:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, cwd=cwd, env=env, timeout=1200)
    require(result.returncode == expected, f'{label}: exit {result.returncode}, expected {expected}; see private VM log')
    return (private / f'{label}.log').read_text()


def guest(candidate_path):
    candidate = json.loads(candidate_path.read_text())
    validate_candidate(candidate)
    # The launcher creates this marker in a NEW named VM. Refuse reused hosts
    # before apt, downloads or any write to the installation tree.
    marker = Path('/run/vidra-a02-disposable')
    require(platform.system() == 'Linux' and os.geteuid() == 0, 'guest requires root on disposable Linux')
    require(marker.exists() and marker.read_text().strip() == platform.node()
            and platform.node().startswith('vidra-a02-'), 'missing fresh-VM marker')
    require(Path('/run/systemd/system').exists(), 'a real systemd VM is required')
    require(not shutil.which('docker') and not Path('/opt/vidra').exists()
            and not Path('/usr/local/bin/vidra').exists(), 'host is not blank')
    private = Path('/root/vidra-a02-private')
    private.mkdir(mode=0o700)
    public = Path('/home/ubuntu/a02-evidence')
    public.mkdir()
    evidence = {'status': 'UNVERIFIED', 'candidate_sha256': sha(candidate_path), 'helper_sha256': sha(__file__),
                'host_architecture': platform.machine(), 'os_release': Path('/etc/os-release').read_text(),
                'checks': {}, 'image_execution': 'UNVERIFIED: pulls only; no containers started'}
    try:
        run_guest(candidate, candidate_path.parent, private, evidence)
        evidence['status'] = 'PASS'
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        evidence['status'] = 'FAIL'
        evidence['error'] = str(error)
        print(f'[a02] ERROR: {error}', file=sys.stderr)
    finally:
        (public / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return 0 if evidence['status'] == 'PASS' else 1


def run_guest(candidate, stage, private, evidence):
    tag = candidate['tag']
    arch = {'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine())
    require(arch is not None, 'unsupported guest architecture')
    installer = stage / 'install.sh'
    evidence['installer_sha256'] = sha(installer)
    base = f'https://github.com/yegamble/vidra-core/releases/download/{tag}'
    args = ['sh', str(installer), '--yes', '--ref', tag, '--dir', '/opt/vidra']
    bundle = f'vidra-bundle_{tag}.tar.gz'
    cli = f'vidra_{tag}_linux_{arch}'
    fault = private / 'fault-bin'
    fault.mkdir()
    # Only the negative lane intercepts curl: perform the REAL transfer, then
    # append one byte to its output. HTTP status and exit semantics are intact.
    (fault / 'curl').write_text('''#!/usr/bin/python3
import os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
result = subprocess.run(['/usr/bin/curl', *args])
if result.returncode == 0 and os.environ['A02_CORRUPT_URL'] in args and '-o' in args:
    with open(args[args.index('-o') + 1], 'ab') as output:
        output.write(b'X')
    Path(os.environ['A02_FAULT_MARKER']).write_text('injected')
sys.exit(result.returncode)
''')
    (fault / 'curl').chmod(0o755)
    for name, label in ((bundle, 'corrupt-bundle'), (cli, 'corrupt-cli')):
        hit = private / f'{label}.injected'
        env = dict(os.environ, PATH=f'{fault}:{os.environ["PATH"]}',
                   A02_CORRUPT_URL=f'{base}/{name}', A02_FAULT_MARKER=str(hit))
        output = command(args, private, label, env=env, expected=1)
        require(hit.exists() and f'CHECKSUM MISMATCH on {name}' in output, f'{label}: wrong failure reason')
        require(not Path('/usr/local/bin/vidra').exists(), f'{label}: unverified CLI installed')
        if name == bundle:
            require(not Path('/opt/vidra/vidra-bundle.manifest').exists(), 'corrupt bundle was promoted')
        require(not Path('/opt/vidra/env/production.env').exists(), f'{label}: configuration unexpectedly written')
        evidence['checks'][label] = 'PASS'
    output = command(args, private, 'install')
    require('needs a terminal and there is none here' in output, 'expected explicit unattended setup handoff')
    root = Path('/opt/vidra')
    require(not (root / '.git').exists(), 'installer used checkout fallback instead of released bundle')
    provenance = (root / 'vidra-bundle.manifest').read_text()
    for key, value in [('tag', tag), ('meta_commit', candidate['repositories']['vidra']['revision']),
                       ('core_commit', candidate['repositories']['vidra-core']['revision'])]:
        require(f'{key}={value}' in provenance.splitlines(), f'bundle {key} mismatch')
    sums_path = private / 'SHA256SUMS'
    command(['curl', '-fsSL', f'{base}/SHA256SUMS', '-o', str(sums_path)], private, 'download-sums')
    require(sha(sums_path) == candidate['assets']['SHA256SUMS']['sha256'], 'release checksums drifted since A01')
    native_hash = expected_hash(sums_path.read_text(), cli)
    require(sha('/usr/local/bin/vidra') == native_hash, 'installed native CLI differs from frozen release checksum')
    evidence['native_cli'] = {'asset': cli, 'sha256': native_hash, 'url': f'{base}/{cli}'}
    evidence['checks']['install'] = 'PASS'
    command(['vidra', 'help'], private, 'cli-help')
    evidence['checks']['native_cli_executes'] = 'PASS (help; binary identity verified by checksum)'
    command(['vidra', 'setup', '--non-interactive', '--domain', 'http://video.test',
             '--instance-name', 'A02 disposable test', '--registration', 'closed',
             '--tls-mode', 'plain-http', '--storage', 'local', '--release-tag', tag,
             '--template', 'env/production.env.example'], private, 'setup', cwd=root)
    files = [root / 'env/production.env', root / 'deploy/Caddyfile.local', Path('/usr/local/bin/vidra')]
    before = [path.read_bytes() for path in files]
    command(args, private, 'reinstall')
    require(before == [path.read_bytes() for path in files], 'reinstall changed env, Caddy config or CLI bytes')
    command(['vidra', 'setup', '--check', 'env/production.env'], private, 'setup-check', cwd=root)
    evidence['checks']['configuration_preserved'] = 'PASS'
    # `setup --release-tag` writes that one tag for all three services. On a
    # core-only release that pins vidra-user and vidra-search at a tag that was
    # never published, so correct the env to the candidate's per-component tags
    # before rendering. Done AFTER the reinstall-idempotence comparison above,
    # which must see exactly the bytes the installer and setup produced.
    env_file = root / 'env/production.env'
    temporary = root / 'env/production.env.tmp'
    temporary.write_text(pin_component_tags(env_file.read_text(), candidate))
    temporary.chmod(0o600)
    temporary.replace(env_file)
    evidence['component_tags'] = {repo: candidate['repositories'][repo]['tag'] for repo in COMPONENTS}
    evidence['checks']['component_tag_pins'] = 'PASS (env rewritten to the per-component release tags)'
    evidence['docker_version'] = command(['docker', '--version'], private, 'docker-version').strip()
    evidence['compose_version'] = command(['docker', 'compose', 'version', '--short'], private, 'compose-version').strip()
    command(['systemctl', 'is-active', '--quiet', 'docker'], private, 'docker-active')
    command(['systemctl', 'is-enabled', '--quiet', 'docker'], private, 'docker-enabled')
    compose = ['docker', 'compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.prod.yml',
               '--env-file', 'env/production.env', '--profile', 'core', '--profile', 'frontend']
    model = json.loads(command(compose + ['config', '--format', 'json'], private, 'compose', cwd=root))
    evidence['ports'] = check_ports(model)
    evidence['checks']['production_ports'] = 'PASS (Compose render; runtime ports belong to A03)'
    for repo, services in [('vidra-core', ['api', 'migrate']), ('vidra-user', ['frontend']),
                           ('vidra-search', ['search', 'search-migrate'])]:
        image = candidate['images'][repo]
        expected = expected_image(candidate, repo)
        for service in services:
            rendered = model['services'][service].get('image')
            require(rendered == expected, f'{service}: pinned {rendered!r}, expected {expected}')
        command(['docker', 'pull', '--platform', image['platform'], image['reference']], private, f'pull-{repo}')
        info = json.loads(command(['docker', 'image', 'inspect', image['reference']], private, f'inspect-{repo}'))[0]
        require(image['reference'] in info['RepoDigests'], f'{repo}: pulled digest mismatch')
        require(f'{info["Os"]}/{info["Architecture"]}' == image['platform'], f'{repo}: pulled platform mismatch')
        require(info['Config']['Labels']['org.opencontainers.image.revision'] == image['revision'], f'{repo}: pulled revision mismatch')
    evidence['checks']['pinned_image_pulls'] = 'PASS'
    require(not command(['docker', 'ps', '-aq'], private, 'no-containers').strip(), 'A02 unexpectedly started containers')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--validate':
        data = json.loads(Path(sys.argv[2]).read_text())
        validate_candidate(data)
        print(data['repositories']['vidra']['revision'])
    elif len(sys.argv) == 3 and sys.argv[1] == '--guest':
        sys.exit(guest(Path(sys.argv[2])))
    else:
        sys.exit('Use blank-server-smoke.sh; internal modes: --validate MANIFEST / --guest MANIFEST')
