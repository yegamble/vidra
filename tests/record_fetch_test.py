"""deploy/lib.sh's fetch_release_record: a best-effort, bounded, HTTPS-only
download that may only ever ADD verification to a deploy.

WHY IT EXISTS. deploy/release.sh pushes this repository's tag before it
publishes the component releases (vidra-core's release-assets workflow builds
the bundle from the meta tree at that tag), so the GHCR digests a record needs
do not exist yet and releases/<TAG>.json is written afterwards. A vN tree and
the vN bundle carry records only up to v(N-1), and deploying vN therefore
compares tag strings and nothing else. Fetching the record at deploy time is
what closes that, for any host with egress.

WHY EVERY FAILURE HERE IS NON-FATAL. A record that could not be downloaded
predicts nothing about the images being deployed — the standing severity
ruling is that a finding may only stop what it predicts. So a 404, a timeout,
an airgapped host and a captive portal all leave the deploy exactly where it
was, with a warning naming the URL and the curl to run by hand. The one thing
that DOES stop a deploy is a record that loads and contradicts the pins, and
that verdict belongs to deploy/release-mapping.py, not here.

The function is lifted out of the real deploy/lib.sh — the same trick
tests/scanner_profile_test.py, tests/caddy_reload_test.py and
tests/rollback_floor_test.py use — so these tests fail if lib.sh changes and
the guard does not come with it. curl is STUBBED throughout: nothing here
touches the network, and the stub's log is how "no call was attempted" is
proved rather than asserted.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASH = shutil.which('bash') or '/bin/bash'
# A PATH holding everything the function needs EXCEPT curl, so "this host has
# no curl" can be rehearsed without also hiding bash, grep and mktemp from it.
NEEDED = ('grep', 'mktemp', 'wc', 'head', 'tr', 'cat', 'rm')

LIB = Path(__file__).resolve().parents[1] / 'deploy/lib.sh'

DEFAULT_BASE = 'https://raw.githubusercontent.com/yegamble/vidra/main/releases'

# Records every argv it is given, then answers with $CURL_BODY (written to the
# path after --output) and exits $CURL_EXIT. A stub that logs is the only way
# to prove a NEGATIVE — that VIDRA_RECORD_FETCH=off and a tag that is not
# release-shaped attempt no request at all.
CURL_STUB = '''#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
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

HARNESS = '''set -euo pipefail
log() { printf 'LOG: %s\\n' "$*"; }
die() { printf 'DIE: %s\\n' "$*" >&2; exit 1; }
env_get() {
  local key="$1" default="${2-}"
  local varname="ENV_$key"
  if [ -n "${!varname-}" ]; then printf '%s' "${!varname}"; else printf '%s' "$default"; fi
}
'''


def extract(name):
    """The shell function `name` as written in deploy/lib.sh."""
    source = LIB.read_text()
    marker = name + '() {'
    if marker not in source:
        raise AssertionError(f'deploy/lib.sh no longer defines {name}() — the deploy-time '
                             f'record fetch it implements was removed or renamed')
    body = source.split(marker, 1)[1].split('\n}', 1)[0]
    return marker + body + '\n}\n'


def record(release='v0.9.0'):
    """A well-formed record for a release that was never cut — fixture only."""
    def component(repo, n):
        return {'tag': release, 'commit': (format(n + 1, 'x') * 40)[:40],
                'image': {'repository': f'ghcr.io/yegamble/{repo}',
                          'index_digest': 'sha256:' + (format(n + 3, 'x') * 64)[:64],
                          'platforms': {'linux/amd64': 'sha256:' + (format(n + 5, 'x') * 64)[:64]}}}
    return {'schema_version': 1, 'release': release, 'meta_commit': 'a' * 40,
            'core_schema_version': 150, 'search_schema_version': 19,
            'components': {'core': component('vidra-core', 0),
                           'user': component('vidra-user', 1),
                           'search': component('vidra-search', 2)}}


class FetchReleaseRecord(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'curl').write_text(CURL_STUB)
        (self.bin / 'curl').chmod(0o755)
        self.curl_log = self.base / 'curl.log'
        self.dest_dir = self.base / 'dest'
        self.dest_dir.mkdir()
        self.nocurl = self.base / 'nocurl'
        self.nocurl.mkdir()
        for tool in NEEDED:
            found = shutil.which(tool)
            self.assertIsNotNone(found, f'{tool} is not on PATH; the harness cannot run')
            (self.nocurl / tool).symlink_to(found)
        self.assertIsNone(shutil.which('curl', path=str(self.nocurl)))

    def fetch(self, tag='v0.9.0', body=None, exit_code=0, env=None, with_curl=True):
        """Run fetch_release_record TAG <dest>, and report what it did."""
        dest = self.dest_dir / f'{tag}.json'
        script = HARNESS + extract('fetch_release_record') + \
            f'\nrc=0\nfetch_release_record {tag!r} "$1" || rc=$?\necho "RC=$rc"\n'
        environ = {
            'PATH': f'{self.bin}:{self.nocurl}' if with_curl else str(self.nocurl),
            'CURL_LOG': str(self.curl_log),
            'CURL_EXIT': str(exit_code),
            'HOME': str(self.base),
            'TMPDIR': str(self.base),
        }
        if body is not None:
            body_file = self.base / 'body'
            body_file.write_text(body)
            environ['CURL_BODY_FILE'] = str(body_file)
        environ.update(env or {})
        result = subprocess.run([BASH, '-c', script, 'harness', str(dest)],
                                capture_output=True, text=True, env=environ)
        out = result.stdout + result.stderr
        self.assertNotIn('DIE:', out, 'the fetch called die(); it must never be fatal')
        self.assertNotIn('command not found', out, out)
        calls = self.curl_log.read_text() if self.curl_log.exists() else ''
        rc = int(out.split('RC=')[1].split('\n')[0]) if 'RC=' in out else None
        return rc, out, calls, dest

    # --- the happy path, and the control every negative below needs ---------

    def test_a_good_record_is_downloaded_and_the_url_is_logged(self):
        body = json.dumps(record())
        rc, out, calls, dest = self.fetch(body=body)
        self.assertEqual(rc, 0, out)
        self.assertEqual(dest.read_text(), body)
        self.assertIn(f'{DEFAULT_BASE}/v0.9.0.json', out, 'the log does not name the exact URL')
        self.assertIn(f'{DEFAULT_BASE}/v0.9.0.json', calls, 'curl was not asked for that URL')

    def test_the_request_is_https_only_bounded_and_size_capped(self):
        """An operator's deploy must not hang on a black-holed host, follow a
        redirect off TLS, or stream an unbounded body into a preflight."""
        _, _, calls, _ = self.fetch(body=json.dumps(record()))
        for flag in ('--proto', '--tlsv1.2', '--fail', '--location', '--max-time', '--max-filesize'):
            self.assertIn(flag, calls, f'curl was invoked without {flag}: {calls}')
        self.assertIn('=https', calls, 'the request does not restrict the protocol to https')

    # --- 6: the airgapped switch --------------------------------------------

    def test_record_fetch_off_attempts_no_call_at_all(self):
        """An airgapped or egress-filtered host must not spend the timeout on a
        request that cannot succeed, and must not be seen reaching out."""
        rc, out, calls, dest = self.fetch(body=json.dumps(record()),
                                          env={'ENV_VIDRA_RECORD_FETCH': 'off'})
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(calls, '', f'curl ran with VIDRA_RECORD_FETCH=off: {calls}')
        self.assertFalse(dest.exists())
        self.assertIn('VIDRA_RECORD_FETCH', out)

    def test_the_spellings_of_no_an_operator_types_all_turn_it_off(self):
        """Same reasoning as is_true's word list: an env file is hand-edited."""
        for value in ('off', 'OFF', 'Off', '0', 'false', 'no'):
            with self.subTest(value=value):
                self.curl_log.unlink(missing_ok=True)
                rc, out, calls, _ = self.fetch(body=json.dumps(record()),
                                               env={'ENV_VIDRA_RECORD_FETCH': value})
                self.assertNotEqual(rc, 0, out)
                self.assertEqual(calls, '', f'{value!r} did not turn the fetch off')

    def test_the_default_and_an_unrecognised_value_still_fetch(self):
        """Control for the test above: the switch is off-only, and the fetch is
        on by default — a typo must not silently disable verification."""
        for env in ({}, {'ENV_VIDRA_RECORD_FETCH': 'on'}, {'ENV_VIDRA_RECORD_FETCH': 'yes please'}):
            with self.subTest(env=env):
                self.curl_log.unlink(missing_ok=True)
                rc, out, calls, _ = self.fetch(body=json.dumps(record()), env=env)
                self.assertEqual(rc, 0, out)
                self.assertNotEqual(calls, '')

    # --- 7: failure is a warning, never a stop ------------------------------

    def test_a_failed_request_warns_and_names_the_curl_to_run_by_hand(self):
        """404 (the record PR has not merged yet), DNS failure, timeout. The
        operator gets the one command that tells them which it was."""
        for label, code in (('404 / --fail', 22), ('could not resolve host', 6),
                            ('timeout', 28), ('TLS failure', 60)):
            with self.subTest(failure=label):
                self.curl_log.unlink(missing_ok=True)
                rc, out, calls, dest = self.fetch(exit_code=code)
                self.assertNotEqual(rc, 0, out)
                self.assertFalse(dest.exists(), 'a failed fetch left a file behind')
                self.assertIn(str(code), out, 'the warning does not say how curl failed')
                self.assertIn('curl ', out, 'the warning does not name a curl to run by hand')
                self.assertIn(f'{DEFAULT_BASE}/v0.9.0.json', out)
                self.assertNotEqual(calls, '', 'control: the request was actually attempted')

    def test_no_curl_on_the_host_is_a_warning_not_a_stop(self):
        rc, out, _, dest = self.fetch(body=json.dumps(record()), with_curl=False)
        self.assertNotEqual(rc, 0, out)
        self.assertFalse(dest.exists())
        self.assertIn('curl', out)

    # --- 8: a body the checker must never see -------------------------------

    def test_an_oversized_body_is_rejected_before_the_checker_sees_it(self):
        """A record is ~2 KiB. Anything near the cap is a redirect page, a
        proxy error or something worse, and the checker should not be handed
        it — nor should a preflight read an unbounded body into memory."""
        rc, out, _, dest = self.fetch(body='{"x":"' + 'y' * (300 * 1024) + '"}')
        self.assertNotEqual(rc, 0, out)
        self.assertFalse(dest.exists())
        self.assertIn('too large', out.lower())

    def test_a_body_that_is_not_a_json_object_is_rejected(self):
        """A captive portal, a GitHub error page, an empty 200: all arrive with
        exit 0 and none of them is a record."""
        for label, body in (('html error page', '<!DOCTYPE html>\n<html>404: Not Found</html>\n'),
                            ('empty', ''),
                            ('a JSON array', '[1, 2, 3]'),
                            ('plain text', '404: Not Found\n')):
            with self.subTest(body=label):
                rc, out, _, dest = self.fetch(body=body)
                self.assertNotEqual(rc, 0, out)
                self.assertFalse(dest.exists(), f'{label} was handed on as a record')

    def test_a_response_curl_never_wrote_is_not_mistaken_for_a_record(self):
        """curl exiting 0 having written nothing (the shape every stubbed curl
        in this repo's other tests has) must not read as a successful fetch."""
        rc, out, _, dest = self.fetch(body=None)
        self.assertNotEqual(rc, 0, out)
        self.assertFalse(dest.exists())

    # --- 9: the fork/mirror knob --------------------------------------------

    def test_a_custom_base_url_is_honoured_and_logged(self):
        """A fork publishes its own records; a mirror serves them inside an
        egress-filtered network. Same reasoning as VIDRA_IMAGE_REGISTRY."""
        base = 'https://mirror.internal/vidra/releases'
        rc, out, calls, dest = self.fetch(body=json.dumps(record()),
                                          env={'ENV_VIDRA_RECORD_BASE_URL': base})
        self.assertEqual(rc, 0, out)
        self.assertIn(f'{base}/v0.9.0.json', calls)
        self.assertIn(f'{base}/v0.9.0.json', out)
        self.assertNotIn('raw.githubusercontent.com', calls)

    def test_a_trailing_slash_on_the_base_url_does_not_double_it(self):
        rc, out, calls, _ = self.fetch(
            body=json.dumps(record()),
            env={'ENV_VIDRA_RECORD_BASE_URL': 'https://mirror.internal/releases/'})
        self.assertEqual(rc, 0, out)
        self.assertIn('https://mirror.internal/releases/v0.9.0.json', calls)
        self.assertNotIn('//v0.9.0.json', calls)

    def test_a_base_url_that_is_not_https_is_refused_without_a_request(self):
        """The record is the input to a verification decision; fetching it over
        a channel anyone on the path can rewrite would be worse than not
        fetching it at all."""
        for base in ('http://mirror.internal/releases', 'file:///etc',
                     'ftp://mirror.internal', 'mirror.internal/releases'):
            with self.subTest(base=base):
                self.curl_log.unlink(missing_ok=True)
                rc, out, calls, _ = self.fetch(body=json.dumps(record()),
                                               env={'ENV_VIDRA_RECORD_BASE_URL': base})
                self.assertNotEqual(rc, 0, out)
                self.assertEqual(calls, '', f'{base!r} reached curl')
                self.assertIn('https', out)

    # --- 10: nothing but a release tag ever reaches a URL -------------------

    def test_a_tag_that_is_not_strict_semver_never_reaches_a_url(self):
        """The tag is operator-controlled (VIDRA_CORE_TAG in the env file) and
        it is interpolated into a URL and into a filename. Anything but
        vMAJOR.MINOR.PATCH is refused BEFORE either, so a tag cannot traverse
        out of the temp directory, append a query, or become a second
        argument. Release records only ever exist for that shape anyway."""
        for tag in ('main', 'latest', 'v1.2', 'v1.2.3.4', 'v0.7.0-rc1',
                    'v0.7.0@sha256:' + 'a' * 64, '../../../etc/passwd',
                    'v1.2.3/../../evil', 'v1.2.3?x=1', 'v1.2.3#f', 'v1.2.3%2e%2e',
                    'v1.2.3 v1.2.4', '', 'sha-abc1234', 'V1.2.3'):
            with self.subTest(tag=tag):
                self.curl_log.unlink(missing_ok=True)
                rc, out, calls, _ = self.fetch(tag=tag, body=json.dumps(record()))
                self.assertNotEqual(rc, 0, out)
                self.assertEqual(calls, '', f'{tag!r} was interpolated into a request: {calls}')

    def test_the_tag_is_checked_against_the_same_shape_releases_are_cut_as(self):
        """Control for the list above: the shape deploy/release.sh cuts."""
        for tag in ('v0.9.0', 'v1.0.0', 'v10.20.30'):
            with self.subTest(tag=tag):
                self.curl_log.unlink(missing_ok=True)
                rc, out, calls, _ = self.fetch(tag=tag, body=json.dumps(record(tag)))
                self.assertEqual(rc, 0, out)
                self.assertIn(f'/{tag}.json', calls)

    # --- the temp file ------------------------------------------------------

    def test_no_temp_file_is_left_behind_on_any_path(self):
        """The download lands in a temp file first, so a partial or oversized
        body never appears at the destination the checker is pointed at."""
        before = set(self.base.iterdir())
        for label, kwargs in (('success', dict(body=json.dumps(record()))),
                              ('curl failed', dict(exit_code=22)),
                              ('oversized', dict(body='{"x":"' + 'y' * (300 * 1024) + '"}')),
                              ('not json', dict(body='<html></html>'))):
            with self.subTest(path=label):
                self.fetch(**kwargs)
                leaked = [p.name for p in set(self.base.iterdir()) - before
                          if p.name.startswith('vidra-record')]
                self.assertEqual(leaked, [], f'temp files left behind: {leaked}')


if __name__ == '__main__':
    unittest.main()
