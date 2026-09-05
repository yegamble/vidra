"""Replacing a bind-mounted Caddyfile must refresh the mount before reload."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class CaddyReloadTests(unittest.TestCase):
    def run_reload(self, stale, recreate_fails=False):
        source = (Path(__file__).resolve().parents[1] / 'deploy/deploy.sh').read_text()
        function = 'reload_caddy() {' + source.split('reload_caddy() {', 1)[1].split('\n}', 1)[0] + '\n}'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'deploy').mkdir()
            (root / 'deploy/Caddyfile.local').write_text('new site\n')
            (root / 'mounted').write_text('old site\n' if stale else 'new site\n')
            script = '''set -euo pipefail
REPO_ROOT="$1"
cd "$REPO_ROOT"
COMPOSE=(compose)
log() { :; }
sleep() { :; }
compose() {
  printf '%s\\n' "$*" >> calls
  if [ "$1" = up ]; then
    [ "$2 $3 $4 $5 $6 $7" = '-d --no-build --no-deps --force-recreate caddy ' ] || return 90
    RECREATE_RESULT
    cp deploy/Caddyfile.local mounted
  elif [ "$4" = cat ]; then
    cat mounted
  elif [ "$4" = caddy ]; then
    cmp -s mounted deploy/Caddyfile.local
  else return 91
  fi
}
'''.replace('    RECREATE_RESULT', '    return 7' if recreate_fails else '    :')
            script = script.replace('$6 $7', '${6-} ${7-}')
            p = subprocess.run(['bash', '-c', script + function + '\nreload_caddy', 'test', tmp], capture_output=True)
            return p.returncode, (root / 'calls').read_text()

    def test_replaced_file_recreates_only_caddy_before_reload(self):
        code, calls = self.run_reload(True)
        self.assertEqual(code, 0)
        self.assertIn('up -d --no-build --no-deps --force-recreate caddy', calls)

    def test_unchanged_file_only_reloads(self):
        code, calls = self.run_reload(False)
        self.assertEqual(code, 0)
        self.assertNotIn('up ', calls)

    def test_recreate_failure_is_fatal(self):
        code, calls = self.run_reload(True, True)
        self.assertNotEqual(code, 0)
        self.assertNotIn('caddy reload', calls)
