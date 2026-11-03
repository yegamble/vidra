"""Hash-bound representative inputs must fail before browser/host execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TABLES = 'users channels videos comments playlists playlist_items channel_follows video_ratings video_tags video_chapters streaming_playlists video_files captions'.split()


class RepresentativeInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate = self.write('candidate.json', {'tag': 'v9.0.0'})
        self.source = {'peertube_schema_version': 1130, 'snapshot_sha256': 'a' * 64,
                       'media_manifest_sha256': 'b' * 64}
        self.expected = {'catalogue_delta': dict.fromkeys(TABLES, 0),
                         'preview': {'user': {'planned': 2}, 'video': {'planned': 3}, 'video_no_media': {'planned': 0}},
                         'import': {'video': {'imported': 3}, 'video_no_media': {'imported': 0}},
                         'repeat': {'video': {'skipped': 3}, 'video_no_media': {'imported': 0}}}
        self.spec = {'schema_version': 2, 'scope': 'representative',
                     'candidate_sha256': self.digest(self.candidate),
                     'target': {'origin': 'https://beta.example.test', 'project': 'private-beta',
                                'install_dir': '/opt/vidra', 'timeout_ms': 86400000}}
        self.freeze()

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def digest(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def freeze(self):
        for key, value in [('source', self.source), ('expectations', self.expected)]:
            path = self.write(key + '.json', value)
            self.spec[key] = {'path': path.name, 'sha256': self.digest(path)}
        self.input = self.write('inputs.json', self.spec)

    def invoke(self, mode='preview', run=None, prepared=None):
        code = """import {loadAcceptanceInputs, assertExpectedReport, assertPreparedSource} from './tests/peertube-acceptance-inputs.mjs';
const input = loadAcceptanceInputs(process.argv[1], process.argv[2], process.argv[3]);
const run = JSON.parse(process.argv[4]);
if (run) assertExpectedReport(input, process.argv[3], run);
if (process.argv[5]) assertPreparedSource(input, JSON.parse(process.argv[5]));
console.log(JSON.stringify(input));"""
        args = ['node', '--input-type=module', '-e', code, str(self.input),
                str(self.candidate), mode, json.dumps(run)]
        if prepared is not None:
            args.append(json.dumps(prepared))
        return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=15)

    def rejects(self, message, mode='preview', run=None):
        result = self.invoke(mode, run)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)

    def test_source_1130_and_recorded_expectations_are_used(self):
        for mode in ['preview', 'import', 'repeat']:
            result = self.invoke(mode, run={'source_version': 1130, 'acknowledged_schema_version': None,
                                           'report': {'entities': self.expected[mode]}})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['source']['peertube_schema_version'], 1130)

    def test_preparation_must_match_the_representative_candidate_and_source(self):
        prepared = {'scope': 'representative', 'candidate_sha256': self.digest(self.candidate),
                    'source_snapshot_sha256': 'a' * 64, 'source_media_manifest_sha256': 'b' * 64,
                    'target': self.spec['target']}
        self.assertEqual(self.invoke(prepared=prepared).returncode, 0)
        for key in prepared:
            result = self.invoke(prepared=dict(prepared, **{key: 'legacy-fixture'}))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('AssertionError', result.stderr)

    def test_older_representative_inputs_cannot_silently_use_fixture_transport(self):
        self.spec['schema_version'] = 1
        self.freeze()
        self.rejects('representative input version 2 required')

    def test_target_rejects_http_credentials_paths_project_and_timer_errors(self):
        for key, value in [('origin', 'http://beta.example.test'),
                           ('origin', 'https://user:secret@beta.example.test'),
                           ('origin', 'https://beta.example.test/path'),
                           ('origin', 'not-a-url'), ('project', 'BAD PROJECT'),
                           ('install_dir', 'relative/path'), ('timeout_ms', True),
                           ('timeout_ms', 0), ('timeout_ms', 2147483648)]:
            with self.subTest(key=key, value=value):
                original = self.spec['target'][key]
                self.spec['target'][key] = value
                self.freeze()
                self.rejects('candidate target')
                self.spec['target'][key] = original

    def test_representative_browser_keeps_certificate_checks_and_real_origin(self):
        code = """import assert from 'node:assert/strict';
import {acceptanceBrowserOptions} from './tests/peertube-acceptance-inputs.mjs';
const real = acceptanceBrowserOptions({target:{origin:'https://beta.example.test'}});
assert.equal(real.context.baseURL, 'https://beta.example.test');
assert.equal(real.context.ignoreHTTPSErrors, false);
assert.ok(!real.launch.args.some(arg => arg.includes('host-resolver-rules')));
const old = acceptanceBrowserOptions(null);
assert.equal(old.context.baseURL, 'https://secure.video.test');
assert.equal(old.context.ignoreHTTPSErrors, true);
assert.ok(old.launch.args.some(arg => arg.includes('secure.video.test')));"""
        result = subprocess.run(['node', '--input-type=module', '-e', code],
                                cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_target_api_must_match_the_frozen_release_before_login(self):
        code = """import assert from 'node:assert/strict';
