import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import release_acceptance as runtime
import recovery_release_acceptance as recovery
import recovery_release_export as export

ROOT = Path(__file__).resolve().parents[1]
# The committed manifest of a real release: validate_candidate checks every
# repository revision, image digest and A01 check, so a hand-written stub is not
# a candidate and a mutated copy is not this one (the lesson of #200).
CANDIDATE = json.loads((ROOT / 'docs/evidence/release-v0.6.5-verification/manifest.json').read_text())
CANDIDATE_V075 = json.loads((ROOT / 'docs/evidence/release-v0.7.5-verification/manifest.json').read_text())


class FakeRun:
    """A `Recorder` stand-in that records every query and answers the probe.

    Shared with the migration-drill tests: both harnesses call the same
    `fingerprint`, and it is the WIRING into it that no pure-helper test covers.
    """

    LEDGERS = {'schema_migrations': 146, 'vidra_search_migrations': 18}

    def __init__(self, present=None, ledgers=None):
        self.present = list(present) if present is not None else None
        self.ledgers = dict(self.LEDGERS if ledgers is None else ledgers)
        self.queries = []

    def relations(self, core_version):
        """Everything a candidate at this schema requires — nothing missing."""
        return [f'public.{table}' for table in recovery.catalogue_for(core_version)] + ['search.documents']

    def sql(self, query):
        self.queries.append(query)
        if 'pg_attribute' in query:                      # the schema-shape key
            return '812|' + 'c' * 32
        if 'pg_class' in query:                          # the presence probe
            found = self.relations(recovery.CATALOGUE_AUDITED_THROUGH) if self.present is None else self.present
            # Real psql output carries compose's own stderr lines; so does this.
            return '[compose] docker compose exec -T postgres psql\n' + '\n'.join(found) + '\n'
        for table, version in self.ledgers.items():
            if f'FROM {table}' in query:
                return f'{version}|f'
        return '0|d41d8cd98f00b204e9800998ecf8427e'


def baseline_with(candidate):
    baseline = Path(tempfile.mkdtemp())
    (baseline / 'candidate.json').write_text(json.dumps(candidate))
    return baseline


def config_archive(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class BackupReportTest(unittest.TestCase):
    def test_one_matched_pair_is_the_backup(self):
        log = '[backup] done — database vidra-20260913T030813Z.dump.gz, config vidra-config-20260913T030813Z.tar.gz\n'
        self.assertEqual(recovery.parse_backup_done(log),
                         ('vidra-20260913T030813Z.dump.gz', 'vidra-config-20260913T030813Z.tar.gz'))

    def test_no_success_line_is_not_a_backup(self):
        with self.assertRaises(ValueError):
            recovery.parse_backup_done('[backup] ERROR pg_dump exited 1\n')

    def test_a_dump_and_config_from_different_runs_are_not_one_data_point(self):
        log = 'done — database vidra-20260913T030813Z.dump.gz, config vidra-config-20260912T030813Z.tar.gz'
        with self.assertRaises(ValueError):
            recovery.parse_backup_done(log)


class ConfigArchiveTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'env').mkdir()
        (self.root / 'deploy').mkdir()
        (self.root / 'env/production.env').write_bytes(b'MFA_KEY_KEK=x\n')
        (self.root / 'deploy/Caddyfile.local').write_bytes(b'secure.video.test {}\n')
        self.archive = self.root / 'config.tar.gz'

    def test_archive_matching_the_live_files_passes(self):
        self.archive.write_bytes(config_archive({'env/production.env': b'MFA_KEY_KEK=x\n',
                                                 'deploy/Caddyfile.local': b'secure.video.test {}\n'}))
        self.assertEqual(set(recovery.check_config_archive(self.archive, self.root)), recovery.CONFIG_MEMBERS)

    def test_an_archive_missing_the_caddyfile_cannot_restore(self):
        self.archive.write_bytes(config_archive({'env/production.env': b'MFA_KEY_KEK=x\n'}))
        with self.assertRaises(ValueError):
            recovery.check_config_archive(self.archive, self.root)

    def test_a_stale_env_file_is_refused(self):
        self.archive.write_bytes(config_archive({'env/production.env': b'MFA_KEY_KEK=rotated\n',
                                                 'deploy/Caddyfile.local': b'secure.video.test {}\n'}))
        with self.assertRaises(ValueError):
            recovery.check_config_archive(self.archive, self.root)


