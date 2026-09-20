"""The REC-03 drill driver must carry no release's literals, and must refuse the ones it is given.

`tests/rec03-upgrade-rollback.sh` is run ONCE, by hand, on a paid disposable host, against a
live Postgres — so every one of its defaults is a loaded gun. It shipped hard-wired to the
v0.6.3 -> v0.6.4 pair: `REC03_OLD=${REC03_OLD:-v0.6.3}`, an injection that pre-creates the
column migration 0145 adds, and a literal `migrate force 144`. Point that at a v0.6.6 host and
the column ALREADY EXISTS at schema 146, so the *injection* errors instead of the migrator —
the drill "fails" at the wrong step for the wrong reason — and the recovery then stamps the
ledger two versions behind the truth. None of that is visible until the host is rented.

The drill itself cannot run here (it needs a host), so what CAN be tested is tested: the
parameter validation, the generated SQL pairing, the SAME_SCHEMA contradiction refusal, the
derived `force` target, and the absence of every stale literal. The validators are lifted
VERBATIM out of the real script — the same trick tests/scanner_profile_test.py,
tests/caddy_reload_test.py and tests/rollback_floor_test.py use on deploy.sh — so these
assertions fail if the driver changes and its guards do not come with it. What a lifted region
cannot show is that the driver actually CALLS them before it talks to the host; that is asserted
separately, by running real phases with $REC03_ROOT redirected and `su` replaced by a recorder.
Nothing here skips.
"""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'rec03-upgrade-rollback.sh'

# The pair this driver exists to rehearse next, and the injection chosen for it: migration
# 0147 adds `federation_deliveries.authored_remote_comment_id` with no IF NOT EXISTS, on a
# table that has existed since 0038, so pre-creating it stops the FIRST pending migration.
PAIR = {'REC03_OLD': 'v0.6.6', 'REC03_NEW': 'v0.7.5'}
INJECTION = {'REC03_INJECT': 'column',
             'REC03_INJECT_TABLE': 'federation_deliveries',
             'REC03_INJECT_COLUMN': 'authored_remote_comment_id',
             'REC03_INJECT_TYPE': 'UUID'}

# Operator-supplied text that ends up in SQL executed against the drill database. Anything but
# a bare lower-case identifier is a typo or an injection attempt.
HOSTILE = [
    'x; DROP TABLE users',
    'x"y',
    "x'y",
    'x y',
    'users --',
    'naïve',
    'Сolumn',          # Cyrillic С: looks like an identifier, is not one
    'Federation_Deliveries',
    'federation_deliveries)',
    'x\nfederation_deliveries',
    '1column',
    '',
    'a' * 64,
]


BEGIN = '# >>> BEGIN validators'
END = '# <<< END validators'


def validators():
    """The driver's parameter block and validators, exactly as the driver defines them."""
    text = SCRIPT.read_text()
    if BEGIN not in text or END not in text:
        raise AssertionError(f'{SCRIPT.name} no longer delimits its validators with '
                             f'{BEGIN!r}/{END!r} — the region these tests assert on was '
                             f'renamed or removed')
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


def helpers(snippet, **env):
    """Run `snippet` against the driver's own validators, with no phase executed."""
    script = 'set -uo pipefail\n' + validators() + '\n' + snippet + '\n'
    child = {'PATH': os.environ.get('PATH', '/usr/bin:/bin')}
    child.update(env)
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                          env=child, stdin=subprocess.DEVNULL)


def phase(name, root, **env):
    """Run a real phase with $REC03_ROOT redirected and `su` replaced by a recorder.

    `su` is how every database and deploy call leaves this script (`psq`, `asv`), so a
    recorder on PATH is a direct probe for "did this phase touch the host at all".
    """
    fake = Path(root) / 'bin'
    fake.mkdir(parents=True, exist_ok=True)
    (fake / 'su').write_text('#!/bin/sh\necho "$@" >> "$REC03_ROOT/su-called"\n')
    (fake / 'su').chmod(0o755)
    child = {'PATH': f'{fake}:' + os.environ.get('PATH', '/usr/bin:/bin'), 'REC03_ROOT': str(root)}
    child.update(env)
    done = subprocess.run(['bash', str(SCRIPT), name], capture_output=True, text=True,
                          env=child, stdin=subprocess.DEVNULL)
    return done, Path(root)


