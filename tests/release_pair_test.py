"""The drilled pair comes from releases/v*.json, compared as numbers, or is refused."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'scripts/ci/release-pair.py'
spec = importlib.util.spec_from_file_location('release_pair', TOOL)
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)

# The newest real record and a version after it, derived rather than typed: every
# release adds a record, and a test that names "the next release" by hand starts
# failing the day that release is cut.
_VERSIONS = sorted(tuple(map(int, m.groups())) for path in (ROOT / 'releases').glob('v*.json')
                   if (m := re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', path.stem)))
NEWEST = 'v%d.%d.%d' % _VERSIONS[-1]
NEXT = 'v%d.%d.%d' % (_VERSIONS[-1][0], _VERSIONS[-1][1], _VERSIONS[-1][2] + 1)


def tree(temp, *extra):
    """A copy of the real records plus `extra` uniform releases cut from v0.7.20."""
    root = Path(temp)
    shutil.copytree(ROOT / 'releases', root / 'releases')
    for name in extra:
        record = json.loads((ROOT / 'releases/v0.7.20.json').read_text())
        record['release'] = name
        for component in record['components'].values():
            component['tag'] = name
        (root / 'releases' / f'{name}.json').write_text(json.dumps(record))
    return root


class Refusals:
    def refused(self, reason, call, *args):
        with self.assertRaises(pair.Refused) as caught:
            call(*args)
        self.assertEqual(str(caught.exception), reason)
        self.assertIn(reason, pair.REASONS)


class Previous(Refusals, unittest.TestCase):
    def test_previous_is_the_greatest_recorded_tag_below(self):
        for release, expected in (('v0.7.20', 'v0.7.19'), ('v0.7.11', 'v0.7.9'), ('v0.7.9', 'v0.7.8'),
                                  ('v0.7.8', 'v0.7.7'), ('v0.7.7', 'v0.7.5'), ('v0.7.0', 'v0.6.9'),
                                  ('v0.6.8', 'v0.6.6')):
            with self.subTest(release=release):
                self.assertEqual(pair.previous(ROOT, release), expected)
                self.assertEqual(pair.resolve(ROOT, release)['old']['release'], expected)

    def test_order_is_numeric_not_alphabetical(self):
        names = sorted(path.stem for path in (ROOT / 'releases').glob('v*.json'))
        for release, numeric, alphabetical in (('v0.7.20', 'v0.7.19', 'v0.7.2'), ('v0.7.11', 'v0.7.9', 'v0.7.1'),
                                               ('v0.7.2', 'v0.7.1', 'v0.7.19')):
            with self.subTest(release=release):
                self.assertEqual(max(name for name in names if name < release), alphabetical)
                self.assertEqual(pair.previous(ROOT, release), numeric)
        with tempfile.TemporaryDirectory() as temp:
            root = tree(temp, 'v0.7.100', 'v0.10.0')
            self.assertEqual(pair.previous(root, 'v0.7.100'), NEWEST)
            self.assertEqual(pair.previous(root, 'v0.10.0'), 'v0.7.100')

    def test_the_oldest_record_has_no_previous(self):
        self.refused(pair.NO_PREVIOUS, pair.previous, ROOT, 'v0.6.4')
        self.refused(pair.NO_PREVIOUS, pair.resolve, ROOT, 'v0.6.4')

    def test_real_pairs_carry_both_records(self):
        for release, previous, old, new, search_tag in (
                ('v0.7.8', '', ('v0.7.7', 151, 18), ('v0.7.8', 182, 18), 'v0.7.3'),
                ('v0.7.20', '', ('v0.7.19', 188, 21), ('v0.7.20', 189, 21), 'v0.7.19'),
                ('v0.7.20', 'v0.7.8', ('v0.7.8', 182, 18), ('v0.7.20', 189, 21), 'v0.7.8')):
            with self.subTest(release=release, previous=previous):
                found = pair.resolve(ROOT, release, previous)
                for side, expected in (('old', old), ('new', new)):
                    record = found[side]
                    self.assertEqual((record['release'], record['core_schema_version'],
                                      record['search_schema_version']), expected)
                self.assertEqual(found['old']['components']['search']['tag'], search_tag)

    def test_an_unrecorded_or_newer_previous_is_refused(self):
        for previous in ('v0.7.6', 'v0.7.10', 'v0.07.8', 'latest', 'v0.7.8\n', '../v0.7.8', 'v0.7'):
            with self.subTest(previous=previous):
                self.refused(pair.PREVIOUS_NOT_RECORDED, pair.resolve, ROOT, 'v0.7.20', previous)
        for previous in ('v0.7.20', 'v0.7.19'):
            with self.subTest(previous=previous):
                self.refused(pair.NOT_OLDER, pair.resolve, ROOT, 'v0.7.19', previous)

    def test_an_unrecorded_or_malformed_release_is_refused(self):
        for release in ('v0.7.10', 'v0.7.6', 'v9.9.9', 'v0.07.20', 'latest', '', 'v0.7.20\n', '../v0.7.20',
                        'v0.7.20.json', None, 20):
            with self.subTest(release=release):
                self.refused(pair.NOT_RECORDED, pair.resolve, ROOT, release)
                self.refused(pair.NOT_RECORDED, pair.resolve, ROOT, release, 'v0.7.8')

    def test_a_newer_record_becomes_the_release_and_moves_no_older_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = tree(temp, NEXT)
            found = pair.resolve(root, NEXT)
            self.assertEqual((found['old']['release'], found['new']['release']), (NEWEST, NEXT))
            self.assertEqual(pair.previous(root, NEWEST), pair.previous(ROOT, NEWEST))
            self.assertEqual(pair.previous(root, 'v0.7.20'), 'v0.7.19')
            self.assertEqual(pair.added(root, [f'releases/{NEXT}.json']), NEXT)
        self.refused(pair.NOT_RECORDED, pair.resolve, ROOT, NEXT)

    def test_one_broken_record_refuses_every_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = tree(temp)
            (root / 'releases/v0.7.3.json').write_text('{"release": "v0.7.3"}')
            self.refused(pair.UNUSABLE, pair.resolve, root, 'v0.7.20')
            self.refused(pair.UNUSABLE, pair.previous, root, 'v0.7.20')
            self.refused(pair.UNUSABLE, pair.added, root, ['releases/v0.7.20.json'])
        with tempfile.TemporaryDirectory() as temp:
            self.refused(pair.UNUSABLE, pair.resolve, Path(temp), 'v0.7.20')

    def test_a_record_that_cannot_be_its_release_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = tree(temp)
            record = json.loads((root / 'releases/v0.7.20.json').read_text())
            for component in record['components'].values():
                component['tag'] = 'v0.9.0'
            (root / 'releases/v0.7.20.json').write_text(json.dumps(record))
            self.refused(pair.UNUSABLE, pair.resolve, root, 'v0.7.20')


class Added(Refusals, unittest.TestCase):
    def test_exactly_one_added_record_names_the_release(self):
        self.assertEqual(pair.added(ROOT, ['releases/v0.7.20.json']), 'v0.7.20')
        self.assertEqual(pair.added(ROOT, ['docs/release-readiness.md', 'releases/v0.7.20.json', 'releases/README.md',
                                           'docs/evidence/release-v0.7.20-verification/manifest.json',
                                           'x/releases/v0.7.19.json', 'releases/old/v0.7.19.json', '']), 'v0.7.20')

    def test_none_or_several_added_records_are_refused(self):
        for names in ([], [''], ['releases/README.md'], ['deploy/deploy.sh', 'docs/releases/v0.7.20.json'],
                      ['releases/v0.7.19.json', 'releases/v0.7.20.json'],
                      ['releases/v0.7.20.json', 'releases/v0.7.20.json'],
                      ['releases/v0.7.20.json', 'releases/vNEXT.json'],
                      ['releases/v0.7.20.json', 'releases/v0.07.20.json']):
            with self.subTest(names=names):
                self.refused(pair.NOT_ONE_ADDED, pair.added, ROOT, names)

    def test_an_added_name_without_a_usable_record_is_refused(self):
        for name in (f'releases/{NEXT}.json', 'releases/v0.7.10.json', 'releases/v0.07.20.json', 'releases/vNEXT.json',
                     'releases/v.json'):
            with self.subTest(name=name):
                self.refused(pair.NOT_RECORDED, pair.added, ROOT, [name])


class CommandLine(unittest.TestCase):
    def run_tool(self, *args, stdin=b''):
        return subprocess.run([sys.executable, str(TOOL), *args], input=stdin, capture_output=True, check=False)

    def test_pair_prints_the_resolved_pair(self):
        done = self.run_tool('pair', '--release', 'v0.7.20', '--previous', 'v0.7.8')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {'previous': 'v0.7.8', 'release': 'v0.7.20',
                                                   'core_schema': [182, 189], 'search_schema': [18, 21]})
        done = self.run_tool('pair', '--release', 'v0.7.20')
        self.assertEqual(json.loads(done.stdout)['previous'], 'v0.7.19')

    def test_added_reads_nul_separated_names_and_writes_the_job_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'github-output'
            done = self.run_tool('added', '--github-output', str(output),
                                 stdin=b'releases/README.md\0releases/v0.7.20.json\0')
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(output.read_text(), 'release=v0.7.20\n')
            self.assertEqual(json.loads(done.stdout), {'release': 'v0.7.20'})

    def test_a_refusal_exits_one_writes_no_output_and_echoes_no_input(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'github-output'
            for args, stdin, reason in (
                    (('pair', '--release', 'private-canary'), b'', pair.NOT_RECORDED),
                    (('pair', '--release', 'v0.7.20', '--previous', 'private-canary'), b'', pair.PREVIOUS_NOT_RECORDED),
                    (('added',), b'releases/vprivate-canary.json\0', pair.NOT_RECORDED),
                    (('added',), b'releases/v0.7.19.json\nreleases/v0.7.20.json\0', pair.NOT_ONE_ADDED),
                    (('added',), b'', pair.NOT_ONE_ADDED)):
                with self.subTest(args=args, stdin=stdin):
                    done = self.run_tool(*args, '--github-output', str(output), stdin=stdin)
                    self.assertEqual(done.returncode, 1)
                    self.assertEqual(done.stdout, b'')
                    self.assertEqual(done.stderr.decode(), f'::error::release pair refused: {reason}\n')
                    self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
