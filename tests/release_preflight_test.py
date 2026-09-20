"""Fail-closed checks for the read-only release preflight."""
import argparse
import contextlib
import importlib.util
import hashlib
import io
import json
from unittest.mock import patch
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preflight', ROOT / 'deploy/release-preflight.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
RELEASES = ROOT / 'releases'


class PreflightTests(unittest.TestCase):
    def test_image_requires_digest_platform_and_matching_source(self):
        image = {'manifest': {'digest': 'sha256:' + 'a' * 64}, 'image': {
            'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
                'org.opencontainers.image.revision': 'b' * 40,
                'org.opencontainers.image.source': 'https://github.com/yegamble/vidra-core'}}}}
        self.assertEqual(p.image_pin(image, 'yegamble/vidra-core', 'b' * 40, 'linux/amd64')['digest'], 'sha256:' + 'a' * 64)
        for revision, platform in [('c' * 40, 'linux/amd64'), ('b' * 40, 'linux/arm64')]:
            with self.assertRaises(ValueError):
                p.image_pin(image, 'yegamble/vidra-core', revision, platform)
        image['manifest']['digest'] = 'latest'
        with self.assertRaises(ValueError):
            p.image_pin(image, 'yegamble/vidra-core', 'b' * 40, 'linux/amd64')

    def test_checksum_missing_duplicate_or_corrupt_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bundle.tar.gz'
            path.write_bytes(b'actual release bytes')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            line = f'{digest}  {path.name}\n'
            self.assertEqual(p.verify_checksum(path, line), digest)
            for sums in ['', line + line, '0' * 64 + '  ' + path.name]:
                with self.assertRaises(ValueError):
                    p.verify_checksum(path, sums)

    def test_resolver_regression_removes_only_resolver(self):
        yaml = 'paths:\n  /api/v1/videos/resolve:\n    get:\n      summary: Resolve\n  /api/v1/videos/{id}:\n    get:\ncomponents:\n  schemas: {}\n'
        result = p.without_resolver(yaml)
        self.assertNotIn('/api/v1/videos/resolve:', result)
        self.assertIn('/api/v1/videos/{id}:', result)
        self.assertIn('components:', result)
        with self.assertRaises(ValueError):
            p.without_resolver(result)

    def test_asset_names_are_explicit_linux_and_bundle(self):
        self.assertEqual(p.asset_names('v0.6.2', 'linux/amd64'),
                         ['vidra-bundle_v0.6.2.tar.gz', 'vidra_v0.6.2_linux_amd64'])

    def test_failed_dependency_preserves_manifest_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'candidate'
            with patch('sys.argv', ['preflight', '--tag', 'v0.6.2', '--out', str(out)]), \
                    patch.object(p, 'freeze', side_effect=RuntimeError('registry unavailable')):
                self.assertEqual(p.main(), 1)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'FAIL')
            self.assertEqual(manifest['error'], 'registry unavailable')
            self.assertEqual(manifest['checks'], {})

    def test_existing_evidence_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'manifest.json'
            marker.write_text('previous evidence')
            with patch('sys.argv', ['preflight', '--tag', 'v0.6.2', '--out', tmp]):
                with self.assertRaises(FileExistsError):
                    p.main()
            self.assertEqual(marker.read_text(), 'previous evidence')

    def test_command_failure_is_not_accepted(self):
        with self.assertRaises(RuntimeError):
            p.run(['python3', '-c', 'raise SystemExit(7)'])

    def test_unsupported_node_rejected_before_network(self):
        with patch.object(p, 'run', return_value='v22.14.0') as run:
            with self.assertRaisesRegex(ValueError, 'Node >=24'):
                p.freeze(None, None, {})
            run.assert_called_once_with(['node', '--version'])


class StopFreeze(Exception):
    """Raised by the stub the moment freeze() reaches the registry, so a test
    can assert what the SOURCE half did without any network at all."""


