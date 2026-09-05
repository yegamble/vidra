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
        remote = f'https://github.com/{args.owner}/{repo}.git'
        dest = source / repo
        # A private detached checkout avoids moving operator release pins or
        # silently reading ignored/uncommitted files from nested workspaces.
        run(['git', 'clone', '--quiet', '--depth', '1', '--branch', args.tag, remote, str(dest)])
        revision = run(['git', 'rev-parse', '--verify', f'refs/tags/{args.tag}^{{commit}}'], cwd=dest).strip()
        run(['git', 'checkout', '--quiet', '--detach', revision], cwd=dest)
        manifest['repositories'][repo] = {'remote': remote, 'tag': args.tag, 'revision': revision}
        save(out, manifest)
    for repo in REPOS[1:]:
        name = f'{args.owner}/{repo}'
        tagged = f'ghcr.io/{name}:{args.tag}'
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
    args = parser.parse_args()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.tag) or not re.fullmatch(r'[A-Za-z0-9-]+', args.owner):
        parser.error('expected vX.Y.Z tag and GitHub owner name')
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
