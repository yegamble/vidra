#!/usr/bin/env python3
"""Assemble releases/<tag>.json so deploy/release.sh writes the record itself
instead of it being hand-crafted out of band (finding #189).

  # what is known before the images exist — a digest-less skeleton
  release-record.py skeleton --release v0.6.6 --meta-commit <40hex> \
      --core-schema 146 --search-schema 18 \
      --evidence docs/evidence/release-v0.6.6-verification/manifest.json \
      --component core:v0.6.6:<40hex>:ghcr.io/yegamble/vidra-core \
      --component user:v0.6.6:<40hex>:ghcr.io/yegamble/vidra-user \
      --component search:v0.6.6:<40hex>:ghcr.io/yegamble/vidra-search --out skel.json

  # after the images publish — the digests the GHCR verification resolves
  release-record.py complete --record skel.json \
      --manifest core=core.mf.json --manifest user=user.mf.json \
      --manifest search=search.mf.json --out releases/v0.6.6.json

WHY A SEAM. The record cannot be written in one shot at tag time: the tag names
image digests that only exist after the release is published (chicken-and-egg —
the tag has to exist before the publish workflow builds the image). Splitting the
work into a digest-less SKELETON (built from tags, source commits and schema
versions, all known before publish) and a FINALIZE that fills the index/platform
digests lets deploy/release.sh do both without guessing, and lets a test build
both halves and hold the finished record against deploy/release-mapping.py — the
same validator the deploy and rollback paths run. A record this script writes
that the checker would refuse is a record that stops a deploy, so the two must
not drift.

The FINALIZED record is what release.sh commits. The skeleton is an intermediate
(release.sh builds it and finalizes it locally in one run); a digest-less record
is deliberately never committed, because release-mapping.py — correctly — refuses
a record with no image digests, and a committed skeleton would refuse every
deploy that read it.

Each `complete --manifest name=FILE` reads the JSON that
`docker buildx imagetools inspect <ref> --format '{{json .Manifest}}'` prints:
the index descriptor's own digest plus its per-platform child manifests. The
buildx attestation child (platform unknown/unknown) is dropped — it is not a
platform anyone deploys.

Stdlib only, no network.
"""
import argparse
import copy
import json
import re
import sys

# The order the record and deploy/release-mapping.py agree on.
COMPONENTS = ('core', 'user', 'search')
REPO_OF = {'core': 'vidra-core', 'user': 'vidra-user', 'search': 'vidra-search'}

DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
PLATFORM = re.compile(r'[a-z0-9]+/[a-z0-9]+(/[a-z0-9]+)?')
COMMIT = re.compile(r'[0-9a-f]{40}')
RELEASE_TAG = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+')


def skeleton_image(repository):
    """The image half of a component before its image exists: the registry
    repository is known, the digests are not. index_digest is null and platforms
    is empty ON PURPOSE — that pair is the signal `is_skeleton` reads, and it is
    what release.sh fills in `complete` after the image is published."""
    return {'repository': repository, 'index_digest': None, 'platforms': {}}


def build_skeleton(release, meta_commit, core_schema_version, search_schema_version,
                   components, evidence=None):
    """A digest-less record from what is known before the images publish.

    `components` maps each of core/user/search to {'tag', 'commit', 'repository'}.
    Schema versions arrive as strings from the CLI and are stored as the integers
    deploy/release-mapping.py requires."""
    missing = [name for name in COMPONENTS if name not in components]
    if missing:
        raise ValueError(f'skeleton is missing component(s): {", ".join(missing)}')
    record = {
        'schema_version': 1,
        'release': release,
        'meta_commit': meta_commit,
        'core_schema_version': _schema_int('core_schema_version', core_schema_version),
        'search_schema_version': _schema_int('search_schema_version', search_schema_version),
        'components': {},
    }
    for name in COMPONENTS:
        part = components[name]
        record['components'][name] = {
            'tag': part['tag'],
            'commit': part['commit'],
            'image': skeleton_image(part['repository']),
        }
    if evidence:
        record['evidence'] = evidence
    return record


def _schema_int(label, value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} {value!r} is not an integer migration version')
    if number <= 0:
        raise ValueError(f'{label} {value!r} is not a positive migration version')
    return number


def is_skeleton(record):
    """True when every component still carries the digest-less placeholder, i.e.
    the record has not been finalized. A record with SOME components filled and
    some not is neither a skeleton nor a valid record — finalize refuses to leave
    one in that state, and release-mapping.py refuses to read one."""
    images = [record['components'][name]['image'] for name in COMPONENTS]
    return all(image.get('index_digest') is None and not image.get('platforms') for image in images)


def parse_manifest(text):
    """(index_digest, {os/arch: digest}) from a
    `docker buildx imagetools inspect --format '{{json .Manifest}}'` payload.

    The top-level descriptor's `digest` is the multi-arch index digest. Each real
    child manifest contributes one platform; the buildx attestation manifest
    (platform unknown/unknown, or the attestation-manifest reference type) is not
    a platform and is dropped."""
    data = json.loads(text)
    index = data.get('digest')
    if not isinstance(index, str) or not DIGEST.fullmatch(index):
        raise ValueError('imagetools manifest has no sha256 index digest')
    platforms = {}
    for child in data.get('manifests', []):
        platform = child.get('platform', {}) or {}
        os_name, arch = platform.get('os'), platform.get('architecture')
        annotations = child.get('annotations', {}) or {}
        if annotations.get('vnd.docker.reference.type') == 'attestation-manifest':
            continue
        if not os_name or not arch or os_name == 'unknown' or arch == 'unknown':
            continue
        key = f'{os_name}/{arch}'
        variant = platform.get('variant')
        if variant:
            key = f'{key}/{variant}'
        child_digest = child.get('digest')
        if not isinstance(child_digest, str) or not DIGEST.fullmatch(child_digest):
            raise ValueError(f'imagetools manifest child for {key} has no sha256 digest')
        platforms[key] = child_digest
    if not platforms:
        raise ValueError('imagetools manifest names no real platform (only attestation?)')
    return index, platforms


