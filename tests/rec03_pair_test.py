"""A pair's drill expectations come from its two records and its first pending migration's SQL."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest

import rec03_pair as pair
import rec03_pair_cases as cases
import rec03_script_test as driver

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_pair', ROOT / 'scripts/ci/release-pair.py')
release_pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_pair)
OLD_PHASES = ('install', 'data', 'fp', 'backup', 'inject')
NEW_PHASES = ('recover', 'backup2', 'rollback', 'restore-refuse', 'repin', 'restore-ok', 'split', 'report')


class Refusals:
    def refused(self, reason, call, *args):
        with self.assertRaises(pair.Refused) as caught:
            call(*args)
        self.assertEqual(str(caught.exception), reason)
        self.assertIn(reason, pair.REASONS)


class RealPairs(Refusals, unittest.TestCase):
    def each(self):
        for case in cases.CASES:
            with self.subTest(pair=case.name):
                yield case, cases.records(case)

    def test_the_records_resolve_to_the_pair(self):
        for case, (old, new) in self.each():
            found = release_pair.resolve(ROOT, case.new, case.explicit_previous)
            self.assertEqual((found['old'], found['new']), (old, new))

    def test_first_pending_migration(self):
        for case, (old, new) in self.each():
            self.assertEqual(pair.first_pending(old, new), case.first)

    def test_ledger_per_phase(self):
        for case, (old, new) in self.each():
            for phase in OLD_PHASES:
                self.assertEqual(pair.ledger(old, new, phase), case.ledger_old, phase)
            self.assertEqual(pair.ledger(old, new, 'upgrade-fail'), case.ledger_failed)
            for phase in NEW_PHASES:
                self.assertEqual(pair.ledger(old, new, phase), case.ledger_new, phase)

    def test_image_tag_per_role(self):
        for case, (old, new) in self.each():
            self.assertEqual(''.join(pair.images(old)), case.images_old)
            self.assertEqual(''.join(pair.images(new)), case.images_new)

    def test_injection_comes_from_the_migrations_own_sql(self):
        for case, _ in self.each():
            self.assertEqual(pair.injection(cases.sql(case)), case.injection)

    def test_the_driver_accepts_the_derived_injection_and_builds_its_ddl_and_undo(self):
        for case, (old, new) in self.each():
            env = pair.env(old, new, pair.injection(cases.sql(case)))
            self.assertEqual(env, {'REC03_OLD': case.old, 'REC03_NEW': case.new, 'REC03_SAME_SCHEMA': '0',
                                   **case.injection})
            done = driver.helpers('require_release_pair && require_injection_setup && inject_ddl && echo && inject_undo_ddl '
                                  f'&& check_same_schema_expectation {case.pre_core} {case.post_core} '
                                  f'{case.pre_search} {case.post_search}', **env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.splitlines(), [case.ddl, case.undo])
            flipped = driver.helpers(f'check_same_schema_expectation {case.pre_core} {case.post_core} '
                                     f'{case.pre_search} {case.post_search}', **dict(env, REC03_SAME_SCHEMA='1'))
            self.assertNotEqual(flipped.returncode, 0)

    def test_conflict_is_this_pairs_object_and_no_other(self):
        for case, _ in self.each():
            pattern = pair.conflict(case.injection)
            self.assertIsNotNone(pattern.search('dbmigrate: apply migrations: migration failed: ' + case.error
                                                + ' in line 0: (details: pq: ' + case.error + ')'))
            for other in cases.others(case):
                self.assertIsNone(pattern.search(other.error), other.name)
            for near in (case.error.replace('already exists', 'does not exist'), case.error.replace('" already', '_2" already'),
                         case.error.replace('already exists', 'already existsx'), ''):
                self.assertIsNone(pattern.search(near), near)

    def test_a_table_clash_is_not_a_column_clash_on_that_table(self):
        pattern = pair.conflict({'REC03_INJECT': 'table', 'REC03_INJECT_TABLE': 'remote_videos'})
        self.assertIsNotNone(pattern.search('relation "remote_videos" already exists'))
        self.assertIsNone(pattern.search('column "is_sensitive" of relation "remote_videos" already exists'))

    def test_restore_refusal_names_both_core_ledgers(self):
        for case, (old, new) in self.each():
            patterns = pair.refusal(old, new)
            self.assertTrue(all(pattern.search(case.refusal) for pattern in patterns))
            for other in cases.others(case):
                if (other.pre_core, other.post_core) != (case.pre_core, case.post_core):
                    self.assertFalse(all(pattern.search(other.refusal) for pattern in patterns), other.name)
            self.assertFalse(all(pattern.search(case.refusal.replace('Nothing was changed', '')) for pattern in patterns))

    def test_a_ledger_number_is_not_matched_as_a_prefix_of_a_longer_one(self):
        old, new = ({'core_schema_version': 18}, {'core_schema_version': 19})
        patterns = pair.refusal(old, new)
        self.assertTrue(all(p.search('the dump is at 19; pinned X carries up to 18. Nothing was changed.') for p in patterns))
        for text in ('the dump is at 190; pinned X carries up to 18. Nothing was changed.',
                     'the dump is at 19; pinned X carries up to 182. Nothing was changed.'):
            self.assertFalse(all(p.search(text) for p in patterns), text)


class EveryRecordedPair(Refusals, unittest.TestCase):
    EXPECTED = {'v0.6.5': pair.NO_MIGRATION, 'v0.6.6': pair.NO_MIGRATION, 'v0.6.8': pair.NOT_LISTED,
                'v0.6.9': pair.NO_MIGRATION, 'v0.7.0': pair.NO_MIGRATION, 'v0.7.1': pair.NOT_LISTED,
                'v0.7.2': pair.NO_MIGRATION, 'v0.7.3': pair.NO_MIGRATION, 'v0.7.4': pair.NO_MIGRATION,
                'v0.7.5': pair.NO_MIGRATION, 'v0.7.7': pair.NOT_LISTED,
                'v0.7.8': (152, '0152_remote_video_sensitive.up.sql'),
                'v0.7.9': (183, '0183_remote_actors_own_host_inboxes.up.sql'),
                'v0.7.11': pair.NO_MIGRATION, 'v0.7.12': pair.NO_MIGRATION, 'v0.7.13': pair.NO_MIGRATION,
                'v0.7.14': pair.NO_MIGRATION, 'v0.7.15': pair.NO_MIGRATION, 'v0.7.16': pair.NO_MIGRATION,
                'v0.7.17': pair.NO_MIGRATION, 'v0.7.18': pair.NO_MIGRATION, 'v0.7.19': pair.NO_MIGRATION,
                'v0.7.20': (189, '0189_user_consents.up.sql')}

    def test_each_adjacent_pair_is_drillable_or_refused_for_a_fixed_reason(self):
        for release, expected in self.EXPECTED.items():
            with self.subTest(release=release):
                found = release_pair.resolve(ROOT, release)
                if isinstance(expected, str):
                    self.refused(expected, pair.first_pending, found['old'], found['new'])
                else:
                    self.assertEqual(pair.first_pending(found['old'], found['new']), expected)

    def test_a_record_added_since_this_table_was_written_is_still_answered(self):
        for path in (ROOT / 'releases').glob('v*.json'):
            try:
                found = release_pair.resolve(ROOT, path.stem)
            except release_pair.Refused:
                continue
            try:
                version, name = pair.first_pending(found['old'], found['new'])
            except pair.Refused as refusal:
                self.assertIn(str(refusal), pair.REASONS)
            else:
                self.assertEqual(version, found['old']['core_schema_version'] + 1)
                self.assertEqual(int(name[:4]), version)
                self.assertIn(name, found['new']['core_migrations'])

    def test_a_list_that_skips_or_repeats_the_first_pending_number_is_refused(self):
        old, new = cases.records(cases.CASES[2])
        for change in (lambda names: names.remove('0183_remote_actors_own_host_inboxes.up.sql'),
                       lambda names: names.append('0183_second_file.up.sql'),
                       lambda names: names.clear()):
            edited = copy.deepcopy(new)
            change(edited['core_migrations'])
            self.refused(pair.NOT_LISTED, pair.first_pending, old, edited)
        edited = copy.deepcopy(new)
        del edited['core_migrations']
        self.refused(pair.NOT_LISTED, pair.first_pending, old, edited)

    def test_a_pair_that_moves_only_the_search_ledger_is_refused_not_downgraded_to_dirty(self):
        old, new = cases.records(cases.CASES[2])
        flat = dict(copy.deepcopy(new), core_schema_version=old['core_schema_version'])
        self.assertNotEqual(old['search_schema_version'], flat['search_schema_version'])
        self.refused(pair.NO_MIGRATION, pair.first_pending, old, flat)
        self.refused(pair.NO_MIGRATION, pair.ledger, old, flat, 'upgrade-fail')
        self.refused(pair.NO_MIGRATION, pair.first_pending, new, old)


class SQLShapes(Refusals, unittest.TestCase):
    TABLE = {'REC03_INJECT': 'table', 'REC03_INJECT_TABLE': 't'}
    COLUMN = {'REC03_INJECT': 'column', 'REC03_INJECT_TABLE': 't', 'REC03_INJECT_COLUMN': 'c', 'REC03_INJECT_TYPE': 'INT'}
    FUNCTION = {'REC03_INJECT': 'function', 'REC03_INJECT_FUNCTION': 'f'}

    def test_each_unguarded_creation_is_read(self):
        for sql, expected in (
                ('CREATE TABLE t (id UUID PRIMARY KEY);', self.TABLE),
                ('create   table\n t(\n id uuid\n)', self.TABLE),
                ('ALTER TABLE t ADD COLUMN c INT;', self.COLUMN),
                ('alter table t\n    add column c int not null default 0;', self.COLUMN),
                ('ALTER TABLE t ADD COLUMN c INT, ADD COLUMN d VARCHAR(8);', self.COLUMN),
                ('CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$;', self.FUNCTION),
                ('CREATE FUNCTION f ( ) RETURNS INT LANGUAGE sql AS $body$ SELECT 1 $body$;', self.FUNCTION)):
            with self.subTest(sql=sql):
                self.assertEqual(pair.injection(sql), expected)

    def test_the_column_type_is_the_migrations_first_word_from_the_drivers_allowlist(self):
        for declared, expected in (('BOOLEAN NOT NULL DEFAULT false', 'BOOLEAN'), ('timestamptz', 'TIMESTAMPTZ'),
                                   ('NUMERIC(10,2)', 'NUMERIC'), ('TEXT[]', 'TEXT'), ('TIMESTAMP WITH TIME ZONE', 'TIMESTAMP'),
                                   ('uuid REFERENCES users (id)', 'UUID')):
            with self.subTest(declared=declared):
                self.assertEqual(pair.injection(f'ALTER TABLE t ADD COLUMN c {declared};')['REC03_INJECT_TYPE'], expected)
        for declared in ('VARCHAR(64)', 'citext', 'INT4', 'DOUBLE PRECISION', 'bytea', 'INTERVAL'):
            with self.subTest(declared=declared):
                self.refused(pair.NOT_INJECTABLE, pair.injection, f'ALTER TABLE t ADD COLUMN c {declared};')

    def test_a_creation_that_cannot_clash_is_not_read(self):
        for sql in ('', '   \n', '-- only a comment', 'SELECT 1;',
                    'CREATE TABLE IF NOT EXISTS t (id INT);', 'create table if not exists t (id int);',
                    'ALTER TABLE t ADD COLUMN IF NOT EXISTS c INT;', 'alter table t add column if not exists c int;',
                    'CREATE OR REPLACE FUNCTION f() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;',
                    'CREATE FUNCTION f(a INT) RETURNS INT LANGUAGE sql AS $$ SELECT a $$;',
                    'CREATE FUNCTION public.f() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;',
                    'CREATE TABLE public.t (id INT);', 'CREATE TABLE "t" (id INT);', 'CREATE TABLE T (id INT);',
                    'CREATE TEMP TABLE t (id INT);', 'CREATE UNLOGGED TABLE t (id INT);', 'CREATE TABLE t AS SELECT 1;',
                    'ALTER TABLE ONLY t ADD COLUMN c INT;', 'alter table only t add column c int;',
                    'ALTER TABLE IF EXISTS t ADD COLUMN c INT;', 'alter table if exists t add column c int;',
                    'ALTER TABLE t ADD c INT;', 'ALTER TABLE t ADD COLUMN "c" INT;', 'ALTER TABLE public.t ADD COLUMN c INT;',
                    'ALTER TABLE t DROP COLUMN x, ADD COLUMN c INT;',
                    'ALTER TABLE t ADD CONSTRAINT t_check CHECK (c > 0);', 'CREATE INDEX t_idx ON t (c);',
                    'CREATE UNIQUE INDEX IF NOT EXISTS t_idx ON t (c);', 'CREATE EXTENSION IF NOT EXISTS pg_trgm;',
                    'CREATE TABLE ' + 'a' * 64 + ' (id INT);', 'CREATE FUNCTION ' + 'a' * 64 + '() RETURNS INT;'):
            with self.subTest(sql=sql):
                self.refused(pair.NOT_INJECTABLE, pair.injection, sql)

    def test_text_that_only_looks_like_a_statement_is_not_read(self):
        for sql in ('-- CREATE TABLE t (id INT);', '/* CREATE TABLE t (id INT); */', '/* a /* nested */ CREATE TABLE t (id INT); */',
                    "SELECT 'CREATE TABLE t (id INT);';", "SELECT 'it''s; CREATE TABLE t (id INT);';",
                    "SELECT E'a\\'; CREATE TABLE t (id INT);';",
                    'DO $$ BEGIN CREATE TABLE t (id INT); END $$;',
                    'DO $do$ BEGIN EXECUTE $q$ CREATE TABLE t (id INT); $q$; END $do$;',
                    'CREATE OR REPLACE FUNCTION g() RETURNS INT LANGUAGE sql AS $$ CREATE TABLE t (id INT); SELECT 1 $$;',
                    'COMMENT ON TABLE x IS \'see: ALTER TABLE t ADD COLUMN c INT;\';',
                    'SELECT "; CREATE TABLE t (id INT); --";',
                    "SELECT 'unterminated; CREATE TABLE t (id INT);", 'SELECT $$ unterminated; CREATE TABLE t (id INT);',
                    '/* unterminated; CREATE TABLE t (id INT);'):
            with self.subTest(sql=sql):
                self.refused(pair.NOT_INJECTABLE, pair.injection, sql)

    def test_the_first_statement_that_can_clash_wins(self):
        self.assertEqual(pair.injection('CREATE INDEX x_idx ON x (y);\n-- then\nALTER TABLE t ADD COLUMN c INT;\n'
                                        'CREATE TABLE later (id INT);'), self.COLUMN)
        self.assertEqual(pair.injection('CREATE TABLE IF NOT EXISTS guarded (id INT); CREATE TABLE t (id INT);'
                                        'CREATE FUNCTION later() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;'), self.TABLE)
        self.assertEqual(pair.injection("SELECT 'a;b'; /* c; */ CREATE FUNCTION f() RETURNS INT LANGUAGE sql AS 'SELECT 1';"),
                         self.FUNCTION)
        self.assertEqual(pair.injection('ALTER TABLE x ADD COLUMN y VARCHAR(8); ALTER TABLE t ADD COLUMN c INT;'), self.COLUMN)

    def test_an_object_an_earlier_statement_touches_is_passed_over(self):
        for sql in ('DROP TABLE IF EXISTS t; CREATE TABLE t (id INT);',
                    'DROP FUNCTION IF EXISTS f(); CREATE FUNCTION f() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;',
                    'ALTER TABLE t DROP COLUMN IF EXISTS c; ALTER TABLE t ADD COLUMN c INT;',
                    'CREATE TABLE IF NOT EXISTS t (id INT); ALTER TABLE t ADD COLUMN c INT;',
                    'ALTER TABLE x RENAME TO t_old; ALTER TABLE "t" RENAME TO x; CREATE TABLE t (id INT);'):
            with self.subTest(sql=sql):
                self.refused(pair.NOT_INJECTABLE, pair.injection, sql)
        self.assertEqual(pair.injection('DROP TABLE IF EXISTS t_old; CREATE TABLE t (id INT);'), self.TABLE)
        self.assertEqual(pair.injection('DROP TABLE IF EXISTS t; CREATE TABLE t (id INT); CREATE TABLE u (id INT);'),
                         {'REC03_INJECT': 'table', 'REC03_INJECT_TABLE': 'u'})

    def test_nothing_derived_can_be_a_value_the_driver_refuses(self):
        script = driver.SCRIPT.read_text()
        self.assertEqual(re.search(r"^IDENT_RE='\^(.*)\$'$", script, re.M)[1], pair.IDENT)
        self.assertEqual(set(re.search(r"^TYPE_RE='\^\((.*)\)\$'$", script, re.M)[1].split('|')), set(pair.TYPES))
        hostile = ('CREATE TABLE t; DROP TABLE users; -- (id INT);', 'CREATE TABLE t\x00 (id INT);',
                   'CREATE FUNCTION f(); DROP TABLE users; --() RETURNS INT;', 'ALTER TABLE t ADD COLUMN c INT; DROP TABLE users;',
                   'ALTER TABLE t ADD COLUMN c INT DEFAULT 1 CHECK (c > 0) REFERENCES users (id);',
                   'CREATE TABLE "t; DROP TABLE users" (id INT);', 'CREATE TABLE t$x (id INT);')
        for sql in hostile:
            with self.subTest(sql=sql):
                try:
                    found = pair.injection(sql)
                except pair.Refused:
                    continue
                kind = found.pop('REC03_INJECT')
                self.assertIn(kind, ('table', 'column', 'function'))
                declared = found.pop('REC03_INJECT_TYPE', 'INT')
                self.assertIn(declared, pair.TYPES)
                for value in found.values():
                    self.assertRegex(value, r'\A[a-z_][a-z0-9_]{0,62}\Z')

    def test_statements_are_split_outside_quotes_only(self):
        self.assertEqual(pair.statements("A 'x;y' ; B $t$ ;;; $t$ ; -- c;\n /* d; */ C \"q;r\" ;; "),
                         ["A ''", 'B $$', 'C "q;r"'])


if __name__ == '__main__':
    unittest.main()
