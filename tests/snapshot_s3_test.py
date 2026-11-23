"""Exercise streaming S3 snapshot failures without a cloud account or SDK dependency."""
import hashlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, quote_plus

spec = importlib.util.spec_from_file_location(
    'snapshot_s3', Path(__file__).resolve().parents[1] / 'deploy/snapshot_s3.py'
)
snapshots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshots)


class S3:
    def __init__(self):
        self.data = {'live': {}, 'recovery': {}}
        self.meta = mock.Mock()
        self.meta.service_model.operation_model.return_value.input_shape.members = {'IfNoneMatch': True}
        self.prior_versions = False
        self.multipart = {}
        self.aborts = []
        self.list_calls = 0

    def get_paginator(self, op):
        assert op == 'list_objects_v2'
        return self

    def paginate(self, Bucket, EncodingType):
        assert EncodingType == 'url'
        self.list_calls += 1
        for key in sorted(self.data[Bucket]):
            body, etag, _ = self.data[Bucket][key]
            yield {'Contents': [{'Key': quote_plus(key, safe=''), 'Size': len(body), 'ETag': etag}]}

    def list_objects_v2(self, Bucket, **kwargs):
        return next(self.paginate(Bucket, EncodingType='url'), {})

    def list_object_versions(self, **kwargs):
        return {'DeleteMarkers': [{}]} if self.prior_versions else {}

    def list_multipart_uploads(self, **kwargs):
        return {'Uploads': list(self.multipart)}

    def add(self, bucket, key, payload, **headers):
        etag = hashlib.sha256(payload).hexdigest()
        self.data[bucket][key] = (payload, etag, headers)
        return {'ETag': etag}

    def get_object(self, Bucket, Key, IfMatch):
        data, etag, headers = self.data[Bucket][Key]
        assert IfMatch == etag
        return dict(headers, ContentLength=len(data), ETag=etag, Body=io.BytesIO(data))

    def get_object_tagging(self, Bucket, Key):
        tags = self.data[Bucket][Key][2].get('Tagging', '')
        return {'TagSet': [{'Key': k, 'Value': v} for k, v in parse_qsl(tags, keep_blank_values=True)]}

    def put_object(self, Bucket, Key, Body, IfNoneMatch, **headers):
        assert IfNoneMatch == '*' and Key not in self.data[Bucket]
        return self.add(Bucket, Key, Body, **headers)

    def create_multipart_upload(self, Bucket, Key, **headers):
        self.multipart[Key] = (bytearray(), headers)
        return {'UploadId': Key}

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):
        assert UploadId == Key
        self.multipart[Key][0].extend(Body.read())
        return {'ETag': str(PartNumber), 'ChecksumCRC32': 'test-receipt'}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload, IfNoneMatch):
        assert IfNoneMatch == '*' and Key not in self.data[Bucket]
        assert all(p['ChecksumCRC32'] == 'test-receipt' for p in MultipartUpload['Parts'])
        body, headers = self.multipart.pop(Key)
        return self.add(Bucket, Key, bytes(body), **headers)

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        del self.multipart[Key]
        self.aborts.append(Key)


