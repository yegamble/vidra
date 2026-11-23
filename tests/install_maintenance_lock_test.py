"""Direct scripts, Go/Python parents and nested deploys share an install's lease."""
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
from snapshot_lock import maintenance_lock


class InstallMaintenanceLockTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        base = Path(work.name)
        self.root = base / "install"
        scripts = self.root / "deploy"
        scripts.mkdir(parents=True)
        for filename in ("lib.sh", "snapshot_lock.py", "checkout-hygiene.py", "release-mapping.py",
                         "backup.sh", "deploy.sh", "pin-release.sh", "restore.sh", "rollback.sh"):
            shutil.copy2(DEPLOY / filename, scripts / filename)
        (self.root / "vidra-bundle.manifest").write_text("tag=v0.7.26\n")
        envfile = self.root / "env/production.env"
        envfile.parent.mkdir()
        envfile.write_text("VIDRA_TLS_MODE=external\n")
        (self.root / "fixture.dump").touch()
        fixture_bin = base / "bin"
        fixture_bin.mkdir()
        # The pin script refuses root; an isolated CI runner may itself be root.
        for name, source in {
            "id": 'test "$1" != -u || { echo 1000; exit; }; exec /usr/bin/id "$@"',
            "docker": 'test "$*" = "compose version --short" || exit 81; echo 2.20.0',
        }.items():
            tool = fixture_bin / name
            tool.write_text("#!/bin/sh\n" + source + "\n")
            tool.chmod(0o755)
        self.env = {**os.environ, "PATH": str(fixture_bin) + ":" + os.environ["PATH"],
                    "ENV_FILE": "env/production.env", "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("VIDRA_MAINTENANCE_LOCK_FD", None)
        self.shell = 'die() { echo "$*" >&2; exit 1; }; . deploy/lib.sh; vidra_maintenance_lock "$PWD";'

    def call(self, args, *, fd=None):
        env = dict(self.env)
        if fd is not None:
            env["VIDRA_MAINTENANCE_LOCK_FD"] = str(fd)
        return subprocess.run(args, cwd=self.root, env=env, capture_output=True, text=True,
                              timeout=15, pass_fds=(fd,) if fd is not None else ())

    def test_all_direct_commands_refuse_an_active_snapshot(self):
        with maintenance_lock(self.root):
            for script, args in (("backup.sh", []), ("deploy.sh", []), ("pin-release.sh", ["v0.7.26"]),
                                 ("restore.sh", ["--yes", "fixture.dump"]), ("rollback.sh", ["v0.7.26"])):
                # Restore validates Compose >=2.24 before consulting the env file.
                docker = Path(self.env["PATH"].split(os.pathsep)[0]) / "docker"
                docker.write_text('#!/bin/sh\ntest "$*" = "compose version --short" || exit 81; echo 2.24.0\n')
                with self.subTest(script=script):
                    r = self.call(["bash", "deploy/" + script, *args])
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("active on this install", r.stderr)
            self.assertEqual(self.call(["bash", "deploy/restore.sh", "--help"]).returncode, 0)

    def test_shell_holds_lock_and_lends_it_to_nested_deploy(self):
        # A real preflight refusal proves that a nested deploy inherited its
        # parent's open file description, with no second lock acquisition.
        body = self.shell + 'echo locked; read -r proceed; exec bash deploy/deploy.sh'
        with subprocess.Popen(["bash", "-ec", body], cwd=self.root, env=self.env, text=True,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
            try:
                with selectors.DefaultSelector() as poll:
                    poll.register(p.stdout, selectors.EVENT_READ)
                    self.assertTrue(poll.select(10), "shell failed to report its lock")
                self.assertEqual(p.stdout.readline().strip(), "locked")
                with self.assertRaisesRegex(ValueError, "active on this install"), maintenance_lock(self.root):
                    pass
                sibling = self.root.parent / "other"
                sibling.mkdir()
                with maintenance_lock(sibling):
                    pass
                out, err = p.communicate("continue\n", timeout=15)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("too old", out + err)
                self.assertNotIn("lock unavailable", err)
            finally:
                if p.poll() is None:
                    p.kill()
        with maintenance_lock(self.root):
            pass

    def test_borrowed_fd_survives_shell_and_rejects_wrong_or_closed_descriptor(self):
        with maintenance_lock(self.root) as fd:
            r = self.call(["bash", "-ec", self.shell + 'exec bash deploy/deploy.sh'], fd=fd)
            self.assertIn("too old", r.stdout + r.stderr)
            self.assertNotIn("lock unavailable", r.stderr)
            with open(self.root / "fixture.dump", "rb") as other:
                r = self.call(["bash", "-ec", self.shell], fd=other.fileno())
                self.assertIn("another install", r.stderr)
        r = self.call(["bash", "-ec", "export VIDRA_MAINTENANCE_LOCK_FD=3; exec 3>&-; " + self.shell])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("file descriptor", r.stderr.lower())

    def test_partial_new_install_refuses_a_missing_helper(self):
        (self.root / "deploy/snapshot_lock.py").unlink()
        self.assertEqual(self.call(["bash", "-ec", self.shell]).returncode, 0)
        (self.root / "deploy/snapshots.py").touch()
        r = self.call(["bash", "-ec", self.shell])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing", r.stderr)