class BashSyntax(unittest.TestCase):
    def test_the_driver_parses(self):
        self.assertEqual(subprocess.run(['bash', '-n', str(SCRIPT)],
                                        capture_output=True, text=True).returncode, 0)

    def test_the_lifted_region_is_pure(self):
        """The validators must define and decide, never touch the host."""
        region = validators()
        for host_call in ('su - vidra', 'docker ', 'curl ', 'psq ', 'asv ', 'mkdir '):
            with self.subTest(host_call=host_call):
                self.assertNotIn(host_call, region,
                                 'the lifted region reaches the host, so lifting it is unsafe')
        with tempfile.TemporaryDirectory() as root:
            r = helpers('echo LIFTED', REC03_ROOT=root, **PAIR, **INJECTION)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('LIFTED', r.stdout)
            self.assertEqual(sorted(os.listdir(root)), [], 'the validators created state')


class ReleasePair(unittest.TestCase):
    def test_both_tags_are_required_with_no_default(self):
        for missing in ('REC03_OLD', 'REC03_NEW'):
            with self.subTest(missing=missing):
                env = dict(PAIR)
                del env[missing]
                r = helpers('require_release_pair', **env)
                self.assertNotEqual(r.returncode, 0, 'a half-set pair was accepted')
                self.assertIn('REC03_OLD', r.stdout + r.stderr)

    def test_the_v075_pair_is_accepted(self):
        self.assertEqual(helpers('require_release_pair', **PAIR).returncode, 0)

    def test_a_tag_that_is_not_a_tag_is_refused(self):
        # OLD and NEW are interpolated into a git ref and a raw.githubusercontent.com URL.
        for bad in ('v0.7.5; rm -rf /', 'main', '0.7.5', 'v0.7', '../../etc', 'v0.7.5 '):
            with self.subTest(bad=bad):
                r = helpers('require_release_pair', REC03_OLD='v0.6.6', REC03_NEW=bad)
                self.assertNotEqual(r.returncode, 0, bad)

    def test_a_pair_of_one_release_is_refused(self):
        r = helpers('require_release_pair', REC03_OLD='v0.7.5', REC03_NEW='v0.7.5')
        self.assertNotEqual(r.returncode, 0)


class InjectionParameters(unittest.TestCase):
    def test_each_missing_parameter_is_named_and_nothing_is_guessed(self):
        for missing in ('REC03_INJECT_TABLE', 'REC03_INJECT_COLUMN', 'REC03_INJECT_TYPE'):
            with self.subTest(missing=missing):
                env = dict(PAIR, **INJECTION)
                del env[missing]
                r = helpers('require_injection_setup', **env)
                self.assertNotEqual(r.returncode, 0, f'{missing} defaulted to something')
                self.assertIn(missing, r.stdout + r.stderr)

    def test_the_chosen_v075_injection_is_accepted(self):
        self.assertEqual(helpers('require_injection_setup', **PAIR, **INJECTION).returncode, 0)

    def test_hostile_identifiers_are_refused(self):
        for field in ('REC03_INJECT_TABLE', 'REC03_INJECT_COLUMN'):
            for bad in HOSTILE:
                with self.subTest(field=field, bad=bad):
                    env = dict(PAIR, **INJECTION)
                    env[field] = bad
                    r = helpers('require_injection_setup', **env)
                    self.assertNotEqual(r.returncode, 0, f'{field}={bad!r} was accepted')

    def test_the_type_is_an_allowlist_not_a_free_string(self):
        for bad in ("TEXT DEFAULT ''", 'UUID; DROP TABLE users', 'SERIAL', 'TEXT[]',
                    'UUID REFERENCES users(id)', 'anyelement', ''):
            with self.subTest(bad=bad):
                env = dict(PAIR, **INJECTION)
                env['REC03_INJECT_TYPE'] = bad
                self.assertNotEqual(helpers('require_injection_setup', **env).returncode, 0, bad)
        for good in ('UUID', 'uuid', 'TEXT', 'BIGINT', 'TIMESTAMPTZ', 'BOOLEAN'):
            with self.subTest(good=good):
                env = dict(PAIR, **INJECTION)
                env['REC03_INJECT_TYPE'] = good
                self.assertEqual(helpers('require_injection_setup', **env).returncode, 0, good)

    def test_the_variant_itself_is_checked(self):
        env = dict(PAIR, **INJECTION)
        env['REC03_INJECT'] = 'colum'
        r = helpers('require_injection_setup', **env)
        self.assertNotEqual(r.returncode, 0, 'a misspelled variant fell through to `column`')
        self.assertEqual(helpers('require_injection_setup', **PAIR, REC03_INJECT='dirty').returncode, 0,
                         'the dirty variant must not demand a column')


