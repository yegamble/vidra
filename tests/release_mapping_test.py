"""deploy/release-mapping.py: a deploy or rollback may only run a component
mapping somebody actually released.

Before this guard, nothing machine-readable said which vidra-core, vidra-user
and vidra-search images make up a platform release. deploy.sh checked that each
VIDRA_*_TAG was SHAPED like a release and, on the git path, that the tag
existed; rollback.sh accepted any --core/--user/--search triple. So a user tag
from another release, or a core/search pairing never released together, went
straight through the pre-deploy dump, the pull, the migrations and `up -d`.

The checker is exercised as a black box (its CLI and exit codes are the
contract the shell scripts consume), and then deploy.sh and rollback.sh are
executed against stub docker/git/curl binaries to prove the refusal happens
before anything is dumped, synced, pulled, migrated or restarted. Each stubbed
refusal has a control run through the same stubs that DOES reach those
commands, so "the log does not contain pull" cannot pass vacuously.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'deploy/release-mapping.py'
# Imported as well as executed: the CLI is the contract the shell reads, but a
# crash inside the resolver cannot be provoked through the CLI by design, and
# proving it is answered with its own exit code needs the function itself.
_spec = importlib.util.spec_from_file_location('release_mapping', CHECKER)
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)
RECORDS = ROOT / 'releases'
EVIDENCE = ROOT / 'docs/evidence/release-v0.6.4-verification'
# Releases whose committed evidence is the RAW release-preflight output. v0.6.4
# is not one: its manifest carries a hand-added platform digest and a runtime
# ledger file, so it keeps a test of its own. Every record must be covered by one
# or the other -- test_every_record_has_an_evidence_cross_check enforces that.
RAW_PREFLIGHT_RELEASES = {'v0.6.5', 'v0.6.6', 'v0.6.8', 'v0.6.9', 'v0.7.0', 'v0.7.1', 'v0.7.2', 'v0.7.3',
                          'v0.7.4', 'v0.7.5'}

OK, REFUSED, UNVERIFIED = 0, 1, 3
SECRET = 'SECRET_MUST_NOT_APPEAR'


def hexsha(seed):
    return (format(seed, 'x') * 40)[:40]


def digest(seed):
    return 'sha256:' + (format(seed, 'x') * 64)[:64]


def synthetic(release, core, user, search, core_schema=150, search_schema=19, seed=1):
    """A well-formed record for a release that was never cut — fixture only."""
    def component(repo, tag, n):
        return {'tag': tag, 'commit': hexsha(seed + n),
                'image': {'repository': f'ghcr.io/yegamble/{repo}',
                          'index_digest': digest(seed + n + 3),
                          'platforms': {'linux/amd64': digest(seed + n + 6)}}}
    return {'schema_version': 1, 'release': release, 'meta_commit': hexsha(seed + 9),
            'core_schema_version': core_schema, 'search_schema_version': search_schema,
            'components': {'core': component('vidra-core', core, 0),
                           'user': component('vidra-user', user, 1),
                           'search': component('vidra-search', search, 2)}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.releases = self.base / 'releases'
        self.releases.mkdir()
        real = RECORDS / 'v0.6.4.json'
        if real.exists():
            shutil.copyfile(real, self.releases / 'v0.6.4.json')

    def add(self, record, name=None):
        path = self.releases / (name or record['release'] + '.json')
        path.write_text(json.dumps(record, indent=2))
        return path

    def env(self, core='v0.6.4', user='v0.6.4', search='v0.6.4', extra=''):
        path = self.base / 'production.env'
        lines = [f'JWT_SECRET={SECRET}']
        for key, value in (('VIDRA_CORE_TAG', core), ('VIDRA_USER_TAG', user),
                           ('VIDRA_SEARCH_TAG', search)):
            if value is not None:
                lines.append(f'{key}={value}')
        path.write_text('\n'.join(lines) + '\n' + extra)
        return path

    def check(self, *args, mode='deploy', env_file=None, process_env=None):
        env_file = env_file or self.env()
        environ = {'PATH': os.environ['PATH']}
        environ.update(process_env or {})
        result = subprocess.run(
            ['python3', str(CHECKER), 'check', '--mode', mode,
             '--releases', str(self.releases), '--env', str(env_file), *args],
            capture_output=True, text=True, env=environ)
        out = result.stdout + result.stderr
        self.assertNotIn(SECRET, out, 'the checker printed a secret from the env file')
        return result.returncode, out

    def bundle(self, tag='v0.6.4', schema='0146', core_commit=None):
        path = self.base / 'vidra-bundle.manifest'
        core_commit = core_commit or 'ed55a6d946dad3f2e72a47b2518ac095352c795d'
        path.write_text(f'# generated\ntag={tag}\ncore_schema_version={schema}\n'
                        f'meta_commit=0da18462b009b3710ceac7e60d2e88653bebbc37\n'
                        f'core_commit={core_commit}\n')
        return path


class MappingTests(Fixture):
    def test_the_released_mapping_passes(self):
        code, out = self.check()
        self.assertEqual(code, OK, out)
        self.assertIn('v0.6.4', out)

    def test_independent_versions_pass_when_a_record_pairs_them(self):
        """Identical tag strings are NOT the rule: a platform release may pair a
        new core with the previous user and search images."""
        self.add(synthetic('v0.6.5', core='v0.6.5', user='v0.6.4', search='v0.6.4'))
        code, out = self.check(env_file=self.env(core='v0.6.5'))
        self.assertEqual(code, OK, out)
        self.assertIn('v0.6.5', out)

    def test_independent_versions_are_refused_when_no_record_pairs_them(self):
        code, out = self.check(env_file=self.env(core='v0.6.5'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_CORE_TAG', out)
        self.assertIn('v0.6.5', out)
        self.assertIn('expects VIDRA_CORE_TAG=v0.6.4', out)

    def test_a_user_tag_from_another_release_is_refused(self):
        self.add(synthetic('v0.6.5', core='v0.6.5', user='v0.6.5', search='v0.6.5'))
        code, out = self.check(env_file=self.env(user='v0.6.5'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_USER_TAG=v0.6.5 belongs to release v0.6.5', out)
        self.assertIn('expects VIDRA_USER_TAG=v0.6.4', out)
        self.assertIn('never released together', out)

    def test_an_unknown_newer_search_tag_is_refused(self):
        code, out = self.check(env_file=self.env(search='v0.6.9'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_SEARCH_TAG=v0.6.9', out)
        self.assertIn('no release record', out)

    def test_a_uniform_release_newer_than_every_record_is_unverified_in_deploy(self):
        """M2. install.sh --git clones main, and after one post-tag commit
        `git tag --points-at HEAD` is empty, so the tree's-own-release
        allowance never applied to a fresh --git install of the newest release
        (nor to a rehearsal lab deploying v0.6.5-rc1 from main). A UNIFORM
        triple newer than every record is UNVERIFIED with a WARNING, whatever
        the tree's tags: a typo'd uniform tag is still caught by the checkout
        sync and `compose pull`; the mixed-triple refusal is where the value
        is."""
        for triple in (('v0.7.0',) * 3, ('v0.7.0-rc1',) * 3):
            with self.subTest(triple=triple):
                code, out = self.check(env_file=self.env(*triple))
                self.assertEqual(code, UNVERIFIED, out)
                self.assertIn('WARNING', out)
                self.assertIn('newer than every record', out)
                self.assertIn('NOT verified', out)
                self.assertIn(f'releases/{triple[0]}.json', out)
                self.assertNotIn('ERROR', out)

    def test_a_mixed_triple_newer_than_every_record_is_still_refused_in_deploy(self):
        for triple in (('v0.7.0', 'v0.6.4', 'v0.7.0'), ('v0.7.0', 'v0.7.1', 'v0.7.0')):
            with self.subTest(triple=triple):
                code, out = self.check(env_file=self.env(*triple))
                self.assertEqual(code, REFUSED, out)
                self.assertIn('VIDRA_USER_TAG', out)

    def test_a_uniform_unrecorded_release_between_records_is_still_refused_in_deploy(self):
        """Newer than SOME record is not newer than every record: a gap in the
        middle of the record set is bookkeeping to fix, not a release whose
        record cannot exist yet."""
        self.add(synthetic('v0.6.6', 'v0.6.6', 'v0.6.6', 'v0.6.6'))
        code, out = self.check(env_file=self.env('v0.6.5', 'v0.6.5', 'v0.6.5'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('releases/v0.6.5.json', out)

    def test_the_trees_own_release_is_unverified_not_refused(self):
        """release.sh tags this repository BEFORE the images exist, so a tree
        pinned to tag vN can never carry vN's digest record. pin-release.sh vN
        followed by deploy.sh must still run — loudly unverified."""
        code, out = self.check('--tree-tag', 'v0.7.0',
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('WARNING', out)
        self.assertIn('NOT verified', out)

    def test_the_trees_own_release_does_not_excuse_a_mixed_triple(self):
        code, out = self.check('--tree-tag', 'v0.7.0',
                               env_file=self.env('v0.7.0', 'v0.6.4', 'v0.7.0'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_USER_TAG=v0.6.4 belongs to release v0.6.4', out)

    def test_the_bundle_tag_counts_as_the_trees_own_release(self):
        code, out = self.check('--bundle-manifest', str(self.bundle(tag='v0.7.0', schema='150')),
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, UNVERIFIED, out)

    def test_a_matching_digest_pin_passes_and_a_wrong_one_is_refused(self):
        record = json.loads((RECORDS / 'v0.6.4.json').read_text())
        core = record['components']['core']['image']
        for pinned in (core['index_digest'], core['platforms']['linux/amd64']):
            with self.subTest(pinned=pinned):
                code, out = self.check(env_file=self.env(core=f'v0.6.4@{pinned}'))
                self.assertEqual(code, OK, out)
        wrong = digest(7)
        code, out = self.check(env_file=self.env(core=f'v0.6.4@{wrong}'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_CORE_TAG', out)
        self.assertIn(wrong, out)
        self.assertIn(core['index_digest'], out)

    def test_a_stale_bundle_is_refused_in_deploy(self):
        code, out = self.check('--bundle-manifest', str(self.bundle(tag='v0.6.3')))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('vidra-bundle.manifest tag', out)
        self.assertIn('expected v0.6.4', out)

    def test_a_bundle_schema_mismatch_is_refused_in_deploy(self):
        code, out = self.check('--bundle-manifest', str(self.bundle(schema='0145')))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('core_schema_version', out)
        self.assertIn('146', out)
        self.assertIn('145', out)

    def test_a_bundle_built_from_another_core_commit_is_refused_in_deploy(self):
        code, out = self.check('--bundle-manifest', str(self.bundle(core_commit=hexsha(5))))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('core_commit', out)

    def test_the_matching_bundle_passes(self):
        code, out = self.check('--bundle-manifest', str(self.bundle()))
        self.assertEqual(code, OK, out)

    def test_an_older_recorded_release_under_a_newer_bundle_is_also_told_to_roll_back(self):
        """L7. "Unpack the v0.6.4 bundle over this tree" is half the advice when
        the env pins an OLDER recorded release under a NEWER bundle: that host
        may be mid-rollback, and rollback.sh runs under the newer bundle on
        purpose. A bundle OLDER than the recorded release is a stale tree, and
        gets no such advice."""
        newer = str(self.bundle(tag='v0.6.5', schema='0150', core_commit=hexsha(5)))
        code, out = self.check('--bundle-manifest', newer)   # env v0.6.4 x3, record v0.6.4
        self.assertEqual(code, REFUSED, out)
        self.assertIn('Unpack the v0.6.4 bundle over this tree', out)
        self.assertIn('deploy/rollback.sh v0.6.4', out)
        self.assertIn('runs under the newer bundle on purpose', out)
        self.add(synthetic('v0.6.5', 'v0.6.5', 'v0.6.5', 'v0.6.5'))
        code, out = self.check('--bundle-manifest', str(self.bundle(tag='v0.6.4')),
                               env_file=self.env('v0.6.5', 'v0.6.5', 'v0.6.5'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('Unpack the v0.6.5 bundle over this tree', out)
        self.assertNotIn('rollback.sh', out)

    def test_rollback_does_not_judge_the_bundle_tree(self):
        """A bundle host rolls back by re-pointing tags UNDER the newer bundle —
        rollback.sh never reads the manifest's schema version, so a bundle that
        differs from the target release predicts nothing about the rollback."""
        self.add(synthetic('v0.6.5', core='v0.6.5', user='v0.6.5', search='v0.6.5'))
        code, out = self.check('--bundle-manifest', str(self.bundle(tag='v0.6.5', schema='150')),
                               mode='rollback')
        self.assertEqual(code, OK, out)

    def test_every_finding_names_the_failure_mode_it_prevents(self):
        """Key, expected, actual and the consequence — for each class of finding."""
        self.add(synthetic('v0.6.5', core='v0.6.5', user='v0.6.5', search='v0.6.5'))
        code, out = self.check(env_file=self.env(user='v0.6.5'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('never released together', out)
        code, out = self.check('--bundle-manifest', str(self.bundle(schema='0145')))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('ledger', out)
        wrong = digest(7)
        code, out = self.check(env_file=self.env(core=f'v0.6.4@{wrong}'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('bytes', out)

    def test_pre_manifest_tags_warn_in_deploy_and_rollback(self):
        """v0.6.4 is the first release with a record. Refusing everything older
        would make every historical release undeployable and un-rollback-able."""
        for mode in ('deploy', 'rollback'):
            for triple in (('v0.6.3', 'v0.6.3', 'v0.6.3'), ('v0.6.3', 'v0.6.2', 'v0.6.3-a37')):
                with self.subTest(mode=mode, triple=triple):
                    code, out = self.check(mode=mode, env_file=self.env(*triple))
                    self.assertEqual(code, UNVERIFIED, out)
                    self.assertIn('WARNING', out)
                    self.assertIn('before v0.6.4', out)

    def test_a_pre_manifest_tag_beside_a_recorded_one_is_refused_in_deploy(self):
        code, out = self.check(env_file=self.env(user='v0.6.3'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_USER_TAG=v0.6.3', out)

    def test_rollback_to_an_unrecorded_uniform_release_warns(self):
        """Mid-incident, a missing record is a bookkeeping gap, not a prediction
        that the rollback fails: a tag that does not exist still fails the pull,
        which restores the env file."""
        code, out = self.check(mode='rollback', env_file=self.env('v0.6.5', 'v0.6.5', 'v0.6.5'))
        self.assertEqual(code, UNVERIFIED, out)

    def test_a_mixed_target_warns_in_rollback_and_is_refused_in_deploy(self):
        """rollback.sh's header documents `--user` on its own (core and search
        stay where they are), so a mixed triple is the DOCUMENTED rollback, and
        refusing it mid-incident predicts no failure of the rollback itself. It
        is still a mapping nobody verified, so the warning must say exactly
        what was not checked. A deploy is the moment to fix it: refused."""
        self.add(synthetic('v0.6.5', core='v0.6.5', user='v0.6.5', search='v0.6.5'))
        triple = self.env('v0.6.5', 'v0.6.4', 'v0.6.5')
        code, out = self.check(env_file=triple)
        self.assertEqual(code, REFUSED, out)
        code, out = self.check(mode='rollback', env_file=triple)
        self.assertEqual(code, UNVERIFIED, out)
        self.assertNotIn('ERROR', out)
        for expected in ('WARNING', 'NOT verified', 'VIDRA_USER_TAG=v0.6.4 belongs to release v0.6.4',
                         'VIDRA_CORE_TAG=v0.6.5 belongs to release v0.6.5',
                         'never released together', 'digests'):
            self.assertIn(expected, out)
        # A pre-manifest tag beside a recorded one is the same shape.
        code, out = self.check(mode='rollback', env_file=self.env(user='v0.6.3'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('VIDRA_USER_TAG=v0.6.3', out)

    def test_rollback_still_refuses_what_predicts_the_wrong_bytes(self):
        """The rollback allowance covers missing bookkeeping only: a digest that
        contradicts the record means running bytes the release never shipped."""
        code, out = self.check(mode='rollback', env_file=self.env(user=f'v0.6.4@{digest(7)}'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_USER_TAG', out)
        self.assertIn(digest(7), out)

    def test_a_stale_bundle_is_refused_even_when_no_record_matches(self):
        """The v0.6.5 bundle unpacked over an install still pinning v0.6.3: no
        record matches, so the record-based bundle comparison never runs, and
        deploy.sh used to dump, pull and migrate before its ledger assertion
        compared v0.6.3's migrator with v0.6.5's schema number."""
        stale = str(self.bundle(tag='v0.6.5', schema='0150', core_commit=hexsha(5)))
        for triple in (('v0.6.3',) * 3, ('v0.6.4', 'v0.6.3', 'v0.6.4')):
            with self.subTest(triple=triple):
                code, out = self.check('--bundle-manifest', stale, env_file=self.env(*triple))
                self.assertEqual(code, REFUSED, out)
                self.assertIn('vidra-bundle.manifest tag is v0.6.5', out)
                self.assertIn(f'VIDRA_CORE_TAG={triple[0]}', out)
        code, out = self.check('--bundle-manifest', stale, mode='rollback',
                               env_file=self.env('v0.6.3', 'v0.6.3', 'v0.6.3'))
        self.assertEqual(code, UNVERIFIED, out)
        code, out = self.check('--bundle-manifest', str(self.bundle(tag='v0.6.3', schema='0144')),
                               env_file=self.env('v0.6.3', 'v0.6.3', 'v0.6.3'))
        self.assertEqual(code, UNVERIFIED, out)

    def test_values_are_read_the_way_compose_reads_them(self):
        """Compose's env-file parser drops an unquoted ` #` comment and trailing
        whitespace, and reads a quoted value up to its closing quote. deploy.sh
        hands the checker env_get's raw text, which keeps both."""
        for raw in ('v0.6.4 # pinned 2026-09-12', 'v0.6.4   ', 'v0.6.4\t', '"v0.6.4" # quoted'):
            with self.subTest(raw=raw):
                code, out = self.check(env_file=self.env(user=raw))
                self.assertEqual(code, OK, out)
                code, out = self.check('--user', raw)
                self.assertEqual(code, OK, out)
        code, out = self.check(env_file=self.env(user='v0.6.4#no-space'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn("'v0.6.4#no-space'", out)
        self.assertIn('as Compose reads it', out)
        self.assertNotIn('would refuse to parse', out)

    def test_non_release_and_missing_tags_are_refused(self):
        for triple, key in ((('v0.6.4', 'latest', 'v0.6.4'), 'VIDRA_USER_TAG'),
                            (('v0.6.4', 'v0.6.4', None), 'VIDRA_SEARCH_TAG')):
            with self.subTest(triple=triple):
                code, out = self.check(env_file=self.env(*triple))
                self.assertEqual(code, REFUSED, out)
                self.assertIn(key, out)

    def test_env_file_is_read_like_deploy_lib_env_get(self):
        """Last assignment wins, quotes are stripped, and a non-empty process
        environment variable outranks the file — the same precedence compose's
        interpolation and deploy/lib.sh's env_get apply."""
        env_file = self.env(user='v0.6.3', extra='VIDRA_USER_TAG="v0.6.4"\n')
        code, out = self.check(env_file=env_file)
        self.assertEqual(code, OK, out)
        code, out = self.check(env_file=env_file, process_env={'VIDRA_USER_TAG': 'v0.6.9'})
        self.assertEqual(code, REFUSED, out)
        code, out = self.check('--user', 'v0.6.4', env_file=env_file,
                               process_env={'VIDRA_USER_TAG': 'v0.6.9'})
        self.assertEqual(code, OK, out)


class RecordValidationTests(Fixture):
    def mutated(self, mutate):
        record = synthetic('v0.6.5', core='v0.6.5', user='v0.6.5', search='v0.6.5')
        mutate(record)
        return record

    def test_malformed_records_are_fatal_in_deploy_and_warn_in_rollback(self):
        """A record that cannot be trusted stops a deploy: matching against a
        half-valid set would turn a typo in one file into a verdict about
        another. A rollback is stopped only by what predicts its failure, and a
        broken record predicts nothing about the target's images (H1)."""
        cases = {
            'short tag': lambda r: r.update(release='v0.6'),
            'short commit': lambda r: r['components']['core'].update(commit='ed55a6d'),
            'meta commit': lambda r: r.update(meta_commit='HEAD'),
            'digest': lambda r: r['components']['user']['image'].update(index_digest='sha256:abc'),
            'platform digest': lambda r: r['components']['search']['image'].update(
                platforms={'linux/amd64': 'latest'}),
            'no platforms': lambda r: r['components']['search']['image'].update(platforms={}),
            'string schema': lambda r: r.update(core_schema_version='150'),
            'bool schema': lambda r: r.update(search_schema_version=True),
            'missing component': lambda r: r['components'].pop('search'),
            'unknown key': lambda r: r['components']['core']['image'].update(index_digets='x'),
            'component tag': lambda r: r['components']['user'].update(tag='latest'),
            'schema version': lambda r: r.update(schema_version=2),
        }
        for label, mutate in cases.items():
            for mode, triple, expected in (('deploy', ('v0.6.4',) * 3, REFUSED),
                                           ('rollback', ('v0.6.3',) * 3, UNVERIFIED),
                                           ('rollback', ('v0.6.4',) * 3, UNVERIFIED)):
                with self.subTest(case=label, mode=mode, triple=triple):
                    path = self.add(self.mutated(mutate), name='v0.6.5.json')
                    try:
                        code, out = self.check(mode=mode, env_file=self.env(*triple))
                        self.assertEqual(code, expected, out)
                        self.assertIn('v0.6.5.json', out)
                        if mode == 'rollback':
                            self.assertIn('WARNING', out)
                            self.assertNotIn('ERROR', out)
                    finally:
                        path.unlink()

    def test_unparseable_json_filename_mismatch_and_duplicates_are_fatal(self):
        bad = self.releases / 'v0.6.6.json'
        bad.write_text('{not json')
        misnamed = self.add(synthetic('v0.6.7', 'v0.6.7', 'v0.6.7', 'v0.6.7'), name='v0.6.8.json')
        duplicate = self.add(synthetic('v0.6.9', 'v0.6.4', 'v0.6.4', 'v0.6.4'))
        code, out = self.check()
        self.assertEqual(code, REFUSED, out)
        # Every finding in one run, not one per attempt.
        self.assertIn('v0.6.6.json', out)
        self.assertIn('v0.6.8.json', out)
        self.assertIn('v0.6.9', out)
        for path in (bad, misnamed, duplicate):
            path.unlink()
        self.assertEqual(self.check()[0], OK)

    def test_a_tree_without_records_is_refused_in_deploy(self):
        shutil.rmtree(self.releases)
        code, out = self.check()
        self.assertEqual(code, REFUSED, out)
        self.assertIn('releases', out)


class RecordSetSeverityTests(Fixture):
    """H1. A missing releases/ directory, or a corrupt record for some OTHER
    release, says nothing about whether the rollback target's images work. The
    deploy-guard rule is that a finding may only stop what it predicts, so in a
    rollback these are WARNINGS that name what was therefore not verified. What
    stays fatal is what predicts wrong bytes or a broken env rewrite: a digest
    that contradicts a record that did load, and a target tag that cannot be
    parsed or is unset."""

    def test_rollback_continues_unverified_when_releases_is_missing(self):
        shutil.rmtree(self.releases)
        code, out = self.check(mode='rollback')
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('WARNING', out)
        self.assertNotIn('ERROR', out)
        self.assertIn('NOTHING about', out)
        self.assertIn('not the pairing, not the digests', out)
        self.assertIn('after service is back', out)

    def test_a_corrupt_record_for_another_release_does_not_stop_a_rollback(self):
        (self.releases / 'v0.6.5.json').write_text('{not json')
        code, out = self.check(mode='rollback')
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('v0.6.5.json', out)
        self.assertIn('WARNING', out)
        self.assertNotIn('ERROR', out)
        self.assertIn('after service is back', out)
        # The record that DID load still paired the target, and says so.
        self.assertIn('v0.6.4.json', out)

    def test_the_same_record_set_problems_stay_fatal_in_deploy(self):
        (self.releases / 'v0.6.5.json').write_text('{not json')
        code, out = self.check()
        self.assertEqual(code, REFUSED, out)
        self.assertIn('v0.6.5.json', out)
        shutil.rmtree(self.releases)
        code, out = self.check()
        self.assertEqual(code, REFUSED, out)

    def test_a_digest_contradicting_a_valid_record_still_stops_a_rollback(self):
        """The demotion covers the record set's bookkeeping, not the one record
        that loaded and pairs the target: a pin that contradicts it still means
        bytes the release never shipped."""
        (self.releases / 'v0.6.5.json').write_text('{not json')
        code, out = self.check(mode='rollback', env_file=self.env(user=f'v0.6.4@{digest(7)}'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_USER_TAG pins digest', out)
        self.assertIn(digest(7), out)

    def test_an_unset_or_unparseable_target_stays_fatal_beside_broken_records(self):
        """rollback.sh rewrites the env file from these values; an unparseable
        one predicts a broken env_set_key, records or no records."""
        shutil.rmtree(self.releases)
        for triple, key in ((('v0.6.4', 'latest', 'v0.6.4'), 'VIDRA_USER_TAG'),
                            (('v0.6.4', 'v0.6.4', None), 'VIDRA_SEARCH_TAG')):
            with self.subTest(triple=triple):
                code, out = self.check(mode='rollback', env_file=self.env(*triple))
                self.assertEqual(code, REFUSED, out)
                self.assertIn(key, out)

    def test_a_duplicate_pairing_warns_in_rollback_and_a_pin_matching_either_record_passes(self):
        """Two records pairing one triple is a record-set fault, so in a
        rollback it warns. A digest pin is then held against BOTH: it is a
        contradiction only when neither record shipped it."""
        other = synthetic('v0.6.9', 'v0.6.4', 'v0.6.4', 'v0.6.4', seed=40)
        self.add(other)
        real = json.loads((RECORDS / 'v0.6.4.json').read_text())
        for pinned in (other['components']['core']['image']['index_digest'],
                       real['components']['core']['image']['index_digest']):
            with self.subTest(pinned=pinned):
                code, out = self.check(mode='rollback', env_file=self.env(core=f'v0.6.4@{pinned}'))
                self.assertEqual(code, UNVERIFIED, out)
                self.assertIn('v0.6.9', out)
                self.assertNotIn('ERROR', out)
        code, out = self.check(mode='rollback', env_file=self.env(core=f'v0.6.4@{digest(7)}'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn(digest(7), out)


class OverrideTests(Fixture):
    """M2. `--unrecorded warn` is what deploy/lib.sh passes for
    VIDRA_RELEASE_MAPPING=warn: a pairing no record pairs WARNS instead of
    stopping the run, naming exactly what was skipped. It is for the first
    deploy of a release whose record has not landed yet, and for rehearsal
    labs. It must never reach past the mapping: a digest that contradicts a
    record, a tag that cannot be parsed, a broken releases/ and a stale bundle
    all predict a real failure and still stop the run."""

    def test_unrecorded_warn_downgrades_a_pairing_refusal_and_names_what_was_skipped(self):
        self.add(synthetic('v0.6.6', 'v0.6.6', 'v0.6.6', 'v0.6.6'))
        for triple in (('v0.6.5',) * 3, ('v0.6.6', 'v0.6.4', 'v0.6.6')):
            with self.subTest(triple=triple):
                code, out = self.check(env_file=self.env(*triple))
                self.assertEqual(code, REFUSED, out)
                code, out = self.check('--unrecorded', 'warn', env_file=self.env(*triple))
                self.assertEqual(code, UNVERIFIED, out)
                self.assertIn('WARNING', out)
                self.assertNotIn('ERROR', out)
                self.assertIn('VIDRA_RELEASE_MAPPING=warn', out)
                self.assertIn('NOT verified', out)
                self.assertIn('released together', out)
                self.assertIn('digests', out)
        self.assertIn('VIDRA_USER_TAG=v0.6.4 belongs to release v0.6.4', out)

    def test_unrecorded_warn_cannot_bypass_a_digest_contradiction(self):
        code, out = self.check('--unrecorded', 'warn', env_file=self.env(core=f'v0.6.4@{digest(7)}'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_CORE_TAG pins digest', out)

    def test_unrecorded_warn_cannot_bypass_an_unparseable_tag_or_a_broken_record_set(self):
        for triple in (('v0.6.4', 'latest', 'v0.6.4'), ('v0.6.4', 'v0.6.4', None)):
            with self.subTest(triple=triple):
                code, out = self.check('--unrecorded', 'warn', env_file=self.env(*triple))
                self.assertEqual(code, REFUSED, out)
        (self.releases / 'v0.6.5.json').write_text('{not json')
        code, out = self.check('--unrecorded', 'warn')
        self.assertEqual(code, REFUSED, out)
        self.assertIn('v0.6.5.json', out)

    def test_unrecorded_warn_cannot_bypass_a_stale_bundle(self):
        stale = str(self.bundle(tag='v0.6.5', schema='0150', core_commit=hexsha(5)))
        code, out = self.check('--unrecorded', 'warn', '--bundle-manifest', stale,
                               env_file=self.env('v0.6.4', 'v0.6.3', 'v0.6.4'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('vidra-bundle.manifest tag is v0.6.5', out)

    def test_unrecorded_warn_changes_nothing_about_a_recorded_release(self):
        code, out = self.check('--unrecorded', 'warn')
        self.assertEqual(code, OK, out)
        self.assertNotIn('WARNING', out)


class RegistryOwnerTests(Fixture):
    """M5. docker-compose.prod.yml renders
    ${VIDRA_IMAGE_REGISTRY:-ghcr.io}/${VIDRA_IMAGE_OWNER:-yegamble}/vidra-core:${TAG}.
    The checker validated the recorded repository's SHAPE and never compared
    it, so a fork or a mirror pulling different images was told "is release
    v0.6.4". The two keys are read the way the tags are (env_get in lib.sh, or
    --env), the effective prefix is compared with the record, and a difference
    is UNVERIFIED with a warning naming both: a fork is legitimate, and the
    record simply cannot describe its images."""

    def test_the_defaults_render_the_recorded_repository(self):
        for extra in ('', 'VIDRA_IMAGE_OWNER=yegamble\nVIDRA_IMAGE_REGISTRY=ghcr.io\n',
                      'VIDRA_IMAGE_OWNER=\nVIDRA_IMAGE_REGISTRY=\n'):   # ${VAR:-x}: empty is unset
            with self.subTest(extra=extra):
                code, out = self.check(env_file=self.env(extra=extra))
                self.assertEqual(code, OK, out)
                self.assertNotIn('WARNING', out)
        code, out = self.check('--registry', '', '--owner', '')
        self.assertEqual(code, OK, out)

    def test_a_fork_owner_is_unverified_not_refused(self):
        for source in ('env file', 'process environment', 'flag'):
            with self.subTest(source=source):
                kwargs = {'env file': dict(env_file=self.env(extra='VIDRA_IMAGE_OWNER=mycorp # fork\n')),
                          'process environment': dict(process_env={'VIDRA_IMAGE_OWNER': 'mycorp'}),
                          'flag': {}}[source]
                args = ('--owner', 'mycorp') if source == 'flag' else ()
                code, out = self.check(*args, **kwargs)
                self.assertEqual(code, UNVERIFIED, out)
                self.assertIn('WARNING', out)
                self.assertNotIn('ERROR', out)
                self.assertIn('ghcr.io/mycorp', out)
                self.assertIn('ghcr.io/yegamble/vidra-core', out)
                self.assertIn('VIDRA_IMAGE_OWNER', out)

    def test_a_mirror_registry_is_unverified_not_refused(self):
        code, out = self.check(env_file=self.env(extra='VIDRA_IMAGE_REGISTRY=registry.internal:5000\n'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('registry.internal:5000/yegamble', out)
        self.assertIn('ghcr.io/yegamble/vidra-core', out)
        code, out = self.check('--registry', 'registry.internal:5000', mode='rollback')
        self.assertEqual(code, UNVERIFIED, out)

    def test_a_fork_pin_is_not_held_to_the_upstream_digest(self):
        """A fork's image cannot carry the upstream digest, so a pin under a
        fork owner is reported as NOT compared, not as a contradiction."""
        code, out = self.check(env_file=self.env(core=f'v0.6.4@{digest(7)}',
                                                 extra='VIDRA_IMAGE_OWNER=mycorp\n'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('Digest pins not checked', out)
        self.assertNotIn('ERROR', out)

    def test_a_fork_owner_excuses_neither_a_mixed_triple_nor_a_stale_bundle(self):
        code, out = self.check(env_file=self.env(user='v0.6.3', extra='VIDRA_IMAGE_OWNER=mycorp\n'))
        self.assertEqual(code, REFUSED, out)
        code, out = self.check('--bundle-manifest', str(self.bundle(schema='0145')),
                               env_file=self.env(extra='VIDRA_IMAGE_OWNER=mycorp\n'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('core_schema_version', out)


class ExtraRecordTests(Fixture):
    """`--extra-record`: ONE record from outside releases/, for this run only.

    The gap it exists for: deploy/release.sh pushes this repository's tag
    BEFORE any image (and so any digest) exists, so a vN tree and the vN bundle
    carry records only up to v(N-1), and deploying vN compares tag strings
    only. deploy/lib.sh fetches releases/vN.json from the repository at deploy
    time and hands it over here.

    The flag may only ever ADD verification. It is admitted when it pairs
    exactly the triple being deployed and releases/ does not already speak for
    that release; anything else — another release, an unreadable file, a file
    that is not a valid record — is IGNORED with a warning and the verdict is
    the one the run would have reached without it. Absence must never become a
    refusal: a record that could not be fetched predicts nothing about the
    bytes, and the fetch is best-effort by design.
    """

    def outside(self, record, name=None, text=None):
        """A record written OUTSIDE releases/, the way lib.sh's fetch writes
        it: into its own temp directory, named <release>.json."""
        directory = self.base / 'fetched'
        directory.mkdir(exist_ok=True)
        path = directory / (name or (record['release'] + '.json') if record else name)
        path.write_text(text if text is not None else json.dumps(record, indent=2))
        return path

    def test_a_fetched_record_verifies_the_newest_release_and_names_its_provenance(self):
        """The whole point: the release whose record cannot be in this tree."""
        record = synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7)
        path = self.outside(record)
        env_file = self.env('v0.7.0', 'v0.7.0', 'v0.7.0')
        code, out = self.check(env_file=env_file)
        self.assertEqual(code, UNVERIFIED, out)          # control: without it
        self.assertIn('newer than every record', out)
        code, out = self.check('--extra-record', str(path), env_file=env_file)
        self.assertEqual(code, OK, out)
        self.assertNotIn('ERROR', out)
        self.assertIn(str(path), out, 'the output does not name where the record came from')
        self.assertIn('v0.7.0', out)

    def test_a_matching_digest_pin_is_held_against_the_fetched_record(self):
        """VIDRA_USER_TAG is the one pin that reaches the digest comparison
        today (deploy.sh's embedded-migrator floor refuses the core/search
        spelling first), so it is the one this must verify."""
        record = synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7)
        path = self.outside(record)
        pinned = record['components']['user']['image']['index_digest']
        code, out = self.check('--extra-record', str(path),
                               env_file=self.env('v0.7.0', f'v0.7.0@{pinned}', 'v0.7.0'))
        self.assertEqual(code, OK, out)
        self.assertNotIn('Digest pins not checked', out)

    def test_a_contradicting_digest_in_a_fetched_record_is_fatal_in_both_modes(self):
        """A contradiction is what predicts wrong bytes: docker pulls by
        digest, so this would run bytes that release never shipped."""
        record = synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7)
        path = self.outside(record)
        env_file = self.env('v0.7.0', f'v0.7.0@{digest(99)}', 'v0.7.0')
        for mode in ('deploy', 'rollback'):
            with self.subTest(mode=mode):
                code, out = self.check('--extra-record', str(path), mode=mode, env_file=env_file)
                self.assertEqual(code, REFUSED, out)
                self.assertIn('VIDRA_USER_TAG pins digest', out)

    def test_a_record_for_another_release_is_ignored_and_changes_no_verdict(self):
        """NO SILENT WIDENING. A record for some other release would join the
        set every verdict is computed against — it would move `newest`, the
        recorded-release list and which findings are reported. Here admitting
        v0.7.1 would make v0.7.0 no longer newer than every record and turn a
        WARNING into a refusal."""
        other = self.outside(synthetic('v0.7.1', 'v0.7.1', 'v0.7.1', 'v0.7.1', seed=7))
        env_file = self.env('v0.7.0', 'v0.7.0', 'v0.7.0')
        without_code, without_out = self.check(env_file=env_file)
        code, out = self.check('--extra-record', str(other), env_file=env_file)
        self.assertEqual(code, without_code, out)
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('newer than every record', out)
        self.assertIn('v0.7.1', out)
        self.assertIn('ignored', out.lower())
        self.assertNotIn('ERROR', out)
        self.assertIn('newer than every record', without_out)

    def test_a_record_the_tree_already_carries_is_ignored(self):
        """releases/ on disk is the tree's own statement; a file handed in for
        one run may not quietly replace it."""
        forged = dict(json.loads((self.releases / 'v0.6.4.json').read_text()))
        forged['core_schema_version'] = 999
        path = self.outside(forged)
        code, out = self.check('--extra-record', str(path))
        self.assertEqual(code, OK, out)
        self.assertIn('ignored', out.lower())
        self.assertNotIn('999', out)

    def test_an_unusable_fetched_record_keeps_todays_unverified_verdict(self):
        """The fetch is best-effort. Truncated JSON, an HTML error page and a
        well-formed file that is not a valid record must each leave the run
        exactly where it would have been, saying the fetched record was
        unusable. Turning absence into a refusal would stop the first deploy of
        every release.

        'deeply nested' is the one that was NOT merely unusable: 60 KB of
        `{"a":[[[[...]]]]}` passes every size and shape guard in lib.sh and
        makes json.loads raise RecursionError, which is not a ValueError. It
        escaped the except clause, printed a traceback and exited 1 — turning
        a body chosen by whoever answers the request into a dead deploy AND a
        dead rollback. Every other entry here is a control for it."""
        cases = {
            'truncated': '{"schema_version": 1, "release": "v0.7.0", "comp',
            'html error page': '<!DOCTYPE html><html><body>404: Not Found</body></html>\n',
            'empty': '',
            'not a record': json.dumps({'hello': 'world'}),
            'unknown key': json.dumps({**synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0'),
                                       'index_digets': 'typo'}),
            'deeply nested': '{"a":' + '[' * 30000 + ']' * 30000 + '}',
            'utf-8 BOM': '﻿' + json.dumps(synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0')),
        }
        env_file = self.env('v0.7.0', 'v0.7.0', 'v0.7.0')
        for label, text in cases.items():
            with self.subTest(body=label):
                path = self.outside(None, name='v0.7.0.json', text=text)
                code, out = self.check('--extra-record', str(path), env_file=env_file)
                self.assertEqual(code, UNVERIFIED, out)
                self.assertNotIn('Traceback', out, 'the checker crashed instead of reporting')
                self.assertIn('unusable', out)
                self.assertIn('newer than every record', out)
                self.assertNotIn('ERROR', out)

    def test_bytes_that_are_not_utf8_are_unusable_not_a_crash(self):
        path = self.base / 'fetched'
        path.mkdir(exist_ok=True)
        target = path / 'v0.7.0.json'
        target.write_bytes(b'{"release": "v0.7.0", "\xff\xfe": 1}')
        code, out = self.check('--extra-record', str(target),
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertNotIn('Traceback', out)
        self.assertIn('unusable', out)

    def test_an_oversized_extra_record_is_refused_without_being_parsed(self):
        """--extra-record takes any path, so the size cap cannot live only in
        lib.sh's curl. A hostile body is cheapest to refuse by its size."""
        path = self.outside(None, name='v0.7.0.json', text='{"x":"' + 'y' * (300 * 1024) + '"}')
        code, out = self.check('--extra-record', str(path),
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('unusable', out)
        self.assertIn('large', out.lower())

    def test_a_record_whose_components_outrank_its_own_release_is_ignored(self):
        """STRUCTURAL RULE. A record is a statement about ONE release, so no
        component in it may carry a tag newer than the release it names, and at
        least one must equal it. A record claiming release v0.7.0 while pairing
        v0.9.0 images describes something release.sh cannot cut, and admitting
        it would let a record vouch for images from a release it is not."""
        bad = synthetic('v0.7.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=7)
        bad['release'] = 'v0.7.0'
        path = self.outside(None, name='v0.7.0.json', text=json.dumps(bad))
        code, out = self.check('--extra-record', str(path),
                               env_file=self.env('v0.9.0', 'v0.9.0', 'v0.9.0'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('ignored', out.lower())
        self.assertNotIn('ERROR', out)

    def test_a_record_no_component_of_which_is_its_own_release_is_ignored(self):
        older = synthetic('v0.9.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7)
        older['release'] = 'v0.9.0'
        path = self.outside(None, name='v0.9.0.json', text=json.dumps(older))
        code, out = self.check('--extra-record', str(path),
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('ignored', out.lower())

    def test_a_core_only_release_is_verified_by_its_fetched_record(self):
        """THE SHAPE VIDRA ACTUALLY SHIPS. v0.7.4 and v0.7.5 re-released
        vidra-core alone, so their records pair a new core with the previous
        user and search. Such a triple is not uniform, and must verify from a
        fetched record exactly as a uniform one does."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.7.3', 'v0.7.3', seed=9)
        path = self.outside(record)
        code, out = self.check('--extra-record', str(path),
                               env_file=self.env('v0.9.0', 'v0.7.3', 'v0.7.3'))
        self.assertEqual(code, OK, out)
        self.assertIn(str(path), out)

    def test_the_admitted_marker_is_printed_on_stdout_only_when_admitted(self):
        """deploy/lib.sh reads this line to decide whether the second pass may
        replace the first pass's verdict. It goes on STDOUT, where no text from
        the fetched record can ever appear (record content only reaches
        warnings and errors, which go to stderr), so a crafted record cannot
        forge it."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        path = self.outside(record)
        env_file = self.env('v0.9.0', 'v0.9.0', 'v0.9.0')
        result = subprocess.run(
            ['python3', str(CHECKER), 'check', '--mode', 'deploy', '--releases', str(self.releases),
             '--env', str(env_file), '--extra-record', str(path)],
            capture_output=True, text=True, env={'PATH': os.environ['PATH']})
        self.assertEqual(result.returncode, OK, result.stdout + result.stderr)
        self.assertIn('[release-mapping] extra-record-admitted v0.9.0', result.stdout)
        self.assertNotIn('extra-record-admitted', result.stderr)
        # Ignored: no marker at all.
        other = self.outside(synthetic('v0.7.1', 'v0.7.1', 'v0.7.1', 'v0.7.1', seed=7))
        result = subprocess.run(
            ['python3', str(CHECKER), 'check', '--mode', 'deploy', '--releases', str(self.releases),
             '--env', str(env_file), '--extra-record', str(other)],
            capture_output=True, text=True, env={'PATH': os.environ['PATH']})
        self.assertNotIn('extra-record-admitted', result.stdout + result.stderr)


    def test_a_path_that_does_not_exist_is_unusable_not_fatal(self):
        code, out = self.check('--extra-record', str(self.base / 'nope/v0.7.0.json'),
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, UNVERIFIED, out)
        self.assertIn('unusable', out)
        self.assertNotIn('ERROR', out)

    def test_a_mixed_triple_is_still_refused_in_a_deploy(self):
        """The fetched record is not an override. The record for v0.7.0 cannot
        vouch for a v0.7.0 core beside a v0.6.4 user, and must not be read as
        if it could."""
        path = self.outside(synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7))
        code, out = self.check('--extra-record', str(path),
                               env_file=self.env('v0.7.0', 'v0.6.4', 'v0.7.0'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('VIDRA_USER_TAG', out)

    def test_a_fetched_record_does_not_excuse_a_stale_bundle(self):
        """The bundle comparison is about THIS tree's compose files and the
        ledger number deploy.sh will assert; a record cannot speak for it."""
        record = synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7, core_schema=150)
        path = self.outside(record)
        code, out = self.check('--extra-record', str(path),
                               '--bundle-manifest', str(self.bundle(tag='v0.6.4', schema='0146')),
                               env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('vidra-bundle.manifest tag is v0.6.4', out)

    def test_a_genuine_bundle_and_its_genuine_fetched_record_verify(self):
        """H. The beta host IS a bundle tree, and the fetched record now
        reaches bundle_findings — a refusal path that was previously
        unreachable for the newest release, because no record ever loaded for
        it. A genuine vN bundle beside vN's genuine record must therefore
        VERIFY: if this ever refused, the fetch would have turned every
        bundle-host upgrade into a stopped deploy."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9, core_schema=151)
        record['components']['core']['commit'] = hexsha(9)
        path = self.outside(record)
        manifest = self.bundle(tag='v0.9.0', schema='0151', core_commit=hexsha(9))
        code, out = self.check('--extra-record', str(path), '--bundle-manifest', str(manifest),
                               env_file=self.env('v0.9.0', 'v0.9.0', 'v0.9.0'))
        self.assertEqual(code, OK, out)
        self.assertNotIn('ERROR', out)
        self.assertIn('151', out, 'the note does not carry the core schema the ledger will assert')

    def test_a_core_only_release_bundle_is_compared_against_the_records_core_tag(self):
        """A core-only release ships a new bundle at the CORE tag, which is
        also the release tag; the user/search pins stay behind. The bundle
        comparison must use the record's core tag, not the platform tag."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.7.3', 'v0.7.3', seed=9, core_schema=151)
        record['components']['core']['commit'] = hexsha(9)
        path = self.outside(record)
        manifest = self.bundle(tag='v0.9.0', schema='0151', core_commit=hexsha(9))
        code, out = self.check('--extra-record', str(path), '--bundle-manifest', str(manifest),
                               env_file=self.env('v0.9.0', 'v0.7.3', 'v0.7.3'))
        self.assertEqual(code, OK, out)

    def test_a_bundle_whose_provenance_disagrees_with_the_fetched_record_is_refused(self):
        """The other direction, and why the path above must stay reachable:
        deploy.sh takes the expected schema number from this manifest, so a
        manifest describing another build would make the ledger assertion pass
        or fail against the wrong number AFTER the migrations have run."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9, core_schema=151)
        record['components']['core']['commit'] = hexsha(9)
        path = self.outside(record)
        for label, manifest in (
                ('schema', self.bundle(tag='v0.9.0', schema='0150', core_commit=hexsha(9))),
                ('commit', self.bundle(tag='v0.9.0', schema='0151', core_commit=hexsha(4)))):
            with self.subTest(disagrees_on=label):
                code, out = self.check('--extra-record', str(path),
                                       '--bundle-manifest', str(manifest),
                                       env_file=self.env('v0.9.0', 'v0.9.0', 'v0.9.0'))
                self.assertEqual(code, REFUSED, out)
                self.assertIn('vidra-bundle.manifest', out)


class MissingReleaseTests(Fixture):
    """`--print-missing-release`: the checker, and ONLY the checker, decides
    which release's record would settle a run.

    deploy/lib.sh needs that answer to know what to fetch, and re-deriving
    "newest of the three pinned tags" in bash would be a second semver
    implementation drifting against this one — the first cut of this feature
    used the CORE tag, which is right for a core-only release by accident and
    wrong for any other shape. It prints the tag and nothing else, and exits 0
    whatever the verdict: an older checker that does not know the flag exits 2
    and prints nothing, which is exactly the "do not fetch, keep the first
    pass's verdict" answer.
    """

    def missing(self, *args, mode='deploy', env_file=None):
        env_file = env_file or self.env()
        result = subprocess.run(
            ['python3', str(CHECKER), 'check', '--mode', mode, '--releases', str(self.releases),
             '--env', str(env_file), '--print-missing-release', *args],
            capture_output=True, text=True, env={'PATH': os.environ['PATH']})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def test_a_uniform_release_newer_than_every_record_is_named(self):
        self.assertEqual(self.missing(env_file=self.env('v0.9.0', 'v0.9.0', 'v0.9.0')), 'v0.9.0')

    def test_a_core_only_release_names_its_newest_pin_not_its_core_by_position(self):
        """v0.7.4/v0.7.5 are core-only, so the newest pin is the core tag —
        but the rule is `newest`, not `core`, so a user-only release would
        name the user tag."""
        self.assertEqual(self.missing(env_file=self.env('v0.9.0', 'v0.6.4', 'v0.6.4')), 'v0.9.0')
        self.assertEqual(self.missing(env_file=self.env('v0.6.4', 'v0.9.0', 'v0.6.4')), 'v0.9.0')
        self.assertEqual(self.missing(env_file=self.env('v0.6.4', 'v0.6.4', 'v0.9.0')), 'v0.9.0')

    def test_a_recorded_release_names_nothing(self):
        self.assertEqual(self.missing(), '')

    def test_a_triple_whose_newest_pin_is_already_recorded_names_nothing(self):
        """Fetching cannot help: the record for the newest pin is right here,
        and it is what produced the refusal."""
        self.add(synthetic('v0.6.5', 'v0.6.5', 'v0.6.5', 'v0.6.5'))
        self.assertEqual(self.missing(env_file=self.env('v0.6.4', 'v0.6.5', 'v0.6.4')), '')

    def test_a_release_older_than_every_record_names_nothing(self):
        """Nothing before the first record has one anywhere; a GET per deploy
        of a historical release would 404 every time."""
        self.assertEqual(self.missing(env_file=self.env('v0.5.0', 'v0.5.0', 'v0.5.0')), '')

    def test_an_unparseable_tag_names_nothing(self):
        self.assertEqual(self.missing(env_file=self.env('latest', 'latest', 'latest')), '')

    def test_a_rollback_of_an_unpaired_triple_names_its_newest_pin(self):
        self.assertEqual(self.missing(mode='rollback',
                                      env_file=self.env('v0.9.0', 'v0.9.0', 'v0.9.0')), 'v0.9.0')

    def test_it_prints_only_the_tag_and_never_a_verdict(self):
        out = self.missing(env_file=self.env('v0.9.0', 'v0.6.4', 'v0.6.4'))
        self.assertEqual(out, 'v0.9.0')
        self.assertNotIn('WARNING', out)
        self.assertNotIn('ERROR', out)


class CommittedRecordTests(unittest.TestCase):
    def test_v064_record_matches_the_release_evidence(self):
        """releases/v0.6.4.json was copied from the frozen verification
        evidence; this keeps the two from drifting apart."""
        record = json.loads((RECORDS / 'v0.6.4.json').read_text())
        manifest = json.loads((EVIDENCE / 'manifest.json').read_text())
        runtime = json.loads((EVIDENCE / 'native-runtime/result.json').read_text())
        self.assertEqual(manifest['status'], 'PASS')
        self.assertEqual(record['release'], manifest['tag'])
        self.assertEqual(record['meta_commit'], manifest['repositories']['vidra']['revision'])
        for key, repo in (('core', 'vidra-core'), ('user', 'vidra-user'), ('search', 'vidra-search')):
            with self.subTest(component=key):
                component = record['components'][key]
                image = manifest['images'][repo]
                self.assertEqual(component['tag'], manifest['repositories'][repo]['tag'])
                self.assertEqual(component['commit'], manifest['repositories'][repo]['revision'])
                self.assertEqual(component['commit'], image['revision'])
                self.assertEqual(f"{component['image']['repository']}@{component['image']['index_digest']}",
                                 image['reference'])
                self.assertEqual(component['image']['platforms'],
                                 {image['platform']: image['platform_manifest_digest']})
        ledgers = runtime['ledgers']
        self.assertEqual(record['core_schema_version'], ledgers['schema_migrations']['expected'])
        self.assertEqual(record['search_schema_version'], ledgers['vidra_search_migrations']['expected'])
        self.assertEqual(ledgers['schema_migrations']['source_revision'], record['components']['core']['commit'])
        self.assertEqual(ledgers['vidra_search_migrations']['source_revision'],
                         record['components']['search']['commit'])

    def assert_record_matches_raw_preflight_evidence(self, tag):
        """A record written from the RAW release-preflight manifest — no
        hand-added platform digest and no runtime ledger file, which only
        v0.6.4's evidence carries. The platform digests therefore come from the
        committed `imagetools inspect` transcript, the schema numbers from the
        released images' own `migrate embedded-max` answers, and the bundle
        provenance a bundle host would read is checked against the record too.
        One body for every such release: a per-release copy drifts, and the copy
        is what stops asserting.

        Every lookup is keyed by the tag or DIGEST the record itself claims, so
        evidence belonging to a different release cannot satisfy it — the live
        hazard when a component is retagged at an unchanged commit, because then
        only the digests tell the two releases apart."""
        evidence = ROOT / f'docs/evidence/release-{tag}-verification'
        record = json.loads((RECORDS / f'{tag}.json').read_text())
        manifest = json.loads((evidence / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'PASS')
        self.assertEqual(record['release'], manifest['tag'])
        self.assertEqual(record['meta_commit'], manifest['repositories']['vidra']['revision'])
        # "Name: <repo>:<tag>@sha256:… / Platform: linux/amd64" pairs, as
        # `docker buildx imagetools inspect` prints them.
        transcript = (evidence / 'platform-digests.txt').read_text()
        platform_digests = {}
        for match in re.finditer(r'Name:\s+(ghcr\.io/yegamble/vidra-[a-z]+):(v[0-9]+\.[0-9]+\.[0-9]+)@(sha256:[0-9a-f]{64})\s+MediaType:.*?\s+Platform:\s+(\S+)', transcript):
            platform_digests[(match.group(1), match.group(2), match.group(4))] = match.group(3)
        # Keyed by the DIGEST that was asked, never by the component name: an
        # answer counts only if it came from the image this record pins. Keying
        # by name let v0.6.5's transcript satisfy v0.6.6 (both say 146 and 18).
        answers = dict(re.findall(r'vidra-(?:core|search)@(sha256:[0-9a-f]{64}) migrate embedded-max\n(?:WARNING:[^\n]*\n)?(\d+)\n',
                                  (evidence / 'embedded-max.txt').read_text()))
        provenance = dict(re.findall(r'^([a-z_]+)=(\S+)$',
                                     (evidence / 'bundle-provenance.txt').read_text(), re.MULTILINE))
        for key, repo in (('core', 'vidra-core'), ('user', 'vidra-user'), ('search', 'vidra-search')):
            with self.subTest(component=key):
                component = record['components'][key]
                image = manifest['images'][repo]
                self.assertEqual(component['tag'], manifest['repositories'][repo]['tag'])
                self.assertEqual(component['commit'], manifest['repositories'][repo]['revision'])
                self.assertEqual(component['commit'], image['revision'])
                self.assertEqual(f"{component['image']['repository']}@{component['image']['index_digest']}",
                                 image['reference'])
                self.assertEqual(component['image']['platforms'],
                                 {'linux/amd64': platform_digests[(component['image']['repository'], component['tag'], 'linux/amd64')]})
        for key in ('core', 'search'):
            with self.subTest(schema=key):
                asked = record['components'][key]['image']['platforms']['linux/amd64']
                self.assertEqual(str(record[f'{key}_schema_version']), answers[asked])
        # What deploy.sh reads on a BUNDLE host instead of the nested checkout,
        # to compute the expected migration version: it must name this release.
        self.assertEqual(provenance['tag'], record['release'])
        self.assertEqual(provenance['meta_commit'], record['meta_commit'])
        self.assertEqual(provenance['core_commit'], record['components']['core']['commit'])
        self.assertEqual(int(provenance['core_schema_version']), record['core_schema_version'])

    def test_raw_preflight_records_match_their_release_evidence(self):
        """v0.6.6 re-released vidra-core and vidra-user for the white-label
        toggle. vidra-search was rebuilt at the SAME source revision as v0.6.5,
        so its commit repeats while its image digests do not — the record must
        carry the v0.6.6 bytes, not v0.6.5's. No migration shipped either side,
        so the released images still answer 146 and 18."""
        for tag in sorted(RAW_PREFLIGHT_RELEASES):
            with self.subTest(release=tag):
                self.assert_record_matches_raw_preflight_evidence(tag)

    def test_every_record_has_an_evidence_cross_check(self):
        """A record nothing cross-checks is only FORMAT-validated — exactly how
        v0.6.5's landed at first, with its values compared to nothing. Adding
        releases/vX.Y.Z.json without listing it in RAW_PREFLIGHT_RELEASES (or
        writing a bespoke test, as v0.6.4 has) fails here instead of shipping an
        unchecked record."""
        self.assertEqual({path.stem for path in RECORDS.glob('*.json')},
                         {'v0.6.4'} | RAW_PREFLIGHT_RELEASES)

    def test_every_committed_record_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / 'production.env'
            env_file.write_text('VIDRA_CORE_TAG=v0.6.4\nVIDRA_USER_TAG=v0.6.4\nVIDRA_SEARCH_TAG=v0.6.4\n')
            result = subprocess.run(['python3', str(CHECKER), 'check', '--mode', 'deploy',
                                     '--releases', str(RECORDS), '--env', str(env_file)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, OK, result.stdout + result.stderr)

    def test_the_bundle_ships_the_records_and_the_checker(self):
        """A bundle host has no checkout to read releases/ from: make-bundle.sh
        must carry it, or every bundle deploy is refused for want of records."""
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp) / 'core'
            (core / 'deploy').mkdir(parents=True)
            (core / 'migrations').mkdir()
            (core / 'migrations/0146_x.up.sql').write_text('select 1;\n')
            (core / 'deploy/x.conf').write_text('x\n')
            (core / 'docker-compose.yml').write_text(
                'services:\n  x:\n    volumes:\n      - ./deploy/x.conf:/etc/x.conf:ro\n')
            out = Path(tmp) / 'bundle.tar.gz'
            result = subprocess.run(['bash', str(ROOT / 'deploy/make-bundle.sh'), '--core', str(core),
                                     '--tag', 'v0.6.4', '--out', str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with tarfile.open(out) as archive:
                names = set(archive.getnames())
        for member in ('./releases/v0.6.4.json', './releases/README.md', './deploy/release-mapping.py'):
            self.assertIn(member, names)


# --- the scripts: a refusal must precede every mutation -----------------------

DOCKER_STUB = '''#!/bin/sh
printf 'docker %s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo v2.30.0 ;;
  *" ps -q postgres") echo pgcid ;;
  "exec -i pgcid psql"*) echo ' 146 | f' ;;
esac
exit 0
'''

GIT_STUB = '''#!/bin/sh
printf 'git %s\\n' "$*" >> "$STUB_LOG"
case " $* " in
  *" fetch "*|*" checkout "*) exit 99 ;;
esac
exec {real} "$@"
'''


class ScriptOrderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.tree = base / 'tree'
        (self.tree / 'deploy').mkdir(parents=True)
        (self.tree / 'env').mkdir()
        for name in ('deploy.sh', 'rollback.sh', 'lib.sh', 'checkout-hygiene.py',
                     'backup-env.sh', 'release-mapping.py'):
            if (ROOT / 'deploy' / name).exists():
                shutil.copyfile(ROOT / 'deploy' / name, self.tree / 'deploy' / name)
        if RECORDS.exists():
            shutil.copytree(RECORDS, self.tree / 'releases')
        self.env_file = self.tree / 'env/production.env'
        self.home = base / 'home'
        self.home.mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()
        self.log = base / 'stub.log'
        for name, body in (('docker', DOCKER_STUB),
                           ('git', GIT_STUB.format(real=shutil.which('git'))),
                           ('curl', '#!/bin/sh\nexit 0\n')):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def write_env(self, core, user, search, extra=''):
        self.env_file.write_text(
            'VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\nPOSTGRES_DB=vidra\n'
            f'JWT_SECRET={SECRET}\nVIDRA_CORE_TAG={core}\nVIDRA_USER_TAG={user}\n'
            f'VIDRA_SEARCH_TAG={search}\n' + extra)

    def as_bundle(self, tag='v0.6.4', schema='0146', core_commit='ed55a6d946dad3f2e72a47b2518ac095352c795d'):
        (self.tree / 'vidra-bundle.manifest').write_text(
            f'tag={tag}\ncore_schema_version={schema}\n'
            'meta_commit=0da18462b009b3710ceac7e60d2e88653bebbc37\n'
            f'core_commit={core_commit}\n')

    def as_checkout(self):
        for repo in (self.tree, self.tree / 'vidra-core'):
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)

    def run_script(self, *args, process_env=None):
        result = subprocess.run(
            ['bash', *map(str, args)],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': str(self.home),
                 'STUB_LOG': str(self.log), 'READY_TIMEOUT': '1', **(process_env or {})},
            capture_output=True, text=True, cwd=str(self.tree))
        calls = self.log.read_text() if self.log.exists() else ''
        out = result.stdout + result.stderr
        self.assertNotIn(SECRET, out)
        return result.returncode, out, calls

    MUTATIONS = ('pg_dump', ' pull', 'run --rm migrate', ' up -d')

    def test_deploy_control_run_reaches_every_mutation_through_the_stubs(self):
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertEqual(code, 0, out)
        for mutation in self.MUTATIONS:
            self.assertIn(mutation, calls)

    def test_deploy_refuses_a_mixed_mapping_before_dump_pull_migrate_or_up(self):
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.3', 'v0.6.4')   # user from the previous release
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertNotEqual(code, 0, out)
        self.assertIn('VIDRA_USER_TAG=v0.6.3', out)
        self.assertIn('release mapping', out)
        for mutation in self.MUTATIONS:
            self.assertNotIn(mutation, calls, f'{mutation!r} ran before the refusal:\n{calls}')

    def test_deploy_refuses_before_the_checkout_sync_moves_anything(self):
        self.as_checkout()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.9')   # a search tag nobody released
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertNotEqual(code, 0, out)
        self.assertIn('VIDRA_SEARCH_TAG=v0.6.9', out)
        self.assertIn(' rev-parse ', calls, 'control: the git stub saw the hygiene preflight')
        self.assertNotIn(' fetch ', calls)
        self.assertNotIn(' checkout ', calls)
        for mutation in self.MUTATIONS:
            self.assertNotIn(mutation, calls)

    def test_rollback_control_run_reaches_pull_and_up_through_the_stubs(self):
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        code, out, calls = self.run_script(self.tree / 'deploy/rollback.sh', '--user', 'v0.6.4')
        self.assertEqual(code, 0, out)
        self.assertIn(' pull', calls)
        self.assertIn(' up -d', calls)

    def test_deploy_refuses_a_stale_bundle_before_dump_pull_migrate_or_up(self):
        """The v0.6.5 bundle unpacked over an install still pinning v0.6.3 (tags
        from before the first record, so no record matches)."""
        self.as_bundle(tag='v0.6.5', schema='0150', core_commit=hexsha(5))
        self.write_env('v0.6.3', 'v0.6.3', 'v0.6.3')
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertNotEqual(code, 0, out)
        self.assertIn('vidra-bundle.manifest tag is v0.6.5', out)
        for mutation in self.MUTATIONS:
            self.assertNotIn(mutation, calls, f'{mutation!r} ran before the refusal:\n{calls}')

    def test_rollback_refuses_a_digest_mismatch_before_rewriting_the_env(self):
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        before = self.env_file.read_bytes()
        code, out, calls = self.run_script(self.tree / 'deploy/rollback.sh', '--user', f'v0.6.4@{digest(7)}')
        self.assertNotEqual(code, 0, out)
        self.assertIn('VIDRA_USER_TAG pins digest', out)
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was rewritten')
        self.assertFalse((self.home / '.local/state/vidra/env-history').exists(),
                         'a snapshot was taken, so the rewrite had started')
        for mutation in (' pull', ' up -d'):
            self.assertNotIn(mutation, calls)

    def test_the_documented_single_component_rollback_warns_and_proceeds(self):
        """`rollback.sh --user <tag>` is in the script's own usage. Mid-incident
        it must not be stopped by a missing pairing record."""
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        code, out, calls = self.run_script(self.tree / 'deploy/rollback.sh', '--user', 'v0.6.3')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING', out)
        self.assertIn('NOT verified', out)
        self.assertIn('VIDRA_USER_TAG=v0.6.3', self.env_file.read_text())
        self.assertIn(' pull', calls)
        self.assertIn(' up -d', calls)

    def test_a_rollback_proceeds_when_releases_is_missing_or_holds_a_corrupt_record(self):
        """H1, end to end: a 3am rollback to a recorded release must not be
        stopped by a releases/ directory that is missing, or by a corrupt record
        for some other release. Neither predicts anything about the target."""
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        for label, damage in (('missing', lambda: shutil.rmtree(self.tree / 'releases')),
                              ('corrupt sibling', lambda: (self.tree / 'releases/v0.6.5.json').write_text('{'))):
            with self.subTest(records=label):
                damage()
                self.log.unlink(missing_ok=True)
                try:
                    code, out, calls = self.run_script(self.tree / 'deploy/rollback.sh', '--user', 'v0.6.4')
                    self.assertEqual(code, 0, out)
                    self.assertIn('WARNING', out)
                    self.assertIn('after service is back', out)
                    self.assertIn(' pull', calls)
                    self.assertIn(' up -d', calls)
                finally:
                    shutil.rmtree(self.tree / 'releases', ignore_errors=True)
                    shutil.copytree(RECORDS, self.tree / 'releases')

    def test_the_env_override_lets_an_unrecorded_pairing_deploy_with_a_warning(self):
        """M2. VIDRA_RELEASE_MAPPING=warn is read through env_get, so it works
        from the env file and from the process environment alike, and lib.sh
        logs it loudly before the checker's own warning."""
        self.as_bundle()
        for source in ('env file', 'process environment'):
            with self.subTest(source=source):
                self.write_env('v0.6.4', 'v0.6.3', 'v0.6.4',
                               extra='VIDRA_RELEASE_MAPPING=warn\n' if source == 'env file' else '')
                self.log.unlink(missing_ok=True)
                code, out, calls = self.run_script(
                    self.tree / 'deploy/deploy.sh',
                    process_env={'VIDRA_RELEASE_MAPPING': 'warn'} if source != 'env file' else None)
                self.assertEqual(code, 0, out)
                self.assertIn('VIDRA_RELEASE_MAPPING=warn', out)
                self.assertIn('WARNING', out)
                self.assertIn('VIDRA_USER_TAG=v0.6.3', out)
                for mutation in self.MUTATIONS:
                    self.assertIn(mutation, calls)

    def test_the_env_override_cannot_bypass_a_digest_contradiction(self):
        self.as_bundle()
        self.write_env('v0.6.4', f'v0.6.4@{digest(7)}', 'v0.6.4', extra='VIDRA_RELEASE_MAPPING=warn\n')
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertNotEqual(code, 0, out)
        self.assertIn('VIDRA_USER_TAG pins digest', out)
        for mutation in self.MUTATIONS:
            self.assertNotIn(mutation, calls, f'{mutation!r} ran before the refusal:\n{calls}')

    def test_a_fork_owner_deploys_with_a_warning_naming_both_repositories(self):
        """M5, end to end: deploy.sh hands VIDRA_IMAGE_REGISTRY/OWNER to the
        checker through env_get, and a fork proceeds UNVERIFIED."""
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4', extra='VIDRA_IMAGE_OWNER=mycorp\n')
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertEqual(code, 0, out)
        self.assertIn('WARNING', out)
        self.assertIn('ghcr.io/mycorp', out)
        self.assertIn('ghcr.io/yegamble/vidra-core', out)
        self.assertIn('release mapping NOT verified', out)
        for mutation in self.MUTATIONS:
            self.assertIn(mutation, calls)

    def test_a_git_failure_reading_tags_is_logged_and_forfeits_the_allowance(self):
        """L11. lib.sh swallowed every `git tag --points-at HEAD` failure. A
        dubious-ownership refusal then silently forfeited the tree's-own-release
        allowance, and the refusal that followed read as a verdict about the
        tags. One logged line makes it visible."""
        self.as_checkout()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        stub = GIT_STUB.format(real=shutil.which('git')).replace(
            'case " $* " in',
            'case " $* " in\n  *" tag --points-at "*) echo "fatal: detected dubious ownership in repository" >&2; exit 128 ;;')
        (self.bin / 'git').write_text(stub)
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertIn('could not read tags at HEAD', out)
        self.assertIn('dubious ownership', out)
        self.assertIn('forfeited', out)
        self.assertIn(' fetch ', calls, 'control: the mapping check passed on the record and the sync began')

    def test_an_unknown_override_value_is_reported_and_ignored(self):
        """A typo'd override must neither bypass the check silently nor stop a
        run on its own: the normal verdict applies, with a line naming the
        value that was ignored."""
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4', extra='VIDRA_RELEASE_MAPPING=warm\n')
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertEqual(code, 0, out)
        self.assertIn('VIDRA_RELEASE_MAPPING=warm', out)
        self.assertIn('ignored', out)
        self.write_env('v0.6.4', 'v0.6.3', 'v0.6.4', extra='VIDRA_RELEASE_MAPPING=warm\n')
        self.log.unlink(missing_ok=True)
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertNotEqual(code, 0, out)
        for mutation in self.MUTATIONS:
            self.assertNotIn(mutation, calls)

    def strip_helper(self):
        lib = self.tree / 'deploy/lib.sh'
        text = lib.read_text()
        start = text.index('release_mapping_check() {')
        end = text.index('\n}\n', start) + 3
        lib.write_text(text[:start] + text[end:])

    def test_a_lib_from_another_revision_is_named_not_reported_as_a_refusal(self):
        """A released tree with only deploy.sh replaced (the A03 harness did
        exactly that) used to exit 127 and print 'refused the tags'."""
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        self.strip_helper()
        for script in ('deploy/deploy.sh', 'deploy/rollback.sh'):
            with self.subTest(script=script):
                args = [self.tree / script] + (['--user', 'v0.6.4'] if 'rollback' in script else [])
                code, out, calls = self.run_script(*args)
                self.assertNotEqual(code, 0, out)
                self.assertIn('deploy/lib.sh does not define release_mapping_check', out)
                self.assertNotIn('refused', out)
                for mutation in self.MUTATIONS:
                    self.assertNotIn(mutation, calls)

    def test_a_missing_checker_is_named_not_reported_as_a_refusal(self):
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        (self.tree / 'deploy/release-mapping.py').unlink()
        code, out, calls = self.run_script(self.tree / 'deploy/deploy.sh')
        self.assertNotEqual(code, 0, out)
        self.assertIn('deploy/release-mapping.py is missing', out)
        self.assertNotIn('refused', out)
        for mutation in self.MUTATIONS:
            self.assertNotIn(mutation, calls)

    def code_of(self, script):
        return '\n'.join(l for l in (ROOT / 'deploy' / script).read_text().splitlines()
                         if l.strip() and not l.lstrip().startswith('#'))

    def test_deploy_source_order(self):
        """Indexes over the CODE, so a comment cannot move them."""
        code = self.code_of('deploy.sh')
        check = code.index('release_mapping_check "$REPO_ROOT" deploy')
        self.assertLess(code.index('require_embedded_migrate_tag VIDRA_SEARCH_TAG "$('), check)
        self.assertLess(check, code.index('for repo in vidra-core vidra-search vidra-user'))
        self.assertLess(check, code.index('pg_dump'))

    def test_rollback_source_order(self):
        code = self.code_of('rollback.sh')
        check = code.index('release_mapping_check "$REPO_ROOT" rollback')
        self.assertLess(check, code.index('ENV_SNAPSHOT='))
        self.assertLess(check, code.index('env_set_key VIDRA_CORE_TAG'))


# --- the second pass: absent record -> fetched -> verified -------------------

FETCH_CURL_STUB = '''#!/bin/sh
printf 'curl %s\\n' "$*" >> "$STUB_LOG"
dest=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--output" ]; then dest="$arg"; fi
  prev="$arg"
done
if [ "${CURL_EXIT:-0}" = "0" ] && [ -n "$dest" ] && [ -n "${CURL_BODY_FILE:-}" ]; then
  cat "$CURL_BODY_FILE" > "$dest"
fi
exit "${CURL_EXIT:-0}"
'''

RM_STUB = '''#!/bin/sh
if [ -n "${{RM_FAIL_RF:-}}" ]; then
  for a in "$@"; do
    if [ "$a" = "-rf" ]; then
      echo "rm: permission denied (stub)" >&2
      exit 1
    fi
  done
fi
exec {real} "$@"
'''


class FetchedRecordThroughLibTests(unittest.TestCase):
    """release_mapping_check's second pass, end to end through lib.sh.

    Pass 1 is unchanged. When it answers UNVERIFIED (exit 3) AND this tree has
    no releases/<core tag>.json — the shape of every deploy of the newest
    release, because release.sh tags this repository before any image exists —
    the record is fetched and the checker is re-run against it. Verified, the
    pairing and any digest pin are finally held against something. Not
    fetched, the run is exactly where it was.

    curl is stubbed: nothing here touches the network.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.tree = self.base / 'tree'
        (self.tree / 'deploy').mkdir(parents=True)
        (self.tree / 'env').mkdir()
        for name in ('lib.sh', 'release-mapping.py'):
            shutil.copyfile(ROOT / 'deploy' / name, self.tree / 'deploy' / name)
        shutil.copytree(RECORDS, self.tree / 'releases')
        self.env_file = self.tree / 'env/production.env'
        self.env_file.write_text(f'JWT_SECRET={SECRET}\n')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'curl').write_text(FETCH_CURL_STUB)
        (self.bin / 'curl').chmod(0o755)
        # A cleanup that FAILS is the point of two tests below; `rm -f` (the
        # download's own temp file) is passed straight through so only the
        # directory removal is affected.
        (self.bin / 'rm').write_text(RM_STUB.format(real=shutil.which('rm')))
        (self.bin / 'rm').chmod(0o755)
        self.log = self.base / 'stub.log'
        self.tmpdir = self.base / 'tmp'
        self.tmpdir.mkdir()

    def run_check(self, core, user, search, mode='deploy', body=None, exit_code=0,
                  env_extra='', process_env=None):
        # ALWAYS rewritten, never only when env_extra is given: leaving the
        # previous call's keys in place made the "and the default does NOT
        # warn" half of a two-part test re-read the mirror line it had just
        # set, and pass or fail for the wrong reason.
        self.env_file.write_text(f'JWT_SECRET={SECRET}\n' + env_extra)
        # The caller's EXIT trap is installed in EVERY run, not just one test:
        # deploy.sh and rollback.sh source lib.sh, so any `trap ... EXIT` this
        # code adds at function scope would silently replace theirs, and the
        # second pass now installs traps of its own. Asserted below on every
        # path through the checker rather than in one test that could stop
        # covering the path that grows the next trap.
        script = ('set -euo pipefail\n'
                  'log() { printf "[deploy] %s\\n" "$*"; }\n'
                  'trap \'echo "CALLER-EXIT-TRAP-RAN"\' EXIT\n'
                  f'ENV_FILE="{self.env_file}"\n'
                  f'. "{self.tree}/deploy/lib.sh"\n'
                  'before="$(trap -p EXIT)"\n'
                  'rc=0\n'
                  f'release_mapping_check "{self.tree}" {mode} "{core}" "{user}" "{search}" || rc=$?\n'
                  '[ "$before" = "$(trap -p EXIT)" ] || echo "CALLER-EXIT-TRAP-CLOBBERED"\n'
                  'echo "RC=$rc"\n')
        environ = {'PATH': f'{self.bin}:{os.environ["PATH"]}', 'STUB_LOG': str(self.log),
                   'CURL_EXIT': str(exit_code), 'TMPDIR': str(self.tmpdir),
                   'HOME': str(self.base)}
        if body is not None:
            body_file = self.base / 'body.json'
            body_file.write_text(body)
            environ['CURL_BODY_FILE'] = str(body_file)
        environ.update(process_env or {})
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=environ)
        out = result.stdout + result.stderr
        self.assertNotIn(SECRET, out)
        self.assertNotIn('CALLER-EXIT-TRAP-CLOBBERED', out,
                         'release_mapping_check replaced the caller\'s EXIT trap')
        self.assertEqual(out.count('CALLER-EXIT-TRAP-RAN'), 1,
                         f'the caller\'s EXIT trap did not run exactly once:\n{out}')
        calls = self.log.read_text() if self.log.exists() else ''
        self.assertIn('RC=', out, out)
        return int(out.split('RC=')[1].split('\n')[0]), out, calls

    def test_a_record_the_tree_cannot_carry_is_fetched_and_verifies_the_release(self):
        """The whole gap, closed: v0.9.0 pinned, no releases/v0.9.0.json in the
        tree, and the pairing checked all the same."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0',
                                        body=json.dumps(record))
        self.assertEqual(rc, 0, out)
        self.assertIn('releases/v0.9.0.json', calls, 'the record was not requested')
        self.assertIn('fetched', out)
        self.assertIn('used for THIS RUN ONLY', out)
        self.assertIn('is release v0.9.0', out)
        self.assertNotIn('release mapping NOT verified', out)

    def test_a_fetched_record_that_contradicts_a_digest_pin_stops_the_run(self):
        """A pinned digest the release never shipped is the one finding here
        that predicts wrong bytes: docker pulls by digest."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, calls = self.run_check('v0.9.0', f'v0.9.0@{digest(99)}', 'v0.9.0',
                                        body=json.dumps(record))
        self.assertEqual(rc, 1, out)
        self.assertIn('VIDRA_USER_TAG pins digest', out)
        self.assertIn('releases/v0.9.0.json', calls)

    def test_a_404_warns_and_the_run_continues_exactly_as_before(self):
        """The window between publishing a release and its record PR merging.
        Nothing can verify that pairing, and nothing should stop for it."""
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', exit_code=22)
        self.assertEqual(rc, 0, out)
        self.assertIn('could not fetch', out)
        self.assertIn("curl -q --proto '=https'", out,
                      'the warning does not name a curl to run by hand')
        self.assertIn('release mapping NOT verified', out)
        self.assertIn('releases/v0.9.0.json', calls)

    def test_a_record_the_tree_already_has_is_never_fetched(self):
        """No request at all on the overwhelmingly common path: a release the
        tree records. The second pass exists for the newest release only."""
        rc, out, calls = self.run_check('v0.6.4', 'v0.6.4', 'v0.6.4')
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, '', f'a deploy of a recorded release reached out: {calls}')

    def test_record_fetch_off_in_the_env_file_reaches_nothing(self):
        """Airgapped hosts keep exactly today's behaviour, read through
        env_get like VIDRA_SKIP_DNS_PREFLIGHT."""
        for source in ('env file', 'process environment'):
            with self.subTest(source=source):
                self.log.unlink(missing_ok=True)
                rc, out, calls = self.run_check(
                    'v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(synthetic(
                        'v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)),
                    env_extra='VIDRA_RECORD_FETCH=off\n' if source == 'env file' else '',
                    process_env={'VIDRA_RECORD_FETCH': 'off'} if source != 'env file' else None)
                self.assertEqual(rc, 0, out)
                self.assertEqual(calls, '', f'curl ran with the fetch off: {calls}')
                self.assertIn('release mapping NOT verified', out)

    def test_a_rollback_also_gets_the_second_pass_and_absence_still_only_warns(self):
        """Rollback is not made stricter about absence — mid-incident a missing
        record must never stop a return to a known-good release."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', mode='rollback',
                                        body=json.dumps(record))
        self.assertEqual(rc, 0, out)
        self.assertIn('is release v0.9.0', out)
        self.log.unlink(missing_ok=True)
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', mode='rollback',
                                        exit_code=6)
        self.assertEqual(rc, 0, out)
        self.assertIn('could not fetch', out)

    def test_the_fetched_record_is_never_written_into_the_tree(self):
        """It is evidence for one run, not a record this tree may then cite."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record))
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.tree / 'releases/v0.9.0.json').exists())
        self.assertEqual(sorted(p.name for p in self.tmpdir.iterdir()), [],
                         'the fetch left its temporary files behind')

    # --- C: the release shape vidra actually ships -------------------------

    def test_a_core_only_release_is_fetched_and_verified(self):
        """v0.7.4 and v0.7.5 are core-only. With the record absent, pass 1
        answers REFUSED (not UNVERIFIED — the triple is not uniform), and the
        first cut of this feature only fetched on UNVERIFIED. So the operator's
        only route past the newest release was the blanket
        VIDRA_RELEASE_MAPPING=warn override, with the proving record one GET
        away."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.7.3', 'v0.7.3', seed=9)
        rc, out, calls = self.run_check('v0.9.0', 'v0.7.3', 'v0.7.3', body=json.dumps(record))
        self.assertEqual(rc, 0, out)
        self.assertIn('releases/v0.9.0.json', calls, 'the core-only shape attempted no fetch')
        self.assertIn('is release v0.9.0', out)

    def test_a_core_only_release_whose_fetch_fails_keeps_the_refusal(self):
        """This PR may never be LOOSER than main without an admitted record:
        a refusal stays a refusal when nothing was fetched."""
        rc, out, calls = self.run_check('v0.9.0', 'v0.7.3', 'v0.7.3', exit_code=22)
        self.assertEqual(rc, 1, out)
        self.assertIn('could not fetch', out)
        self.assertIn('not a recorded release', out)
        self.assertNotEqual(calls, '')

    def test_a_fetched_record_that_does_not_pair_the_triple_keeps_the_refusal(self):
        """The record is fetched for the newest pin; if it does not pair what
        is actually pinned, the operator has a genuinely unreleased mapping
        and the refusal must stand."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.6.4', 'v0.9.0', body=json.dumps(record))
        self.assertEqual(rc, 1, out)
        self.assertIn('ignored', out.lower())
        self.assertIn('not a recorded release', out)

    def test_a_release_older_than_every_record_reaches_out_for_nothing(self):
        """Nothing before the first record has one anywhere, so a GET here
        would 404 on every historical deploy."""
        rc, out, calls = self.run_check('v0.5.0', 'v0.5.0', 'v0.5.0')
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, '', f'a pre-record release reached out: {calls}')

    # --- B: an unexpected exit from the second pass may not become a die ---

    def stub_checker(self, body):
        (self.tree / 'deploy/release-mapping.py').write_text(body)

    REJECTS_EXTRA_RECORD = '''#!/usr/bin/env python3
"""An older release-mapping.py: it knows --print-missing-release (so the fetch
is attempted) but not --extra-record. A hand-patched NO-GIT bundle tree really
can hold a new lib.sh beside an older checker."""
import sys
if '--print-missing-release' in sys.argv:
    print('v0.9.0')
    sys.exit(0)
if '--extra-record' in sys.argv:
    sys.stderr.write('usage: release-mapping.py\\nrelease-mapping.py: error: '
                     'unrecognized arguments: --extra-record\\n')
    sys.exit(2)
sys.stderr.write('[release-mapping] WARNING: pass one said UNVERIFIED\\n')
sys.exit(3)
'''

    CRASHES_ON_EXTRA_RECORD = REJECTS_EXTRA_RECORD.replace('sys.exit(2)', 'sys.exit(9)')

    def test_a_checker_that_rejects_the_flag_keeps_the_first_passs_verdict(self):
        """The second pass may only REPLACE a verdict, never invent one. Before
        this, rc was reassigned from the second run unconditionally, so
        argparse's exit 2 fell through to `return 1` and KILLED a deploy that
        pass 1 had allowed — a mixed-revision tree turned into an outage by a
        feature whose whole contract is that it can only ever add
        verification."""
        for label, stub, code in (('rejects the flag', self.REJECTS_EXTRA_RECORD, 2),
                                  ('crashes', self.CRASHES_ON_EXTRA_RECORD, 9)):
            with self.subTest(second_pass=label):
                self.log.unlink(missing_ok=True)
                self.stub_checker(stub)
                rc, out, calls = self.run_check(
                    'v0.9.0', 'v0.9.0', 'v0.9.0',
                    body=json.dumps(synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)))
                self.assertEqual(rc, 0, f'exit {code} from the second pass became a die:\n{out}')
                self.assertIn('release mapping NOT verified', out)
                self.assertIn(str(code), out, 'the warning does not say how the second pass ended')
                self.assertNotEqual(calls, '', 'control: the fetch was attempted')

    def test_a_checker_that_never_admits_the_record_keeps_the_first_passs_verdict(self):
        """Exit 0 alone is not enough. Only a run that says it ADMITTED the
        fetched record may speak for it."""
        self.stub_checker('#!/usr/bin/env python3\n'
                          'import sys\n'
                          "if '--print-missing-release' in sys.argv:\n"
                          "    print('v0.9.0'); sys.exit(0)\n"
                          "if '--extra-record' in sys.argv:\n"
                          "    print('[release-mapping] nothing was admitted'); sys.exit(0)\n"
                          "sys.stderr.write('[release-mapping] WARNING: unverified\\n'); sys.exit(3)\n")
        rc, out, _ = self.run_check(
            'v0.9.0', 'v0.9.0', 'v0.9.0',
            body=json.dumps(synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)))
        self.assertEqual(rc, 0, out)
        self.assertIn('release mapping NOT verified', out)

    def test_a_checker_too_old_to_name_a_missing_release_never_fetches(self):
        self.stub_checker('#!/usr/bin/env python3\n'
                          'import sys\n'
                          "sys.stderr.write('usage error\\n')\n"
                          "sys.exit(2 if '--print-missing-release' in sys.argv else 3)\n")
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0')
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, '', 'an older checker still triggered a fetch')

    # --- A: a hostile body may not kill the run ----------------------------

    def test_a_deeply_nested_body_cannot_kill_a_deploy_or_a_rollback(self):
        """60 KB of nested arrays passes every guard in lib.sh and used to
        raise RecursionError inside the checker: traceback, exit 1, dead run.
        Whoever answers the request must not be able to do that."""
        hostile = '{"a":' + '[' * 30000 + ']' * 30000 + '}'
        for mode, expected in (('deploy', 0), ('rollback', 0)):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', mode=mode, body=hostile)
                self.assertEqual(rc, expected, out)
                self.assertNotIn('Traceback', out)
                self.assertIn('release mapping NOT verified', out)

    # --- D: the trust model, made visible ----------------------------------

    def test_a_verdict_resting_on_a_fetched_record_says_so_and_names_the_url(self):
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record))
        self.assertEqual(rc, 0, out)
        self.assertIn('raw.githubusercontent.com/yegamble/vidra/main/releases/v0.9.0.json', out)
        self.assertIn('fetched', out)

    def test_a_non_canonical_record_source_is_a_distinct_warning(self):
        """Pointing the fetch at a mirror moves the trust anchor off the one
        that delivered the bundle. That is legitimate and the operator's
        choice, and it must be visible in the log that records the verdict."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record),
                                    env_extra='VIDRA_RECORD_BASE_URL=https://mirror.internal/rel\n')
        self.assertEqual(rc, 0, out)
        self.assertIn('NON-CANONICAL', out)
        self.assertIn('mirror.internal', out)
        # And the canonical default must NOT raise it.
        self.log.unlink(missing_ok=True)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record))
        self.assertEqual(rc, 0, out)
        self.assertNotIn('NON-CANONICAL', out)

    def test_a_die_caused_by_a_fetched_record_names_the_way_out(self):
        """A forged or simply wrong remote record must never trap an operator
        mid-incident: the stop it causes has to carry its own one-line
        override, or the only way out is reading this source."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', f'v0.9.0@{digest(99)}', 'v0.9.0',
                                    mode='rollback', body=json.dumps(record))
        self.assertEqual(rc, 1, out)
        self.assertIn('VIDRA_RECORD_FETCH=off', out)
        self.assertIn('fetched', out)

    def test_the_stop_names_both_knobs_because_one_is_not_enough(self):
        """THE 3AM PATH, and the reason the message needs two names.

        Turning the fetch off falls back to the tree alone, which can never
        report VERIFIED for a release the tree has no record for. For a
        UNIFORM triple that lands on UNVERIFIED and the run continues, so
        naming one knob was enough. For a CORE-ONLY triple — the shape v0.7.4
        and v0.7.5 actually shipped — pass 1's PAIRING REFUSAL stands, so an
        operator who follows the advice hits a second refusal with nothing to
        follow. VIDRA_RELEASE_MAPPING=warn is what clears that one, and the
        message has to say so."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.7.3', 'v0.7.3', seed=9)
        rc, out, _ = self.run_check('v0.9.0', f'v0.7.3@{digest(99)}', 'v0.7.3',
                                    body=json.dumps(record))
        self.assertEqual(rc, 1, out)
        # Asserted against THE STOP MESSAGE ITSELF, not the whole transcript:
        # pass 1's own refusal text happens to mention the mapping override
        # further up, so a whole-output assertion passes while the line the
        # operator is actually told to act on says nothing about it.
        stop = [line for line in out.splitlines() if 'this stop rests on the record FETCHED' in line]
        self.assertEqual(len(stop), 1, f'the stop message is missing or duplicated:\n{out}')
        self.assertIn('VIDRA_RECORD_FETCH=off', stop[0])
        self.assertIn('VIDRA_RELEASE_MAPPING=warn', stop[0])

    def test_following_that_advice_does_what_the_message_says_for_both_shapes(self):
        """The assertions behind the wording. Without these the message is a
        claim about behaviour with nothing holding it true."""
        # Uniform: the fetch off leaves UNVERIFIED, and the run continues.
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0',
                                        env_extra='VIDRA_RECORD_FETCH=off\n')
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, '')
        self.assertIn('release mapping NOT verified', out)
        # Core-only: the fetch off leaves the PAIRING REFUSAL in place.
        self.log.unlink(missing_ok=True)
        rc, out, calls = self.run_check('v0.9.0', 'v0.7.3', 'v0.7.3',
                                        env_extra='VIDRA_RECORD_FETCH=off\n')
        self.assertEqual(rc, 1, out)
        self.assertEqual(calls, '')
        self.assertIn('not a recorded release', out)
        # ...and the mapping override is what clears it.
        self.log.unlink(missing_ok=True)
        rc, out, _ = self.run_check(
            'v0.9.0', 'v0.7.3', 'v0.7.3',
            env_extra='VIDRA_RECORD_FETCH=off\nVIDRA_RELEASE_MAPPING=warn\n')
        self.assertEqual(rc, 0, out)
        self.assertIn('VIDRA_RELEASE_MAPPING=warn', out)

    # --- the second pass's temp directory ----------------------------------

    def test_the_second_pass_directory_is_made_under_tmpdir(self):
        """A bare `mktemp -d` ignores TMPDIR on BSD, so the directory landed
        somewhere the operator did not choose while the download's own temp
        file honoured it. One convention, or a host that points TMPDIR at a
        big disk gets half of it."""
        # curl's --output is the download's own temp FILE, which already
        # followed the convention — the directory under test is only ever
        # visible as the checker's --extra-record argument, so that is what
        # this records. The stub logs argv and then runs the real checker, so
        # the verdict is still genuine.
        self.stub_checker(
            '#!/usr/bin/env python3\n'
            'import os, subprocess, sys\n'
            'open(os.environ["STUB_LOG"], "a").write("checker " + " ".join(sys.argv[1:]) + "\\n")\n'
            'sys.exit(subprocess.run([sys.executable, os.environ["REAL_CHECKER"], *sys.argv[1:]]).returncode)\n')
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, calls = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record),
                                        process_env={'REAL_CHECKER': str(CHECKER)})
        self.assertEqual(rc, 0, out)
        used = [line.split('--extra-record ', 1)[1].split(' ', 1)[0]
                for line in calls.splitlines() if '--extra-record ' in line]
        self.assertTrue(used, f'the checker was never given an --extra-record path:\n{calls}')
        for path in used:
            self.assertTrue(path.startswith(str(self.tmpdir)),
                            f'the record landed in {path}, outside TMPDIR {self.tmpdir}')
            # A bare `mktemp -d` names its directory `tmp.XXXXXXXX`. The
            # prefix is how this asserts the ONE convention rather than
            # whichever default the host's mktemp happens to pick.
            self.assertIn('vidra-record', path,
                          'the second-pass directory does not follow the same '
                          '"${TMPDIR:-/tmp}/vidra-record.XXXXXX" convention as the '
                          f'download temp file: {path}')

    # --- the second pass's exit-status channel ------------------------------

    def test_a_failing_cleanup_cannot_turn_a_verified_run_into_a_refusal(self):
        """`set -euo pipefail` is in force inside the subshell, because
        deploy.sh and rollback.sh set it and lib.sh is sourced into them. Under
        errexit a FAILING COMMAND IN AN EXIT TRAP rewrites the shell's exit
        status to 1 — measured on 3.2: intended 0, 3, 65 and 64 all came back
        as 1. So an undeletable temp directory turned an ADMITTED, VERIFIED
        re-check into status 1, which the caller read as the checker's
        REFUSED: a fabricated refusal that also blocks a rollback, for a reason
        that predicts nothing about the images.

        The status the subshell means to return must therefore be pinned
        before the trap runs, and the cleanup must not be able to change it."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record),
                                    process_env={'RM_FAIL_RF': '1'})
        self.assertEqual(rc, 0, f'a failed cleanup fabricated a refusal:\n{out}')
        self.assertIn('is release v0.9.0', out)
        self.assertIn('rests on the record fetched from', out)
        self.assertIn('could not be removed', out,
                      'a cleanup that failed should say so, not pass silently')

    def test_a_failing_cleanup_does_not_swallow_a_real_contradiction_either(self):
        """The other direction: pinning the status must not pin it to 'fine'."""
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', f'v0.9.0@{digest(99)}', 'v0.9.0',
                                    body=json.dumps(record), process_env={'RM_FAIL_RF': '1'})
        self.assertEqual(rc, 1, out)
        self.assertIn('VIDRA_RECORD_FETCH=off', out)
        self.assertIn('VIDRA_RELEASE_MAPPING=warn', out)

    KILLS_ITS_PARENT = '''#!/usr/bin/env python3
"""Exits the second pass by a route no trap can catch, so the subshell returns
a status outside this contract's set."""
import os, signal, sys
if '--print-missing-release' in sys.argv:
    print('v0.9.0')
    sys.exit(0)
if '--extra-record' in sys.argv:
    os.kill(os.getppid(), signal.SIGKILL)
    sys.exit(0)
sys.stderr.write('[release-mapping] WARNING: pass one\\n')
sys.exit(int(os.environ.get('PASS1', '3')))
'''

    def test_a_status_outside_the_contract_is_ignored_and_pass_one_stands(self):
        """Status 1 must never again mean two things. With the status pinned,
        the only way out of that subshell other than 0/3/64/65/130 is a signal
        no trap can catch — and whatever it is, the first pass's verdict is
        what stands, in BOTH directions: a run pass 1 allowed still runs, and
        a run pass 1 refused is still refused."""
        record = json.dumps(synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9))
        for label, pass1, expected in (('pass 1 said UNVERIFIED', '3', 0),
                                       ('pass 1 REFUSED', '1', 1)):
            with self.subTest(case=label):
                self.log.unlink(missing_ok=True)
                self.stub_checker(self.KILLS_ITS_PARENT)
                rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=record,
                                            process_env={'PASS1': pass1})
                self.assertEqual(rc, expected, f'{label}: the verdict moved:\n{out}')
                self.assertIn('unexpectedly', out)
                self.assertIn('IGNORED', out)

    def test_an_incidental_errexit_cannot_fabricate_a_verdict(self):
        """The invariant behind the status channel: 0, 3 and 65 must be
        reachable ONLY from the branches that found the admission marker.
        Anything that goes wrong on the way — errexit on a broken binary, an
        unset variable, a missing file — has to land on 64 and leave the first
        pass alone. Here `cat` fails, which aborts the subshell under
        `set -e` BEFORE the marker is ever examined."""
        cat_stub = self.bin / 'cat'
        cat_stub.write_text('#!/bin/sh\necho "cat: broken (stub)" >&2\nexit 1\n')
        cat_stub.chmod(0o755)
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record))
        self.assertEqual(rc, 0, f'a broken binary produced a verdict:\n{out}')
        self.assertIn('release mapping NOT verified', out)
        self.assertNotIn('is release v0.9.0', out,
                         'a run that never read the marker reported a verified release')

    def test_the_status_channel_is_pinned_before_every_exit(self):
        """Source-level guard for the same invariant, because the behavioural
        test above can only reach one of the failure routes. Every `exit` in
        the second-pass subshell must set `st` first, or the EXIT trap returns
        a stale code and the caller acts on the wrong verdict."""
        body = (ROOT / 'deploy/lib.sh').read_text()
        block = body.split('      (\n        st=64\n', 1)
        self.assertEqual(len(block), 2, 'the second-pass subshell was restructured')
        block = block[1].split('\n      )\n', 1)[0]
        pinned = False
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('trap '):
                continue
            if 'exit ' in stripped:
                # `st=` either on an earlier line, or ahead of the exit on
                # this one (`... || { st=64; exit 64; }`).
                self.assertTrue(pinned or 'st=' in stripped.split('exit ', 1)[0],
                                f'`{stripped}` is not preceded by an st= assignment')
                pinned = False
            if stripped.startswith('st='):
                pinned = True

    def test_an_interrupt_during_the_second_pass_leaves_no_directory(self):
        """Ctrl-C while the re-check is running. The download already cleaned
        up after itself; the directory holding it did not."""
        self.stub_checker('#!/usr/bin/env python3\n'
                          'import os, signal, sys\n'
                          "if '--print-missing-release' in sys.argv:\n"
                          "    print('v0.9.0'); sys.exit(0)\n"
                          "if '--extra-record' in sys.argv:\n"
                          '    os.kill(os.getppid(), signal.SIGINT)\n'
                          '    sys.exit(0)\n'
                          "sys.stderr.write('[release-mapping] WARNING: unverified\\n')\n"
                          'sys.exit(3)\n')
        before = {p.name for p in self.tmpdir.iterdir()}
        record = synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9)
        rc, out, _ = self.run_check('v0.9.0', 'v0.9.0', 'v0.9.0', body=json.dumps(record))
        leaked = sorted({p.name for p in self.tmpdir.iterdir()} - before)
        self.assertEqual(leaked, [], f'an interrupted re-check left {leaked} behind')
        self.assertEqual(rc, 1, f'an interrupted preflight must stop the run:\n{out}')
        self.assertIn('interrupted', out.lower())


class ResolveTests(Fixture):
    """`resolve`: WHICH tag each of the three keys should carry for a release.

    `check` answers "may this triple run?". Nothing answered "what IS the
    triple for release vN?", so deploy/pin-release.sh wrote one tag into all
    three VIDRA_*_TAG keys. v0.7.4 and v0.7.5 re-released vidra-core alone and
    pair user and search at v0.7.3, so the documented upgrade command pinned
    ghcr.io/yegamble/vidra-user:v0.7.5 — an image that does not exist — for
    exactly the release running on beta. The record already says what the
    pairing is; this command is the single reader of it, so the shell never
    grows a second record parser of its own.

    Absence is never a refusal (the standing severity ruling: a finding may
    only stop what it predicts). No record, an unreadable one, one naming
    another release: exit 3 with the uniform triple on stdout and a warning,
    which is byte-for-byte what pin-release.sh did before this existed. Exit 1
    is reserved for what DOES predict the wrong bytes: a flag value that is not
    a release tag, and a flag that contradicts a record that loaded.
    """

    def resolve(self, release, *args, record=None, fetched=None):
        argv = ['python3', str(CHECKER), 'resolve', '--release', release]
        if record is not None:
            argv += ['--record', str(record)]
        if fetched is not None:
            argv += ['--fetched-record', str(fetched)]
        result = subprocess.run([*argv, *args], capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def triple(self, stdout):
        """{role: tag} from the three `<role> <tag> <source>` lines."""
        return {line.split()[0]: line.split()[1] for line in stdout.split('\n') if line.strip()}

    def sources(self, stdout):
        return {line.split()[0]: line.split()[2] for line in stdout.split('\n') if line.strip()}

    def written(self, record, name=None):
        path = self.base / (name or record['release'] + '.json')
        path.write_text(json.dumps(record, indent=2))
        return path

    def test_the_real_core_only_record_resolves_each_key_to_its_own_tag(self):
        """THE DEFECT, stated as the shipped release it breaks. Not a synthetic
        fixture: releases/v0.7.5.json is the record on beta today."""
        real = RECORDS / 'v0.7.5.json'
        self.assertTrue(real.is_file(), 'releases/v0.7.5.json is gone; this test guards it')
        code, out, err = self.resolve('v0.7.5', record=real)
        self.assertEqual(code, OK, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.7.5', 'user': 'v0.7.3', 'search': 'v0.7.3'})
        self.assertEqual(set(self.sources(out).values()), {'record-tree'})

    def test_a_uniform_record_resolves_all_three_to_the_release(self):
        path = self.written(synthetic('v0.9.0', 'v0.9.0', 'v0.9.0', 'v0.9.0', seed=9))
        code, out, err = self.resolve('v0.9.0', record=path)
        self.assertEqual(code, OK, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})

    def test_no_record_at_all_falls_back_to_the_release_for_all_three(self):
        """The behaviour every caller had before records were consulted, and
        the one an offline host must keep: UNVERIFIED, never refused."""
        code, out, err = self.resolve('v0.9.0')
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})
        self.assertEqual(set(self.sources(out).values()), {'--release'})

    def test_a_record_path_that_does_not_exist_is_unverified_not_a_crash(self):
        code, out, err = self.resolve('v0.9.0', record=self.base / 'nope.json')
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertNotIn('Traceback', out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})

    def test_a_record_for_another_release_is_ignored_not_obeyed(self):
        """The filename is not the record's identity, and a record served from
        the wrong path must not pair a release it does not name."""
        path = self.written(synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0', seed=7),
                            name='v0.9.0.json')
        code, out, err = self.resolve('v0.9.0', record=path)
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})
        self.assertIn('v0.7.0', err)

    def test_malformed_bodies_are_ignored_not_crashes_and_never_refusals(self):
        cases = {'truncated': '{"schema_version": 1, "release": "v0.9.0", "comp',
                 'html error page': '<!DOCTYPE html><html>404: Not Found</html>\n',
                 'empty': '',
                 'not a record': json.dumps({'hello': 'world'}),
                 'deeply nested': '{"a":' + '[' * 30000 + ']' * 30000 + '}'}
        for label, text in cases.items():
            with self.subTest(body=label):
                path = self.base / 'v0.9.0.json'
                path.write_text(text)
                code, out, err = self.resolve('v0.9.0', record=path)
                self.assertEqual(code, UNVERIFIED, out + err)
                self.assertNotIn('Traceback', out + err, 'it crashed instead of reporting')
                self.assertEqual(self.triple(out),
                                 {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})

    def test_a_record_whose_component_outranks_its_release_is_ignored(self):
        bad = synthetic('v0.9.0', 'v0.9.1', 'v0.9.0', 'v0.9.0', seed=9)
        code, out, err = self.resolve('v0.9.0', record=self.written(bad))
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})
        self.assertIn('NEWER', err)

    def test_a_record_no_component_of_which_is_its_release_is_ignored(self):
        code, out, err = self.resolve(
            'v0.9.0', record=self.written(synthetic('v0.9.0', 'v0.7.3', 'v0.7.3', 'v0.7.3', seed=7)))
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.9.0', 'search': 'v0.9.0'})

    def test_a_component_tag_pins_by_hand_where_no_record_can_be_had(self):
        """The by-hand path the WARNING points at: an airgapped host, or the
        window before the record PR merges."""
        code, out, err = self.resolve('v0.9.0', '--component-tag', 'user=v0.7.3',
                                      '--component-tag', 'search=v0.7.3')
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.7.3', 'search': 'v0.7.3'})
        self.assertEqual(self.sources(out)['user'], '--component-tag')
        self.assertEqual(self.sources(out)['core'], '--release')

    def test_a_component_tag_that_agrees_with_the_record_is_not_a_contradiction(self):
        code, out, err = self.resolve('v0.7.5', '--component-tag', 'user=v0.7.3',
                                      record=RECORDS / 'v0.7.5.json')
        self.assertEqual(code, OK, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.7.5', 'user': 'v0.7.3', 'search': 'v0.7.3'})

    def test_a_component_tag_contradicting_a_usable_record_is_refused(self):
        """A contradiction DOES predict the wrong bytes — one of the two values
        pulls an image the release never contained — so this one stops, and the
        message has to name both so the operator can see which is wrong."""
        code, out, err = self.resolve('v0.7.5', '--component-tag', 'user=v0.7.4',
                                      record=RECORDS / 'v0.7.5.json')
        self.assertEqual(code, REFUSED, out + err)
        self.assertEqual(out, '', 'a refusal printed a triple a caller could act on')
        self.assertIn('v0.7.4', err)
        self.assertIn('v0.7.3', err)
        self.assertIn('--force', err, 'the refusal does not name its own escape')

    def test_force_lets_a_component_tag_beat_the_record_but_never_quietly(self):
        code, out, err = self.resolve('v0.7.5', '--component-tag', 'user=v0.7.4', '--force',
                                      record=RECORDS / 'v0.7.5.json')
        self.assertEqual(code, OK, out + err)
        self.assertEqual(self.triple(out)['user'], 'v0.7.4')
        self.assertIn('WARNING', err)
        self.assertIn('v0.7.3', err, 'the warning does not name the value it overrode')

    def test_nonsense_flag_values_are_refused_and_print_no_triple(self):
        """Every one of these would otherwise be written into the env file and
        die at `compose pull` — or, worse, pull something real and wrong.
        Leading zeros are their own case: v0.07.3 parses to the same (0, 7, 3)
        as v0.7.3, sails through the ordering gate and is not a tag
        deploy/release.sh ever cut."""
        cases = ('frontend=v0.7.3', 'user', 'user=v0.07.3', 'user=latest', 'user=0.7.3',
                 'user=v0.7', 'user=v0.7.3 v0.7.4', '=v0.7.3', 'USER=v0.7.3')
        for value in cases:
            with self.subTest(flag=value):
                code, out, err = self.resolve('v0.9.0', '--component-tag', value)
                self.assertEqual(code, REFUSED, out + err)
                self.assertEqual(out, '')
                self.assertNotIn('Traceback', err)

    def test_a_component_tag_newer_than_the_release_is_refused(self):
        """A release cannot contain an image built after it, with or without a
        record to say so — and v0.7.10 is newer than v0.7.9, not older."""
        for release, override in (('v0.9.0', 'user=v0.9.1'), ('v0.7.9', 'user=v0.7.10')):
            with self.subTest(release=release):
                code, out, err = self.resolve(release, '--component-tag', override)
                self.assertEqual(code, REFUSED, out + err)
                self.assertEqual(out, '')
                self.assertIn('newer', err.lower())

    def test_one_role_named_twice_with_different_tags_is_refused(self):
        code, out, err = self.resolve('v0.9.0', '--component-tag', 'user=v0.7.3',
                                      '--component-tag', 'user=v0.7.2')
        self.assertEqual(code, REFUSED, out + err)
        self.assertEqual(out, '')

    def test_a_release_that_is_not_a_tag_is_refused(self):
        for release in ('latest', 'v0.7', '0.7.5', 'v0.7.5/../x'):
            with self.subTest(release=release):
                code, out, err = self.resolve(release)
                self.assertEqual(code, REFUSED, out + err)
                self.assertEqual(out, '')

    def test_a_prerelease_release_still_resolves_uniformly(self):
        """A rehearsal lab pins vN-rc1, which has no record anywhere and never
        will. pin-release.sh has always accepted it, so this must answer with
        the uniform triple rather than refusing and locking the lab out."""
        code, out, err = self.resolve('v0.7.5-rc1')
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out),
                         {'core': 'v0.7.5-rc1', 'user': 'v0.7.5-rc1', 'search': 'v0.7.5-rc1'})

    def test_a_fetched_record_beats_a_tree_copy_that_disagrees(self):
        """THE STALE-TREE HAZARD. pin-release.sh reads the record off the tree
        the run STARTS on, then checks that tree out at the target tag — which
        does not carry its own record. deploy.sh, running from the moved tree,
        then fetches the canonical copy. If the two disagree the pin is made
        from one record and judged against another, and the deploy is refused
        with the host already moved. The canonical copy wins, and the
        disagreement is named rather than silently resolved."""
        # validate() ties a record's identity to its filename, so each copy
        # needs its own directory rather than its own name.
        for sub, rec in (('tree', synthetic('v0.9.0', 'v0.9.0', 'v0.7.2', 'v0.7.3', seed=2)),
                         ('fetched', synthetic('v0.9.0', 'v0.9.0', 'v0.7.3', 'v0.7.3', seed=5))):
            (self.base / sub).mkdir(exist_ok=True)
            (self.base / sub / 'v0.9.0.json').write_text(json.dumps(rec, indent=2))
        code, out, err = self.resolve('v0.9.0', record=self.base / 'tree/v0.9.0.json',
                                      fetched=self.base / 'fetched/v0.9.0.json')
        self.assertEqual(code, OK, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.7.3', 'search': 'v0.7.3'})
        self.assertEqual(set(self.sources(out).values()), {'record-fetched'})
        self.assertIn('WARNING', err)
        self.assertIn('v0.7.2', err, 'the warning does not name the tree copy it set aside')
        self.assertIn('v0.7.3', err, 'the warning does not name the pairing it used')

    def test_two_records_that_agree_raise_no_disagreement_warning(self):
        for sub in ('tree', 'fetched'):
            (self.base / sub).mkdir(exist_ok=True)
            (self.base / sub / 'v0.9.0.json').write_text(
                json.dumps(synthetic('v0.9.0', 'v0.9.0', 'v0.7.3', 'v0.7.3', seed=5), indent=2))
        code, out, err = self.resolve('v0.9.0', record=self.base / 'tree/v0.9.0.json',
                                      fetched=self.base / 'fetched/v0.9.0.json')
        self.assertEqual(code, OK, out + err)
        self.assertEqual(set(self.sources(out).values()), {'record-fetched'})
        self.assertNotIn('WARNING', err)

    def test_an_unusable_fetched_record_falls_back_to_the_tree_copy(self):
        """A 404 or a captive portal must not cost the pairing this tree can
        state on its own."""
        (self.base / 'fetched').mkdir(exist_ok=True)
        (self.base / 'fetched/v0.7.5.json').write_text('<!DOCTYPE html>not a record')
        code, out, err = self.resolve('v0.7.5', record=RECORDS / 'v0.7.5.json',
                                      fetched=self.base / 'fetched/v0.7.5.json')
        self.assertEqual(code, OK, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.7.5', 'user': 'v0.7.3', 'search': 'v0.7.3'})
        self.assertEqual(set(self.sources(out).values()), {'record-tree'})
        self.assertIn('unusable', err)

    def test_repository_spellings_of_a_role_are_accepted(self):
        """deploy/release-preflight.py's flag takes vidra-user, this one takes
        user, and deploy/README.md now documents them a few paragraphs apart.
        Both spellings work here so the reader cannot pick the wrong one."""
        code, out, err = self.resolve('v0.9.0', '--component-tag', 'vidra-user=v0.7.3',
                                      '--component-tag', 'vidra-search=v0.7.3')
        self.assertEqual(code, UNVERIFIED, out + err)
        self.assertEqual(self.triple(out), {'core': 'v0.9.0', 'user': 'v0.7.3', 'search': 'v0.7.3'})

    def test_the_two_spellings_of_one_role_still_cannot_disagree(self):
        code, out, err = self.resolve('v0.9.0', '--component-tag', 'user=v0.7.3',
                                      '--component-tag', 'vidra-user=v0.7.2')
        self.assertEqual(code, REFUSED, out + err)
        self.assertEqual(out, '')
        code, out, err = self.resolve('v0.9.0', '--component-tag', 'user=v0.7.3',
                                      '--component-tag', 'vidra-user=v0.7.3')
        self.assertEqual(code, UNVERIFIED, out + err)

    def test_the_refusal_lists_the_roles_it_would_accept(self):
        code, out, err = self.resolve('v0.9.0', '--component-tag', 'frontend=v0.7.3')
        self.assertEqual(code, REFUSED, out + err)
        for role in ('core', 'user', 'search'):
            self.assertIn(role, err)

    def test_a_crash_is_its_own_exit_code_and_not_a_refusal(self):
        """THE LESSON FROM #234, applied here. `1` is what any failure returns,
        so sharing it between "this flag contradicts the record" and "the
        resolver fell over" makes the two indistinguishable to the shell — and
        the shell's message would then blame the operator's flag for a bug in
        this file. Forced by making the record reader raise, which is the one
        thing no crafted input can do now that every path through it is
        guarded."""
        args = argparse.Namespace(release='v0.9.0', record=Path('x'), fetched_record=None,
                                  component_tag=[], force=False)
        with patch.object(mapping, 'record_pairing', side_effect=RuntimeError('boom')):
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = mapping.resolve(args)
        self.assertEqual(code, mapping.CRASHED)
        self.assertNotIn(code, (OK, REFUSED, UNVERIFIED, 2))
        self.assertEqual(buf.getvalue(), '', 'a crash printed a triple a caller could act on')
        self.assertIn('boom', err.getvalue())

    def test_check_still_requires_a_mode(self):
        """resolve takes no --mode, so --mode stopped being argparse-required.
        `check` must still refuse to run without one rather than default to a
        severity nobody asked for."""
        result = subprocess.run(['python3', str(CHECKER), 'check', '--releases',
                                 str(self.releases)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('--mode', result.stderr)


if __name__ == '__main__':
    unittest.main()
