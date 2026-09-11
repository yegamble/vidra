"""Wrong bucket or key scope must fail before any bucket request or install."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_acceptance_b2 import CAPABILITIES, TestBucket, validate_scope, validate_spec

SPEC = {'bucket': 'vidra-acceptance-v064-20260911-media', 'bucket_id': 'a' * 24,
        'region': 'us-east-005', 'endpoint': 's3.us-east-005.backblazeb2.com'}


def authorization():
    return {'s3ApiUrl': 'https://' + SPEC['endpoint'], 'apiUrl': 'https://api005.backblazeb2.com',
            'allowed': {'buckets': [{'id': SPEC['bucket_id'], 'name': SPEC['bucket']}],
                        'capabilities': sorted(CAPABILITIES), 'namePrefix': None}}


class B2AcceptanceTests(unittest.TestCase):
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

    def test_media_requires_attested_original_and_real_transcoded_objects(self):
        bucket = TestBucket.__new__(TestBucket); bucket.proof = {}; bucket.commands = []
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'fixture.mp4'; fixture.write_bytes(b'abc')
            rows = [{'fileName': '.vidra/owner', 'action': 'upload'},
                    {'fileName': 'originals/video-id.mp4', 'action': 'upload', 'contentLength': 3,
                     'contentSha1': 'a9993e364706816aba3e25717850c26c9cd0d89d'},
                    {'fileName': 'hls/video-id/master.m3u8', 'action': 'upload', 'contentLength': 20},
                    {'fileName': 'hls/video-id/chunk.m4s', 'action': 'upload', 'contentLength': 30}]
            for row in rows:
                row.setdefault('contentSha1', None)
            with patch.object(bucket, 'inventory', return_value=rows):
                self.assertEqual(bucket.verify_media('video-id', fixture)['provider_objects'], 'PASS')
            for missing in range(len(rows)):
                with self.subTest(missing=missing), patch.object(bucket, 'inventory', return_value=rows[:missing] + rows[missing+1:]):
                    with self.assertRaises(ValueError):
                        bucket.verify_media('video-id', fixture)


if __name__ == '__main__':
    unittest.main()
