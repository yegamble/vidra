import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import recovery_release_acceptance as recovery
import recovery_release_export as export


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


# The drill was written for v0.6.4 and read its candidate, expected ledgers,
# installer, frozen deployment hashes and pinned prod overlay from one hard-coded
# directory, so it could not be pointed at the v0.6.5 stage being prepared now.
# The baseline is an argument whose default keeps every v0.6.4 record valid.
class BaselineTest(unittest.TestCase):
    def test_candidate_is_read_from_the_chosen_baseline(self):
        baseline = Path(tempfile.mkdtemp())
        (baseline / 'candidate.json').write_text(json.dumps({'tag': 'v0.6.5', 'platform': 'linux/amd64'}))
        self.assertEqual(recovery.load_candidate(baseline)['tag'], 'v0.6.5')

    def test_a_baseline_without_a_candidate_manifest_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            recovery.load_candidate(Path(tempfile.mkdtemp()))

    def test_a_candidate_without_a_release_tag_is_refused(self):
        baseline = Path(tempfile.mkdtemp())
        (baseline / 'candidate.json').write_text(json.dumps({'platform': 'linux/amd64'}))
        with self.assertRaises(ValueError):
            recovery.load_candidate(baseline)

    def test_the_default_baseline_keeps_the_v064_drill_unchanged(self):
        args = recovery.build_parser().parse_args(['snapshot', '--stage', '/tmp/attempt'])
        self.assertEqual(args.baseline, recovery.DEFAULT_BASELINE)
        self.assertEqual(str(recovery.DEFAULT_BASELINE), '/root/vidra-v064-runtime')

    def test_baseline_flag_selects_another_candidates_stage(self):
        args = recovery.build_parser().parse_args(
            ['restore', '--stage', '/tmp/attempt', '--baseline', '/root/vidra-v065-runtime'])
        self.assertEqual(args.baseline, Path('/root/vidra-v065-runtime'))


# A dump, or an outage clock, recorded on one release and restored onto another
# rebuilds the wrong images and then passes every downstream comparison, because
# both sides of that comparison came from the same wrong evidence.
class RecordedTagTest(unittest.TestCase):
    def test_evidence_from_the_candidate_being_restored_is_accepted(self):
        recovery.check_recorded_tag('source-loss', {'candidate_tag': 'v0.6.5'}, {'tag': 'v0.6.5'})

    def test_a_dump_from_another_release_cannot_be_restored(self):
        with self.assertRaises(ValueError):
            recovery.check_recorded_tag('backup', {'candidate_tag': 'v0.6.4'}, {'tag': 'v0.6.5'})

    def test_a_record_without_a_tag_is_refused_not_assumed_to_match(self):
        with self.assertRaises(ValueError):
            recovery.check_recorded_tag('source-loss', {'status': 'PASS'}, {'tag': 'v0.6.4'})


