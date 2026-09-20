"""pin-release.sh against a real local origin: the two hand steps it replaces.

THE PAIRING. v0.7.4 and v0.7.5 re-released vidra-core ALONE and pair
vidra-user and vidra-search at v0.7.3, so one tag written into all three
VIDRA_*_TAG keys pins ghcr.io/yegamble/vidra-user:v0.7.5 — an image that does
not exist — for exactly the release running on beta today. The pairing is read
from releases/<tag>.json (in the tree, else fetched), and the resolution is
deploy/release-mapping.py's, never a second record parser here.

curl is STUBBED in every test: nothing reaches the network, and the stub's log
is how "no request was attempted" is proved rather than asserted. The default
stub 404s, so the tests that predate the record lookup exercise the offline
fallback and must still produce the byte-identical uniform env file they always
did.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
RECORDS = ROOT / 'releases'
SCRIPTS = ('pin-release.sh', 'lib.sh', 'backup-env.sh', 'checkout-hygiene.py',
           'release-mapping.py')

# Logs every argv, then answers with $CURL_BODY_FILE at the path after
# --output and exits $CURL_EXIT (22 by default: curl --fail on a 404, which is
# what a release whose record PR has not merged yet really returns).
CURL_STUB = '''#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
dest=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--output" ]; then dest="$arg"; fi
  prev="$arg"
done
if [ "${CURL_EXIT:-22}" = "0" ] && [ -n "$dest" ] && [ -n "${CURL_BODY_FILE:-}" ]; then
  cat "$CURL_BODY_FILE" > "$dest"
fi
exit "${CURL_EXIT:-22}"
'''


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def synthetic(release, core, user, search):
    """A well-formed record for a release that was never cut — fixture only."""
    def component(repo, tag, n):
        return {'tag': tag, 'commit': (format(n + 1, 'x') * 40)[:40],
                'image': {'repository': f'ghcr.io/yegamble/{repo}',
                          'index_digest': 'sha256:' + (format(n + 3, 'x') * 64)[:64],
                          'platforms': {'linux/amd64': 'sha256:' + (format(n + 5, 'x') * 64)[:64]}}}
    return {'schema_version': 1, 'release': release, 'meta_commit': 'a' * 40,
            'core_schema_version': 150, 'search_schema_version': 19,
            'components': {'core': component('vidra-core', core, 0),
                           'user': component('vidra-user', user, 1),
                           'search': component('vidra-search', search, 2)}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        # An origin with the deploy scripts committed and one release tag, and a
        # clone standing in for /opt/vidra. The scripts are committed so that
        # checking out the tag reproduces them — the real trap this script is
        # built around is that it changes the tree it is running from.
        seed = base / 'seed'
        (seed / 'deploy').mkdir(parents=True)
        (seed / 'env').mkdir()
        (seed / 'releases').mkdir()
        for name in SCRIPTS:
            shutil.copyfile(DEPLOY / name, seed / 'deploy' / name)
        # The REAL core-only record, not a fixture: the pairing this script got
        # wrong is the one shipped as v0.7.5, and a synthetic stand-in would
        # keep passing if that record's shape ever changed.
        shutil.copyfile(RECORDS / 'v0.7.5.json', seed / 'releases/v0.7.5.json')
        (seed / 'env/production.env.example').write_text('VIDRA_CORE_TAG=\n')
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(seed)], check=True)
        subprocess.run(['git', 'add', '-A'], cwd=seed, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'seed'], cwd=seed, check=True, env=env)
        # v0.7.5 stands for a release this tree DOES carry the record for;
        # v9.9.9, one commit later, for a release it does not (the window
        # before the record PR merges, and every offline host). Two commits,
        # not two tags on one, so `git describe` names the tag each test asked
        # for instead of whichever of the pair it happens to pick.
        subprocess.run(['git', 'tag', '-a', 'v0.7.5', '-m', 'v0.7.5'], cwd=seed, check=True, env=env)
        (seed / 'releases/README.md').write_text('records\n')
        subprocess.run(['git', 'add', '-A'], cwd=seed, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'a later release'], cwd=seed, check=True, env=env)
        subprocess.run(['git', 'tag', '-a', 'v9.9.9', '-m', 'v9.9.9'], cwd=seed, check=True, env=env)
        self.origin = base / 'origin.git'
        subprocess.run(['git', 'clone', '-q', '--bare', str(seed), str(self.origin)], check=True)
        self.root = base / 'checkout'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.root)], check=True)
        self.env_file = self.root / 'env/production.env'
        self.env_file.write_text('VIDRA_CORE_TAG=v0.0.1\nVIDRA_USER_TAG=v0.0.1\nJWT_SECRET=fake-not-a-secret\n')
        self.home = base / 'home'
        self.home.mkdir()
        self.bin = base / 'bin'
        self.bin.mkdir()
        (self.bin / 'curl').write_text(CURL_STUB)
        (self.bin / 'curl').chmod(0o755)
        self.curl_log = base / 'curl.log'
        self.body = base / 'body'

    def serve(self, text):
        """What the stubbed curl answers with, instead of 404."""
        self.body.write_text(text)

    def curl_calls(self):
        return self.curl_log.read_text() if self.curl_log.exists() else ''

    def run_pin(self, *args):
        environ = {**os.environ, 'HOME': str(self.home),
                   'PATH': f'{self.bin}:{os.environ["PATH"]}',
                   'CURL_LOG': str(self.curl_log),
                   'CURL_EXIT': '0' if self.body.exists() else '22'}
        if self.body.exists():
            environ['CURL_BODY_FILE'] = str(self.body)
        return subprocess.run(
            ['bash', str(self.root / 'deploy/pin-release.sh'), *args],
            env=environ, capture_output=True, text=True)

    def pins(self):
        return {l.split('=')[0]: l.split('=', 1)[1] for l in self.env_file.read_text().splitlines() if '=' in l}

    def triple(self):
        p = self.pins()
        return (p.get('VIDRA_CORE_TAG'), p.get('VIDRA_USER_TAG'), p.get('VIDRA_SEARCH_TAG'))

    def assertUntouched(self, before_head, before_env):
        """Nothing mutated: the tree has not moved, the env file is byte-for-
        byte what it was, and no snapshot was even taken."""
        self.assertEqual(git('rev-parse', 'HEAD', cwd=self.root), before_head)
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'main')
        self.assertEqual(self.env_file.read_text(), before_env)
        self.assertFalse((self.home / '.local/state/vidra/env-history').exists())

    def reset(self):
        """Back to a pristine checkout, for a test that runs the script more
        than once with different answers from the stub."""
        subprocess.run(['git', 'checkout', '-q', 'main'], cwd=self.root, check=True)
        self.env_file.write_text(
            'VIDRA_CORE_TAG=v0.0.1\nVIDRA_USER_TAG=v0.0.1\nJWT_SECRET=fake-not-a-secret\n')


class PinReleaseTests(Fixture):
    def test_pins_tree_and_env_together_and_snapshots_outside(self):
        result = self.run_pin('v9.9.9')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(git('describe', '--tags', cwd=self.root), 'v9.9.9')
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'HEAD')  # detached
        pins = self.pins()
        self.assertEqual({pins['VIDRA_CORE_TAG'], pins['VIDRA_USER_TAG'], pins['VIDRA_SEARCH_TAG']}, {'v9.9.9'})
        self.assertEqual(pins['JWT_SECRET'], 'fake-not-a-secret')
        history = self.home / '.local/state/vidra/env-history'
        snapshots = list(history.iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(stat.S_IMODE(snapshots[0].stat().st_mode), 0o600)
        self.assertIn('VIDRA_CORE_TAG=v0.0.1', snapshots[0].read_text())
        self.assertFalse(list(self.root.glob('env/*.bak*')))
        self.assertIn('next: ./deploy/deploy.sh', result.stdout)

    def test_target_release_without_the_snapshot_helper_still_pins(self):
        # v0.6.3 and v0.6.4 trees carry neither deploy/backup-env.sh nor
        # deploy/checkout-hygiene.py (both landed after v0.6.4). An operator on
        # main — or on any later tag — pinning to such a release ran the
        # snapshot AFTER the checkout, so the helper it needed had just been
        # removed from under it: "env snapshot failed — the tree is at vX, the
        # env file is untouched", with the tree moved and the pins not. Every
        # rollback of the tree to a pre-helper release hit this.
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        old = Path(self.temp.name) / 'old'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(old)], check=True)
        for helper in ('deploy/backup-env.sh', 'deploy/checkout-hygiene.py', 'deploy/pin-release.sh'):
            subprocess.run(['git', 'rm', '-q', helper], cwd=old, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'a release cut before the helpers existed'], cwd=old, check=True, env=env)
        subprocess.run(['git', 'tag', '-a', 'v9.9.8', '-m', 'v9.9.8'], cwd=old, check=True, env=env)
        subprocess.run(['git', 'push', '-q', 'origin', 'v9.9.8'], cwd=old, check=True)
        result = self.run_pin('v9.9.8')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(git('describe', '--tags', cwd=self.root), 'v9.9.8')
        self.assertFalse((self.root / 'deploy/backup-env.sh').exists())
        pins = self.pins()
        self.assertEqual({pins['VIDRA_CORE_TAG'], pins['VIDRA_USER_TAG'], pins['VIDRA_SEARCH_TAG']}, {'v9.9.8'})
        snapshots = list((self.home / '.local/state/vidra/env-history').iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertIn('VIDRA_CORE_TAG=v0.0.1', snapshots[0].read_text())

    def test_a_refused_checkout_leaves_only_a_harmless_snapshot(self):
        # The snapshot now precedes the checkout, so the one observable side
        # effect of a refused checkout is a snapshot that is a byte-identical
        # copy of the env file nothing changed. A dirty tracked file that the
        # target tag would overwrite is what git refuses on, so the target
        # must actually change that file.
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        other = Path(self.temp.name) / 'other'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(other)], check=True)
        (other / 'env/production.env.example').write_text('VIDRA_CORE_TAG=\nNEW_KEY=\n')
        subprocess.run(['git', 'commit', '-q', '-am', 'a release that changes the template'], cwd=other, check=True, env=env)
        subprocess.run(['git', 'tag', '-a', 'v9.9.7', '-m', 'v9.9.7'], cwd=other, check=True, env=env)
        subprocess.run(['git', 'push', '-q', 'origin', 'v9.9.7'], cwd=other, check=True)
        (self.root / 'env/production.env.example').write_text('VIDRA_CORE_TAG=\nDIRTY=1\n')
        before = self.env_file.read_text()
        result = self.run_pin('v9.9.7')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('could not check out v9.9.7', result.stderr)
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'main')
        self.assertEqual(self.env_file.read_text(), before)
        snapshots = list((self.home / '.local/state/vidra/env-history').iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].read_text(), before)

    def test_rerun_is_a_no_op_apart_from_a_fresh_snapshot(self):
        self.assertEqual(self.run_pin('v9.9.9').returncode, 0)
        before = self.env_file.read_text()
        self.assertEqual(self.run_pin('v9.9.9').returncode, 0)
        self.assertEqual(self.env_file.read_text(), before)
        self.assertEqual(len(list((self.home / '.local/state/vidra/env-history').iterdir())), 2)

    def test_root_is_refused_before_any_git_command(self):
        fake_id = self.bin / 'id'
        fake_id.write_text('#!/bin/sh\necho 0\n')
        fake_id.chmod(0o755)
        before_head = git('rev-parse', 'HEAD', cwd=self.root)
        result = self.run_pin('v9.9.9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing to run as root', result.stderr)
        self.assertIn('sudo -u', result.stderr)
        self.assertNotIn('fetching', result.stdout)
        self.assertEqual(git('rev-parse', 'HEAD', cwd=self.root), before_head)
        self.assertEqual(self.pins()['VIDRA_CORE_TAG'], 'v0.0.1')

    def test_unreleased_tag_changes_nothing(self):
        result = self.run_pin('v9.9.8')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a tag on origin', result.stderr)
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'main')
        self.assertEqual(self.pins()['VIDRA_CORE_TAG'], 'v0.0.1')
        self.assertFalse((self.home / '.local/state/vidra/env-history').exists())

    def test_malformed_tag_is_refused(self):
        for bad in ('latest', '0.6.4', 'v0.6'):
            with self.subTest(tag=bad):
                result = self.run_pin(bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('not a vMAJOR.MINOR.PATCH tag', result.stderr)

    def test_stray_env_copy_stops_it_before_the_tree_moves(self):
        (self.root / 'env/production.env.backup').write_text('copy')
        result = self.run_pin('v9.9.9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Stray environment backup', result.stderr)
        self.assertEqual(git('rev-parse', '--abbrev-ref', 'HEAD', cwd=self.root), 'main')
        self.assertEqual(self.pins()['VIDRA_CORE_TAG'], 'v0.0.1')


class PairingTests(Fixture):
    """The three keys are three components, and a release may not move all of
    them. Before this, `pin-release.sh v0.7.5` wrote v0.7.5 into all three —
    and ghcr.io/yegamble/vidra-user:v0.7.5 has never existed, so the documented
    upgrade command could not deploy the release beta is running. The only way
    to deploy it was to hand-edit the env file, which is the exact step this
    script exists to remove.
    """

    def test_a_core_only_record_in_the_tree_pins_each_key_at_its_own_tag(self):
        result = self.run_pin('v0.7.5')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertEqual(git('describe', '--tags', cwd=self.root), 'v0.7.5')
        # The canonical copy is fetched even though the tree has one — see
        # test_the_canonical_record_wins_over_a_stale_tree_copy for why. Here
        # the stub 404s, so the tree copy is what decides, and the provenance
        # line has to say so rather than name a URL nothing was read from.
        self.assertIn('v0.7.5.json', self.curl_calls())
        self.assertIn('releases/v0.7.5.json', result.stdout,
                      'the run does not say where the pairing came from')
        for line in ('VIDRA_CORE_TAG=v0.7.5', 'VIDRA_USER_TAG=v0.7.3', 'VIDRA_SEARCH_TAG=v0.7.3'):
            self.assertIn(line, result.stdout, 'the pairing table does not show what was pinned')

    def test_the_pairing_is_read_before_the_tag_removes_it_from_the_tree(self):
        """ORDERING. release.sh tags this repository BEFORE the images exist,
        so releases/vN.json is written afterwards and lands on main in a PR: a
        tree checked out AT vN carries records only up to v(N-1). Reading the
        record after the checkout would therefore find nothing for exactly the
        releases this matters for. Rehearsed by deleting the record from the
        target tag while leaving it on main, where the run starts."""
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        other = Path(self.temp.name) / 'no-record'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(other)], check=True)
        subprocess.run(['git', 'rm', '-q', 'releases/v0.7.5.json'], cwd=other, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'the tag a release is cut at'],
                       cwd=other, check=True, env=env)
        subprocess.run(['git', 'tag', '-a', '-f', 'v0.7.5', '-m', 'v0.7.5'],
                       cwd=other, check=True, env=env)
        subprocess.run(['git', 'push', '-q', '-f', 'origin', 'v0.7.5'], cwd=other, check=True)
        result = self.run_pin('v0.7.5')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertFalse((self.root / 'releases/v0.7.5.json').exists(),
                         'the checkout did not actually remove the record')

    def test_a_fetched_record_pins_per_component_and_names_its_provenance(self):
        """The window this closes: the release is published, its record PR has
        not merged, and the tree therefore cannot carry the pairing."""
        self.serve(json.dumps(synthetic('v9.9.9', 'v9.9.9', 'v0.7.3', 'v0.7.3')))
        result = self.run_pin('v9.9.9')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v9.9.9', 'v0.7.3', 'v0.7.3'))
        self.assertIn('v9.9.9.json', self.curl_calls(), 'the record was never requested')
        self.assertIn('https://', result.stdout,
                      'the run does not name the URL the pairing was fetched from')

    def test_no_record_anywhere_pins_uniformly_and_says_what_that_risks(self):
        """A record that could not be obtained predicts nothing — most
        releases are uniform — so this stays exit 0 with the pins it has
        always written, and warns."""
        before = {'VIDRA_CORE_TAG': 'v9.9.9', 'VIDRA_USER_TAG': 'v9.9.9',
                  'VIDRA_SEARCH_TAG': 'v9.9.9'}
        result = self.run_pin('v9.9.9')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), tuple(before.values()))
        out = result.stdout + result.stderr
        self.assertIn('WARNING', out)
        self.assertIn('--component-tag', out, 'the warning does not say how to pin by hand')
        self.assertIn('failed to checkout tag', out,
                      'the warning does not name the failure it predicts, in the words deploy.sh '
                      'will actually print')

    def test_the_fetch_switch_is_honoured_and_no_request_is_made(self):
        self.env_file.write_text(self.env_file.read_text() + 'VIDRA_RECORD_FETCH=off\n')
        result = self.run_pin('v9.9.9')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v9.9.9', 'v9.9.9', 'v9.9.9'))
        self.assertEqual(self.curl_calls(), '', 'VIDRA_RECORD_FETCH=off still reached out')
        self.assertIn('WARNING', result.stdout + result.stderr)

    def test_an_unusable_fetched_record_falls_back_uniformly_and_never_refuses(self):
        """A body that is not the record it claims to be must not turn an
        upgrade into a refusal: whoever answers the request would then be able
        to stop a deploy."""
        cases = {'another release': json.dumps(synthetic('v0.7.0', 'v0.7.0', 'v0.7.0', 'v0.7.0')),
                 'malformed': '{"schema_version": 1, "release": "v9.9.9", "comp',
                 'component newer than the release':
                     json.dumps(synthetic('v9.9.9', 'v9.9.10', 'v9.9.9', 'v9.9.9'))}
        for label, text in cases.items():
            with self.subTest(body=label):
                self.reset()
                self.serve(text)
                result = self.run_pin('v9.9.9')
                out = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, out)
                self.assertEqual(self.triple(), ('v9.9.9', 'v9.9.9', 'v9.9.9'))
                self.assertIn('WARNING', out)
                self.assertNotIn('Traceback', out)

    def test_component_tag_pins_by_hand_where_no_record_can_be_had(self):
        result = self.run_pin('v9.9.9', '--component-tag', 'user=v0.7.3',
                              '--component-tag', 'search=v0.7.3')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v9.9.9', 'v0.7.3', 'v0.7.3'))
        self.assertEqual(git('describe', '--tags', cwd=self.root), 'v9.9.9')

    def test_a_component_tag_contradicting_the_record_is_refused_before_anything_moves(self):
        before_head = git('rev-parse', 'HEAD', cwd=self.root)
        before_env = self.env_file.read_text()
        result = self.run_pin('v0.7.5', '--component-tag', 'user=v0.7.4')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('v0.7.4', result.stderr)
        self.assertIn('v0.7.3', result.stderr)
        self.assertUntouched(before_head, before_env)

    def test_force_overrides_a_record_but_never_quietly(self):
        result = self.run_pin('v0.7.5', '--component-tag', 'user=v0.7.4', '--force')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.4', 'v0.7.3'))
        self.assertIn('WARNING', result.stdout + result.stderr)

    def test_nonsense_flag_values_stop_it_before_anything_moves(self):
        # 'user=v0.7.3 ' is the word-splitting probe, not decoration: the flags
        # travel to python3 through a bash array, and if that expansion split
        # on whitespace the resolver would see a clean 'user=v0.7.3', accept
        # it and pin. Only an intact, trailing-space value is refused, so this
        # case fails loudly the day the array expansion is rewritten.
        cases = (('--component-tag', 'frontend=v0.7.3'),
                 ('--component-tag', 'user=v0.07.3'),
                 ('--component-tag', 'user=latest'),
                 ('--component-tag', 'user=v9.9.10'),
                 ('--component-tag', 'user=v0.7.3 '),
                 ('--component-tag', 'user'),
                 ('--component-tag',),
                 ('--nonsense',),
                 ('v9.9.8',))
        before_head = git('rev-parse', 'HEAD', cwd=self.root)
        before_env = self.env_file.read_text()
        for flags in cases:
            with self.subTest(flags=flags):
                self.reset()
                result = self.run_pin('v9.9.9', *flags)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('Traceback', result.stderr)
                self.assertUntouched(before_head, before_env)

    def test_a_flag_is_validated_before_the_first_git_command(self):
        """Validation belongs with the root refusal, not after the fetch: a
        typo'd flag must not leave a checkout that has already moved."""
        result = self.run_pin('v9.9.9', '--component-tag', 'frontend=v0.7.3')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('fetching', result.stdout)
        self.assertEqual(self.curl_calls(), '')

    def test_the_bare_tag_form_is_unchanged_for_a_uniform_release(self):
        """Backward compatibility, asserted on the BYTES: an operator's
        existing runbook and every uniform release must produce exactly the
        env file they produced before the pairing lookup existed."""
        self.run_pin('v9.9.9')
        self.assertEqual(
            self.env_file.read_text(),
            'VIDRA_CORE_TAG=v9.9.9\nVIDRA_USER_TAG=v9.9.9\n'
            'JWT_SECRET=fake-not-a-secret\nVIDRA_SEARCH_TAG=v9.9.9\n')

    def test_a_per_component_pin_is_idempotent(self):
        self.assertEqual(self.run_pin('v0.7.5').returncode, 0)
        before = self.env_file.read_text()
        self.assertEqual(self.run_pin('v0.7.5').returncode, 0)
        self.assertEqual(self.env_file.read_text(), before)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))

    def test_the_canonical_record_wins_over_a_stale_tree_copy(self):
        """The tree copy read here belongs to the revision the run STARTS on,
        and the checkout is about to replace it with one that carries no
        record for this release at all — so deploy.sh will judge the pins
        against the canonical copy it fetches. Pinning from a tree copy that
        disagrees produces a host that is moved and a deploy that is refused."""
        stale = json.loads((RECORDS / 'v0.7.5.json').read_text())
        stale['components']['user']['tag'] = 'v0.7.2'
        (self.root / 'releases/v0.7.5.json').write_text(json.dumps(stale, indent=2))
        self.serve((RECORDS / 'v0.7.5.json').read_text())
        result = self.run_pin('v0.7.5')
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertIn('v0.7.5.json', self.curl_calls(),
                      'a tree copy suppressed the fetch of the canonical record')
        self.assertIn('WARNING', out)
        self.assertIn('v0.7.2', out, 'the warning does not name the tree copy it set aside')

    def test_the_tree_copy_is_used_when_the_fetch_cannot_be_made(self):
        result = self.run_pin('v0.7.5')          # stub curl 404s by default
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertIn('releases/v0.7.5.json', result.stdout,
                      'the provenance line does not say the tree copy was used')

    def test_the_fetch_switch_still_leaves_a_tree_copy_usable(self):
        self.env_file.write_text(self.env_file.read_text() + 'VIDRA_RECORD_FETCH=off\n')
        result = self.run_pin('v0.7.5')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertEqual(self.curl_calls(), '')

    def test_repository_spellings_of_a_role_are_accepted(self):
        result = self.run_pin('v9.9.9', '--component-tag', 'vidra-user=v0.7.3')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v9.9.9', 'v0.7.3', 'v9.9.9'))

    def test_every_resolver_failure_says_which_one_it_was(self):
        """A resolver that exits 2 (an older release-mapping.py that does not
        know `resolve`), one that crashes, and one that returns something this
        contract does not define are three different problems with three
        different fixes. `[pin] ERROR: nothing was changed` named none of
        them. Nothing may be mutated by any of the three: pinning is not an
        incident path, and guessing a uniform triple after the tool that
        decides the pairing has fallen over is worse than stopping."""
        checker = self.root / 'deploy/release-mapping.py'
        cases = {2: 'predates', 70: 'crash', 99: 'not an answer'}
        for code, expected in cases.items():
            with self.subTest(exit=code):
                self.reset()
                checker.write_text(f'#!/usr/bin/env python3\nimport sys\nsys.exit({code})\n')
                before_head = git('rev-parse', 'HEAD', cwd=self.root)
                before_env = self.env_file.read_text()
                result = self.run_pin('v0.7.5')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(expected, result.stderr.lower(),
                              f'exit {code} was not distinguished: {result.stderr}')
                self.assertNotEqual(result.stderr.strip(), '[pin] ERROR: nothing was changed')
                self.assertUntouched(before_head, before_env)
        checker.write_text((DEPLOY / 'release-mapping.py').read_text())

    def test_a_resolver_that_cannot_be_run_at_all_stops_before_the_fetch(self):
        (self.root / 'deploy/release-mapping.py').unlink()
        before_head = git('rev-parse', 'HEAD', cwd=self.root)
        before_env = self.env_file.read_text()
        result = self.run_pin('v0.7.5')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('release-mapping.py', result.stderr)
        self.assertEqual(self.curl_calls(), '')
        self.assertUntouched(before_head, before_env)

    def test_the_uniform_warning_does_not_claim_pins_it_is_not_writing(self):
        """With --component-tag the pins are NOT what this script has always
        written, and the warning said they were."""
        plain = self.run_pin('v9.9.9')
        self.assertIn('always done', plain.stdout + plain.stderr)
        self.reset()
        mixed = self.run_pin('v9.9.9', '--component-tag', 'user=v0.7.3')
        out = mixed.stdout + mixed.stderr
        self.assertEqual(mixed.returncode, 0, out)
        self.assertNotIn('always done', out)
        self.assertIn('--component-tag', out)

    def test_the_warning_names_the_step_that_actually_fails(self):
        """pin-release.sh only ever runs on a git tree, and there deploy.sh's
        component checkout sync reaches a tag that does not exist BEFORE any
        pull — `failed to checkout tag vX in vidra-user`. Naming `compose
        pull` sent the operator to the wrong line of the log."""
        result = self.run_pin('v9.9.9')
        warning = [l for l in (result.stdout + result.stderr).splitlines()
                   if 'pairing could not be determined' in l]
        self.assertEqual(len(warning), 1, result.stdout + result.stderr)
        self.assertIn('checkout sync', warning[0])
        self.assertIn('vidra-user', warning[0])
        self.assertNotIn('compose pull', warning[0],
                         'the warning still names a step that is reached later, if at all')

    def test_a_prerelease_tag_a_rehearsal_lab_pins_is_unaffected(self):
        """vN-rc1 has no record anywhere and never will. It pinned before the
        pairing lookup existed and must still pin: making the tag gate strict
        would have locked every rehearsal lab out of this script, and no
        record fetch should even be attempted for a tag that cannot have one."""
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com'}
        lab = Path(self.temp.name) / 'lab'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(lab)], check=True)
        subprocess.run(['git', 'tag', '-a', 'v9.9.9-rc1', '-m', 'rc'], cwd=lab, check=True, env=env)
        subprocess.run(['git', 'push', '-q', 'origin', 'v9.9.9-rc1'], cwd=lab, check=True)
        result = self.run_pin('v9.9.9-rc1')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.triple(), ('v9.9.9-rc1', 'v9.9.9-rc1', 'v9.9.9-rc1'))
        self.assertEqual(self.curl_calls(), '', 'a tag that can have no record was still fetched')

    def test_a_bundle_tree_is_refused_before_any_record_is_looked_for(self):
        """The beta host is an UNPACKED bundle with no .git anywhere. This
        script has always refused there (a bundle is pinned by unpacking the
        next one), and the record lookup must not turn that refusal into a
        network call or a half-written env file."""
        bundle = Path(self.temp.name) / 'bundle'
        shutil.copytree(self.root, bundle, ignore=shutil.ignore_patterns('.git'))
        before_env = (bundle / 'env/production.env').read_text()
        result = subprocess.run(
            ['bash', str(bundle / 'deploy/pin-release.sh'), 'v0.7.5'],
            env={**os.environ, 'HOME': str(self.home),
                 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'CURL_LOG': str(self.curl_log)},
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a git checkout', result.stderr)
        self.assertEqual((bundle / 'env/production.env').read_text(), before_env)
        self.assertEqual(self.curl_calls(), '')

    def test_no_temporary_record_directory_is_left_behind(self):
        self.serve(json.dumps(synthetic('v9.9.9', 'v9.9.9', 'v0.7.3', 'v0.7.3')))
        tmpdir = Path(self.temp.name) / 'scratch'
        tmpdir.mkdir()
        environ = {**os.environ, 'HOME': str(self.home), 'TMPDIR': str(tmpdir),
                   'PATH': f'{self.bin}:{os.environ["PATH"]}', 'CURL_LOG': str(self.curl_log),
                   'CURL_EXIT': '0', 'CURL_BODY_FILE': str(self.body)}
        result = subprocess.run(['bash', str(self.root / 'deploy/pin-release.sh'), 'v9.9.9'],
                                env=environ, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        leaked = sorted(p.name for p in tmpdir.iterdir() if p.name.startswith('vidra-record'))
        self.assertEqual(leaked, [], f'the record fetch left {leaked} behind')


class ShipHintTests(unittest.TestCase):
    """The command deploy/release.sh tells an operator to run next must be one
    that WORKS.

    After a SUBSET release the record does not exist yet, so the by-hand pin
    writes a mixed triple — and `release-mapping.py check --mode deploy` then
    refuses it: "core=v0.7.6 user=v0.7.3 search=v0.7.3 is not a recorded
    release ... Nothing was changed" (measured, exit 1). So a hint of the form
    `pin-release.sh vN --component-tag ... && ./deploy/deploy.sh` walks the
    operator straight into a refusal on the second half of its own chain.

    Two honest ways out, and the hint has to name one: land the record first
    and let a plain `pin-release.sh vN` resolve it (preferred — it is the only
    one that ends verified), or, before the record exists, waive the pairing
    check for that one run with VIDRA_RELEASE_MAPPING=warn.
    """

    def test_the_subset_ship_hint_does_not_end_in_a_refusal(self):
        source = (DEPLOY / 'release.sh').read_text()
        subset = source.split('FULL_RELEASE')[-1]
        self.assertIn('--component-tag', subset,
                      'the subset hint no longer names the by-hand pin')
        self.assertTrue(
            'VIDRA_RELEASE_MAPPING=warn' in subset or 'record' in subset,
            'the subset hint chains into ./deploy/deploy.sh without naming the '
            'override that lets a by-hand pin through, or the land-the-record-'
            'first path that makes the override unnecessary')
        self.assertIn('VIDRA_RELEASE_MAPPING=warn', subset)

    def test_the_readme_by_hand_recipe_names_the_override_too(self):
        readme = (DEPLOY / 'README.md').read_text()
        recipe = readme.split('--component-tag user=v0.7.3')[1][:2500]
        self.assertIn('VIDRA_RELEASE_MAPPING=warn', recipe,
                      'the README shows a by-hand pin followed by a deploy that '
                      'release-mapping.py refuses, and does not name the override')


if __name__ == '__main__':
    unittest.main()
