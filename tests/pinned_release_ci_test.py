"""Real-record resolution and workflow wiring for source-pinned stack CI."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stack_refs', ROOT / 'scripts/ci/resolve-stack-refs.py')
refs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refs)


class UniqueLoader(yaml.BaseLoader):
    """BaseLoader preserves `on` as a string; reject duplicate YAML keys."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


class PinnedStackRefsTest(unittest.TestCase):
    def test_newest_real_record_uses_existing_deployment_resolver(self):
        selected = refs.select('release', ROOT / 'releases')
        records, problems = refs.mapping.load_records(ROOT / 'releases')
        self.assertFalse(problems)
        newest = max(records, key=lambda r: refs.mapping.semver(r['release']))
        self.assertEqual(selected['release'], newest['release'])
        for role in refs.ROLES:
            self.assertEqual(selected['components'][role]['ref'], newest['components'][role]['commit'])
            self.assertEqual(selected['components'][role]['tag'], newest['components'][role]['tag'])

    def test_actual_v077_record_preserves_older_search_pairing(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'v0.7.7.json').write_bytes((ROOT / 'releases/v0.7.7.json').read_bytes())
            selected = refs.select('release', directory)
        self.assertEqual(selected['release'], 'v0.7.7')
        self.assertEqual(selected['components']['core']['ref'], '368883a996ed4bbebf586aa2c9f1212344fb9706')
        self.assertEqual(selected['components']['user']['ref'], 'adaa14968124b9ea1bdc8c53be9a7921504c47c8')
        self.assertEqual(selected['components']['search']['tag'], 'v0.7.3')
        self.assertEqual(selected['components']['search']['ref'], '4daed1850a4289e297bd7cd40a4310f20ccd1c44')
        self.assertEqual((selected['core_schema_version'], selected['search_schema_version']), (151, 18))

    def test_main_mode_preserves_floating_refs_without_requiring_records(self):
        with patch.object(refs.mapping, 'load_records', side_effect=AssertionError('main must stay independent')):
            selected = refs.select('main', Path('/missing'))
        self.assertEqual({v['ref'] for v in selected['components'].values()}, {'main'})

    def test_uniform_fallback_is_refused_even_if_it_prints_three_tags(self):
        result = subprocess.CompletedProcess([], 3, 'core v0.7.7 --release\nuser v0.7.7 --release\nsearch v0.7.7 --release\n', 'record unavailable')
        with patch.object(refs.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'fallback is forbidden'):
                refs.select('release', ROOT / 'releases')

    def test_invalid_record_is_not_silently_ignored_for_older_release(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for tag in ('v0.7.5', 'v0.7.7'):
                (directory / (tag + '.json')).write_bytes((ROOT / 'releases' / (tag + '.json')).read_bytes())
            record = json.loads((directory / 'v0.7.7.json').read_text())
            record['components']['core']['commit'] = 'main'
            (directory / 'v0.7.7.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, '40-hex commit'):
                refs.select('release', directory)

    def test_incomplete_checkout_evidence_cannot_pass_verification(self):
        with self.assertRaisesRegex(ValueError, 'all three components'):
            refs.verify({'mode': 'release', 'components': {}}, ROOT)

    def test_checkout_must_match_recorded_commit(self):
        selected = refs.select('release', ROOT / 'releases')
        with patch.object(refs.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '0' * 40, '')):
            with self.assertRaisesRegex(ValueError, 'differs from recorded commit'):
                refs.verify(selected, ROOT)


class PinnedStackWorkflowTest(unittest.TestCase):
    def test_modes_use_same_assertions_with_exact_resolved_refs_and_separate_artifacts(self):
        workflow = yaml.load((ROOT / '.github/workflows/stack-e2e.yml').read_text(), Loader=UniqueLoader)
        job = workflow['jobs']['stack-e2e']
        self.assertEqual(job['strategy']['matrix']['mode'], ['main', 'release'])
        self.assertEqual(job['strategy']['fail-fast'], 'false')
        self.assertIn('pinned-release-e2e', job['name'])
        steps = job['steps']
        resolver = next(s for s in steps if s.get('id') == 'refs')
        self.assertIn('--github-output "$GITHUB_OUTPUT"', resolver['run'])
        self.assertEqual(resolver['env']['STACK_MODE'], '${{ matrix.mode }}')
        for role in refs.ROLES:
            checkout = next(s for s in steps if s.get('with', {}).get('repository') == 'yegamble/vidra-' + role)
            self.assertEqual(checkout['with']['ref'], '${{ steps.refs.outputs.' + role + '_ref }}')
        verification = next(i for i, s in enumerate(steps) if 'resolve-stack-refs.py verify' in s.get('run', ''))
        boot = next(i for i, s in enumerate(steps) if s.get('name') == 'Boot vidra-search (its migrations run alone)')
        self.assertLess(verification, boot)
        artifact = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertIn('${{ matrix.mode }}', artifact['with']['name'])
        self.assertIn('ci-report/', artifact['with']['path'])
        self.assertEqual(artifact['if'], 'always()')
        paths = workflow['on']['pull_request']['paths']
        for source in ('scripts/ci/resolve-stack-refs.py', 'deploy/release-mapping.py', 'releases/*.json', 'tests/pinned_release_ci_test.py'):
            self.assertIn(source, paths)

    def test_meta_ci_installs_yaml_before_the_unit_suite(self):
        workflow = yaml.load((ROOT / '.github/workflows/meta-ci.yml').read_text(), Loader=UniqueLoader)
        steps = workflow['jobs']['validate']['steps']
        dependency = next(i for i, s in enumerate(steps) if s.get('name') == 'Ensure PyYAML is available')
        tests = next(i for i, s in enumerate(steps) if s.get('name') == 'Deploy-script unit tests (tests/*_test.py)')
        self.assertLess(dependency, tests)

    def test_duplicate_yaml_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate YAML key'):
            yaml.load('jobs:\n  stack: one\n  stack: two\n', Loader=UniqueLoader)


if __name__ == '__main__':
    unittest.main()