class SnapshotS3Test(unittest.TestCase):
    def setUp(self):
        self.s3 = S3()
        self.env = {'STORAGE_S3_BUCKET': 'live', 'STORAGE_S3_ENDPOINT': 's3.example.test'}
        client = mock.patch.object(snapshots, '_client', return_value=self.s3)
        client.start()
        self.addCleanup(client.stop)
        chunk = mock.patch.object(snapshots, 'PART', 8)
        chunk.start()
        self.addCleanup(chunk.stop)

    def archive(self):
        file = io.BytesIO()
        snapshots.capture(self.env, file)
        return file.getvalue()

    def recover(self, data, bucket='recovery', **kwargs):
        return snapshots.restore(self.env, io.BytesIO(data), bucket, **kwargs)

    def test_separate_bucket_round_trip_opaque_keys_metadata_and_multipart(self):
        strange = '../space/\n🥑%2F+#/old.jpg'
        self.s3.add(
            'live',
            strange,
            b'0123456789' * 3,
            ContentType='image/jpeg',
            CacheControl='private',
            Metadata={'test': 'preserved'},
        )
        self.s3.add('live', 'empty', b'')
        original = self.s3.data['live'].copy()
        self.assertEqual(self.recover(self.archive()), {'bucket': 'recovery', 'objects': 2, 'bytes': 30})
        self.assertEqual(original, self.s3.data['live'])
        self.assertEqual(original, self.s3.data['recovery'])

    def test_protected_and_previously_used_buckets(self):
        data = self.archive()
        for name in ('live', 'other-live'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'separate'):
                self.recover(data, name, protected_buckets=['other-live'])
        self.s3.prior_versions = True
        with self.assertRaisesRegex(ValueError, 'unused'):
            self.recover(data)
        self.s3.prior_versions = False
        self.s3.add('recovery', 'exists', b'keep')
        with self.assertRaisesRegex(ValueError, 'unused'):
            self.recover(data)
        self.assertEqual(self.s3.data['recovery']['exists'][0], b'keep')

    def test_payload_corruption_aborts_multipart_without_writing_the_object(self):
        payload = b'synthetic video contents'
        self.s3.add('live', 'video', payload)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.recover(self.archive().replace(payload, bytes(len(payload))))
        self.assertEqual(self.s3.aborts, ['video'])
        self.assertEqual(self.s3.data['recovery'], {})

    def test_partial_archive_and_changed_inventory_refuse_activation(self):
        self.s3.add('live', 'image', b'x')
        archive = self.archive()
        with self.assertRaisesRegex(ValueError, 'unexpected end'):
            self.recover(archive[:-1])
        # A second inventory pass must notice a writer that arrived after capture.
        original = self.s3.paginate
        count = 0

        def changed(**kwargs):
            nonlocal count
            count += 1
            if count == 2:
                self.s3.add('live', 'late', b'new')
            return original(**kwargs)

        self.s3.paginate = changed
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            self.archive()

    def test_tag_read_requires_permission_even_without_tagcount(self):
        self.s3.add('live', 'photo', b'saved', Tagging='permit=private')
        with mock.patch.object(self.s3, 'get_object_tagging', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.archive()
            with self.assertRaises(PermissionError):
                snapshots.preflight(self.env)
        self.recover(self.archive())
        self.assertEqual(self.s3.data['recovery']['photo'][2]['Tagging'], 'permit=private')

    def test_explicitly_unsupported_tagging_can_archive_untagged_objects(self):
        class Unsupported(Exception):
            response = {'Error': {'Code': 'NotImplemented'}}

        self.s3.add('live', 'photo', b'saved', ContentType='image/jpeg')
        with mock.patch.object(self.s3, 'get_object_tagging', side_effect=Unsupported):
            self.recover(self.archive())
            self.s3.add('live', 'tagged', b'saved', TagCount=1)
            with self.assertRaises(Unsupported):
                self.archive()

    def test_silently_lost_playback_headers_refuse_activation(self):
        self.s3.add('live', 'photo', b'saved', ContentEncoding='gzip')
        archive = self.archive()
        original = self.s3.get_object

        def stripped(**kwargs):
            result = original(**kwargs)
            result.pop('ContentEncoding', None)
            return result

        self.s3.get_object = stripped
        with self.assertRaisesRegex(ValueError, 'headers or tagging'):
            self.recover(archive)

    def test_restored_bytes_are_read_back_before_success(self):
        self.s3.add('live', 'photo', b'saved')
        archive = self.archive()
        original = self.s3.get_object

        def corrupt(**kwargs):
            result = original(**kwargs)
            if kwargs['Bucket'] == 'recovery':
                result['Body'] = io.BytesIO(b'wrong')
            return result

        self.s3.get_object = corrupt
        with self.assertRaisesRegex(ValueError, 'restored S3 object checksum'):
            self.recover(archive)


if __name__ == '__main__':
    unittest.main()
