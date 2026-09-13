import io
import tarfile
import tempfile
import unittest
from pathlib import Path

import recovery_release_acceptance as recovery


def config_archive(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class BackupReportTest(unittest.TestCase):
    def test_one_matched_pair_is_the_backup(self):
        log = '[backup] done — database vidra-20260913T030813Z.dump.gz, config vidra-config-20260913T030813Z.tar.gz\n'
        self.assertEqual(recovery.parse_backup_done(log),
                         ('vidra-20260913T030813Z.dump.gz', 'vidra-config-20260913T030813Z.tar.gz'))

    def test_no_success_line_is_not_a_backup(self):
        with self.assertRaises(ValueError):
            recovery.parse_backup_done('[backup] ERROR pg_dump exited 1\n')

    def test_a_dump_and_config_from_different_runs_are_not_one_data_point(self):
        log = 'done — database vidra-20260913T030813Z.dump.gz, config vidra-config-20260912T030813Z.tar.gz'
        with self.assertRaises(ValueError):
            recovery.parse_backup_done(log)


class ConfigArchiveTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'env').mkdir()
        (self.root / 'deploy').mkdir()
        (self.root / 'env/production.env').write_bytes(b'MFA_KEY_KEK=x\n')
        (self.root / 'deploy/Caddyfile.local').write_bytes(b'secure.video.test {}\n')
        self.archive = self.root / 'config.tar.gz'

    def test_archive_matching_the_live_files_passes(self):
        self.archive.write_bytes(config_archive({'env/production.env': b'MFA_KEY_KEK=x\n',
                                                 'deploy/Caddyfile.local': b'secure.video.test {}\n'}))
        self.assertEqual(set(recovery.check_config_archive(self.archive, self.root)), recovery.CONFIG_MEMBERS)

    def test_an_archive_missing_the_caddyfile_cannot_restore(self):
        self.archive.write_bytes(config_archive({'env/production.env': b'MFA_KEY_KEK=x\n'}))
        with self.assertRaises(ValueError):
            recovery.check_config_archive(self.archive, self.root)

    def test_a_stale_env_file_is_refused(self):
        self.archive.write_bytes(config_archive({'env/production.env': b'MFA_KEY_KEK=rotated\n',
                                                 'deploy/Caddyfile.local': b'secure.video.test {}\n'}))
        with self.assertRaises(ValueError):
            recovery.check_config_archive(self.archive, self.root)


class FailedBackupTest(unittest.TestCase):
    before = {'last_success': 'a', 'vidra-20260913T040024Z.dump.gz': 'b'}

    def test_a_private_partial_is_the_documented_residue(self):
        after = dict(self.before, **{'vidra-20260913T040037Z.dump.gz.part': 'c'})
        self.assertEqual(recovery.check_failed_backup(self.before, after, 'pg_dump: error'),
                         ['vidra-20260913T040037Z.dump.gz.part'])

    def test_advancing_the_success_marker_is_advertising_success(self):
        with self.assertRaises(ValueError):
            recovery.check_failed_backup(self.before, dict(self.before, last_success='z'), 'pg_dump: error')

    def test_publishing_a_dump_is_advertising_success(self):
        after = dict(self.before, **{'vidra-20260913T040037Z.dump.gz': 'c'})
        with self.assertRaises(ValueError):
            recovery.check_failed_backup(self.before, after, 'pg_dump: error')

    def test_a_success_line_is_advertising_success(self):
        with self.assertRaises(ValueError):
            recovery.check_failed_backup(self.before, dict(self.before), '[backup] done — database x')


class FingerprintTest(unittest.TestCase):
    def test_sealed_secret_tables_are_part_of_the_data_point(self):
        self.assertIn('user_mfa', recovery.CATALOGUE)
        self.assertIn('mfa_recovery_codes', recovery.CATALOGUE)

    def test_table_names_are_never_interpolated_unchecked(self):
        with self.assertRaises(ValueError):
            recovery.fingerprint_sql('users; DROP TABLE users')

    def test_differences_are_reported_by_name(self):
        self.assertEqual(recovery.differing({'users': '1|a', 'videos': '2|b'}, {'users': '1|a', 'videos': '3|c'}), ['videos'])
        self.assertEqual(recovery.differing({'users': '1|a'}, {}), ['users'])


if __name__ == '__main__':
    unittest.main()