class RunStub:
    """Records every command instead of running it. Proves which tag each
    component was cloned and inspected at -- and, for a refusal, that nothing
    ran at all. Stops the run at the first GitHub release read."""

    def __init__(self):
        self.calls, self.inspected = [], []

    @staticmethod
    def revision(repo):
        return hashlib.sha1(repo.encode()).hexdigest()

    def __call__(self, args, cwd=None, env=None, expected=0):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args == ['node', '--version']:
            return 'v26.8.1\n'
        if args == ['npm', '--version']:
            return '11.19.0\n'
        if args[:3] == ['docker', 'buildx', 'version']:
            return 'github.com/docker/buildx v0.37.0\n'
        if args[:2] == ['git', 'clone']:
            Path(args[-1]).mkdir(parents=True)
            return ''
        if args[:2] == ['git', 'rev-parse']:
            return self.revision(Path(cwd).name) + '\n'
        if args[:2] == ['git', 'checkout']:
            return ''
        if args[:4] == ['docker', 'buildx', 'imagetools', 'inspect']:
            reference = args[4]
            self.inspected.append(reference)
            repo = reference.split('/')[-1].split(':')[0].split('@')[0]
            return json.dumps({
                'manifest': {'digest': 'sha256:' + hashlib.sha256(repo.encode()).hexdigest()},
                'image': {'os': 'linux', 'architecture': 'amd64', 'config': {'Labels': {
                    'org.opencontainers.image.revision': self.revision(repo),
                    'org.opencontainers.image.source': f'https://github.com/yegamble/{repo}'}}}})
        raise StopFreeze(' '.join(args))

    def cloned_at(self):
        return {call[-1].rsplit('/', 1)[-1]: call[call.index('--branch') + 1]
                for call in self.calls if call[:2] == ['git', 'clone']}


