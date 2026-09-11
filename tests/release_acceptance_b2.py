"""Dedicated Backblaze test storage only; no account-wide object access."""
import base64
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request

from blank_server_smoke import require

CAPABILITIES = {'listBuckets', 'readBuckets', 'listFiles', 'readFiles', 'writeFiles', 'deleteFiles'}


def validate_spec(spec):
    require(set(spec) == {'bucket', 'bucket_id', 'region', 'endpoint'}, 'bucket spec must contain only nonsecret fields')
    require(re.fullmatch(r'vidra-acceptance-v064-[0-9]{8}-[a-z0-9-]+', spec['bucket']) is not None,
            'requires a new dedicated v0.6.4 acceptance bucket; existing/shared buckets forbidden')
    require('sizetube' not in spec['bucket'], 'Sizetube buckets are forbidden')
    require(re.fullmatch(r'[0-9a-f]{24}', spec['bucket_id']) is not None, 'invalid test bucket ID')
    require(re.fullmatch(r'[a-z]{2}-[a-z]+-[0-9]{3}', spec['region']) is not None, 'invalid B2 region')
    require(spec['endpoint'] == f's3.{spec["region"]}.backblazeb2.com', 'requires regional B2 TLS endpoint')


def validate_scope(spec, storage):
    validate_spec(spec)
    allowed = storage['allowed']
    require(allowed.get('buckets') == [{'id': spec['bucket_id'], 'name': spec['bucket']}],
            'key must be restricted by Backblaze to exactly the dedicated test bucket')
    require(set(allowed['capabilities']) == CAPABILITIES and not allowed.get('namePrefix'),
            'key must have only test-bucket read/write/delete capabilities; no account or policy management')
    require(storage['s3ApiUrl'] == 'https://' + spec['endpoint'], 'credential belongs to another region')


def validate_runtime_config(services, spec, credentials):
    require('api' in services, 'missing API service')
    # The released default runs queues in the API process. A separate worker
    # is optional and absent from a render unless its profile is selected.
    for service in ('api', 'worker'):
        if service not in services:
            continue
        actual = services[service]['environment']
        for key, value in {'STORAGE_BACKEND': 's3', 'STORAGE_S3_BUCKET': spec['bucket'],
                           'STORAGE_S3_ENDPOINT': spec['endpoint'], 'STORAGE_S3_REGION': spec['region'],
                           'STORAGE_S3_ACCESS_KEY': credentials['access_key'],
                           'STORAGE_S3_SECRET_KEY': credentials['secret_key'],
                           'STORAGE_S3_USE_SSL': 'true', 'STORAGE_S3_FORCE_PATH_STYLE': 'false'}.items():
            require(str(actual.get(key)).lower() == value if value in ('true', 'false')
                    else actual.get(key) == value, f'{service}: wrong test storage {key}')


class TestBucket:
    def __init__(self, spec, credentials):
        validate_spec(spec)
        require(set(credentials) == {'access_key', 'secret_key'} and all(credentials.values()), 'invalid dedicated key file')
        self.spec = spec
        self.credentials = credentials
        self.commands = []
        basic = base64.b64encode((credentials['access_key'] + ':' + credentials['secret_key']).encode()).decode()
        auth = self.request('https://api.backblazeb2.com/b2api/v4/b2_authorize_account', {}, 'Basic ' + basic)
        storage = auth['apiInfo']['storageApi']
        validate_scope(spec, storage)  # before any bucket request or host mutation
        self.api = storage['apiUrl']
        require(re.fullmatch(r'https://api[0-9]+\.backblazeb2\.com', self.api) is not None, 'unexpected B2 API host')
        self.token = auth['authorizationToken']
        self.proof = {'provider': 'Backblaze B2', **spec, 'authorized_scope': storage['allowed']}

    def request(self, url, body, token):
        entry = {'url': url, 'body': body, 'started_at': time.time()}
        self.commands.append(entry)
        request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                        headers={'Authorization': token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                entry['http_status'] = response.status
                return json.load(response)
        finally:
            entry['finished_at'] = time.time()

    def call(self, method, **values):
        return self.request(self.api + '/b2api/v4/' + method, values, self.token)

    def inventory(self):
        # Deliberately no generic bucket argument, pagination or account listing.
        # A tiny, new acceptance bucket cannot legitimately exceed this bound.
        result = self.call('b2_list_file_versions', bucketId=self.spec['bucket_id'], maxFileCount=1000)
        require(result.get('nextFileName') is None, 'test bucket exceeded bounded inventory')
        return [{key: row.get(key) for key in ('fileId', 'fileName', 'action', 'contentLength',
                'contentType', 'contentSha1', 'uploadTimestamp')} for row in result['files']]

    def require_empty(self):
        files = self.inventory()
        require(not files, 'test bucket is not empty, including versions; never clean or reuse it automatically')
        self.proof['before'] = files
        self.proof['preflight'] = 'PASS'
        return self.proof

    def download_original(self, name, destination):
        # Native metadata can say "none" (multipart) or "unverified:<sha1>".
        # Neither is a checksum attestation. Download the canonical S3 object
        # and hash actual bytes independently of Vidra's browser download.
        url = 'https://' + self.spec['bucket'] + '.' + self.spec['endpoint'] + '/' + urllib.parse.quote(name, safe='/')
        args = ['curl', '--silent', '--show-error', '--fail', '--max-time', '90',
                '--proto', '=https', '--aws-sigv4', f'aws:amz:{self.spec["region"]}:s3',
                '--config', '-', '--output', str(destination), '--write-out', '%{json}', url]
        config = 'user = ' + json.dumps(self.credentials['access_key'] + ':' + self.credentials['secret_key']) + '\n'
        entry = {'argv': args, 'authorization': 'single-bucket key via private stdin; omitted', 'started_at': time.time()}
        self.commands.append(entry)
        response = subprocess.run(args, input=config, text=True, capture_output=True, timeout=100)
        entry.update(exit_code=response.returncode, finished_at=time.time())
        require(response.returncode == 0, 'direct B2 S3 download failed')
        metadata = json.loads(response.stdout)
        require(metadata['http_code'] == 200, 'direct B2 S3 download did not return 200')
        return {'url': url, 'status': metadata['http_code'], 'type': metadata['content_type'],
                'bytes': destination.stat().st_size, 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}

    def verify_media(self, video_id, fixture):
        files = self.inventory()
        uploads = [row for row in files if row['action'] == 'upload']
        require(any(row['fileName'] == '.vidra/owner' for row in uploads), 'missing test bucket ownership marker')
        video = [row for row in uploads if video_id in row['fileName']]
        originals = [row for row in video if row['fileName'] == f'web-videos/{video_id}.mp4']
        require(len(originals) == 1 and originals[0]['contentLength'] == fixture.stat().st_size,
                'canonical original missing or ambiguous in B2')
        source_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
        downloaded = self.download_original(originals[0]['fileName'], fixture.parent / 'private/b2-original-readback.mp4')
        require(downloaded['sha256'] == source_sha256 and downloaded['bytes'] == fixture.stat().st_size
                and downloaded['type'] == 'video/mp4', 'direct B2 original differs from uploaded fixture')
        for suffix in ('.m3u8', '.m4s'):
            require(any(row['fileName'].endswith(suffix) and row['contentLength'] > 0 for row in video),
                    'transcoded objects missing from B2: ' + suffix)
        self.proof.update(after=files, fixture_sha256=source_sha256, original_download=downloaded,
                          native_original_sha1_field=originals[0]['contentSha1'], video_id=video_id,
                          provider_objects='PASS', requests=self.commands)
        return self.proof