import {assertTargetVersion} from './tests/peertube-acceptance-inputs.mjs';
const candidate = {tag:'v9.0.0',images:{'vidra-core':{revision:'a'.repeat(40)}}};
assertTargetVersion(candidate, {version:'v9.0.0',commit:'a'.repeat(12)});
for (const actual of [{version:'v8.0.0',commit:'a'.repeat(12)},
  {version:'v9.0.0',commit:'b'.repeat(12)}, {version:'v9.0.0',commit:'a'}]) {
  assert.throws(() => assertTargetVersion(candidate, actual), /candidate API identity/);
}"""
        result = subprocess.run(['node', '--input-type=module', '-e', code],
                                cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_compose_project_is_refused_before_execution(self):
        result = subprocess.run(['node', 'tests/peertube-release-acceptance.mjs',
                                 str(self.root), 'preview', 'preview', str(self.root), str(self.input)],
                                cwd=ROOT, text=True, capture_output=True, timeout=15,
                                env=dict(os.environ, COMPOSE_PROJECT_NAME='wrong-project'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('compose project differs', result.stderr)
        self.assertFalse((self.root / 'preview-browser.json').exists())

    def test_changed_candidate_source_or_expectations_are_refused(self):
        for name in ['candidate.json', 'source.json', 'expectations.json']:
            with self.subTest(name=name):
                self.freeze()
                self.candidate.write_text(json.dumps({'tag': 'v9.0.0'}))
                path = self.root / name
                original = path.read_text()
                path.write_text(original + ' ')
                self.rejects('hash mismatch')
                path.write_text(original)

    def test_bad_scope_marker_and_missing_provenance_are_refused(self):
        self.spec['scope'] = 'synthetic'
        self.freeze()
        self.rejects('representative scope required')
        self.spec['scope'] = 'representative'
        for key, value in [('peertube_schema_version', True), ('snapshot_sha256', ''),
                           ('media_manifest_sha256', None)]:
            with self.subTest(key=key):
                old = self.source[key]
                self.source[key] = value
                self.freeze()
                self.rejects('source provenance')
                self.source[key] = old

    def test_missing_tables_and_invalid_or_failed_counters_are_refused(self):
        del self.expected['catalogue_delta']['videos']
        self.freeze()
        self.rejects('catalogue tables')
        self.expected['catalogue_delta']['videos'] = 0
        for value in [-1, True, 1.5]:
            self.expected['import']['video']['imported'] = value
            self.freeze()
            self.rejects('nonnegative integer')
        self.expected['import']['video'] = {'failed': 1}
        self.freeze()
        self.rejects('failed entities')

    def test_schema_mismatch_acknowledgement_and_wrong_counts_are_refused(self):
        run = {'source_version': 1130, 'acknowledged_schema_version': None,
               'report': {'entities': self.expected['preview']}}
        for field, value, message in [('source_version', 1040, 'source schema'),
                                      ('acknowledged_schema_version', 1130, 'acknowledgement')]:
            wrong = dict(run, **{field: value})
            self.rejects(message, run=wrong)
        run['report']['entities']['video']['planned'] = 970
        self.rejects('video.planned', run=run)

    def test_missing_counts_and_unrecorded_unsupported_items_are_refused(self):
        del self.expected['preview']['video']['planned']
        self.freeze()
        self.rejects('entity counters required')
        self.expected['preview']['video']['planned'] = 3
        self.freeze()
        run = {'source_version': 1130, 'acknowledged_schema_version': None,
               'report': {'entities': {'video': {'planned': 3, 'unsupported': 1}}}}
        self.rejects('video.unsupported', run=run)

    def test_fixture_only_actions_are_refused_before_browser_or_host_calls(self):
        for mode in ['schema-refusal', 'search', 'playback']:
            self.rejects('representative mode supports preview/import/repeat only', mode)
        result = subprocess.run(['node', 'tests/peertube-release-acceptance.mjs',
                                 str(self.root), 'schema-refusal', 'refusal',
                                 str(self.root), str(self.input)], cwd=ROOT, text=True,
                                capture_output=True, timeout=15,
                                env=dict(os.environ, COMPOSE_PROJECT_NAME='vidra-release-acceptance'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('representative mode supports preview/import/repeat only', result.stderr)
        self.assertFalse((self.root / 'refusal-browser.json').exists())
