"""Negative fixtures for wiring and the real Stop hook (no network or npm)."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vertical_slice_completeness', ROOT / 'scripts/ci/check-vertical-slice-completeness.py')
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

YAML = '''openapi: 3.0.3
paths:
  /api/v1/auth/oauth/{provider}/callback:
    get:
      description: Failure `access_denied`.
  /api/v1/auth/atproto/callback:
    get:
      description: Failure `access_denied`.
  /api/v1/me/example/{id}:
    get:
      operationId: getExample
    delete:
      operationId: deleteExample
components:
  schemas: {}
'''
OAUTH = '''export function oauthErrorMessage(code: string): string {
  switch(code) { case "access_denied": return "Denied"; default: return "Unknown"; }
}'''
CLIENT = '''export const api = {
  getExample: (id: string) => apiRequest<Example>(
    `/api/v1/me/example/${encodeURIComponent(id)}`, { signal }),
  deleteExample: (id: string) => apiRequest<void>(
    `/api/v1/me/example/${encodeURIComponent(id)}`, { method: "DELETE" }),
};'''


def fixture():
    return {
        'app/page.tsx': 'import Widget from "@/components/Widget"; export default Widget;',
        'components/Widget.tsx': '''import { api as client } from "@/lib/api";
          export default function Widget() { client.getExample("x"); client.deleteExample("x"); }''',
        'components/auth/OAuthButtons.tsx': OAUTH,
        'lib/api/index.ts': 'export { api } from "./endpoints";',
        'lib/api/endpoints.ts': CLIENT,
    }


def findings(files=None, yaml=YAML):
    return {f.key for f in gate.static_findings(yaml, files or fixture())
            if f.key != 'orphan:components/auth/OAuthButtons.tsx'}


class StaticGateTest(unittest.TestCase):
    def test_complete_wrappers_match_methods_templates_barrels_and_import_aliases(self):
        self.assertEqual(findings(), set())

    def test_missing_method_not_hidden_by_same_path_get(self):
        files = fixture()
        files['lib/api/endpoints.ts'] = CLIENT.replace('method: "DELETE"', 'method: "POST"')
        self.assertIn('endpoint:DELETE:/api/v1/me/example/{}', findings(files))

    def test_dynamic_method_is_not_misread_as_default_get(self):
        files = fixture()
        files['lib/api/endpoints.ts'] = CLIENT.replace('{ signal }', '{ method: requestedMethod, signal }')
        self.assertIn('endpoint:GET:/api/v1/me/example/{}', findings(files))

    def test_unused_wrapper_not_satisfied_by_comment_string_or_test(self):
        files = fixture()
        files['components/Widget.tsx'] = '''import { api } from "@/lib/api";
          // api.deleteExample("x");
          const text = 'api.deleteExample("x")'; api.getExample("x");'''
        files['components/Widget.test.tsx'] = 'api.deleteExample("x");'
        # File filters run before the pure scanner.
        files = {f: s for f, s in files.items() if gate.is_source(f)}
        self.assertIn('endpoint:DELETE:/api/v1/me/example/{}', findings(files))

    def test_unmounted_consumer_does_not_satisfy_endpoint(self):
        files = fixture()
        files['app/page.tsx'] = 'export default function Page() { return null; }'
        found = findings(files)
        self.assertIn('orphan:components/Widget.tsx', found)
        self.assertIn('endpoint:GET:/api/v1/me/example/{}', found)

    def test_orphan_cycle_test_import_and_type_import_do_not_mount_components(self):
        files = fixture()
        files['components/A.tsx'] = 'import B from "./B"; export default B;'
        files['components/B.tsx'] = 'import A from "./A"; export default A;'
        files['app/page.tsx'] += ' import type { A } from "@/components/A";'
        self.assertTrue({'orphan:components/A.tsx', 'orphan:components/B.tsx'} <= findings(files))

    def test_dynamic_import_mounts_component(self):
        files = fixture()
        files['app/page.tsx'] = 'const Widget = dynamic(() => import("@/components/Widget"));'
        self.assertEqual(findings(files), set())

    def test_oauth_case_must_be_in_error_function_not_comment_or_other_function(self):
        files = fixture()
        files['components/auth/OAuthButtons.tsx'] = OAUTH + '''
          // case "new_policy":
          function other(code) { switch(code) { case "new_policy": return "x"; } }'''
        yaml = YAML.replace('Failure `access_denied`.', 'Failure `access_denied` or `new_policy`.')
        self.assertIn('oauth:new_policy', findings(files, yaml))

    def test_openapi_unsupported_syntax_is_error_not_silent_empty_pass(self):
        with self.assertRaisesRegex(ValueError, 'unsupported OpenAPI'):
            gate.openapi_operations(YAML.replace('  /api/v1/me/example/{id}:', '  "/api/v1/me/example/{id}":'))

    def test_factory_expansion_keeps_method_and_consumer_identity(self):
        files = fixture()
        files['lib/api/endpoints.ts'] = '''function endpoints(base: string) {
          const one = (id: string) => `${base}/${encodeURIComponent(id)}`;
          return {
            getExample: (id: string) => apiRequest<Example>(one(id)),
            deleteExample: (id: string) => apiRequest<void>(one(id), {method: "DELETE"}),
          };
        }
        export const api = endpoints("/api/v1/me/example");'''
        self.assertEqual(findings(files), set())

    def test_no_broad_me_or_admin_allowlist(self):
        self.assertFalse(any(p.startswith(('/api/v1/me/', '/api/v1/admin/'))
                             for _, p in gate.BACKEND_ONLY_PATHS))
        yaml = YAML.replace('components:', '  /api/v1/admin/new-feature:\n    post:\n      operationId: new\ncomponents:')
        self.assertIn('endpoint:POST:/api/v1/admin/new-feature', findings(yaml=yaml))


class ContractAndMigrationTest(unittest.TestCase):
    def test_type_generation_uses_temporary_output_and_detects_byte_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            user = Path(temp)
            (user / 'node_modules/.bin').mkdir(parents=True)
            (user / 'node_modules/.bin/openapi-typescript').touch()
            (user / 'lib/api').mkdir(parents=True)
            committed = user / 'lib/api/generated.ts'
            committed.write_text('old types')
            def run(command, **kwargs):
                if '-o' in command:
                    out = Path(command[-1])
                    self.assertNotEqual(out, committed)
                    out.write_text('new types')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(gate.subprocess, 'run', side_effect=run):
                self.assertTrue(any('stale' in p for p in gate.contract_findings(user, user)))
            self.assertEqual(committed.read_text(), 'old types')

    def test_migration_ceiling_inventory_and_classification_fail_independently(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'migrations').mkdir()
            migration = root / 'migrations/0182_example.up.sql'
            migration.write_text('CREATE TABLE new_secret (id uuid);')
            catalogue = root / 'catalogue.py'
            catalogue.write_text('TABLES_ADDED = {181: ()}\nCATALOGUE = {}\nEXCLUDED_TABLES = {}\n')
            self.assertIn('exceeds', gate.migration_findings(root, catalogue)[0])
            catalogue.write_text('TABLES_ADDED = {182: ()}\nCATALOGUE = {}\nEXCLUDED_TABLES = {}\n')
            self.assertEqual(len(gate.migration_findings(root, catalogue)), 2)
            catalogue.write_text("TABLES_ADDED = {182: ('new_secret',)}\nCATALOGUE = {'new_secret': (182, ())}\nEXCLUDED_TABLES = {}\n")
            self.assertEqual(gate.migration_findings(root, catalogue), [])


class SessionBaselineTest(unittest.TestCase):
    def test_merged_in_session_unwired_endpoint_is_not_forgiven_by_updated_main(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repos = {}
            for name in ('core', 'user'):
                repo = root / ('vidra-' + name)
                repo.mkdir()
                subprocess.run(['git', 'init', '-b', 'main', str(repo)], check=True, capture_output=True)
                for key, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
                    subprocess.run(['git', '-C', str(repo), 'config', key, value], check=True)
                repos[name] = repo
            def commit(repo, message):
                subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
                subprocess.run(['git', '-C', str(repo), 'commit', '-m', message], check=True, capture_output=True)
            (repos['core'] / 'api').mkdir()
            (repos['core'] / 'api/openapi.yaml').write_text(YAML)
            for file, content in fixture().items():
                target = repos['user'] / file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            for repo in repos.values():
                commit(repo, 'session starts')
            with patch.object(sys, 'stdin', io.StringIO('{"session_id":"session"}')):
                gate.record_session_baseline(root)
            baseline = next((root / '.claude/hooks/.state').glob('*.baseline.json'))
            original = baseline.read_bytes()
            yaml = YAML.replace('components:', '  /api/v1/admin/new-feature:\n    post:\n      operationId: newFeature\ncomponents:')
            (repos['core'] / 'api/openapi.yaml').write_text(yaml)
            commit(repos['core'], 'backend merged without frontend')
            subprocess.run(['git', '-C', str(repos['core']), 'update-ref', 'refs/remotes/origin/main', 'HEAD'], check=True)
            # SessionStart also fires on resume/compact. It cannot reset debt.
            with patch.object(sys, 'stdin', io.StringIO('{"session_id":"session"}')):
                gate.record_session_baseline(root)
            self.assertEqual(baseline.read_bytes(), original)
            args = ['--root', str(root), '--baseline-file', str(baseline)]
            with patch.object(gate, 'contract_findings', return_value=[]), patch.object(gate, 'migration_findings', return_value=[]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(gate.main(args), 1)
                self.assertIn('POST /api/v1/admin/new-feature', output.getvalue())
            # No static changes never allows stale generated types through.
            with patch.object(gate, 'contract_findings', return_value=['generated.ts is stale']), patch.object(gate, 'migration_findings', return_value=[]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(gate.main(args), 1)


class StopHookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / 'remote.git'
        self.git(self.base, 'init', '--bare', str(self.remote))
        self.repo = self.base / 'vidra'
        self.git(self.base, 'clone', str(self.remote), str(self.repo))
        self.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        self.git(self.repo, 'config', 'user.name', 'Test')
        self.git(self.repo, 'checkout', '-b', 'main')
        (self.repo / 'tracked').write_text('base')
        self.git(self.repo, 'add', 'tracked')
        self.git(self.repo, 'commit', '-m', 'base')
        self.git(self.repo, 'push', '-u', 'origin', 'main')
        self.hook = ROOT / '.claude/hooks/finished-means-merged.sh'

    def git(self, cwd, *args):
        return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()

    def stop(self, repo=None, components=None):
        env = os.environ | {'CLAUDE_PROJECT_DIR': str(repo or self.repo)}
        for component in ('CORE', 'USER', 'SEARCH'):
            env[f'VIDRA_{component}_ROOT'] = str((components or {}).get(component, self.base / f'missing-{component}'))
        return subprocess.run(['bash', str(self.hook)], input='{"session_id":"../../unsafe"}',
                              env=env, text=True, capture_output=True)

    def test_clean_pushed_main_passes_and_untracked_secret_is_ignored(self):
        (self.repo / 'local.env').write_text('never commit')
        self.assertEqual(self.stop().returncode, 0)

    def test_pushed_feature_branch_is_blocked_even_after_six_attempts(self):
        self.git(self.repo, 'checkout', '-b', 'feature')
        self.git(self.repo, 'push', '-u', 'origin', 'feature')
        for _ in range(8):
            result = self.stop()
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('unmerged branch', result.stdout)
        self.assertIn('6/6', result.stdout)
        self.assertFalse((self.base / 'unsafe').exists())

    def test_detached_dirty_checkout_is_blocked(self):
        self.git(self.repo, 'checkout', '--detach')
        (self.repo / 'tracked').write_text('dirty')
        self.assertEqual(self.stop().returncode, 2)

    def test_detached_commit_outside_main_is_blocked(self):
        self.git(self.repo, 'checkout', '--detach')
        (self.repo / 'tracked').write_text('new')
        self.git(self.repo, 'commit', '-am', 'new')
        self.assertIn('not contained', self.stop().stdout)

    def test_worktree_git_file_is_checked(self):
        worktree = self.base / 'worktree'
        self.git(self.repo, 'worktree', 'add', '-b', 'worktree', str(worktree))
        self.assertEqual(self.stop(worktree).returncode, 2)

    def test_main_with_unpushed_commit_blocks(self):
        (self.repo / 'tracked').write_text('new')
        self.git(self.repo, 'commit', '-am', 'unpushed')
        result = self.stop()
        self.assertEqual(result.returncode, 2)
        self.assertIn('not pushed', result.stdout)

    def test_four_present_repos_invoke_completeness_and_block_on_failure(self):
        script = self.repo / 'scripts/ci/check-vertical-slice-completeness.py'
        script.parent.mkdir(parents=True)
        script.write_text('print("fixture contract broken")\nraise SystemExit(1)\n')
        components = {}
        for component in ('CORE', 'USER', 'SEARCH'):
            path = self.base / ('vidra-' + component.lower())
            self.git(self.base, 'clone', '--branch', 'main', str(self.remote), str(path))
            components[component] = path
        result = self.stop(components=components)
        self.assertEqual(result.returncode, 2)
        self.assertIn('fixture contract broken', result.stdout)

    def test_remote_fetch_failure_blocks_instead_of_trusting_stale_main(self):
        self.git(self.repo, 'remote', 'set-url', 'origin', str(self.base / 'missing.git'))
        self.assertIn('cannot refresh', self.stop().stdout)


if __name__ == '__main__':
    unittest.main()