def finalize(record, digests):
    """Fill the image digests, returning a NEW record (the input skeleton is left
    untouched). `digests` maps each of core/user/search to (index_digest,
    platforms). Refuses a record that is not a skeleton (already finalized, so
    finalizing again would silently overwrite verified digests) and refuses a
    missing or malformed component digest (a half-filled record is one
    release-mapping.py rejects)."""
    if not is_skeleton(record):
        raise ValueError('record is already finalized (has image digests); refusing to overwrite them')
    result = copy.deepcopy(record)
    for name in COMPONENTS:
        if name not in digests:
            raise ValueError(f'no image digest supplied for component {name}')
        index, platforms = digests[name]
        if not isinstance(index, str) or not DIGEST.fullmatch(index):
            raise ValueError(f'{name}: index digest {index!r} is not a sha256 digest')
        if not platforms:
            raise ValueError(f'{name}: no platform digests')
        cleaned = {}
        for platform, value in platforms.items():
            if not PLATFORM.fullmatch(platform):
                raise ValueError(f'{name}: platform {platform!r} is not os/arch')
            if not isinstance(value, str) or not DIGEST.fullmatch(value):
                raise ValueError(f'{name}: platform {platform} digest {value!r} is not a sha256 digest')
            cleaned[platform] = value
        image = result['components'][name]['image']
        image['index_digest'] = index
        image['platforms'] = cleaned
    return result


# --- CLI ---------------------------------------------------------------------

def _component_arg(value):
    # name:tag:commit:repository — split on the first three ':' only, so a
    # registry with a port (registry:5000/owner/repo) survives in `repository`.
    parts = value.split(':', 3)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f'--component must be name:tag:commit:repository, got {value!r}')
    name, tag, commit, repository = parts
    if name not in COMPONENTS:
        raise argparse.ArgumentTypeError(f'--component name must be one of {", ".join(COMPONENTS)}, got {name!r}')
    if not RELEASE_TAG.fullmatch(tag):
        raise argparse.ArgumentTypeError(f'--component {name} tag {tag!r} is not vMAJOR.MINOR.PATCH')
    if not COMMIT.fullmatch(commit):
        raise argparse.ArgumentTypeError(f'--component {name} commit {commit!r} is not a 40-hex commit')
    if not repository.endswith('/' + REPO_OF[name]):
        raise argparse.ArgumentTypeError(
            f'--component {name} repository {repository!r} must end in /{REPO_OF[name]}')
    return name, {'tag': tag, 'commit': commit, 'repository': repository}


def _manifest_arg(value):
    name, _, path = value.partition('=')
    if name not in COMPONENTS or not path:
        raise argparse.ArgumentTypeError(f'--manifest must be name=path with name in {", ".join(COMPONENTS)}')
    return name, path


def _write(record, out):
    text = json.dumps(record, indent=2) + '\n'
    if out and out != '-':
        with open(out, 'w', encoding='utf-8') as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    skel = sub.add_parser('skeleton', help='build the digest-less record')
    skel.add_argument('--release', required=True)
    skel.add_argument('--meta-commit', required=True)
    skel.add_argument('--core-schema', required=True)
    skel.add_argument('--search-schema', required=True)
    skel.add_argument('--evidence')
    skel.add_argument('--component', action='append', type=_component_arg, default=[],
                      help='name:tag:commit:repository (give core, user and search)')
    skel.add_argument('--out', help='write here instead of stdout')

    comp = sub.add_parser('complete', help='fill the image digests of a skeleton')
    comp.add_argument('--record', required=True, help='the skeleton to finalize')
    comp.add_argument('--manifest', action='append', type=_manifest_arg, default=[],
                      help="name=<imagetools '{{json .Manifest}}' file> (give core, user and search)")
    comp.add_argument('--out', help='write here instead of stdout')

    args = parser.parse_args(argv)
    try:
        if args.command == 'skeleton':
            components = dict(args.component)
            if not RELEASE_TAG.fullmatch(args.release):
                raise ValueError(f'release {args.release!r} is not vMAJOR.MINOR.PATCH')
            if not COMMIT.fullmatch(args.meta_commit):
                raise ValueError(f'meta-commit {args.meta_commit!r} is not a 40-hex commit')
            record = build_skeleton(
                release=args.release, meta_commit=args.meta_commit,
                core_schema_version=args.core_schema, search_schema_version=args.search_schema,
                components=components, evidence=args.evidence)
            _write(record, args.out)
        else:
            with open(args.record, encoding='utf-8') as handle:
                record = json.load(handle)
            digests = {}
            for name, path in args.manifest:
                with open(path, encoding='utf-8') as handle:
                    digests[name] = parse_manifest(handle.read())
            record = finalize(record, digests)
            _write(record, args.out)
    except (ValueError, OSError, KeyError) as error:
        print(f'[release-record] ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
