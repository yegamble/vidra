"""pin-release.sh on a BUNDLE tree: fetch, verify, safely unpack, then pin.

The default install is an unpacked vidra-bundle (vidra-bundle.manifest, no
.git). Its upgrade used to be five hand steps, one of which — `tar -xzf` over
the live tree — trusts every member name in a downloaded archive. These tests
pin the safety properties: nothing is unpacked before the checksum verifies,
a hostile or malformed archive changes NOTHING (tree, env file), and the env
file's secrets and deploy/Caddyfile.local are never overwritten.

curl is stubbed (no network): it serves files from $SERVE_DIR by URL basename
and 404s everything else, so the record fetch falls back to the tree copy.
`id` is stubbed to a non-root uid so the suite also passes when run as root;
the real root refusal is covered in pin_release_test.py.
"""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'deploy'
SCRIPTS = ('pin-release.sh', 'lib.sh', 'backup-env.sh', 'checkout-hygiene.py',
           'release-mapping.py')

CURL_STUB = '''#!/bin/sh
printf '%s\\n' "$*" >> "$CURL_LOG"
dest=""; prev=""; url=""
for arg in "$@"; do
  if [ "$prev" = "--output" ] || [ "$prev" = "-o" ]; then dest="$arg"; fi
  prev="$arg"; url="$arg"
done
src="$SERVE_DIR/$(basename "$url")"
[ -f "$src" ] || exit 22
cat "$src" > "$dest"
'''
ID_STUB = '''#!/bin/sh
if [ "$1" = "-u" ]; then echo 1000; exit 0; fi
exec /usr/bin/id "$@"
'''
TAG = 'v0.7.5'            # releases/v0.7.5.json: core v0.7.5, user/search v0.7.3
ASSET = f'vidra-bundle_{TAG}.tar.gz'
ENV = 'VIDRA_CORE_TAG=v0.7.1\nVIDRA_USER_TAG=v0.7.1\nVIDRA_SEARCH_TAG=v0.7.1\nJWT_SECRET=fake-not-a-secret\n'


def build_bundle(path, extra=(), skip_manifest=False, omit=()):
    """A bundle shaped like make-bundle.sh's: ./-relative, manifest included."""
    new_pin = (DEPLOY / 'pin-release.sh').read_text() + '\necho REREAD_AFTER_OVERWRITE\n# from the new bundle\n'
    files = {'./deploy/marker.txt': 'new\n', './deploy/pin-release.sh': new_pin,
             './releases/README.md': 'new records\n',
             './vidra-bundle.manifest': f'tag={TAG}\ncore_schema_version=0150\n'}
    for name in omit:
        files.pop(name)
    with tarfile.open(path, 'w:gz') as tar:
        for name, text in files.items():
            if skip_manifest and name == './vidra-bundle.manifest':
                continue
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755 if name.endswith('.sh') else 0o644
            tar.addfile(info, io.BytesIO(data))
        for info, data in extra:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)


def member(name, kind=tarfile.REGTYPE, linkname='', data=b''):
    info = tarfile.TarInfo(name)
    info.type, info.linkname, info.size = kind, linkname, len(data)
    return info, data if kind == tarfile.REGTYPE else None


class BundlePinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'tree'
        (self.root / 'deploy').mkdir(parents=True)
        (self.root / 'env').mkdir()
        (self.root / 'releases').mkdir()
        for name in SCRIPTS:
            shutil.copyfile(DEPLOY / name, self.root / 'deploy' / name)
        shutil.copyfile(ROOT / 'releases/v0.7.5.json', self.root / 'releases/v0.7.5.json')
        (self.root / 'env/production.env').write_text(ENV)
        (self.root / 'deploy/Caddyfile.local').write_text('local.example.com {}\n')
        (self.root / 'vidra-bundle.manifest').write_text('tag=v0.7.1\ncore_schema_version=0149\n')
        self.bin, self.serve = base / 'bin', base / 'serve'
        (base / 'home').mkdir()
        self.bin.mkdir()
        self.serve.mkdir()
        for name, text in (('curl', CURL_STUB), ('id', ID_STUB)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.curl_log = base / 'curl.log'
        self.publish()

    def publish(self, sums_for=None, **kwargs):
        """Put the bundle and its SHA256SUMS where the stub serves them."""
        build_bundle(self.serve / ASSET, **kwargs)
        digest = hashlib.sha256((self.serve / ASSET).read_bytes()).hexdigest()
        if sums_for is not None:
            digest = sums_for
        (self.serve / 'SHA256SUMS').write_text(f'{"0" * 64}  vidra_{TAG}_linux_amd64\n{digest}  {ASSET}\n')

    def run_pin(self, *args):
        environ = {**os.environ, 'HOME': str(Path(self.temp.name) / 'home'), 'CURL_LOG': str(self.curl_log),
                   'PATH': f'{self.bin}:{os.environ["PATH"]}', 'SERVE_DIR': str(self.serve)}
        return subprocess.run(['bash', str(self.root / 'deploy/pin-release.sh'), TAG, *args],
                              env=environ, capture_output=True, text=True)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(self.root.rglob('*'))
                if p.is_file() and 'backups' not in p.parts}

    def assertUntouched(self, result, before, fragment):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(fragment, result.stderr)
        self.assertEqual(self.snapshot(), before, 'a refused upgrade changed the tree')
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith('.vidra')], [],
                         'the staging directory was left behind')

    def test_happy_path_unpacks_pins_and_leaves_env_and_caddyfile_alone(self):
        result = self.run_pin()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.root / 'deploy/marker.txt').read_text(), 'new\n')
        self.assertIn('tag=v0.7.5', (self.root / 'vidra-bundle.manifest').read_text())
        self.assertIn('from the new bundle', (self.root / 'deploy/pin-release.sh').read_text())
        # The script was replaced while running; bash must not resume inside the new file.
        self.assertNotIn('REREAD_AFTER_OVERWRITE', result.stdout)
        self.assertEqual((self.root / 'deploy/Caddyfile.local').read_text(), 'local.example.com {}\n')
        env = (self.root / 'env/production.env').read_text()
        # The pairing, not one tag three times: user/search stay at v0.7.3.
        pins = dict(l.split('=', 1) for l in env.splitlines() if '=' in l)
        self.assertEqual((pins['VIDRA_CORE_TAG'], pins['VIDRA_USER_TAG'], pins['VIDRA_SEARCH_TAG']),
                         ('v0.7.5', 'v0.7.3', 'v0.7.3'))
        self.assertEqual(pins['JWT_SECRET'], 'fake-not-a-secret')
        self.assertIn('./deploy/deploy.sh', result.stdout)
        self.assertNotIn('deploying', result.stdout.lower())
        self.assertTrue(list((Path(self.temp.name) / 'home/.local/state/vidra/env-history').glob('production.env.*')),
                        'no env snapshot was taken before the tags were written')
        self.assertIn(f'releases/download/{TAG}/{ASSET}', self.curl_log.read_text())

    def test_checksum_mismatch_changes_nothing(self):
        self.publish(sums_for='f' * 64)
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'CHECKSUM MISMATCH')

    def test_a_bundle_with_no_sums_entry_is_refused(self):
        (self.serve / 'SHA256SUMS').write_text(f'{"0" * 64}  something_else\n')
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'lists no entry')

    def test_symlink_member_is_refused_before_anything_is_unpacked(self):
        self.publish(extra=[member('./deploy/evil', tarfile.SYMTYPE, '/etc/cron.d')])
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'symlink')

    def test_hardlink_member_is_refused(self):
        self.publish(extra=[member('./deploy/evil', tarfile.LNKTYPE, './deploy/marker.txt')])
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'link')

    def test_dotdot_member_is_refused(self):
        self.publish(extra=[member('./deploy/../../escape.txt', data=b'x')])
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, "'..'")
        self.assertFalse((self.root.parent / 'escape.txt').exists())

    def test_absolute_member_is_refused(self):
        self.publish(extra=[member('/tmp/vidra-escape.txt', data=b'x')])
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'not relative')

    def test_missing_manifest_is_refused(self):
        self.publish(skip_manifest=True)
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'vidra-bundle.manifest')

    def test_a_bundle_carrying_env_secrets_or_the_local_caddyfile_is_refused(self):
        for name in ('./env/production.env', './deploy/Caddyfile.local'):
            with self.subTest(name=name):
                self.publish(extra=[member(name, data=b'attacker=1\n')])
                before = self.snapshot()
                self.assertUntouched(self.run_pin(), before, 'must never ship')

    def test_a_release_with_no_bundle_asset_changes_nothing(self):
        (self.serve / ASSET).unlink()
        before = self.snapshot()
        self.assertUntouched(self.run_pin(), before, 'download')

    def test_unpaired_warning_speaks_of_the_image_pull_not_a_checkout_sync(self):
        # No record in the tree and none fetchable (the stub 404s it), so the
        # pairing is unknown and --component-tag is taken on trust. A bundle has
        # no nested checkouts: the "component checkout sync" the git-tree wording
        # names is a step its deploy never runs.
        (self.root / 'releases/v0.7.5.json').unlink()
        result = self.run_pin('--component-tag', 'user=v0.7.3', '--component-tag', 'search=v0.7.3')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        output = result.stdout + result.stderr
        self.assertIn('could not be determined', output)
        self.assertIn('the image pull', output)
        self.assertIn('manifest unknown', output)
        self.assertNotIn('checkout sync', output)
        self.assertNotIn('failed to checkout tag', output)

    def test_rerun_is_idempotent(self):
        self.assertEqual(self.run_pin().returncode, 0)
        first = (self.root / 'env/production.env').read_text()
        self.assertEqual(self.run_pin().returncode, 0)
        self.assertEqual((self.root / 'env/production.env').read_text(), first)


if __name__ == '__main__':
    unittest.main()
