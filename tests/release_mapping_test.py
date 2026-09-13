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

    def test_a_release_newer_than_every_record_is_refused_in_deploy(self):
        code, out = self.check(env_file=self.env('v0.7.0', 'v0.7.0', 'v0.7.0'))
        self.assertEqual(code, REFUSED, out)
        self.assertIn('releases/v0.7.0.json', out)

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

    def test_a_pre_manifest_tag_beside_a_recorded_one_is_refused(self):
        for mode in ('deploy', 'rollback'):
            with self.subTest(mode=mode):
                code, out = self.check(mode=mode, env_file=self.env(user='v0.6.3'))
                self.assertEqual(code, REFUSED, out)
                self.assertIn('VIDRA_USER_TAG=v0.6.3', out)

    def test_rollback_to_an_unrecorded_uniform_release_warns(self):
        """Mid-incident, a missing record is a bookkeeping gap, not a prediction
        that the rollback fails: a tag that does not exist still fails the pull,
        which restores the env file. A MIXED target stays fatal."""
        code, out = self.check(mode='rollback', env_file=self.env('v0.6.5', 'v0.6.5', 'v0.6.5'))
        self.assertEqual(code, UNVERIFIED, out)
        code, out = self.check(mode='rollback', env_file=self.env('v0.6.4', 'v0.6.5', 'v0.6.4'))
        self.assertEqual(code, REFUSED, out)

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

    def test_malformed_records_are_fatal_in_every_mode(self):
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
            for mode, triple in (('deploy', ('v0.6.4',) * 3), ('rollback', ('v0.6.3',) * 3)):
                with self.subTest(case=label, mode=mode):
                    path = self.add(self.mutated(mutate), name='v0.6.5.json')
                    try:
                        code, out = self.check(mode=mode, env_file=self.env(*triple))
                        self.assertEqual(code, REFUSED, out)
                        self.assertIn('v0.6.5.json', out)
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

    def test_a_tree_without_records_is_refused(self):
        shutil.rmtree(self.releases)
        code, out = self.check()
        self.assertEqual(code, REFUSED, out)
        self.assertIn('releases', out)


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

    def write_env(self, core, user, search):
        self.env_file.write_text(
            'VIDRA_TLS_MODE=external\nPOSTGRES_USER=vidra\nPOSTGRES_DB=vidra\n'
            f'JWT_SECRET={SECRET}\nVIDRA_CORE_TAG={core}\nVIDRA_USER_TAG={user}\n'
            f'VIDRA_SEARCH_TAG={search}\n')

    def as_bundle(self):
        (self.tree / 'vidra-bundle.manifest').write_text(
            'tag=v0.6.4\ncore_schema_version=0146\n'
            'meta_commit=0da18462b009b3710ceac7e60d2e88653bebbc37\n'
            'core_commit=ed55a6d946dad3f2e72a47b2518ac095352c795d\n')

    def as_checkout(self):
        for repo in (self.tree, self.tree / 'vidra-core'):
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)

    def run_script(self, *args):
        result = subprocess.run(
            ['bash', *map(str, args)],
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'HOME': str(self.home),
                 'STUB_LOG': str(self.log), 'READY_TIMEOUT': '1'},
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

    def test_rollback_refuses_a_mixed_target_before_rewriting_the_env(self):
        self.as_bundle()
        self.write_env('v0.6.4', 'v0.6.4', 'v0.6.4')
        before = self.env_file.read_bytes()
        code, out, calls = self.run_script(self.tree / 'deploy/rollback.sh', '--user', 'v0.6.3')
        self.assertNotEqual(code, 0, out)
        self.assertIn('VIDRA_USER_TAG=v0.6.3', out)
        self.assertEqual(self.env_file.read_bytes(), before, 'the env file was rewritten')
        self.assertFalse((self.home / '.local/state/vidra/env-history').exists(),
                         'a snapshot was taken, so the rewrite had started')
        for mutation in (' pull', ' up -d'):
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
