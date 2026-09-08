"""deploy.sh must refuse a scanner address whose container nothing will start.

Since scanning became derived from CLAMAV_ADDR (vidra-core #201), an address
pointing at the BUNDLED `clamav` service without the `scan` compose profile is a
deployment that boots healthy and then refuses every upload, import, poster,
avatar, banner, caption and DM attachment — MALWARE_SCAN_MODE=fail-closed cannot
reach a container that was never started, health probes pass, and nothing in the
logs mentions a profile.

`vidra setup --scan=false` produces exactly that pair: it drops `scan` from
VIDRA_COMPOSE_PROFILES and leaves CLAMAV_ADDR alone. So does hand-editing either
line. The function is lifted out of the real script — the same trick
tests/caddy_reload_test.py and tests/rollback_floor_test.py use — so these tests
fail if deploy.sh changes and the guard does not come with it.
"""
from pathlib import Path
import subprocess
import unittest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'


def extract(script, name):
    """The shell function `name` as written in deploy/<script>."""
    source = (DEPLOY / script).read_text()
    marker = name + '() {'
    if marker not in source:
        raise AssertionError(f'{script} no longer defines {name}() — the guard it '
                             f'implements was removed or renamed')
    body = source.split(marker, 1)[1].split('\n}', 1)[0]
    return marker + body + '\n}\n'


HARNESS = '''set -euo pipefail
ENV_FILE=env/production.env
die() { echo "DIE: $*" >&2; exit 1; }
env_get() {
  local key="$1" default="${2-}"
  local varname="ENV_$key"
  if [ -n "${!varname-}" ]; then printf '%s' "${!varname}"; else printf '%s' "$default"; fi
}
'''


def run(addr, profiles, extra='', mode='fail-closed'):
    script = HARNESS + extract('deploy.sh', 'require_scanner_profile') + '\nrequire_scanner_profile\necho OK\n'
    env = {
        'ENV_CLAMAV_ADDR': addr,
        'ENV_VIDRA_COMPOSE_PROFILES': profiles,
        'ENV_EXTRA_COMPOSE_PROFILES': extra,
        'ENV_MALWARE_SCAN_MODE': mode,
        'PATH': '/usr/bin:/bin',
    }
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env)


class ScannerProfileGuard(unittest.TestCase):
    def test_bundled_clamd_without_the_scan_profile_is_refused(self):
        """The `vidra setup --scan=false` shape: address kept, profile dropped."""
        r = run('clamav:3310', 'core frontend')
        self.assertNotEqual(r.returncode, 0, 'deploy proceeded with a scanner nothing starts')
        # The message must name every lever an operator can pull, or it sends
        # them to read the source.
        for expected in ['scan', 'VIDRA_COMPOSE_PROFILES', 'CLAMAV_ADDR', 'MALWARE_SCAN_MODE=disabled']:
            self.assertIn(expected, r.stderr, f'refusal does not name {expected}: {r.stderr}')

    def test_scan_profile_present_passes(self):
        self.assertEqual(run('clamav:3310', 'core frontend scan').returncode, 0)

    def test_scan_via_extra_profiles_also_passes(self):
        """EXTRA_COMPOSE_PROFILES is the operator-owned half of the same list."""
        self.assertEqual(run('clamav:3310', 'core frontend', extra='scan').returncode, 0)

    def test_external_clamd_is_never_second_guessed(self):
        """An external daemon is the operator's own host: this project neither
        starts it nor can verify it, so the guard must not block on it."""
        for addr in ['scanner.internal:3310', '10.0.0.9:3310', 'clamav.example.org:3310']:
            self.assertEqual(run(addr, 'core frontend').returncode, 0, addr)

    def test_no_address_is_not_this_guards_business(self):
        """Unset CLAMAV_ADDR is the opt-out (or the unconfigured refusal the api
        itself reports); either way there is no container to reconcile."""
        self.assertEqual(run('', 'core frontend', mode='disabled').returncode, 0)

    def test_the_refusal_quotes_the_mode_actually_in_force(self):
        r = run('clamav:3310', 'core frontend', mode='quarantine')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('quarantine', r.stderr)


if __name__ == '__main__':
    unittest.main()
