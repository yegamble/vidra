"""Exercise comment-approval rollback safety through the real deploy script."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = '0161_comment_approval.up.sql'
DOCKER_STUB = r'''#!/bin/sh
printf 'docker %s\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo v2.30.0 ;;
  *" ps -q postgres") echo pgcid ;;
  exec*"FROM comments WHERE held_for_review"*)
    case "$COMMENT_ANSWER" in
      err) echo 'psql: error: connection to server failed' >&2; exit 2 ;;
      timeout) echo 'ERROR: canceling statement due to statement timeout' >&2; exit 1 ;;
      old|partial) echo 'ERROR: column "held_for_review" does not exist' >&2; exit 1 ;;
    esac
    printf '%b\n' "$COMMENT_ANSWER" ;;
  exec*"FROM videos WHERE comments_policy"*)
    [ "$COMMENT_ANSWER" != partial ] || { echo t; exit 0; }
    echo f ;;
  exec*"SELECT EXISTS"*|exec*"FROM watched_word_lists"*|exec*"FROM oidc_providers"*) echo f ;;
esac
exit 0
'''


class RollbackCommentApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.tree = base / 'tree'
        (self.tree / 'deploy').mkdir(parents=True)
        (self.tree / 'env').mkdir()
        for name in ('rollback.sh', 'lib.sh', 'checkout-hygiene.py', 'backup-env.sh',
                     'release-mapping.py'):
            shutil.copyfile(ROOT / 'deploy' / name, self.tree / 'deploy' / name)
        shutil.copytree(ROOT / 'releases', self.tree / 'releases')
        (self.tree / 'vidra-bundle.manifest').write_text('tag=v0.8.1\ncore_schema_version=0182\n')
        self.env_file = self.tree / 'env/production.env'
        self.env_file.write_text('VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\nPOSTGRES_DB=vidra\n'
                                 'VIDRA_CORE_TAG=v0.8.1\nVIDRA_USER_TAG=v0.8.1\nVIDRA_SEARCH_TAG=v0.7.3\n')
        (base / 'home').mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()
        self.log = base / 'stub.log'
        for name, body in (('docker', DOCKER_STUB), ('git', '#!/bin/sh\nexit 0\n'),
                           ('curl', '#!/bin/sh\nexit 0\n')):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def rollback(self, *args, answer=r'f\nf'):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(
            ['bash', str(self.tree / 'deploy/rollback.sh'), *args],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                 'HOME': str(self.temp.name) + '/home', 'STUB_LOG': str(self.log),
                 'READY_TIMEOUT': '1', 'VIDRA_RECORD_FETCH': '0', 'COMMENT_ANSWER': answer},
            capture_output=True, text=True, cwd=str(self.tree))
        return result.returncode, result.stdout + result.stderr

    def calls(self):
        return self.log.read_text() if self.log.exists() else ''

    def assert_untouched(self, before, out):
        self.assertEqual(self.env_file.read_bytes(), before, out)
        for mutation in (' pull', ' up -d', 'UPDATE ', 'DELETE '):
            self.assertNotIn(mutation, self.calls(), out)
        self.assertNotIn('env snapshot:', out)

    def test_each_unsafe_state_refuses_even_with_unchecked_override(self):
        for answer in (r't\nf', r'f\nt', r't\nt'):
            for flags in ((), ('--allow-unchecked-comment-approval',)):
                with self.subTest(answer=answer, flags=flags):
                    before = self.env_file.read_bytes()
                    code, out = self.rollback('v0.7.7', *flags, answer=answer)
                    self.assertNotEqual(code, 0, out)
                    self.assertIn(f'does not carry migration {MIGRATION}', out)
                    self.assertIn('publicly display held comments', out)
                    self.assertIn('Nothing was changed', out)
                    self.assert_untouched(before, out)

    def test_no_approval_data_proceeds(self):
        code, out = self.rollback('v0.7.7')
        self.assertEqual(code, 0, out)
        self.assertIn('no held comments or approval-only videos exist', out)
        self.assertIn(' up -d', self.calls())

    def test_pre_migration_schema_still_checks_policy(self):
        code, out = self.rollback('v0.7.7', answer='old')
        self.assertEqual(code, 0, out)
        self.assertIn('FROM videos WHERE comments_policy', self.calls())
        before = self.env_file.read_bytes()
        code, out = self.rollback('v0.7.7', answer='partial')
        self.assertNotEqual(code, 0, out)
        self.assertIn('publicly display held comments', out)
        self.assert_untouched(before, out)

    def test_unknown_target_requires_explicit_override_when_data_exists(self):
        before = self.env_file.read_bytes()
        code, out = self.rollback('--core', 'v0.7.9', answer=r't\nf')
        self.assertNotEqual(code, 0, out)
        self.assertIn('could not be placed', out)
        self.assert_untouched(before, out)
        code, out = self.rollback('--core', 'v0.7.9', '--allow-unchecked-comment-approval', answer=r't\nf')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING: comment-approval check NOT settled', out)

    def test_known_compatible_target_does_not_query_comments(self):
        data = json.loads((ROOT / 'releases' / 'v0.7.7.json').read_text())
        data['release'] = 'v0.8.0'
        data['components']['core']['tag'] = 'v0.8.0'
        data['core_schema_version'] = 161
        data['core_migrations'] = ['0001_init.up.sql', MIGRATION]
        (self.tree / 'releases' / 'v0.8.0.json').write_text(json.dumps(data))
        code, out = self.rollback('v0.8.0', answer=r't\nt')
        self.assertEqual(code, 0, out)
        self.assertIn(f'carries migration {MIGRATION}', out)
        self.assertNotIn('FROM comments', self.calls())

    def test_frontend_only_rollback_does_not_query_comments(self):
        code, out = self.rollback('--user', 'v0.7.7', answer=r't\nt')
        self.assertEqual(code, 0, out)
        self.assertIn('comment-approval check: core is not being rolled back', out)
        self.assertNotIn('FROM comments', self.calls())

    def test_errors_timeouts_and_malformed_answers_fail_closed(self):
        for answer in ('err', 'timeout', '', 't', r'f\nf\nf', r'f\ninvalid'):
            with self.subTest(answer=answer):
                before = self.env_file.read_bytes()
                code, out = self.rollback('v0.7.7', answer=answer)
                self.assertNotEqual(code, 0, out)
                self.assertIn('--allow-unchecked-comment-approval', out)
                self.assert_untouched(before, out)
                code, out = self.rollback('v0.7.7', '--allow-unchecked-comment-approval', answer=answer)
                self.assertEqual(code, 0, out)
                self.assertIn('WARNING: comment-approval check NOT settled', out)

    def test_all_approval_queries_are_bounded_and_read_only(self):
        self.rollback('v0.7.7', answer='old')
        queries = [line for line in self.calls().splitlines() if ' exec ' in line and
                   ('held_for_review' in line or 'comments_policy' in line)]
        self.assertEqual(len(queries), 2)
        for query in queries:
            for bound in ('default_transaction_read_only=on', 'statement_timeout=15s',
                          'lock_timeout=5s', 'PGCONNECT_TIMEOUT=10'):
                self.assertIn(bound, query)


if __name__ == '__main__':
    unittest.main()
