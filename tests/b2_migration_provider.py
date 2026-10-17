#!/usr/bin/env python3
"""Read-only, independent B2 readback of a generated migration's asset pairs.

The migration recorder supplies source hashes, not provider attestations. This
helper checks those retained source files, then downloads every destination via
signed S3 GET. Native version inventory and request records stay in a private,
new evidence directory outside the checkout. The result contains only hashes,
counts and booleans; account identifiers and credentials are never published.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time

from blank_server_smoke import require
from release_acceptance_b2 import TestBucket, validate_spec

MAX_OBJECTS = 500
MAX_SOURCE_BYTES = 1 << 30
MAX_PLAYLIST_BYTES = 1 << 20
PREFIXES = ('web-videos/', 'streaming-playlists/hls/', 'captions/',
            'thumbnails/', 'storyboards/', 'avatars/', 'banners/')
KINDS = {'original': 'web-videos/', 'hls_binary': 'streaming-playlists/hls/',
         'playlist': 'streaming-playlists/hls/', 'caption': 'captions/',
         'artwork': ('thumbnails/', 'avatars/', 'banners/'),
         'storyboard': 'storyboards/', 'storyboard_vtt': 'storyboards/'}
LOCAL_HLS_NAME = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\Z')
WRITE_PROBE_KEY = re.compile(r'\.vidra/write-probe/[A-Z2-7]{26}\Z')
# Frozen storage/writeprobe.go uses PutSized for this exact UTF-8 body, then
# deletes its unique key. B2 retains an upload plus a hide version. These are
# capability diagnostics, never imported assets and never an excuse to ignore
# a hidden or overwritten media object.
WRITE_PROBE_BODY = 'vidra storage write probe — scratch object, safe to delete.\n'.encode('utf-8')
WRITE_PROBE_SHA1 = hashlib.sha1(WRITE_PROBE_BODY).hexdigest()
WRITE_PROBE_SHA256 = hashlib.sha256(WRITE_PROBE_BODY).hexdigest()
EMPTY_SHA1 = hashlib.sha1(b'').hexdigest()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            value.update(chunk)
    return value.hexdigest()


def safe_relative(value):
    require(isinstance(value, str) and 0 < len(value) <= 1024,
            'invalid relative asset path')
    require(all(re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', part)
                for part in value.split('/')), 'unsafe relative asset path')
    return value


def safe_key(value):
    safe_relative(value)
    require(value.startswith(PREFIXES), 'object key is outside migration prefixes')
    return value


def source_key(row):
    if 'source_key' in row:
        return safe_key(row['source_key'])
    key = row['source_relative']
    if key.startswith('source-media/'):
        key = key[len('source-media/'):]
    # PeerTube stores private HLS under an additional directory; Vidra copies
    # its tree to the ordinary destination prefix, preserving local filenames.
    key = key.replace('streaming-playlists/hls/private/', 'streaming-playlists/hls/', 1)
    return safe_key(key)


def validate_pairs(rows, source_root):
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_OBJECTS,
            'asset pairs must be a bounded nonempty list')
    root = source_root.resolve(strict=True)
    require(root.is_dir(), 'source root is not a directory')
    keys, hls_sources, result = set(), set(), []
    total = 0
    for row in rows:
        require(isinstance(row, dict) and
                set(row) <= {'key', 'source_relative', 'bytes', 'sha256', 'kind', 'source_key'} and
                {'key', 'source_relative', 'bytes', 'sha256', 'kind'} <= set(row),
                'invalid asset pair schema')
        key = safe_key(row['key'])
        kind = row['kind']
        require(kind in KINDS and key.startswith(KINDS[kind]), 'asset kind disagrees with key prefix')
        require((kind == 'playlist') == key.endswith('.m3u8'), 'playlist kind disagrees with extension')
        require(kind not in ('caption', 'storyboard_vtt') or key.endswith('.vtt'),
                'caption/map key must be WebVTT')
        require(key not in keys, 'duplicate destination asset')
        keys.add(key)
        require(type(row['bytes']) is int and 0 < row['bytes'] <= MAX_SOURCE_BYTES,
                'invalid source asset size')
        require(isinstance(row['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', row['sha256']),
                'invalid source SHA256')
        relative = safe_relative(row['source_relative'])
        path = (root / relative).resolve(strict=True)
        require(path.is_relative_to(root) and path.is_file(), 'source asset escapes retained source root')
        require(path.stat().st_size == row['bytes'] and digest(path) == row['sha256'],
                'retained source asset differs from recorded hash or length')
        total += row['bytes']
        require(total <= MAX_SOURCE_BYTES, 'generated source exceeds readback byte budget')
        checked = dict(row, path=path)
        if kind in ('playlist', 'hls_binary'):
            checked['source_key'] = source_key(row)
            require(checked['source_key'].startswith('streaming-playlists/hls/'),
                    'HLS source key is outside HLS prefix')
            require(checked['source_key'] not in hls_sources, 'ambiguous source HLS mapping')
            hls_sources.add(checked['source_key'])
        if kind == 'playlist':
            require(row['bytes'] <= MAX_PLAYLIST_BYTES, 'source playlist exceeds size bound')
        result.append(checked)
    counts = Counter(row['kind'] for row in result)
    require(all(counts[kind] for kind in ('original', 'playlist', 'hls_binary', 'caption')),
            'generated fixture must include originals, HLS and captions')
    return result


def attributes(value):
    """Parse quoted commas without mistaking CODECS values for attributes."""
    result, seen = [], set()
    while value:
        match = re.match(r'([A-Z0-9-]+)=', value)
        require(match is not None and match[1] not in seen, 'invalid HLS attribute list')
        name = match[1]
        seen.add(name)
        value = value[match.end():]
        quoted = value.startswith('"')
        if quoted:
            end = value.find('"', 1)
            require(end > 1, 'invalid quoted HLS attribute')
            item, value = value[1:end], value[end + 1:]
        else:
            item, comma, rest = value.partition(',')
            require(item and not re.search(r'[\s"=]', item), 'invalid HLS attribute value')
            value = comma + rest
        require(not re.search(r'[\r\n\x00]', item), 'invalid HLS attribute value')
        result.append((name, item, quoted))
        if value:
            require(value.startswith(',') and len(value) > 1, 'invalid HLS attribute separator')
            value = value[1:]
    require(result, 'empty HLS attribute list')
    return result


def playlist_shape(body, key, available, mapping=None):
    """Compare meaningful playlist content after supported import rewrites.

    Source subtitle groups are removed by the importer because caption API
    objects replace PeerTube's external subtitle URLs. Every retained URI must
    resolve to its independently verified destination pair. Other tags and
    attributes must survive unchanged, so a local but incorrect rewrite fails.
    """
    require(len(body) <= MAX_PLAYLIST_BYTES, 'readback playlist exceeds size bound')
    text = body.decode('utf-8')
    require(text.splitlines() and text.splitlines()[0] == '#EXTM3U' and '\x00' not in text,
            'invalid HLS playlist')
    result, references = [], []

    def reference(value):
        require(LOCAL_HLS_NAME.fullmatch(value) is not None, 'nonlocal HLS reference')
        target = safe_key(str(PurePosixPath(key).parent / value))
        if mapping is not None:
            require(target in mapping, 'source HLS dependency is absent from asset pairs')
            target = mapping[target]
        require(target in available, 'destination HLS dependency is absent from asset pairs')
        references.append(target)
        return target

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith('#'):
            result.append(('uri', reference(line)))
            continue
        tag, colon, fields = line.partition(':')
        if tag in ('#EXT-X-MEDIA', '#EXT-X-STREAM-INF') or re.search(r'(?:^|,)[A-Z0-9-]*URI=', fields):
            require(bool(colon), 'missing HLS attributes')
            parsed = attributes(fields)
            values = {name: (value, quoted) for name, value, quoted in parsed}
            if tag == '#EXT-X-MEDIA':
                require('TYPE' in values and not values['TYPE'][1], 'invalid HLS media type')
                if values['TYPE'][0] == 'SUBTITLES':
                    require(mapping is not None and 'URI' in values and values['URI'][1],
                            'destination retains external HLS subtitle group')
                    continue
            kept = []
            for name, value, quoted in parsed:
                if tag == '#EXT-X-STREAM-INF' and name == 'SUBTITLES':
                    require(mapping is not None and quoted, 'destination retains HLS subtitle attribute')
                    continue
                if name.endswith('URI'):
                    require(quoted, 'unquoted HLS URI attribute')
                    value = reference(value)
                kept.append((name, value, quoted))
            result.append(('attributes', tag, tuple(kept)))
        else:
            result.append(('tag', line))
    require(references, 'playlist has no retained media references')
    return result, references


def capability_probe_evidence(groups):
    for versions in groups.values():
        require(len(versions) == 2 and {row.get('action') for row in versions} == {'upload', 'hide'},
                'capability probe must have exactly one upload and one hide version')
        uploaded = next(row for row in versions if row['action'] == 'upload')
        hidden = next(row for row in versions if row['action'] == 'hide')
        require(isinstance(uploaded.get('fileId'), str) and uploaded['fileId'] and
                isinstance(hidden.get('fileId'), str) and hidden['fileId'] and
                uploaded['fileId'] != hidden['fileId'],
                'capability probe versions must have distinct native version IDs')
        require(type(uploaded.get('contentLength')) is int and
                uploaded['contentLength'] == len(WRITE_PROBE_BODY) and
                uploaded.get('contentType') == 'application/octet-stream' and
                uploaded.get('contentSha1') in (WRITE_PROBE_SHA1, 'unverified:' + WRITE_PROBE_SHA1),
                'capability probe upload differs from frozen diagnostic metadata')
        require(type(hidden.get('contentLength')) is int and hidden['contentLength'] == 0 and
                hidden.get('contentType') == 'application/x-bz-hide-marker' and
                hidden.get('contentSha1') == EMPTY_SHA1,
                'capability probe hide differs from empty deletion marker')
        require(type(uploaded.get('uploadTimestamp')) is int and uploaded['uploadTimestamp'] > 0 and
                type(hidden.get('uploadTimestamp')) is int and
                hidden['uploadTimestamp'] > uploaded['uploadTimestamp'],
                'capability probe hide must follow its upload')
    return {'objects': len(groups), 'provider_versions': 2 * len(groups),
            'upload_bytes': len(WRITE_PROBE_BODY) * len(groups),
            'expected_body_sha256': WRITE_PROBE_SHA256,
            'frozen_metadata_matches': True, 'exact_upload_hide_pairs': True,
            # Native unverified:SHA1 is metadata, not an independent readback.
            # Only migration assets count toward signed GET/SHA256 assertions.
            'independently_downloaded': False,
            'object_key_sha256': sorted(hashlib.sha256(key.encode()).hexdigest() for key in groups)}


def validate_inventory(rows, pairs):
    require(isinstance(rows, list) and len(rows) <= 1000, 'unbounded provider version inventory')
    expected = {row['key']: row for row in pairs}
    found, probes, owners = {}, {}, 0
    for row in rows:
        key = row.get('fileName')
        if isinstance(key, str) and key.startswith('.vidra/write-probe/'):
            require(WRITE_PROBE_KEY.fullmatch(key) is not None, 'malformed capability probe key')
            probes.setdefault(key, []).append(row)
            continue
        require(row.get('action') == 'upload', 'test bucket contains a hidden/deleted object version')
        if key == '.vidra/owner':
            owners += 1
            continue
        safe_key(key)
        require(key in expected, 'provider media object is absent from asset pairs')
        require(key not in found, 'multiple provider versions of one generated asset')
        require(type(row.get('contentLength')) is int and row['contentLength'] > 0,
                'provider asset has invalid length')
        pair = expected[key]
        if pair['kind'] == 'playlist':
            require(row['contentLength'] <= MAX_PLAYLIST_BYTES, 'provider playlist exceeds size bound')
        else:
            require(row['contentLength'] == pair['bytes'], 'provider asset length differs from source')
        found[key] = row
    require(owners == 1 and set(found) == set(expected), 'provider inventory lacks owner marker or expected media')
    return found, capability_probe_evidence(probes)


def verify(bucket, pairs, private):
    inventory = bucket.inventory()
    # The full native inventory contains bucket-local object/version IDs and
    # belongs only in private evidence, never the published result.
    save(private / 'inventory.json', inventory)
    found, probes = validate_inventory(inventory, pairs)
    available = {row['key'] for row in pairs}
    mapping = {row['source_key']: row['key'] for row in pairs if 'source_key' in row}
    evidence = []
    for index, row in enumerate(sorted(pairs, key=lambda item: item['key'])):
        path = private / f'readback-{index:04d}'
        download = bucket.download_original(row['key'], path)
        require(download.get('status') == 200 and path.is_file(), 'signed S3 GET failed')
        size, checksum = path.stat().st_size, digest(path)
        require(size == found[row['key']]['contentLength'], 'readback length differs from provider inventory')
        matches = size == row['bytes'] and checksum == row['sha256']
        entry = {'object_key_sha256': hashlib.sha256(row['key'].encode()).hexdigest(),
                 'kind': row['kind'], 'source_bytes': row['bytes'], 'readback_bytes': size,
                 'source_sha256': row['sha256'], 'readback_sha256': checksum,
                 'hash_matches_source': matches, 'signed_get_200': True}
        if row['kind'] == 'playlist':
            expected, _ = playlist_shape(row['path'].read_bytes(), row['source_key'], available, mapping)
            actual, references = playlist_shape(path.read_bytes(), row['key'], available)
            require(actual == expected, 'playlist content or reference rewrite differs from source')
            entry.update(playlist_rewrite_valid=True, local_reference_count=len(references))
        else:
            require(matches, 'signed S3 readback SHA256 differs from retained source')
        evidence.append(entry)
    return {'status': 'PASS', 'provider': 'Backblaze B2', 'provider_version_count': len(inventory),
            'capability_probes': probes,
            'verified_objects': len(evidence), 'verified_bytes': sum(row['readback_bytes'] for row in evidence),
            'object_counts': dict(sorted(Counter(row['kind'] for row in pairs).items())),
            'checks': {'dedicated_bucket_scope': True, 'bounded_version_inventory': True,
                       'every_media_inventory_object_covered': True, 'every_asset_signed_get': True,
                       'only_completed_frozen_capability_probes_exempted': True,
                       'all_binary_sha256_match': True, 'playlist_rewrites_and_local_references': True},
            'assets': evidence}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    path.chmod(0o600)


def execute(pairs_path, source_root, stage, spec_path, credentials_path, tag):
    os.umask(0o077)
    checkout = Path(__file__).resolve().parents[1]
    require(not stage.resolve().is_relative_to(checkout) and
            not source_root.resolve().is_relative_to(checkout),
            'source and provider evidence must remain outside the checkout')
    spec = json.loads(spec_path.read_text())
    validate_spec(spec, tag)
    pairs = validate_pairs(json.loads(pairs_path.read_text()), source_root)
    # Guard every source and destination before authorization or any object GET.
    stage.mkdir(mode=0o700)
    private = stage / 'private'
    private.mkdir(mode=0o700)
    bucket = None
    result = {'status': 'FAIL', 'provider': 'Backblaze B2', 'candidate_tag': tag,
              'asset_pairs_sha256': digest(pairs_path), 'started_at': time.time()}
    try:
        bucket = TestBucket(spec, json.loads(credentials_path.read_text()), tag)
        result.update(verify(bucket, pairs, private))
    except Exception as error:
        # Exceptions from networking or JSON may contain private URLs/paths.
        save(private / 'failure.json', {'type': type(error).__name__, 'message': str(error)})
        result['failure'] = 'independent provider verification failed; inspect private evidence'
        raise
    finally:
        if bucket is not None:
            save(private / 'requests.json', bucket.commands)
        result['finished_at'] = time.time()
        result['tool_sha256'] = digest(Path(__file__))
        save(stage / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairs', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--stage', required=True, type=Path, help='new private stage outside the checkout')
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--credentials', required=True, type=Path)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    try:
        result = execute(args.pairs, args.source_root, args.stage,
                         args.spec, args.credentials, args.tag)
    except Exception:
        print('Independent provider verification failed; private evidence retains details.', file=sys.stderr)
        return 1
    print(json.dumps({key: value for key, value in result.items() if key not in ('assets',)}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
