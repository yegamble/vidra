"""Backup artifact confidentiality and failed-dump publication regressions."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.environ.pop('BACKUP_OFFSITE_PLAINTEXT', None)
        for directory in ('deploy', 'env', 'bin'):
            (self.root / directory).mkdir()
        for name in ('backup.sh', 'lib.sh'):
            shutil.copy2(ROOT / 'deploy' / name, self.root / 'deploy' / name)
        (self.root / 'env/production.env').write_text('POSTGRES_DB=vidra\nPOSTGRES_USER=vidra\n')
        (self.root / 'deploy/Caddyfile.local').write_text('localhost {}\n')
        docker = self.root / 'bin/docker'
        docker.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:]
if args[0]=='compose' and args[-3:]==['ps','-q','postgres']:
 print('test-postgres')
elif 'pg_dump' in args:
 sys.stdout.buffer.write(b'synthetic archive')
 sys.exit(int(os.environ.get('DUMP_EXIT','0')))
elif 'pg_restore' in args:
 sys.stdin.buffer.read()
 root=pathlib.Path(os.environ['BACKUP_DIR'])
 pathlib.Path(os.environ['PROBE']).write_text(json.dumps({p.name:p.stat().st_mode & 0o777 for p in root.iterdir()}))
else:
 raise SystemExit('unexpected docker invocation')
''')
        docker.chmod(0o755)
        self.backups = self.root / 'backups'
        self.env = {**os.environ, 'PATH': str(self.root / 'bin') + ':' + os.environ['PATH'],
                    'BACKUP_DIR': str(self.backups), 'PROBE': str(self.root / 'probe.json'),
                    'ENV_FILE': 'env/production.env', 'HEALTHCHECKS_URL': '',
                    'BACKUP_RCLONE_REMOTE': '', 'BACKUP_S3_URI': '',
                    'CRYPT_REMOTES': '',
                    'VIDRA_EXTERNAL_POSTGRES': 'false', 'VIDRA_EXTERNAL_REDIS': 'false'}

    def run_backup(self, **env):
        return subprocess.run(['bash', '-c', 'umask 022; exec bash deploy/backup.sh'],
                              cwd=self.root, env={**self.env, **env}, capture_output=True, text=True)

    def configure_offsite(self, settings):
        with (self.root / 'env/production.env').open('a') as out:
            out.write(settings)
        for key in ('BACKUP_RCLONE_REMOTE', 'BACKUP_S3_URI', 'BACKUP_S3_ENDPOINT',
                    'HEALTHCHECKS_URL'):
            self.env.pop(key, None)
        self.env['CALLS'] = str(self.root / 'calls.jsonl')
        for name in ('rclone', 'aws', 'curl'):
            tool = self.root / 'bin' / name
            # `rclone config show <name>` is recorded as 'rclone-config' so the
            # upload counts below stay uploads, and answers `type = crypt` only
            # for the remote names listed in CRYPT_REMOTES.
            tool.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
if name=='rclone' and args[:2]==['config','show']:
 name='rclone-config'
 kind='crypt' if args[2] in os.environ.get('CRYPT_REMOTES','').split() else 's3'
 print('[' + args[2] + ']\\ntype = ' + kind + '\\nremote = r2:crypt-bucket')
with open(os.environ['CALLS'], 'a') as out:
 out.write(json.dumps([name, *args]) + '\\n')
''')
            tool.chmod(0o755)

    def offsite_calls(self, tool):
        path = self.root / 'calls.jsonl'
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [call[1:] for call in calls if call[0] == tool]

    def test_env_file_enables_encrypted_pair_and_backup_monitor(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE="offsite:backup folder"\n'
                               'HEALTHCHECKS_URL=https://monitor.invalid/backup\n')
        run = self.run_backup(CRYPT_REMOTES='offsite')
        self.assertEqual(run.returncode, 0, run.stderr)
        uploads = self.offsite_calls('rclone')
        self.assertEqual(len(uploads), 2, run.stdout)
        self.assertTrue(any('.dump.gz' in call[1] for call in uploads))
        self.assertTrue(any('.tar.gz' in call[1] for call in uploads))
        for call in uploads:
            self.assertEqual(call, ['copyto', call[1], 'offsite:backup folder/' + Path(call[1]).name])
        self.assertEqual([call[-1] for call in self.offsite_calls('curl')],
                         ['https://monitor.invalid/backup/start', 'https://monitor.invalid/backup'])

    def test_env_file_s3_endpoint_is_one_argument(self):
        self.configure_offsite('BACKUP_S3_URI=s3://candidate-backups/migration\n'
                               'BACKUP_S3_ENDPOINT=https://s3.us-east-005.backblazeb2.com\n'
                               'BACKUP_OFFSITE_PLAINTEXT=true\n')
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        uploads = self.offsite_calls('aws')
        self.assertEqual(len(uploads), 2, run.stdout)
        for call in uploads:
            self.assertEqual(call[:4], ['--endpoint-url', 'https://s3.us-east-005.backblazeb2.com', 's3', 'cp'])
            self.assertEqual(call[5], 's3://candidate-backups/migration/' + Path(call[4]).name)

    def test_process_overrides_file_and_explicit_empty_disables_offsite(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE=file-target:\n'
                               'HEALTHCHECKS_URL=https://monitor.invalid/backup\n')
        run = self.run_backup(BACKUP_RCLONE_REMOTE='override:', HEALTHCHECKS_URL='',
                              CRYPT_REMOTES='override')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(self.offsite_calls('rclone')), 2)
        self.assertTrue(all(call[-1].startswith('override:/') for call in self.offsite_calls('rclone')))
        self.assertEqual(self.offsite_calls('curl'), [])
        (self.root / 'calls.jsonl').unlink()
        run = self.run_backup(BACKUP_RCLONE_REMOTE='', HEALTHCHECKS_URL='')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('LOCAL COPY ONLY', run.stdout)
        self.assertEqual(self.offsite_calls('rclone'), [])
        self.assertEqual(self.offsite_calls('curl'), [])

    def install_age(self, exit_code=0):
        """A recording `age` stub: writes a recognisable ciphertext to its -o path."""
        tool = self.root / 'bin' / 'age'
        tool.write_text(f'''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['CALLS'], 'a') as out:
 out.write(json.dumps(['age', *sys.argv[1:]]) + '\\n')
if {exit_code}:
 sys.exit({exit_code})
open(sys.argv[sys.argv.index('-o') + 1], 'wb').write(b'AGE-CIPHERTEXT')
''')
        tool.chmod(0o755)

    def hide_real_age(self):
        """PATH without any real `age`: symlink every other tool from the dirs that hold it."""
        farm = self.root / 'noage'
        farm.mkdir()
        kept = []
        for d in os.environ['PATH'].split(':'):
            if not os.path.isdir(d) or not os.path.exists(os.path.join(d, 'age')):
                kept.append(d)
                continue
            for name in os.listdir(d):
                if name != 'age' and not (farm / name).exists():
                    os.symlink(os.path.join(d, name), farm / name)
        self.env['PATH'] = ':'.join([str(self.root / 'bin'), str(farm), *kept])

    def test_age_recipients_encrypt_every_offsite_file_and_upload_only_age_names(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE="offsite:backup folder"\n'
                               'BACKUP_AGE_RECIPIENTS="age1aaa, age1bbb"\n')
        self.install_age()
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        encrypts = self.offsite_calls('age')
        self.assertEqual(len(encrypts), 2, run.stdout)
        for call in encrypts:
            self.assertEqual(call[:4], ['-r', 'age1aaa', '-r', 'age1bbb'])
        uploads = self.offsite_calls('rclone')
        self.assertEqual(len(uploads), 2, run.stdout)
        for call in uploads:
            self.assertTrue(call[1].endswith('.age'), call)
            self.assertEqual(call[2], 'offsite:backup folder/' + Path(call[1]).name)
            self.assertFalse(Path(call[1]).exists(), 'ciphertext temp file must be removed')
        self.assertEqual(sorted(Path(c[1]).name[:-4] for c in uploads),
                         sorted(p.name for p in (*self.backups.glob('*.dump.gz'), *self.backups.glob('*.tar.gz'))))
        self.assertNotIn('WARNING: off-site', run.stdout)
        # Local copies stay plaintext so deploy/restore.sh is unchanged.
        self.assertEqual(len(list(self.backups.glob('*.dump.gz'))), 1)
        self.assertEqual(list(self.backups.glob('*.age')), [])

    def test_age_recipients_apply_to_s3_target_too(self):
        self.configure_offsite('BACKUP_S3_URI=s3://bucket/vidra\nBACKUP_AGE_RECIPIENTS=age1aaa\n')
        self.install_age()
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        uploads = self.offsite_calls('aws')
        self.assertEqual(len(uploads), 2, run.stdout)
        for call in uploads:
            self.assertTrue(call[2].endswith('.age') and call[3].endswith('.age'), call)

    def test_age_missing_aborts_before_any_upload(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE=offsite:\nBACKUP_AGE_RECIPIENTS=age1aaa\n')
        self.hide_real_age()
        run = self.run_backup()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('age is not installed', run.stderr)
        self.assertEqual(self.offsite_calls('rclone'), [])

    def test_age_failure_never_falls_back_to_plaintext(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE=offsite:\nBACKUP_AGE_RECIPIENTS=age1aaa\n')
        self.install_age(exit_code=1)
        run = self.run_backup()
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(self.offsite_calls('rclone'), [])
        self.assertEqual(list(self.backups.glob('.offsite-age.*')), [])

    def test_malformed_recipient_is_refused(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE=offsite:\nBACKUP_AGE_RECIPIENTS="age1aaa -o"\n')
        self.install_age()
        run = self.run_backup()
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(self.offsite_calls('age') + self.offsite_calls('rclone'), [])

    def assert_refused(self, run, tool):
        """The P0-1 contract: dump off-site, config archive NOT, run red."""
        self.assertNotEqual(run.returncode, 0, run.stdout)
        uploads = self.offsite_calls(tool)
        self.assertEqual(len(uploads), 1, run.stdout)
        self.assertTrue(any(arg.endswith('.dump.gz') for arg in uploads[0]), uploads)
        self.assertFalse(any('vidra-config-' in arg for call in uploads for arg in call), uploads)
        refusal = run.stdout + run.stderr
        for way_out in ('BACKUP_AGE_RECIPIENTS', 'crypt', 'BACKUP_OFFSITE_PLAINTEXT=true'):
            self.assertIn(way_out, refusal)
        # Both local files are still written: only the off-site copy is refused.
        self.assertEqual(len(list(self.backups.glob('vidra-config-*.tar.gz'))), 1)
        self.assertEqual(len(list(self.backups.glob('vidra-*.dump.gz'))), 1)
        # A refused run is not a full success: doctor's marker does not advance
        # and the dead-man's switch hears /fail, never the success ping.
        self.assertFalse((self.backups / 'last_success').exists())
        self.assertEqual([call[-1] for call in self.offsite_calls('curl')],
                         ['https://monitor.invalid/backup/start', 'https://monitor.invalid/backup/fail'])

    def test_plaintext_rclone_remote_refuses_config_archive_but_uploads_dump(self):
        # An explicit `false` is not an acknowledgement.
        self.configure_offsite('BACKUP_RCLONE_REMOTE=offsite:\n'
                               'HEALTHCHECKS_URL=https://monitor.invalid/backup\n'
                               'BACKUP_OFFSITE_PLAINTEXT=false\n')
        run = self.run_backup()
        self.assert_refused(run, 'rclone')
        self.assertEqual(self.offsite_calls('rclone-config'), [['config', 'show', 'offsite']])

    def test_s3_without_age_is_plaintext_and_refuses_config_archive(self):
        self.configure_offsite('BACKUP_S3_URI=s3://bucket/vidra\n'
                               'HEALTHCHECKS_URL=https://monitor.invalid/backup\n')
        run = self.run_backup()
        self.assert_refused(run, 'aws')

    def test_crypt_remote_uploads_both_without_age_or_plaintext_warning(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE="vault:nightly"\n')
        run = self.run_backup(CRYPT_REMOTES='vault')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(len(self.offsite_calls('rclone')), 2, run.stdout)
        self.assertEqual(self.offsite_calls('rclone-config'), [['config', 'show', 'vault']])
        self.assertNotIn('PLAINTEXT', run.stdout)
        self.assertTrue((self.backups / 'last_success').exists())

    def test_age_path_never_asks_rclone_about_crypt(self):
        self.configure_offsite('BACKUP_RCLONE_REMOTE=offsite:\nBACKUP_AGE_RECIPIENTS=age1aaa\n')
        self.install_age()
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(len(self.offsite_calls('rclone')), 2)
        self.assertEqual(self.offsite_calls('rclone-config'), [])

    def test_acknowledged_plaintext_uploads_both_and_warns(self):
        # Negative control for the refusal: the same non-crypt remote, with the
        # explicit acknowledgement, from the env file and from the process env.
        for setting, extra in (('BACKUP_OFFSITE_PLAINTEXT=true\n', {}),
                               ('', {'BACKUP_OFFSITE_PLAINTEXT': 'yes'})):
            with self.subTest(setting=setting, extra=extra):
                (self.root / 'env/production.env').write_text('POSTGRES_DB=vidra\nPOSTGRES_USER=vidra\n')
                shutil.rmtree(self.backups, ignore_errors=True)
                self.configure_offsite('BACKUP_RCLONE_REMOTE=offsite:\n' + setting)
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                run = self.run_backup(**extra)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                uploads = self.offsite_calls('rclone')
                self.assertEqual(len(uploads), 2, run.stdout)
                self.assertTrue(any('vidra-config-' in call[1] for call in uploads))
                warning = [l for l in run.stdout.splitlines() if 'WARNING' in l and 'BACKUP_AGE_RECIPIENTS' in l]
                self.assertEqual(len(warning), 1, run.stdout)
                self.assertIn('PLAINTEXT', warning[0])
                self.assertTrue((self.backups / 'last_success').exists())

    def test_local_only_run_does_not_warn_about_offsite_plaintext(self):
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn('BACKUP_AGE_RECIPIENTS', run.stdout)

    def test_archives_and_plaintext_verification_are_private_from_creation(self):
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        probe = json.loads((self.root / 'probe.json').read_text())
        self.assertTrue(any(name.endswith('.verify') for name in probe))
        for name, mode in probe.items():
            self.assertEqual(mode & 0o077, 0, name)
        for path in self.backups.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, path.name)
        self.assertEqual(stat.S_IMODE(self.backups.stat().st_mode), 0o700)

    def test_failed_dump_never_publishes_or_advances_success(self):
        self.backups.mkdir()
        marker = self.backups / 'last_success'
        marker.write_text('previous successful backup\n')
        run = self.run_backup(DUMP_EXIT='9')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(marker.read_text(), 'previous successful backup\n')
        self.assertEqual(list(self.backups.glob('*.dump.gz')), [])
        self.assertEqual(list(self.backups.glob('*.tar.gz')), [])
        partials = list(self.backups.glob('*.part'))
        self.assertEqual(len(partials), 1)
        self.assertEqual(stat.S_IMODE(partials[0].stat().st_mode) & 0o077, 0)


    def test_success_marker_is_replaced_not_rewritten_in_place(self):
        # A manual `sudo ./deploy/backup.sh` leaves a root-owned 0600 marker; the
        # 03:15 timer runs as the service user, which owns backups/ but not that
        # file, so writing through it fails AFTER the dump. A rename only needs
        # the directory, so the marker must arrive as a new file. (Asserted by
        # inode: the suite may run as root, which ignores the file's mode.)
        self.backups.mkdir(mode=0o700)
        marker = self.backups / 'last_success'
        marker.write_text('previous successful backup\n')
        marker.chmod(0o400)
        before = marker.stat().st_ino
        run = self.run_backup()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotEqual(marker.stat().st_ino, before)
        self.assertRegex(marker.read_text(), r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ \S+\.dump\.gz\n$')
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode) & 0o077, 0)
        self.assertEqual(list(self.backups.glob('last_success.*')), [])

if __name__ == '__main__':
    unittest.main()
