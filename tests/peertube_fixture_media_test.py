import contextlib
import io
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import peertube_fixture_media as media


class PrivateOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_new_directory_is_private_even_with_permissive_umask(self):
        previous = os.umask(0)
        try:
            output = media.new_private_directory(self.root / 'new')
            media.write_private(output / 'canary', 'PRIVATE-CANARY')
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((output / 'canary').stat().st_mode), 0o600)

    def test_existing_output_is_untouched(self):
        media.write_private(self.root / 'canary', 'PRIVATE-CANARY')
        with self.assertRaisesRegex(media.FixtureError, '^output_exists$'):
            media.new_private_directory(self.root)
        self.assertEqual((self.root / 'canary').read_text(), 'PRIVATE-CANARY')
        with self.assertRaises(FileExistsError):
            media.write_private(self.root / 'canary', 'replacement')

    def test_symlinks_and_noncanonical_paths_refused(self):
        (self.root / 'link').symlink_to(self.root, target_is_directory=True)
        (self.root / 'dangling').symlink_to(self.root / 'absent')
        (self.root / 'loop').symlink_to('loop')
        for path in (self.root / 'link/new', self.root / 'dangling',
                     self.root / 'loop/new', self.root / 'absent/../new', Path('relative')):
            with self.subTest(path=path), self.assertRaises(media.FixtureError):
                media.new_private_directory(path)
        self.assertFalse((self.root / 'new').exists())

    def test_repository_outputs_refused_before_creation(self):
        (self.root / '.git').mkdir()
        (self.root / '.git/HEAD').write_text('ref: refs/heads/main\n')
        with self.assertRaisesRegex(media.FixtureError, '^repository_output_refused$'):
            media.new_private_directory(self.root / 'new')
        self.assertFalse((self.root / 'new').exists())

    def test_missing_tools_leave_no_output_and_restore_umask(self):
        previous = os.umask(0o027)
        try:
            with patch.object(media.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(media.FixtureError, '^media_tool_missing$'):
                    media.generate(self.root / 'new')
            self.assertEqual(os.umask(0o027), 0o027)
        finally:
            os.umask(previous)
        self.assertFalse((self.root / 'new').exists())

    def test_cli_redacts_unexpected_tool_errors(self):
        captured = io.StringIO()
        with patch.object(media, 'generate', side_effect=OSError('PRIVATE-CANARY')), \
                contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            self.assertEqual(media.main(['--out', '/PRIVATE-CANARY']), 1)
        self.assertEqual(captured.getvalue(), 'fixture_generation_failed\n')

    def test_tool_failure_output_stays_private(self):
        media.write_private(self.root / 'tools.log', b'')
        with patch.object(media.shutil, 'which', return_value='/usr/bin/python3'):
            tools = media.Tools(self.root)
        completed = subprocess.CompletedProcess([], 2, b'PRIVATE-CANARY', b'PRIVATE-ERROR')
        with patch.object(media.subprocess, 'run', return_value=completed) as runner:
            with self.assertRaisesRegex(media.FixtureError, '^media_tool_failed$'):
                tools.run('ffmpeg', ['-version'])
        self.assertIn(b'PRIVATE-CANARY', (self.root / 'tools.log').read_bytes())
        self.assertNotIn('shell', runner.call_args.kwargs)
        self.assertEqual(runner.call_args.kwargs['timeout'], 120)
        self.assertEqual(stat.S_IMODE((self.root / 'tools.log').stat().st_mode), 0o600)

    def test_hls_dependency_graph_includes_map_audio_and_variants(self):
        for name in ('audio.m3u8', 'video.m3u8', 'init.mp4', 'segment-000.m4s'):
            media.write_private(self.root / name, 'nonempty')
        playlist = self.root / 'master.m3u8'
        media.write_private(playlist, '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\n'
                            '#EXT-X-MAP:URI="init.mp4"\nvideo.m3u8\nsegment-000.m4s\n')
        self.assertEqual(media.hls_dependencies(playlist),
                         ['audio.m3u8', 'init.mp4', 'video.m3u8', 'segment-000.m4s'])

    def test_missing_empty_symlink_and_nonlocal_dependencies_refused(self):
        media.write_private(self.root / 'empty.mp4', b'')
        (self.root / 'link.mp4').symlink_to(self.root / 'empty.mp4')
        for index, reference in enumerate(('absent.mp4', 'empty.mp4', 'link.mp4',
                                           '../escape.mp4', 'https://example.test/a.mp4',
                                           '/absolute.mp4', 'segment.mp4?token=PRIVATE-CANARY')):
            playlist = self.root / f'playlist-{index}.m3u8'
            media.write_private(playlist, '#EXTM3U\n' + reference + '\n')
            with self.subTest(reference=reference), self.assertRaises(media.FixtureError):
                media.hls_dependencies(playlist)
        media.write_private(self.root / 'blank.m3u8', '#EXTM3U\n')
        with self.assertRaises(media.FixtureError):
            media.hls_dependencies(self.root / 'blank.m3u8')


if __name__ == '__main__':
    unittest.main()