class FailedBackupTest(unittest.TestCase):
    before = {'last_success': 'a', 'vidra-20260913T040024Z.dump.gz': 'b'}

    def test_a_private_partial_is_the_documented_residue(self):
        after = dict(self.before, **{'vidra-20260913T040037Z.dump.gz.part': 'c'})
        self.assertEqual(recovery.check_failed_backup(self.before, after, 'pg_dump: error'),
                         ['vidra-20260913T040037Z.dump.gz.part'])

    def test_advancing_the_success_marker_is_advertising_success(self):
        with self.assertRaises(ValueError):
            recovery.check_failed_backup(self.before, dict(self.before, last_success='z'), 'pg_dump: error')

    def test_publishing_a_dump_is_advertising_success(self):
        after = dict(self.before, **{'vidra-20260913T040037Z.dump.gz': 'c'})
        with self.assertRaises(ValueError):
            recovery.check_failed_backup(self.before, after, 'pg_dump: error')

    def test_a_success_line_is_advertising_success(self):
        with self.assertRaises(ValueError):
            recovery.check_failed_backup(self.before, dict(self.before), '[backup] done — database x')


class FingerprintTest(unittest.TestCase):
    def test_sealed_secret_tables_are_part_of_the_data_point(self):
        self.assertIn('user_mfa', recovery.CATALOGUE)
        self.assertIn('mfa_recovery_codes', recovery.CATALOGUE)

    # The catalogue was written for core schema 146. Migrations 0147-0150 added
    # five tables it had never heard of, so a restore that lost every one of
    # them reproduced 15/15 fingerprints and PASSED the recovery objective.
    def test_the_tables_0147_to_0150_added_are_part_of_the_data_point(self):
        for table in ('authored_remote_comments', 'ipfs_control_config', 'ipfs_control_operations',
                      'ipfs_capacity', 'ipfs_copy_cleanup'):
            with self.subTest(table=table):
                self.assertIn(table, recovery.CATALOGUE)

    def test_table_names_are_never_interpolated_unchecked(self):
        with self.assertRaises(ValueError):
            recovery.fingerprint_sql('users; DROP TABLE users')

    def test_differences_are_reported_by_name(self):
        self.assertEqual(recovery.differing({'users': '1|a', 'videos': '2|b'}, {'users': '1|a', 'videos': '3|c'}), ['videos'])
        self.assertEqual(recovery.differing({'users': '1|a'}, {}), ['users'])

    # A table with nothing volatile keeps the SQL the v0.6.x drills recorded, so
    # this change cannot move a fingerprint for a reason nobody asked for.
    def test_a_table_with_nothing_excluded_is_fingerprinted_exactly_as_before(self):
        self.assertEqual(recovery.fingerprint_sql('users'),
                         "SELECT count(*)||'|'||md5(COALESCE(string_agg(r::text,E'\\n' ORDER BY r::text),'')) "
                         "FROM (SELECT to_jsonb(t) AS r FROM users t) s")

    # A background worker rewriting a column between the backup and the restore
    # comparison would fail the drill for a reason that predicts nothing, so the
    # volatile columns are deleted from the row's jsonb. Everything NOT named
    # stays in the fingerprint, so a future migration's new column is asserted
    # the day it lands and a lost one changes the hash.
    def test_volatile_columns_are_deleted_from_the_row_before_hashing(self):
        sql = recovery.fingerprint_sql('ipfs_capacity', ('reserved_bytes', 'measure_after'))
        self.assertIn("to_jsonb(t) - ARRAY['reserved_bytes','measure_after']::text[] AS r", sql)
        self.assertIn('FROM ipfs_capacity t', sql)

    def test_column_names_are_never_interpolated_unchecked(self):
        with self.assertRaises(ValueError):
            recovery.fingerprint_sql('ipfs_capacity', ("x'; DROP TABLE users; --",))

    # The presence probe is the one place a relation name goes into SQL as a
    # literal rather than as an identifier, so the guard sits there too.
    def test_probe_names_are_never_interpolated_unchecked(self):
        for bad in ("public.users'); DROP TABLE users; --", 'public', 'Public.users', 'public.'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                recovery.split_qualified(bad)
        self.assertEqual(recovery.split_qualified('search.documents'), ('search', 'documents'))

    # "exists and empty" is a PASS (the table survived and the fixture never
    # populated it); "missing" is the loss the whole catalogue exists to catch.
    # psql's own `relation does not exist` reaches the operator as `exit 1; see
    # 0NN-compose-exec.log`, so the table is named here or nowhere.
    def test_a_missing_table_is_named_and_an_empty_one_is_not(self):
        self.assertEqual(recovery.missing_tables(('public.users', 'public.ipfs_capacity'), ('public.users',)),
                         ['public.ipfs_capacity'])
        self.assertEqual(recovery.missing_tables(('public.users',), ('public.users', 'search.documents')), [])

    # `Recorder.run` redirects stderr ONTO stdout and returns the whole log, and
    # `deploy/compose.sh` prints `[compose] …` there on every call, so the probe's
    # answer arrives mixed with lines psql never wrote. Splitting the raw text
    # would turn a NOTICE into a table name and a real absence into a match.
    def test_the_presence_probe_reads_only_lines_shaped_like_a_table_name(self):
        polluted = ('[compose] docker compose exec -T postgres psql\n'
                    'NOTICE:  relation "users" already exists, skipping\n'
                    'public.users\n'
                    ' Container vidra-postgres-1  Running\n'
                    'search.documents\n'
                    'public.ipfs_capacity\n')
        self.assertEqual(recovery.present_tables(polluted),
                         ['public.users', 'search.documents', 'public.ipfs_capacity'])
        self.assertEqual(recovery.present_tables('[compose] nothing matched\n'), [])


class SchemaShapeTest(unittest.TestCase):
    """One key that notices a table or column lost ANYWHERE in `public`.

    Only 20 of vidra-core's ~109 tables are catalogued, and the audit floor is
    147, so a restore that lost `instance_settings`, `audit_log`, `reports`,
    `user_blocks`, `watched_words`, `sessions`, `notifications` or
    `remote_videos` would still report every catalogued fingerprint intact. This
    key carries no row data — it is the column inventory of `public` — so it
    classifies nothing and needs no per-table decision, and it compares a
    database only with ITSELF across a backup/restore or a reboot, never across
    releases, so it is schema-version-agnostic by construction.
    """

    def test_the_shape_key_cannot_collide_with_a_catalogued_table(self):
        # Table names are [a-z_]+, so a key with a dot is unreachable as one.
        self.assertNotIn(recovery.SCHEMA_SHAPE, recovery.CATALOGUE)
        self.assertIn('.', recovery.SCHEMA_SHAPE)

    # Partition children would multiply the parent's columns and, with monthly
    # partitions, change between the two fingerprints of one drill. vidra-core
    # and vidra-search create none today (verified at v0.7.5 / v0.7.3: no DDL
    # outside migrations, no PARTITION OF, no partman), and the query excludes
    # them anyway so introducing one cannot start a flap.
    def test_partition_children_and_other_schemas_are_excluded(self):
        self.assertIn('NOT c.relispartition', recovery.SCHEMA_SHAPE_SQL)
        self.assertIn("n.nspname = 'public'", recovery.SCHEMA_SHAPE_SQL)
        # Dropped and system columns are not shape; temp tables live in pg_temp.
        self.assertIn('a.attnum > 0', recovery.SCHEMA_SHAPE_SQL)
        self.assertIn('NOT a.attisdropped', recovery.SCHEMA_SHAPE_SQL)

    # A key present on one side only IS a difference, deliberately: a catalogue
    # key that vanishes between the backup data point and the restored database
    # is exactly the loss being hunted. Both sides of every comparison in both
    # harnesses come from one drill on one harness version, so this cannot fire
    # for a new key alone — and mixing an archived pre-#238 record with a
    # post-#238 one is already refused in the docstring's terms (re-run the
    # source actions on this harness), and would be reported by NAME here.
    def test_a_key_on_one_side_only_is_reported_not_ignored(self):
        self.assertEqual(recovery.differing({'users': '1|a'}, {'users': '1|a', recovery.SCHEMA_SHAPE: '9|b'}),
                         [recovery.SCHEMA_SHAPE])


class CatalogueSchemaTest(unittest.TestCase):
    """The catalogue is a function of the CANDIDATE's schema, not of the host.

    The same two harness files drill candidates at different schema versions. A
    v0.6.x stage has none of the 0147-0150 tables, so demanding them would fail
    a correct drill; fingerprinting "whatever tables happen to exist" would pass
    a restore that lost them. The expected ledgers the stage already carries —
    computed from the frozen source migrations, never typed by hand — are what
    says which schema this candidate is.
    """

    def ledgers(self, core=150, search=18):
        return {'schema_migrations': {'version': core}, 'vidra_search_migrations': {'version': search}}

    def test_the_schema_version_comes_from_the_frozen_expected_ledgers(self):
        self.assertEqual(recovery.core_schema_version(self.ledgers(core=146)), 146)

    def test_a_stage_that_names_no_core_ledger_cannot_choose_a_catalogue(self):
        with self.assertRaises(ValueError):
            recovery.core_schema_version({'vidra_search_migrations': {'version': 18}})

    def test_the_expected_ledgers_are_read_from_the_baseline_the_drill_was_pointed_at(self):
        baseline = Path(tempfile.mkdtemp())
        (baseline / 'expected-ledgers.json').write_text(json.dumps(self.ledgers(core=150)))
        self.assertEqual(recovery.core_schema_version(recovery.expected_ledgers(baseline)), 150)

    def test_a_v066_candidate_is_not_asked_for_tables_its_schema_never_had(self):
        catalogue = recovery.catalogue_for(146)
        self.assertIn('user_mfa', catalogue)
        for table in ('authored_remote_comments', 'ipfs_control_config', 'ipfs_capacity', 'ipfs_copy_cleanup'):
            self.assertNotIn(table, catalogue)

    def test_a_v075_candidate_is_asked_for_every_table_its_schema_requires(self):
        catalogue = recovery.catalogue_for(150)
        for table in ('authored_remote_comments', 'ipfs_control_config', 'ipfs_control_operations',
                      'ipfs_capacity', 'ipfs_copy_cleanup'):
            self.assertIn(table, catalogue)

    def test_each_table_appears_at_the_migration_that_created_it(self):
        self.assertNotIn('ipfs_copy_cleanup', recovery.catalogue_for(149))
        self.assertIn('ipfs_capacity', recovery.catalogue_for(149))
        self.assertNotIn('ipfs_capacity', recovery.catalogue_for(148))

    # Fail-closed: drilling a candidate whose schema is newer than the catalogue
    # was audited against must REFUSE, naming the migrations to read. Certifying
    # "the restored database is the same database" while silently ignoring every
    # table a newer migration added is the failure this whole change closes.
    def test_a_candidate_newer_than_the_audit_refuses_the_drill(self):
        with self.assertRaises(ValueError) as raised:
            recovery.catalogue_for(recovery.CATALOGUE_AUDITED_THROUGH + 1)
        self.assertIn(str(recovery.CATALOGUE_AUDITED_THROUGH + 1), str(raised.exception))
        self.assertIn('0151', str(raised.exception))


class FingerprintWiringTest(unittest.TestCase):
    """The two fail-closed guards must be WIRED IN, not merely implemented.

    `catalogue_for` and `missing_tables` are covered as pure functions above,
    and that is exactly the hole: with both helpers correct, deleting the two
    lines in `fingerprint` that CALL them leaves every other test green. Live,
    that costs a paid host-day each way — the by-name refusal degrades to an
    anonymous `exit 1`, and a v0.6.x re-drill demands five tables its schema
    never had and fails for a reason that predicts nothing.
    """

    def keys(self, rows):
        return set(rows) - {'search.documents', recovery.SCHEMA_SHAPE}

    def test_fingerprint_asks_only_for_the_candidates_tables(self):
        # Everything the newest schema has is present, so nothing can be missing:
        # this test is only about WHICH tables are asked for.
        run = FakeRun(present=FakeRun().relations(recovery.CATALOGUE_AUDITED_THROUGH))
        rows = recovery.fingerprint(run, 146)
        self.assertEqual(self.keys(rows), set(recovery.catalogue_for(146)))
        self.assertNotIn('ipfs_copy_cleanup', ' '.join(run.queries))
        self.assertNotIn('authored_remote_comments', ' '.join(run.queries))

    def test_fingerprint_proves_existence_by_name_before_hashing_anything(self):
        lost = ('public.authored_remote_comments', 'public.ipfs_control_config')
        run = FakeRun(present=[r for r in FakeRun().relations(150) if r not in lost])
        with self.assertRaises(ValueError) as raised:
            recovery.fingerprint(run, 150)
        for name in lost:
            self.assertIn(name, str(raised.exception))
        self.assertEqual(len(run.queries), 1, 'the probe must refuse before a single row is hashed')

    def test_search_documents_absence_is_named_like_any_other_relation(self):
        run = FakeRun(present=[r for r in FakeRun().relations(150) if r != 'search.documents'])
        with self.assertRaises(ValueError) as raised:
            recovery.fingerprint(run, 150)
        self.assertIn('search.documents', str(raised.exception))

    def test_the_whole_public_schema_shape_is_part_of_every_fingerprint(self):
        rows = recovery.fingerprint(FakeRun(), 150)
        self.assertIn(recovery.SCHEMA_SHAPE, rows)
        self.assertEqual(rows[recovery.SCHEMA_SHAPE], '812|' + 'c' * 32)



class CatalogueRotTest(unittest.TestCase):
    """The catalogue cannot silently fall behind vidra-core's migrations again.

    A migration reaches a drill only through a RELEASE, and every release this
    repo has published is recorded in `releases/<tag>.json` with the core schema
    version it embeds. So the audit is pinned to that record: landing a release
    whose schema is newer than the audit fails here until someone reads the new
    migrations. `TABLES_ADDED` is what "read them" means — one line per schema
    version from the floor up, listing the tables its migration CREATEs (empty
    when it creates none) — and the audit ceiling is derived from it, so the
    ceiling cannot be advanced by editing a number alone.
    """

    def records(self):
        found = [json.loads(p.read_text()) for p in sorted((ROOT / 'releases').glob('v*.json'))]
        self.assertTrue(found, 'no release records found at all; this guard has drifted')
        return found

    def test_the_audit_covers_every_release_this_repo_records(self):
        newest = max(self.records(), key=lambda record: record['core_schema_version'])
        self.assertLessEqual(
            newest['core_schema_version'], recovery.CATALOGUE_AUDITED_THROUGH,
            f"release {newest['release']} embeds core schema {newest['core_schema_version']} but the "
            f'drill catalogue is audited only through {recovery.CATALOGUE_AUDITED_THROUGH}: read the new '
            'vidra-core migrations and add a TABLES_ADDED line for each schema version they introduce')

    def test_the_audit_leaves_no_migration_between_the_floor_and_the_ceiling_unread(self):
        expected = list(range(recovery.CATALOGUE_AUDIT_FLOOR, recovery.CATALOGUE_AUDITED_THROUGH + 1))
        self.assertEqual(
            sorted(recovery.TABLES_ADDED), expected,
            'TABLES_ADDED must carry one line per core schema version from '
            f'{recovery.CATALOGUE_AUDIT_FLOOR} to {recovery.CATALOGUE_AUDITED_THROUGH} — an empty tuple '
            'when that migration creates no table. Missing: '
            f'{sorted(set(expected) - set(recovery.TABLES_ADDED))}; unexpected: '
            f'{sorted(set(recovery.TABLES_ADDED) - set(expected))}')

    def test_a_table_a_migration_creates_that_nobody_classified_is_named(self):
        self.assertEqual(recovery.unclassified_tables({151: ('ipfs_swarm_peers', 'ipfs_capacity')}),
                         ['ipfs_swarm_peers'])

    def test_every_table_the_audit_read_is_catalogued_or_excluded_with_a_reason(self):
        self.assertEqual(recovery.unclassified_tables(), [],
                         'a vidra-core migration CREATEs these tables and the drill catalogue knows '
                         'neither to fingerprint them nor why it should not: add each to CATALOGUE '
                         'with the columns a worker rewrites, or to EXCLUDED_TABLES with the reason')
        for table, (since, reason) in recovery.EXCLUDED_TABLES.items():
            with self.subTest(table=table):
                self.assertNotIn(table, recovery.CATALOGUE)
                self.assertIn(table, recovery.TABLES_ADDED[since])
                self.assertTrue(reason.strip(), f'{table} is excluded with no written reason')

    def test_the_catalogue_and_the_audit_agree_on_when_a_table_appeared(self):
        for version, tables in recovery.TABLES_ADDED.items():
            for table in tables:
                if table in recovery.CATALOGUE:
                    with self.subTest(table=table):
                        self.assertEqual(recovery.CATALOGUE[table][0], version)


# The drill was written for v0.6.4 and read its candidate, expected ledgers,
# installer, frozen deployment hashes and pinned prod overlay from one hard-coded
# directory, so it could not be pointed at the v0.6.5 stage being prepared now.
# The baseline is an argument whose default keeps every v0.6.4 record valid.
class BaselineTest(unittest.TestCase):
    def test_candidate_is_read_from_the_chosen_baseline(self):
        self.assertEqual(recovery.load_candidate(baseline_with(CANDIDATE))['tag'], 'v0.6.5')

    # The recovery drill inherits A01 validation, so a core-only release was
    # unrunnable here too: v0.7.5 pins vidra-user and vidra-search at v0.7.3.
    def test_a_core_only_candidate_is_read_like_any_other(self):
        self.assertEqual(recovery.load_candidate(baseline_with(CANDIDATE_V075))['tag'], 'v0.7.5')

    def test_a_baseline_without_a_candidate_manifest_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            recovery.load_candidate(Path(tempfile.mkdtemp()))

    def test_a_candidate_without_a_release_tag_is_refused(self):
        with self.assertRaises(ValueError):
            recovery.load_candidate(baseline_with({k: v for k, v in CANDIDATE.items() if k != 'tag'}))

    # The drill installs from, and asserts against, whatever this manifest says.
    # Shape-checking the tag alone would accept a manifest of a release whose own
    # verification did not pass, so the shared A01 validation is what runs here.
    def test_a_manifest_whose_verification_did_not_pass_is_refused(self):
        with self.assertRaises(ValueError):
            recovery.load_candidate(baseline_with(dict(CANDIDATE, status='FAIL')))

    def test_the_refusal_names_the_offending_file(self):
        baseline = baseline_with(dict(CANDIDATE, status='FAIL'))
        with self.assertRaises(ValueError) as raised:
            recovery.load_candidate(baseline)
        self.assertIn(str(baseline / 'candidate.json'), str(raised.exception))

    def test_the_default_baseline_keeps_the_v064_drill_unchanged(self):
        args = recovery.build_parser().parse_args(['snapshot', '--stage', '/tmp/attempt'])
        self.assertEqual(args.baseline, recovery.DEFAULT_BASELINE)
        self.assertEqual(str(recovery.DEFAULT_BASELINE), '/root/vidra-v064-runtime')

    def test_baseline_flag_selects_another_candidates_stage(self):
        args = recovery.build_parser().parse_args(
            ['restore', '--stage', '/tmp/attempt', '--baseline', '/root/vidra-v065-runtime'])
        self.assertEqual(args.baseline, Path('/root/vidra-v065-runtime'))


# A dump, or an outage clock, recorded on one release and restored onto another
# rebuilds the wrong images and then passes every downstream comparison, because
# both sides of that comparison came from the same wrong evidence.
class RecordedTagTest(unittest.TestCase):
    def test_evidence_from_the_candidate_being_restored_is_accepted(self):
        recovery.check_recorded_tag('source-loss', {'candidate_tag': 'v0.6.5'}, {'tag': 'v0.6.5'})

    def test_a_dump_from_another_release_cannot_be_restored(self):
        with self.assertRaises(ValueError):
            recovery.check_recorded_tag('backup', {'candidate_tag': 'v0.6.4'}, {'tag': 'v0.6.5'})

    def test_a_record_without_a_tag_is_refused_not_assumed_to_match(self):
        with self.assertRaises(ValueError):
            recovery.check_recorded_tag('source-loss', {'status': 'PASS'}, {'tag': 'v0.6.4'})

    # The archived v0.6.4 source results predate the stamping, so a restore run
    # against them refuses. That is deliberate; the message has to say so, or the
    # operator reads a real refusal as a harness bug.
    def test_the_refusal_names_the_cause_and_the_remedy(self):
        with self.assertRaises(ValueError) as raised:
            recovery.check_recorded_tag('source backup', {'status': 'PASS'}, {'tag': 'v0.6.4'})
        self.assertIn('re-run the source actions', str(raised.exception))


class WiringTest(unittest.TestCase):
    """The guards above are pure functions; these pin them to the real call sites."""

    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o022))  # main() sets the umask process-wide

    def test_every_action_stamps_the_release_it_ran_on(self):
        # The action itself cannot run without a stack; main() records the
        # release and the baseline before that, and saves result.json in its
        # `finally` regardless — which is exactly what restore later reads.
        stage = Path(tempfile.mkdtemp()) / 'attempt'
        baseline = baseline_with(CANDIDATE)
        with self.assertRaises(Exception):
            recovery.main(['snapshot', '--stage', str(stage), '--baseline', str(baseline)])
        result = json.loads((stage / 'result.json').read_text())
        self.assertEqual(result['candidate_tag'], 'v0.6.5')
        self.assertEqual(result['baseline'], str(baseline.resolve()))
        self.assertEqual(result['status'], 'FAIL')

    def test_restore_checks_the_source_loss_record_before_touching_the_host(self):
        # The first statement of restore(), so a foreign record costs nothing:
        # no host facts, no install, no container.
        with self.assertRaises(ValueError) as raised:
            recovery.restore(None, CANDIDATE, Path('/nonexistent'), None, None,
                             {'status': 'PASS', 'candidate_tag': 'v0.6.4'}, {})
        self.assertIn('source-loss', str(raised.exception))

    def test_restore_checks_the_backup_that_produced_the_dump(self):
        # Reached with a matching source-loss record and a real handoff layout,
        # with the host probes faked out: the refusal still lands before the
        # installer runs, on the backup result that produced the dump.
        handoff = Path(tempfile.mkdtemp()) / 'handoff'
        handoff.mkdir()
        (handoff / 'vidra-20260913T030813Z.dump.gz').write_bytes(b'dump')
        (handoff / 'vidra-config-20260913T030813Z.tar.gz').write_bytes(b'config')
        (handoff.parent / 'backup-result.json').write_text(json.dumps({'status': 'PASS', 'candidate_tag': 'v0.6.4'}))
        run = mock.Mock(**{'run.return_value': ''})
        with mock.patch.object(runtime, 'host_facts', return_value={}), \
                mock.patch.object(runtime, 'check_host'):
            with self.assertRaises(ValueError) as raised:
                recovery.restore(run, CANDIDATE, Path('/nonexistent'), Path(tempfile.mkdtemp()), handoff,
                                 {'status': 'PASS', 'candidate_tag': 'v0.6.5'}, {})
        self.assertIn('source backup', str(raised.exception))


