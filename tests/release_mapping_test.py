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
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'deploy/release-mapping.py'
RECORDS = ROOT / 'releases'
EVIDENCE = ROOT / 'docs/evidence/release-v0.6.4-verification'
# Releases whose committed evidence is the RAW release-preflight output. v0.6.4
# is not one: its manifest carries a hand-added platform digest and a runtime
# ledger file, so it keeps a test of its own. Every record must be covered by one
# or the other -- test_every_record_has_an_evidence_cross_check enforces that.
RAW_PREFLIGHT_RELEASES = {'v0.6.5', 'v0.6.6'}

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
        for match in re.finditer(rf'Name:\s+(ghcr\.io/yegamble/vidra-[a-z]+):{re.escape(tag)}@(sha256:[0-9a-f]{{64}})\s+MediaType:.*?\s+Platform:\s+(\S+)', transcript):
            platform_digests[(match.group(1), match.group(3))] = match.group(2)
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
                                 {'linux/amd64': platform_digests[(component['image']['repository'], 'linux/amd64')]})
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


if __name__ == '__main__':
    unittest.main()
