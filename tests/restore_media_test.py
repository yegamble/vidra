"""Recovery acceptance must refuse missing or unverifiable media before app startup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RestoreMediaTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ('deploy', 'env', 'bin'):
            (self.root / directory).mkdir()
        for name in ('restore.sh', 'lib.sh'):
            shutil.copy2(ROOT / 'deploy' / name, self.root / 'deploy' / name)
        (self.root / 'env/production.env').write_text(
            'POSTGRES_DB=vidra\nPOSTGRES_USER=vidra\nVIDRA_CORE_TAG=v0.7.8\nVIDRA_SEARCH_TAG=v0.7.8\n')
        (self.root / 'deploy/Caddyfile.local').write_text('localhost {}\n')
        (self.root / 'synthetic.dump').write_bytes(b'synthetic archive; no database is contacted')
        self.calls = self.root / 'calls.jsonl'
        docker = self.root / 'bin/docker'
        docker.write_text('''#!/usr/bin/env python3
import json,os,sys
a=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(a)+'\\n')
if a[:2]==['compose','version']: print('2.24.0')
elif a[-3:]==['ps','-q','postgres']: print('synthetic-postgres')
elif 'verify-blobs' in a:
 if '--json' in a: print(os.environ.get('VERIFY_REPORT','{"deep_verification_version":1}'))
 sys.exit(int(os.environ['VERIFY_EXIT']))
elif a[-2:]==['migrate','embedded-max']: print('188')
elif '--data-only' in a:
 t=a[a.index('-t')+1]; print('COPY public.'+t+' (version, dirty) FROM stdin;\\n183\\tf\\n\\\\.')
elif a[0]=='cp' or (a[0]=='exec' and any(x in a for x in ('pg_restore','dropdb','createdb','rm'))): pass
elif a[0]=='compose' and ('stop' in a or 'up' in a or a[-1] in ('migrate','search-migrate')): pass
else: raise SystemExit('unexpected docker invocation: '+repr(a))
''')
        docker.chmod(0o755)
        curl = self.root / 'bin/curl'
        curl.write_text('#!/bin/sh\nexit 0\n')
        curl.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.root / 'bin') + ':' + os.environ['PATH'],
                    'CALLS': str(self.calls), 'ENV_FILE': 'env/production.env',
                    'VIDRA_EXTERNAL_POSTGRES': 'false', 'VIDRA_EXTERNAL_REDIS': 'false',
                    'RESTORE_MEDIA_TIMEOUT': '24h'}

    def run_restore(self, exit_code, strict=True, **env):
        return subprocess.run(['bash', 'deploy/restore.sh', '--yes',
                               *(['--require-media-consistent'] if strict else []), 'synthetic.dump'],
                              cwd=self.root, env={**self.env, 'VERIFY_EXIT': str(exit_code), **env},
                              capture_output=True, text=True, timeout=15)

    def recorded(self):
        return [json.loads(s) for s in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_strict_success_requires_hash_and_deep_before_startup(self):
        run = self.run_restore(0, RESTORE_MEDIA_TIMEOUT='36h')
        self.assertEqual(run.returncode, 0, run.stderr)
        calls = self.recorded()
        verify = next(i for i, a in enumerate(calls) if 'verify-blobs' in a)
        startup = next(i for i, a in enumerate(calls) if 'up' in a)
        self.assertLess(verify, startup)
        self.assertEqual(calls[verify][-5:], ['verify-blobs', '--hash', '--deep', '--json', '--timeout=36h'])

    def test_old_or_invalid_success_report_cannot_qualify_recovery(self):
        for report in ('{}', 'not json', '[]', '{"deep_verification_version":true}',
                       '{"deep_verification_version":0}', '{"deep_verification_version":2}'):
            with self.subTest(report=report):
                self.calls.unlink(missing_ok=True)
                run = self.run_restore(0, VERIFY_REPORT=report)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('strict media verification', run.stderr)
                self.assertFalse(any('up' in a for a in self.recorded()))

    def test_strict_missing_unreachable_and_unknown_failures_keep_apps_stopped(self):
        for code in (3, 1, 7):
            with self.subTest(code=code):
                self.calls.unlink(missing_ok=True)
                run = self.run_restore(code)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertIn('strict media verification', run.stderr)
                self.assertTrue(any('verify-blobs' in a for a in self.recorded()))
                self.assertFalse(any('up' in a for a in self.recorded()))
                self.assertNotIn('restore complete', run.stdout)

    def test_default_emergency_restore_still_warns_and_starts_apps(self):
        for code in (3, 1):
            with self.subTest(code=code):
                self.calls.unlink(missing_ok=True)
                run = self.run_restore(code, strict=False)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn('WARNING', run.stderr)
                verify = next(a for a in self.recorded() if 'verify-blobs' in a)
                self.assertEqual(verify[-2:], ['verify-blobs', '--timeout=10m'])
                self.assertTrue(any('up' in a for a in self.recorded()))

    def test_invalid_strict_timeout_refuses_before_docker_or_database_actions(self):
        for timeout in ('0h', '-1h', 'forever', '1h;false', '999999999999999999h'):
            with self.subTest(timeout=timeout):
                run = self.run_restore(0, RESTORE_MEDIA_TIMEOUT=timeout)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('RESTORE_MEDIA_TIMEOUT', run.stderr)
                self.assertEqual(self.recorded(), [])