class ExportTest(unittest.TestCase):
    def test_health_probe_output_is_hashed_not_exported(self):
        value = export.hash_health_output({'Health': {'Log': [{'Output': 'token=abc'}]}})
        self.assertNotIn('Output', value['Health']['Log'][0])
        self.assertEqual(len(value['Health']['Log'][0]['output_sha256']), 64)

    def test_any_host_secret_in_any_file_refuses_the_export(self):
        files = {'a/result.json': b'{"ok": true}', 'b/commands.json': b'["--password", "hunter2-long-secret"]'}
        self.assertEqual(export.leaks(files, {'hunter2-long-secret'}), ['b/commands.json'])
        self.assertEqual(export.leaks({'a/result.json': b'{}'}, {'hunter2-long-secret'}), [])

    # The v0.6.4 drill exports were scanned by a revision that loaded secrets
    # only from files that happened to exist and recorded nothing about what it
    # loaded, so "no secret found" could not be told from "no secret looked
    # for". The scan set must be recorded, key-id values count, and an export
    # with an empty env scan set is refused rather than certified.
    def test_key_id_values_count_as_secrets(self):
        self.assertTrue(export.SECRET_KEY.search('B2_KEY_ID'))
        self.assertTrue(export.SECRET_KEY.search('AWS_ACCESS_KEY_ID'))
        self.assertFalse(export.SECRET_KEY.search('HTTP_PORT'))

    def test_host_secrets_records_what_it_loaded(self):
        root = Path(tempfile.mkdtemp())
        env = root / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\nB2_KEY_ID=0012345678abcdef\nSHORT_SECRET=abc\n'
                       '# PASSWORD=commented-out-1\nHTTP_PORT=8080\n')
        secrets, loaded = export.host_secrets(root, env_file=env, bucket_key_file=root / 'absent.json',
                                              owner_file=root / 'absent-owner.json')
        self.assertEqual(secrets, {'abcdefgh1234', '0012345678abcdef'})
        self.assertEqual(loaded, {'env': 2, 'bucket_key': False, 'mfa': False, 'owner': False})

    def test_export_with_no_env_secret_loaded_is_refused(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        with self.assertRaises(SystemExit):
            export.export(drill, drill / 'out', ['stage'], env_file=drill / 'absent.env',
                          bucket_key_file=drill / 'absent.json', owner_file=drill / 'absent-owner.json')
        self.assertFalse((drill / 'out').exists())

    def test_export_manifest_records_the_scan_set(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        (drill / 'private').mkdir()
        (drill / 'private/mfa.json').write_text('{"secret": "JBSWY3DPEHPK3PXP"}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        manifest = export.export(drill, drill / 'out', ['stage'], env_file=env,
                                 bucket_key_file=drill / 'absent.json', owner_file=drill / 'absent-owner.json')
        written = json.loads((drill / 'out/artifact-hashes.json').read_text())
        self.assertEqual(written['secrets_loaded'], {'env': 1, 'bucket_key': False, 'mfa': True, 'owner': False})
        self.assertEqual(written['files'], manifest)
        self.assertEqual(list(manifest), ['stage/result.json'])

    # A v0.6.5 host keeps its bucket key and owner fixture under v065 paths. The
    # v0.6.4 exporter read every source "if it exists", so run there it scanned
    # neither the B2 credential nor the owner password and still certified the
    # export clean. A source the exporter NAMES must be present, or refused.
    def test_a_named_secret_source_that_is_missing_refuses_the_export(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        with self.assertRaises(SystemExit):
            export.export(drill, drill / 'out', ['stage'], required=export.REQUIRED_SOURCES,
                          env_file=env, bucket_key_file=drill / 'absent.json',
                          owner_file=drill / 'absent-owner.json')
        self.assertFalse((drill / 'out').exists())

    def test_every_named_source_present_is_scanned_and_recorded(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        key = drill / 'b2-key.json'
        key.write_text(json.dumps({'access_key': '0012345678abcdef', 'secret_key': 'K005longsecretvalue'}))
        owner = drill / 'owner.json'
        owner.write_text(json.dumps({'password': 'owner-password-long'}))
        export.export(drill, drill / 'out', ['stage'], required=export.REQUIRED_SOURCES,
                      env_file=env, bucket_key_file=key, owner_file=owner)
        written = json.loads((drill / 'out/artifact-hashes.json').read_text())
        self.assertEqual(written['secrets_loaded'], {'env': 1, 'bucket_key': True, 'mfa': False, 'owner': True})

    def test_the_owner_fixture_is_derived_from_the_baseline(self):
        self.assertEqual(export.owner_path(Path('/root/vidra-v065-runtime')),
                         Path('/root/vidra-v065-runtime/private/owner.json'))

    def test_a_foreign_baseline_with_the_default_bucket_key_is_refused(self):
        # Forgetting --b2-key on a v0.6.5 host must not quietly scan a leftover
        # v0.6.4 key file and report a covered scan.
        with self.assertRaises(SystemExit):
            export.main(['drill', 'out', 'stage', '--baseline', '/root/vidra-v065-runtime'])


if __name__ == '__main__':
    unittest.main()