class GeneratedSQL(unittest.TestCase):
    """The undo is built from the same three parameters as the injection, so they cannot drift."""

    def test_the_v075_injection_and_its_undo(self):
        r = helpers('inject_ddl; echo; inject_undo_ddl', **PAIR, **INJECTION)
        self.assertEqual(r.returncode, 0, r.stderr)
        add, drop = r.stdout.splitlines()
        self.assertEqual(add, 'ALTER TABLE federation_deliveries ADD COLUMN '
                              'authored_remote_comment_id UUID')
        self.assertEqual(drop, 'ALTER TABLE federation_deliveries DROP COLUMN '
                               'authored_remote_comment_id')

    def test_add_and_drop_always_name_the_same_table_and_column(self):
        for table, column, sqltype in (('media_ipfs_pins', 'claim_token', 'UUID'),
                                       ('ipfs_capacity', 'reserved_bytes', 'bigint'),
                                       ('videos', 'x_2_y', 'TEXT')):
            with self.subTest(table=table, column=column):
                env = dict(PAIR, REC03_INJECT='column', REC03_INJECT_TABLE=table,
                           REC03_INJECT_COLUMN=column, REC03_INJECT_TYPE=sqltype)
                r = helpers('inject_ddl; echo; inject_undo_ddl', **env)
                add, drop = r.stdout.splitlines()
                self.assertEqual(add.split()[:6],
                                 ['ALTER', 'TABLE', table, 'ADD', 'COLUMN', column])
                self.assertEqual(drop.split(),
                                 ['ALTER', 'TABLE', table, 'DROP', 'COLUMN', column])
                self.assertEqual(add.split()[-1], sqltype.upper())


class SameSchemaExpectation(unittest.TestCase):
    """`restore-refuse` may be neither skipped when it applies nor demanded when it cannot."""

    def test_claiming_the_same_schema_across_a_migrating_pair_is_refused(self):
        r = helpers('check_same_schema_expectation 146 150', REC03_SAME_SCHEMA='1', **PAIR)
        self.assertNotEqual(r.returncode, 0)
        out = r.stdout + r.stderr
        self.assertIn('146', out)
        self.assertIn('150', out)
        self.assertIn('REC03_SAME_SCHEMA', out)

    def test_omitting_it_on_a_pair_that_does_not_migrate_is_refused(self):
        r = helpers('check_same_schema_expectation 146 146', **PAIR)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('REC03_SAME_SCHEMA', r.stdout + r.stderr)

    def test_the_two_honest_combinations_pass(self):
        self.assertEqual(helpers('check_same_schema_expectation 146 150', **PAIR).returncode, 0)
        self.assertEqual(helpers('check_same_schema_expectation 146 146',
                                 REC03_SAME_SCHEMA='1', **PAIR).returncode, 0)


