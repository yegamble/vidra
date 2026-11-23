"""Stream a quiesced Vidra media bucket into an install snapshot and recover into an empty bucket.

Each framed JSON header is followed by exactly size raw bytes and a SHA-256 digest.
Keys are opaque S3 names, never filesystem paths. A mandatory footer checks
the object order, metadata, lengths and hashes against accidental corruption.
"""

import hashlib
import json
import re
import struct
import tempfile
from contextlib import closing
from urllib.parse import unquote_plus, urlencode

MAGIC = b'Vidra S3 snapshot\x00\x01'
CHUNK = 1024 * 1024
PART = 8 * CHUNK
MAX_PART = 5 * 1024**3
HEADERS = (
    'ContentType',
    'ContentEncoding',
    'ContentLanguage',
    'ContentDisposition',
    'CacheControl',
    'Expires',
    'WebsiteRedirectLocation',
    'Metadata',
)


def _flag(env, key, default):
    value = str(env.get(key) or str(default)).lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    raise ValueError("invalid boolean in " + key)


def _client(env):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise ValueError(
            'S3 install snapshots require boto3 and botocore in this Python environment'
        ) from exc
    for name in ('ENDPOINT', 'BUCKET', 'ACCESS_KEY', 'SECRET_KEY'):
        if not env.get('STORAGE_S3_' + name):
            raise ValueError('missing STORAGE_S3_' + name)
    if env.get('STORAGE_MIGRATION_TARGET_BACKEND'):
        raise ValueError('finish the storage migration before taking an install snapshot')
    tls = _flag(env, "STORAGE_S3_USE_SSL", True)
    path = _flag(env, "STORAGE_S3_FORCE_PATH_STYLE", False)
    return boto3.client(
        's3',
        endpoint_url=('https://' if tls else 'http://') + env['STORAGE_S3_ENDPOINT'],
        region_name=env.get('STORAGE_S3_REGION') or 'us-east-1',
        aws_access_key_id=env['STORAGE_S3_ACCESS_KEY'],
        aws_secret_access_key=env['STORAGE_S3_SECRET_KEY'],
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path' if path else 'auto'}),
    )


def preflight(api_env):
    """Check read access without requiring a local mirror."""
    s3 = _client(api_env)
    s3.list_objects_v2(Bucket=api_env['STORAGE_S3_BUCKET'], MaxKeys=1, EncodingType='url')


def _check_target(env, destination, protected):
    if (
        not isinstance(destination, str)
        or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', destination)
        or '..' in destination
    ):
        raise ValueError('supply the plain name of a new S3 recovery bucket')
    if destination in (env['STORAGE_S3_BUCKET'], *protected):
        raise ValueError('the S3 recovery bucket must be separate from every live and archived bucket')


def _empty(s3, bucket):
    listed = s3.list_objects_v2(Bucket=bucket, MaxKeys=1, EncodingType='url')
    versions = s3.list_object_versions(Bucket=bucket, MaxKeys=1, EncodingType='url')
    uploads = s3.list_multipart_uploads(Bucket=bucket, MaxUploads=1)
    if (
        listed.get('Contents')
        or versions.get('Versions')
        or versions.get('DeleteMarkers')
        or uploads.get('Uploads')
    ):
        raise ValueError(
            'S3 recovery requires an unused destination without objects, versions or multipart uploads'
        )


def preflight_restore(api_env, destination_bucket, *, protected_buckets=()):
    _check_target(api_env, destination_bucket, protected_buckets)
    s3 = _client(api_env)
    for op in ('PutObject', 'CompleteMultipartUpload'):
        if 'IfNoneMatch' not in s3.meta.service_model.operation_model(op).input_shape.members:
            raise ValueError('upgrade boto3 and botocore to a version supporting conditional S3 writes')
    _empty(s3, destination_bucket)


def _frame(value):
    data = json.dumps(value, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode()
    if len(data) > 1024 * 1024:
        raise ValueError('S3 object header exceeds snapshot format limit')
    return struct.pack('>I', len(data)) + data


def _exact(stream, n):
    result = bytearray()
    while len(result) < n:
        part = stream.read(n - len(result))
        if not part:
            raise ValueError('unexpected end of S3 snapshot or object')
        result.extend(part)
    return bytes(result)


def _read_frame(stream):
    length = _exact(stream, 4)
    (n,) = struct.unpack('>I', length)
    if n > 1024 * 1024:
        raise ValueError('invalid S3 snapshot header size')
    data = _exact(stream, n)
    frame = json.loads(data)
    if not isinstance(frame, dict):
        raise ValueError('invalid S3 snapshot frame')
    return frame, length + data


def _copy(source, size, digest, dest=None):
    while size:
        data = source.read(min(size, CHUNK))
        if not data:
            raise ValueError('S3 object ended before its recorded size')
        digest.update(data)
        if dest is not None:
            dest.write(data)
        size -= len(data)


def _objects(s3, bucket):
    # Request encoded keys explicitly. In this mode botocore leaves decoding to
    # the caller. In particular a literal %2F must not turn into a slash twice.
    pages = s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, EncodingType='url')
    for page in pages:
        for obj in page.get('Contents', []):
            yield unquote_plus(obj['Key'], errors='strict'), obj


def _inventory_item(key, obj):
    return _frame([key, obj['Size'], obj['ETag'], str(obj.get('LastModified', ''))])


def _source_info(env):
    return {'bucket': env['STORAGE_S3_BUCKET'], 'endpoint': env['STORAGE_S3_ENDPOINT']}