class ExportTest(unittest.TestCase):
    def test_health_probe_output_is_hashed_not_exported(self):
        value = export.hash_health_output({'Health': {'Log': [{'Output': 'token=abc'}]}})
        self.assertNotIn('Output', value['Health']['Log'][0])
        self.assertEqual(len(value['Health']['Log'][0]['output_sha256']), 64)

    def test_any_host_secret_in_any_file_refuses_the_export(self):
        files = {'a/result.json': b'{"ok": true}', 'b/commands.json': b'["--password", "hunter2-long-secret"]'}
        self.assertEqual(export.leaks(files, {'hunter2-long-secret'}), ['b/commands.json'])
        self.assertEqual(export.leaks({'a/result.json': b'{}'}, {'hunter2-long-secret'}), [])

    # The v0.6.4 drill exports were scanned by a revision that loaded secrets
    # only from files that happened to exist and recorded nothing about what it
    # loaded, so "no secret found" could not be told from "no secret looked
    # for". The scan set must be recorded, key-id values count, and an export
    # with an empty env scan set is refused rather than certified.
    def test_key_id_values_count_as_secrets(self):
        self.assertTrue(export.SECRET_KEY.search('B2_KEY_ID'))
        self.assertTrue(export.SECRET_KEY.search('AWS_ACCESS_KEY_ID'))
        self.assertFalse(export.SECRET_KEY.search('HTTP_PORT'))

    def test_host_secrets_records_what_it_loaded(self):
        root = Path(tempfile.mkdtemp())
        env = root / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\nB2_KEY_ID=0012345678abcdef\nSHORT_SECRET=abc\n'
                       '# PASSWORD=commented-out-1\nHTTP_PORT=8080\n')
        secrets, loaded = export.host_secrets(root, env_file=env, bucket_key_file=root / 'absent.json',
                                              owner_file=root / 'absent-owner.json')
        self.assertEqual(secrets, {'abcdefgh1234', '0012345678abcdef'})
        self.assertEqual(loaded, {'env': 2, 'bucket_key': False, 'mfa': False, 'owner': False})

    def test_export_with_no_env_secret_loaded_is_refused(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        with self.assertRaises(SystemExit):
            export.export(drill, drill / 'out', ['stage'], env_file=drill / 'absent.env',
                          bucket_key_file=drill / 'absent.json', owner_file=drill / 'absent-owner.json')
        self.assertFalse((drill / 'out').exists())

    def test_export_manifest_records_the_scan_set(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        (drill / 'private').mkdir()
        (drill / 'private/mfa.json').write_text('{"secret": "JBSWY3DPEHPK3PXP"}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        manifest = export.export(drill, drill / 'out', ['stage'], env_file=env,
                                 bucket_key_file=drill / 'absent.json', owner_file=drill / 'absent-owner.json')
        written = json.loads((drill / 'out/artifact-hashes.json').read_text())
        self.assertEqual(written['secrets_loaded'], {'env': 1, 'bucket_key': False, 'mfa': True, 'owner': False})
        self.assertEqual(written['files'], manifest)
        self.assertEqual(list(manifest), ['stage/result.json'])

    # A v0.6.5 host keeps its bucket key and owner fixture under v065 paths. The
    # v0.6.4 exporter read every source "if it exists", so run there it scanned
    # neither the B2 credential nor the owner password and still certified the
    # export clean. A source the exporter NAMES must be present, or refused.
    def test_a_named_secret_source_that_is_missing_refuses_the_export(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        with self.assertRaises(SystemExit):
            export.export(drill, drill / 'out', ['stage'], required=export.REQUIRED_SOURCES,
                          env_file=env, bucket_key_file=drill / 'absent.json',
                          owner_file=drill / 'absent-owner.json')
        self.assertFalse((drill / 'out').exists())

    def test_every_named_source_present_is_scanned_and_recorded(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        key = drill / 'b2-key.json'
        key.write_text(json.dumps({'access_key': '0012345678abcdef', 'secret_key': 'K005longsecretvalue'}))
        owner = drill / 'owner.json'
        owner.write_text(json.dumps({'password': 'owner-password-long'}))
        export.export(drill, drill / 'out', ['stage'], required=export.REQUIRED_SOURCES,
                      env_file=env, bucket_key_file=key, owner_file=owner)
        written = json.loads((drill / 'out/artifact-hashes.json').read_text())
        self.assertEqual(written['secrets_loaded'], {'env': 1, 'bucket_key': True, 'mfa': False, 'owner': True})

    def test_a_required_source_cannot_be_declared_absent(self):
        # DECLARED_ABSENT is a truthy string, so a truthiness test reads a
        # declared-absent source as scanned. Declaring a source absent is what
        # takes it OUT of the required set; a caller that keeps bucket_key in
        # `required` while passing bucket_key_file=None would otherwise certify
        # "bucket_key scanned" having scanned nothing.
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\n')
        owner = drill / 'owner.json'
        owner.write_text(json.dumps({'password': 'owner-password-long'}))
        with self.assertRaises(SystemExit):
            export.export(drill, drill / 'out', ['stage'], required=export.REQUIRED_SOURCES,
                          env_file=env, bucket_key_file=None, owner_file=owner)
        self.assertFalse((drill / 'out').exists())

    def test_the_owner_fixture_is_derived_from_the_baseline(self):
        self.assertEqual(export.owner_path(Path('/root/vidra-v065-runtime')),
                         Path('/root/vidra-v065-runtime/private/owner.json'))

    def test_a_foreign_baseline_with_the_default_bucket_key_is_refused(self):
        # Forgetting --b2-key on a v0.6.5 host must not quietly scan a leftover
        # v0.6.4 key file and report a covered scan.
        with self.assertRaises(SystemExit):
            export.main(['drill', 'out', 'stage', '--baseline', '/root/vidra-v065-runtime'])

    def test_the_default_guard_compares_resolved_paths(self):
        # /root/./vidra-v064-runtime is the default stage; it must not read as a
        # foreign baseline and refuse an otherwise correct v0.6.4 export.
        self.assertEqual(export.resolve_baseline('/root/./vidra-v064-runtime'), export.DEFAULT_BASELINE)

    # The B2 key file exists only on the SOURCE host: the replacement host is
    # rebuilt blank from the released bundle and never holds one, so requiring it
    # there would refuse every replacement-half export. `--b2-key none` is the
    # operator declaring that on the record, not the scan quietly shrinking.
    def test_a_declared_absent_bucket_key_drops_out_of_the_required_set(self):
        self.assertEqual(export.required_sources(None), ('env', 'owner'))
        self.assertEqual(export.required_sources(Path('/root/vidra-v065-b2-key.json')), export.REQUIRED_SOURCES)

    def test_none_is_the_declaration_and_any_other_value_is_a_path(self):
        self.assertIsNone(export.bucket_key_argument('none'))
        self.assertEqual(export.bucket_key_argument('/root/k.json'), Path('/root/k.json'))

    def test_a_declared_absent_bucket_key_is_written_into_the_record(self):
        drill = Path(tempfile.mkdtemp())
        (drill / 'stage').mkdir()
        (drill / 'stage/result.json').write_text('{"ok": true}\n')
        env = drill / 'production.env'
        env.write_text('JWT_SECRET=abcdefgh1234\nSTORAGE_S3_SECRET_KEY=replacement-host-s3-secret\n')
        owner = drill / 'owner.json'
        owner.write_text(json.dumps({'password': 'owner-password-long'}))
        export.export(drill, drill / 'out', ['stage'], required=export.required_sources(None),
                      env_file=env, bucket_key_file=None, owner_file=owner)
        written = json.loads((drill / 'out/artifact-hashes.json').read_text())
        self.assertEqual(written['secrets_loaded']['bucket_key'], export.DECLARED_ABSENT)
        self.assertEqual(written['secrets_loaded']['owner'], True)


if __name__ == '__main__':
    unittest.main()