class ForceTarget(unittest.TestCase):
    """The recovery `force` is derived from the ledger the drill captured, never typed."""

    def test_the_first_pending_migration_failing_forces_back_to_the_pre_upgrade_version(self):
        r = helpers('force_target 146 147', **PAIR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '146')

    def test_a_later_migration_failing_is_refused_rather_than_forced_over(self):
        # Dirty at 149 means 147 and 148 ALREADY APPLIED; forcing to 146 would re-run them.
        r = helpers('force_target 146 149', **PAIR)
        self.assertNotEqual(r.returncode, 0)
        out = r.stdout + r.stderr
        self.assertIn('149', out)
        self.assertIn('148', out, 'the refusal must name the version that IS fully applied')

    def test_non_numeric_or_missing_ledger_values_are_refused(self):
        for pre, dirty_at in (('', '147'), ('146', ''), ('14x', '147'), ('146', '1 4 7')):
            with self.subTest(pre=pre, dirty_at=dirty_at):
                r = helpers(f'force_target {shlex.quote(pre)} {shlex.quote(dirty_at)}', **PAIR)
                self.assertNotEqual(r.returncode, 0, (pre, dirty_at))


class NoReleaseLiterals(unittest.TestCase):
    def test_no_other_releases_facts_are_baked_in(self):
        text = SCRIPT.read_text()
        for stale in ('paused_reason', 'force 144', 'dump144', 'dump146',
                      'REC03_OLD:-v', 'REC03_NEW:-v'):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text, f'{stale} is another release\'s fact, not a default')


class DiesBeforeTouchingTheHost(unittest.TestCase):
    """A bad parameter must be refused by a preflight, not discovered mid-drill."""

    def run_inject(self, **env):
        with tempfile.TemporaryDirectory() as root:
            done, r = phase('inject', root, **env)
            return done, (r / 'su-called').exists(), (r / 'facts' / 'inject.json').exists()

    def test_the_probe_is_not_vacuous(self):
        """Positive control: with valid parameters the phase DOES reach the database."""
        done, touched, facts = self.run_inject(**PAIR, **INJECTION)
        self.assertTrue(touched, 'the su probe never fired, so the refusal tests prove nothing')
        self.assertTrue(facts, 'the phase wrote no facts, so it did not run')
        self.assertIn('ALTER TABLE federation_deliveries ADD COLUMN', done.stdout + done.stderr)

    def test_a_missing_injection_parameter_stops_the_phase_before_any_sql(self):
        env = dict(PAIR, **INJECTION)
        del env['REC03_INJECT_COLUMN']
        done, touched, facts = self.run_inject(**env)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(touched, 'the drill database was touched despite a missing parameter')
        self.assertFalse(facts)
        self.assertIn('REC03_INJECT_COLUMN', done.stdout + done.stderr)

    def test_a_hostile_identifier_stops_the_phase_before_any_sql(self):
        env = dict(PAIR, **INJECTION)
        env['REC03_INJECT_COLUMN'] = 'x; DROP TABLE users'
        done, touched, facts = self.run_inject(**env)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(touched, 'hostile SQL reached the drill database')
        self.assertFalse(facts)

    def test_a_missing_release_pair_stops_every_phase(self):
        with tempfile.TemporaryDirectory() as root:
            done, r = phase('recover', root, **INJECTION)
            self.assertNotEqual(done.returncode, 0)
            self.assertFalse((r / 'su-called').exists())
            self.assertIn('REC03_OLD', done.stdout + done.stderr)

    def test_recover_refuses_when_the_pre_upgrade_ledger_was_never_captured(self):
        """`force` needs the version `backup` recorded; there is no literal to fall back to."""
        with tempfile.TemporaryDirectory() as root:
            done, r = phase('recover', root, **PAIR, **INJECTION)
            self.assertNotEqual(done.returncode, 0)
            self.assertFalse((r / 'facts' / 'recover.json').exists())
            self.assertIn('backup', done.stdout + done.stderr)


if __name__ == '__main__':
    unittest.main()