def capture(api_env, output):
    s3 = _client(api_env)
    bucket = api_env['STORAGE_S3_BUCKET']
    identity = _frame(_source_info(api_env))
    output.write(MAGIC + identity)
    manifest = hashlib.sha256(identity)
    inventory = hashlib.sha256()
    stats = {'bucket': bucket, 'objects': 0, 'bytes': 0}
    for key, obj in _objects(s3, bucket):
        inventory.update(_inventory_item(key, obj))
        response = s3.get_object(Bucket=bucket, Key=key, IfMatch=obj['ETag'])
        size = obj['Size']
        with closing(response['Body']) as body:
            if size != response['ContentLength']:
                raise ValueError('S3 object changed during snapshot')
            headers = {h: response[h] for h in HEADERS if h in response}
            if 'Expires' in headers:
                headers['Expires'] = headers['Expires'].isoformat()
            if response.get('TagCount'):
                selector = {'VersionId': response['VersionId']} if response.get('VersionId') else {}
                tags = s3.get_object_tagging(Bucket=bucket, Key=key, **selector)['TagSet']
                headers['Tagging'] = urlencode([(tag['Key'], tag['Value']) for tag in tags])
            header = _frame({'key': key, 'size': size, 'headers': headers})
            output.write(header)
            checksum = hashlib.sha256()
            _copy(body, size, checksum, output)
            if body.read(1):
                raise ValueError('S3 object exceeds its recorded size')
        output.write(checksum.digest())
        manifest.update(header + checksum.digest())
        stats['objects'] += 1
        stats['bytes'] += size
    final_inventory = hashlib.sha256()
    for key, obj in _objects(s3, bucket):
        final_inventory.update(_inventory_item(key, obj))
    if inventory.digest() != final_inventory.digest():
        raise ValueError('S3 inventory changed during snapshot; quiesce all writers and retry')
    output.write(_frame({'complete': stats, 'sha256': manifest.hexdigest()}))
    return stats


def _upload(s3, bucket, header, stream):
    size = header['size']
    key = header['key']
    headers = header['headers']
    if (
        not isinstance(key, str)
        or not key
        or len(key.encode()) > 1024
        or type(size) is not int
        or not 0 <= size <= MAX_PART * 10000
        or not isinstance(headers, dict)
        or headers.keys() - set(HEADERS + ('Tagging',))
    ):
        raise ValueError('invalid S3 object description in snapshot')
    target = {'Bucket': bucket, 'Key': key}
    digest = hashlib.sha256()
    part_size = max(PART, (size + 9999) // 10000)
    if size <= PART:
        data = _exact(stream, size)
        digest.update(data)
        if _exact(stream, 32) != digest.digest():
            raise ValueError('S3 snapshot object checksum mismatch')
        result = s3.put_object(**target, Body=data, IfNoneMatch='*', **headers)
    else:
        upload = s3.create_multipart_upload(**target, **headers)['UploadId']
        parts = []
        try:
            remaining = size
            while remaining:
                n = min(part_size, remaining)
                # Very large videos can need parts larger than the memory budget.
                # Spooling one part also lets the SDK retry its HTTP request.
                with tempfile.SpooledTemporaryFile(max_size=PART) as body:
                    _copy(stream, n, digest, body)
                    body.seek(0)
                    num = len(parts) + 1
                    part = s3.upload_part(**target, UploadId=upload, PartNumber=num, Body=body)
                # Some providers require the per-part checksum receipts in the
                # completion request in addition to each part's ETag.
                receipts = {k: v for k, v in part.items() if k.startswith('Checksum') and k != 'ChecksumType'}
                parts.append({'PartNumber': num, 'ETag': part['ETag'], **receipts})
                remaining -= n
            if _exact(stream, 32) != digest.digest():
                raise ValueError('S3 snapshot object checksum mismatch')
            result = s3.complete_multipart_upload(
                **target, UploadId=upload, MultipartUpload={'Parts': parts}, IfNoneMatch='*'
            )
        except BaseException:
            s3.abort_multipart_upload(**target, UploadId=upload)
            raise
    # A multipart ETag is not a payload checksum. Verify the full destination
    # object before this bucket can become the recovered deployment's authority.
    stored = s3.get_object(**target, IfMatch=result['ETag'])
    remote = hashlib.sha256()
    with closing(stored['Body']) as body:
        _copy(body, size, remote)
        if body.read(1) or digest.digest() != remote.digest():
            raise ValueError('restored S3 object checksum mismatch')
    return digest.digest(), result['ETag']


def restore(api_env, source, destination_bucket, *, protected_buckets=()):
    if _exact(source, len(MAGIC)) != MAGIC:
        raise ValueError('unsupported S3 snapshot format')
    identity, raw = _read_frame(source)
    if identity != _source_info(api_env):
        raise ValueError('S3 archive belongs to another endpoint or bucket')
    preflight_restore(api_env, destination_bucket, protected_buckets=protected_buckets)
    s3 = _client(api_env)
    manifest = hashlib.sha256(raw)
    inventory = hashlib.sha256()
    stats = {'bucket': identity['bucket'], 'objects': 0, 'bytes': 0}
    while True:
        header, raw = _read_frame(source)
        if 'complete' in header:
            if header != {'complete': stats, 'sha256': manifest.hexdigest()} or source.read(1):
                raise ValueError('S3 snapshot completion record mismatch')
            break
        digest, etag = _upload(s3, destination_bucket, header, source)
        manifest.update(raw + digest)
        stats['objects'] += 1
        stats['bytes'] += header['size']
        inventory.update(_frame([header['key'], header['size'], etag]))
    observed = hashlib.sha256()
    for key, obj in _objects(s3, destination_bucket):
        observed.update(_frame([key, obj['Size'], obj['ETag']]))
    if observed.digest() != inventory.digest():
        raise ValueError('destination S3 inventory changed during restore')
    return dict(stats, bucket=destination_bucket)