class ComponentTagTests(unittest.TestCase):
    """A core-only release (v0.7.4, v0.7.5) pairs vidra-user and vidra-search at
    an OLDER tag. Cloning every repository at --tag cannot freeze one at all."""

    def resolve(self, tag, overrides=None, releases=RELEASES):
        return p.resolve_component_tags(tag, overrides or {}, releases)

    def refuse(self, argv, releases=None):
        """main() over a stubbed run(): asserts the refusal cost NOTHING -- exit
        2, no clone attempted, no half-built --out directory, no traceback --
        and hands the test the stderr so it can check what was named."""
        stub, stderr = RunStub(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'candidate'
            where = patch.object(p, 'RELEASES', Path(releases)) if releases \
                else contextlib.nullcontext()
            with patch.object(p, 'run', stub), contextlib.redirect_stderr(stderr), where, \
                    patch('sys.argv', ['preflight', '--out', str(out)] + argv):
                with self.assertRaises(SystemExit) as raised:
                    p.main()
            self.assertEqual(raised.exception.code, 2, stderr.getvalue())
            self.assertEqual(stub.calls, [], 'refused only AFTER running commands')
            self.assertFalse(out.exists(), 'refused only AFTER creating evidence')
        self.assertNotIn('Traceback', stderr.getvalue())
        return stderr.getvalue()

    def test_a_leading_zero_tag_is_not_a_release_tag(self):
        """v0.07.3 parsed as (0, 7, 3): equal to the real tag, so it passed the
        newer-than gate and died LATE at git clone -- exit 1, --out half built."""
        for tag in ['v0.07.3', 'v00.7.5', 'v0.7.05', 'v01.0.0', 'v0.7.3 ', 'v0.7.+3']:
            with self.assertRaises(ValueError, msg=tag):
                p.release_order(tag)
            with self.assertRaises(ValueError, msg=tag):
                p.parse_component_tags([f'vidra-user={tag}'])
        self.assertEqual(p.release_order('v0.7.10'), (0, 7, 10))
        self.assertEqual(p.release_order('v10.0.0'), (10, 0, 0))

    def test_a_leading_zero_tag_is_refused_before_any_clone(self):
        for tag in ['v0.07.3', 'v00.7.5', 'v0.7.05']:
            self.assertIn(tag, self.refuse(['--tag', 'v0.7.5',
                                            '--component-tag', f'vidra-user={tag}']))
            self.assertIn(tag, self.refuse(['--tag', tag]))

    def test_a_record_that_names_another_release_is_refused(self):
        """Copy releases/v0.7.5.json to v0.7.6.json, forget to edit `release`,
        and v0.7.6 froze at v0.7.5's components with tag_source reading
        authoritative. The filename alone is not the record's identity."""
        with tempfile.TemporaryDirectory() as rel:
            shutil.copyfile(RELEASES / 'v0.7.5.json', Path(rel) / 'v0.7.6.json')
            with self.assertRaises(ValueError) as raised:
                self.resolve('v0.7.6', releases=rel)
            for value in ('v0.7.6.json', 'v0.7.5', 'v0.7.6'):
                self.assertIn(value, str(raised.exception))
            self.assertIn('v0.7.5', self.refuse(['--tag', 'v0.7.6'], releases=rel))

    def test_a_record_that_does_not_name_every_component_is_refused(self):
        """A record file that exists but cannot answer the question is never
        treated as absent: falling back to --tag is the very drift this reads
        the record to prevent."""
        records = {
            'components is a list': {'release': 'v0.7.6', 'components': []},
            'no user role': {'release': 'v0.7.6', 'components': {
                'core': {'tag': 'v0.7.6'}, 'search': {'tag': 'v0.7.3'}}},
            'a non-string tag': {'release': 'v0.7.6', 'components': {
                'core': {'tag': 'v0.7.6'}, 'user': {'tag': 705},
                'search': {'tag': 'v0.7.3'}}},
            'a leading-zero tag': {'release': 'v0.7.6', 'components': {
                'core': {'tag': 'v0.7.6'}, 'user': {'tag': 'v0.07.3'},
                'search': {'tag': 'v0.7.3'}}},
            'the record is not an object': [1, 2],
        }
        for label, record in records.items():
            with tempfile.TemporaryDirectory() as rel:
                (Path(rel) / 'v0.7.6.json').write_text(json.dumps(record))
                with self.assertRaises(ValueError, msg=label):
                    self.resolve('v0.7.6', releases=rel)
                self.assertIn('v0.7.6.json', self.refuse(['--tag', 'v0.7.6'], releases=rel))

    def test_component_tags_come_from_the_platform_release_record(self):
        tags, sources, warnings = self.resolve('v0.7.5')
        self.assertEqual(tags, {'vidra': 'v0.7.5', 'vidra-core': 'v0.7.5',
                                'vidra-user': 'v0.7.3', 'vidra-search': 'v0.7.3'})
        self.assertEqual(sources['vidra-user'], 'releases/v0.7.5.json')
        self.assertEqual(sources['vidra'], '--tag')
        self.assertEqual(warnings, [])

    def test_a_release_with_no_record_still_freezes_every_repository_at_the_tag(self):
        with tempfile.TemporaryDirectory() as empty:
            tags, sources, warnings = self.resolve('v0.6.2', releases=empty)
        self.assertEqual(set(tags.values()), {'v0.6.2'})
        self.assertEqual(sorted(tags), sorted(p.REPOS))
        self.assertEqual(set(sources.values()), {'--tag'})
        self.assertEqual(warnings, [])

    def test_the_flag_pins_a_component_before_its_record_exists(self):
        with tempfile.TemporaryDirectory() as empty:
            tags, sources, _ = self.resolve(
                'v0.7.5', p.parse_component_tags(['vidra-user=v0.7.3', 'vidra-search=v0.7.3']),
                releases=empty)
        self.assertEqual(tags['vidra-user'], 'v0.7.3')
        self.assertEqual(tags['vidra-core'], 'v0.7.5')
        self.assertEqual(sources['vidra-search'], '--component-tag')

    def test_the_flag_beats_a_disagreeing_record_but_never_silently(self):
        overrides = p.parse_component_tags(['vidra-user=v0.7.2'])
        tags, sources, warnings = self.resolve('v0.7.5', overrides)
        self.assertEqual(tags['vidra-user'], 'v0.7.2')
        self.assertEqual(len(warnings), 1)
        for value in ('vidra-user', 'v0.7.2', 'v0.7.3', 'releases/v0.7.5.json'):
            self.assertIn(value, warnings[0])
        # The manifest, not only the console log, names both values.
        for value in ('--component-tag', 'v0.7.3', 'releases/v0.7.5.json'):
            self.assertIn(value, sources['vidra-user'])

    def test_nonsense_flags_are_refused(self):
        for value in ['vidra=v0.7.5', 'vidra-code=v0.7.5', 'vidra-user', 'vidra-user=0.7.3',
                      'vidra-user=v0.7', 'vidra-user=main', 'vidra-user=v0.7.3-rc1']:
            with self.assertRaises(ValueError, msg=value):
                p.parse_component_tags([value])
        with self.assertRaisesRegex(ValueError, 'twice'):
            p.parse_component_tags(['vidra-user=v0.7.3', 'vidra-user=v0.7.2'])
        # Naming a repository twice with the SAME tag contradicts nothing.
        self.assertEqual(p.parse_component_tags(['vidra-user=v0.7.3', 'vidra-user=v0.7.3']),
                         {'vidra-user': 'v0.7.3'})

    def test_a_component_newer_than_the_release_is_refused(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(ValueError, 'newer'):
                self.resolve('v0.7.5', p.parse_component_tags(['vidra-user=v0.8.0']), releases=empty)

    def test_release_tags_compare_numerically_not_lexically(self):
        # Lexically 'v0.7.10' < 'v0.7.9', which would invert both assertions.
        with tempfile.TemporaryDirectory() as empty:
            tags, _, _ = self.resolve('v0.7.10', p.parse_component_tags(['vidra-user=v0.7.9']),
                                      releases=empty)
            self.assertEqual(tags['vidra-user'], 'v0.7.9')
            with self.assertRaisesRegex(ValueError, 'newer'):
                self.resolve('v0.7.9', p.parse_component_tags(['vidra-user=v0.7.10']), releases=empty)

    def test_an_unusable_record_is_refused_rather_than_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'v0.7.5.json').write_text('{"components": ')
            with self.assertRaisesRegex(ValueError, 'v0.7.5.json'):
                self.resolve('v0.7.5', releases=tmp)

    def test_nonsense_is_refused_before_any_clone_or_output_directory(self):
        stub = RunStub()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'candidate'
            for flag in ['vidra-code=v0.7.5', 'vidra-user=main', 'vidra-user=v0.9.0']:
                stderr = io.StringIO()
                with patch.object(p, 'run', stub), contextlib.redirect_stderr(stderr), \
                        patch('sys.argv', ['preflight', '--tag', 'v0.7.5', '--out', str(out),
                                           '--component-tag', flag]):
                    with self.assertRaises(SystemExit) as raised:
                        p.main()
                self.assertEqual(raised.exception.code, 2)
                # Refused on its MERITS, not because argparse never learnt the flag.
                self.assertNotIn('unrecognized', stderr.getvalue())
                self.assertIn(flag.split('=')[-1], stderr.getvalue())
                self.assertEqual(stub.calls, [])
                self.assertFalse(out.exists())

    def test_a_core_only_release_clones_each_component_at_its_recorded_tag(self):
        """The whole point: --tag v0.7.5 freezes user/search at v0.7.3 with no
        hand-applied patch, and the manifest records the tag actually used."""
        tags, sources, _ = self.resolve('v0.7.5')
        args = argparse.Namespace(tag='v0.7.5', owner='yegamble', platform='linux/amd64',
                                  component_tags=tags, component_tag_sources=sources)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            manifest = {'repositories': {}, 'images': {}}
            stub = RunStub()
            with patch.object(p, 'run', stub):
                with self.assertRaises(StopFreeze):
                    p.freeze(args, out, manifest)
        self.assertEqual(stub.cloned_at(), {'vidra': 'v0.7.5', 'vidra-core': 'v0.7.5',
                                            'vidra-user': 'v0.7.3', 'vidra-search': 'v0.7.3'})
        self.assertEqual({repo: entry['tag'] for repo, entry in manifest['repositories'].items()},
                         {'vidra': 'v0.7.5', 'vidra-core': 'v0.7.5',
                          'vidra-user': 'v0.7.3', 'vidra-search': 'v0.7.3'})
        self.assertEqual(manifest['repositories']['vidra-user']['tag_source'],
                         'releases/v0.7.5.json')
        # The registry is asked for the component's own tag, not the release's.
        self.assertIn('ghcr.io/yegamble/vidra-user:v0.7.3', stub.inspected)
        self.assertNotIn('ghcr.io/yegamble/vidra-user:v0.7.5', stub.inspected)


if __name__ == '__main__':
    unittest.main()
