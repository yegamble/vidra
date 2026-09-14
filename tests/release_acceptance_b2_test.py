"""Wrong bucket or key scope must fail before any bucket request or install."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_acceptance_b2 import CAPABILITIES, TestBucket, validate_scope, validate_spec, validate_runtime_config
from release_acceptance_complete_b2 import complete

SPEC = {'bucket': 'vidra-acceptance-v064-20260911-media', 'bucket_id': 'a' * 24,
        'region': 'us-east-005', 'endpoint': 's3.us-east-005.backblazeb2.com'}
# The real v0.6.5 acceptance bucket, so these tests fail here rather than on the host.
V065_SPEC = dict(SPEC, bucket='vidra-acceptance-v065-20260914-media',
                 bucket_id='9555421b394994e8a7070215')


def authorization(spec=SPEC):
    return {'s3ApiUrl': 'https://' + spec['endpoint'], 'apiUrl': 'https://api005.backblazeb2.com',
            'allowed': {'buckets': [{'id': spec['bucket_id'], 'name': spec['bucket']}],
                        'capabilities': sorted(CAPABILITIES), 'namePrefix': None}}


class B2AcceptanceTests(unittest.TestCase):
    def test_completion_cannot_promote_an_unrelated_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'result.json').write_text(json.dumps({'status': 'FAIL', 'error': 'deployment failed'}))
            (stage / 'browser-result.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'only the known'):
                complete(stage, stage / 'completion', stage / 'key.json')
            self.assertFalse((stage / 'completion').exists())

    def test_completion_cannot_promote_a_failed_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            browser = {'status': 'FAIL'}
            (stage / 'result.json').write_text(json.dumps({'status': 'FAIL', 'error': 'B2 does not attest the uploaded original bytes', 'browser': browser}))
            (stage / 'browser-result.json').write_text(json.dumps(browser))
            with self.assertRaisesRegex(ValueError, 'browser sequence did not pass'):
                complete(stage, stage / 'completion', stage / 'key.json')
            self.assertFalse((stage / 'completion').exists())

    def test_default_inline_worker_and_optional_split_worker_storage(self):
        credentials = {'access_key': 'test-access', 'secret_key': 'test-secret'}
        env = {'STORAGE_BACKEND': 's3', 'STORAGE_S3_ENDPOINT': SPEC['endpoint'],
               'STORAGE_S3_REGION': SPEC['region'], 'STORAGE_S3_BUCKET': SPEC['bucket'],
               'STORAGE_S3_ACCESS_KEY': credentials['access_key'], 'STORAGE_S3_SECRET_KEY': credentials['secret_key'],
               'STORAGE_S3_USE_SSL': True, 'STORAGE_S3_FORCE_PATH_STYLE': False}
        services = {'api': {'environment': env}}
        validate_runtime_config(services, SPEC, credentials)
        services['worker'] = {'environment': env.copy()}
        validate_runtime_config(services, SPEC, credentials)
        for service in ('api', 'worker'):
            for key, wrong in [('STORAGE_BACKEND', 'local'), ('STORAGE_S3_BUCKET', 'sizetube'),
                               ('STORAGE_S3_SECRET_KEY', 'different-key')]:
                bad = copy.deepcopy(services); bad[service]['environment'][key] = wrong
                with self.subTest(service=service, key=key), self.assertRaises(ValueError):
                    validate_runtime_config(bad, SPEC, credentials)
        with self.assertRaisesRegex(ValueError, 'missing API'):
            validate_runtime_config({}, SPEC, credentials)

    def test_shared_historical_or_secret_bearing_spec_refused(self):
        validate_spec(SPEC)
        for change in ({'bucket': 'sizetube'}, {'bucket': 'sizetube-backup'},
                       {'bucket': 'vidra-acceptance-20260905-a36'},
                       {'bucket': 'vidra-acceptance-v064-20260911-sizetube'},
                       {'secret_key': 'not-public'}, {'endpoint': 's3.attacker.example'},
                       {'bucket_id': '../other'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_spec(dict(SPEC, **change))

    def test_provider_scope_must_be_exact_not_account_wide_or_multiple(self):
        validate_scope(SPEC, authorization())
        for buckets in (None, [], [{'id': 'b' * 24, 'name': SPEC['bucket']}],
                        [{'id': SPEC['bucket_id'], 'name': 'sizetube'}],
                        authorization()['allowed']['buckets'] * 2):
            with self.subTest(buckets=buckets), self.assertRaises(ValueError):
                auth = authorization(); auth['allowed']['buckets'] = buckets
                validate_scope(SPEC, auth)

    def test_management_permissions_prefix_or_wrong_region_refused(self):
        for field, value in [('capabilities', sorted(CAPABILITIES | {'writeKeys'})),
                             ('capabilities', sorted(CAPABILITIES - {'writeFiles'})),
                             ('namePrefix', 'testing/')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                auth = authorization(); auth['allowed'][field] = value
                validate_scope(SPEC, auth)
        auth = authorization(); auth['s3ApiUrl'] = 'https://s3.us-west-004.backblazeb2.com'
        with self.assertRaises(ValueError):
            validate_scope(SPEC, auth)

    def test_account_key_never_reaches_a_bucket_request(self):
        auth = authorization(); auth['allowed']['buckets'] = None
        with patch.object(TestBucket, 'request', return_value={'apiInfo': {'storageApi': auth}}) as network:
            with self.assertRaises(ValueError):
                TestBucket(SPEC, {'access_key': 'id', 'secret_key': 'secret'})
            self.assertEqual(network.call_count, 1)
            self.assertTrue(network.call_args.args[0].endswith('b2_authorize_account'))

    def test_existing_versions_refused_without_cleanup(self):
        bucket = TestBucket.__new__(TestBucket)
        bucket.proof = {}; bucket.spec = copy.deepcopy(SPEC)
        with patch.object(bucket, 'inventory', return_value=[{'action': 'hide'}]):
            with self.assertRaisesRegex(ValueError, 'not empty'):
                bucket.require_empty()

    def test_media_requires_direct_original_download_and_real_transcoded_objects(self):
        bucket = TestBucket.__new__(TestBucket); bucket.proof = {}; bucket.commands = []
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'fixture.mp4'; fixture.write_bytes(b'abc')
            rows = [{'fileName': '.vidra/owner', 'action': 'upload'},
                    {'fileName': 'web-videos/video-id.mp4', 'action': 'upload', 'contentLength': 3,
                     'contentSha1': 'none'},
                    {'fileName': 'hls/video-id/master.m3u8', 'action': 'upload', 'contentLength': 20},
                    {'fileName': 'hls/video-id/chunk.m4s', 'action': 'upload', 'contentLength': 30}]
            for row in rows:
                row.setdefault('contentSha1', None)
            downloaded = {'sha256': hashlib.sha256(b'abc').hexdigest(), 'bytes': 3, 'type': 'video/mp4'}
            with patch.object(bucket, 'inventory', return_value=rows), patch.object(bucket, 'download_original', return_value=downloaded):
                self.assertEqual(bucket.verify_media('video-id', fixture)['provider_objects'], 'PASS')
            with patch.object(bucket, 'inventory', return_value=rows), patch.object(bucket, 'download_original', return_value=dict(downloaded, sha256='wrong')):
                with self.assertRaisesRegex(ValueError, 'direct B2 original differs'):
                    bucket.verify_media('video-id', fixture)
            for missing in range(len(rows)):
                with self.subTest(missing=missing), patch.object(bucket, 'inventory', return_value=rows[:missing] + rows[missing+1:]), patch.object(bucket, 'download_original', return_value=downloaded):
                    with self.assertRaises(ValueError):
                        bucket.verify_media('video-id', fixture)


class BucketNamingTests(unittest.TestCase):
    def test_bucket_must_be_named_for_the_candidate_release(self):
        validate_spec(V065_SPEC, 'v0.6.5')
        with self.assertRaises(ValueError):
            validate_spec(SPEC, 'v0.6.5')  # a v064 bucket cannot serve a v0.6.5 run
        with self.assertRaises(ValueError):
            validate_spec(V065_SPEC, 'v0.6.4')
        validate_spec(SPEC)  # the default keeps the v0.6.4 records valid

    def test_scope_check_honours_the_callers_tag_not_the_default(self):
        # validate_scope re-validates the spec. If it does that against its own
        # default instead of the tag the caller established, a correctly named
        # v0.6.5 bucket is refused the moment its scope is checked.
        validate_scope(V065_SPEC, authorization(V065_SPEC), 'v0.6.5')
        with self.assertRaises(ValueError):
            validate_scope(V065_SPEC, authorization(V065_SPEC))  # default tag rejects it
        with self.assertRaises(ValueError):
            validate_scope(SPEC, authorization(SPEC), 'v0.6.5')  # and v064 cannot serve v0.6.5
        validate_scope(SPEC, authorization(SPEC))  # the default keeps the v0.6.4 records valid

    def test_bucket_authorizes_a_v065_candidate_end_to_end(self):
        # The regression this closes would have surfaced on the acceptance host:
        # __init__ validated the spec against its tag, then dropped the tag on
        # the way into validate_scope, so the v0.6.5 B2 drill died at its first
        # b2_authorize_account with "requires a new dedicated v0.6.4 bucket".
        response = {'apiInfo': {'storageApi': authorization(V065_SPEC)}, 'authorizationToken': 'auth-token'}
        with patch.object(TestBucket, 'request', return_value=response) as network:
            bucket = TestBucket(V065_SPEC, {'access_key': 'id', 'secret_key': 'secret'}, 'v0.6.5')
        self.assertEqual(network.call_count, 1)
        self.assertTrue(network.call_args.args[0].endswith('b2_authorize_account'))
        self.assertEqual(bucket.api, 'https://api005.backblazeb2.com')
        self.assertEqual(bucket.proof['bucket'], 'vidra-acceptance-v065-20260914-media')
        self.assertEqual(bucket.proof['bucket_id'], V065_SPEC['bucket_id'])
        self.assertEqual(bucket.proof['authorized_scope'], authorization(V065_SPEC)['allowed'])

if __name__ == '__main__':
    unittest.main()
