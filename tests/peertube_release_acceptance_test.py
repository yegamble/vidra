"""Guard archive handling and the sole Compose adaptation of the COPY rehearsal."""
import io
import tarfile
import unittest

import peertube_release_acceptance as p
from peertube_release_checks import original_files, match_assets
from peertube_release_export import reject_secrets


class PeerTubeReleaseTests(unittest.TestCase):
    def test_export_rejects_pem_content_but_not_scanner_literals(self):
        marker = '-----BEGIN ' + 'RSA PRIVATE KEY-----'
        reject_secrets(repr(marker), [])
        for text in (marker + '\nREDACTED', marker + r'\nREDACTED', 'prefix-test-secret-suffix', '$2b$12$' + 'A' * 53):
            with self.assertRaises(AssertionError):
                reject_secrets(text, ['test-secret'])

    def test_byte_equal_files_must_belong_to_correct_video(self):
        source = [{'source_id': 'one', 'filename': 'a'}, {'source_id': 'two', 'filename': 'b'}]
        match_assets(source, source, 'filename')
        for wrong in ([source[0], source[0]],
                      [{'source_id': 'one', 'filename': 'b'}, {'source_id': 'two', 'filename': 'a'}]):
            with self.assertRaises(ValueError):
                match_assets(source, wrong, 'filename')

    def test_progressive_reconciliation_excludes_image_metadata(self):
        originals = [{'kind': 'original', 'storage_key': str(n)} for n in range(5)]
        images = [{'kind': kind} for kind in ('thumbnail', 'storyboard', 'storyboard_vtt') for _ in range(7)]
        self.assertEqual(original_files(originals + images), originals)
        with self.assertRaises(ValueError):
            original_files(originals[:4] + images)

    def archive(self, name, kind=tarfile.REGTYPE):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            archive.addfile(member)
        data.seek(0)
        return tarfile.open(fileobj=data)

    def test_only_regular_media_is_extracted_read_only(self):
        for name in ('source-config8/production.yaml', 'source-media8/logs/server.log', '._source-media8'):
            with self.archive(name) as archive:
                self.assertEqual(list(p.media_members(archive)), [])
        with self.archive('source-media8/web-videos/a.mp4') as archive:
            self.assertEqual(list(p.media_members(archive))[0].mode, 0o444)

    def test_traversal_and_links_are_refused(self):
        for name, kind in [('source-media8/../../outside', tarfile.REGTYPE),
                           ('source-media8/link', tarfile.SYMTYPE)]:
            with self.archive(name, kind) as archive:
                with self.assertRaises(ValueError):
                    list(p.media_members(archive))

    def test_mount_preserves_images_and_existing_volumes(self):
        original = ('volumes:\n  - media_data:/app/data\n  - transcode_tmp:/scratch\nimage: frozen\n'
                    'services:\n  prep-volumes:\n    volumes:\n      - media_data:/app/data\n')
        changed = p.source_mount(original, '/root/rehearsal/source-media8')
        self.assertEqual(changed.replace('  - /root/rehearsal/source-media8:/peertube-source:ro\n', ''), original)
        for bad in ('', original + original):
            with self.assertRaises(ValueError):
                p.source_mount(bad, '/root/rehearsal/source-media8')
