"""Recovery mistakes must be caught before any writer or application is restarted."""
import contextlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import snapshots
from snapshot_lock import maintenance_lock
from snapshot_repo import Repository
from snapshot_stack import check_datastores, environment_digest


class SnapshotsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "env").mkdir()
        (self.root / "env/production.env").write_text("")
        self.folder = snapshots.private_dir(self.root)
        self.repo = Mock(root=self.root)
        self.doc = {"time": "2026-02-01", "release": "v0.7.26", "reason": "manual",
                    "storage": "local", "volumes": {}, "images": {}, "project": "lab",
                    "env_file": "env/production.env"}
        self.repo.read.return_value = self.doc
        self.args = SimpleNamespace(ident="a" * 64, apply=True, media_bucket=None, discard_current=False)
        self.live = {"project": "lab", "running": ["api"]}

    def test_preview_cannot_change_running_stack(self):
        self.args.apply = False
        with patch.object(snapshots, "current", side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
            snapshots.restore(self.repo, self.args)
        self.assertFalse((self.folder / snapshots.JOURNAL).exists())

    def test_current_snapshot_failure_restarts_original_before_any_replacement(self):
        with patch.object(snapshots, "current", return_value=(self.live, {})), \
                patch.object(snapshots, "prepare"), patch.object(snapshots, "stop"), \
                patch.object(snapshots, "capture", side_effect=ValueError("full")), \
                patch.object(snapshots, "recover") as recover, patch.object(snapshots, "restart_original") as restart:
            with self.assertRaisesRegex(ValueError, "full"):
                snapshots.restore(self.repo, self.args)
            restart.assert_called_once_with(self.root, ["api"])
            recover.assert_not_called()
        self.assertFalse((self.folder / snapshots.JOURNAL).exists())

    def test_retry_keeps_the_original_safety_point(self):
        with patch.object(snapshots, "current", return_value=(self.live, {})) as current, \
                patch.object(snapshots, "prepare"), patch.object(snapshots, "stop"), \
                patch.object(snapshots, "capture", return_value="b" * 64) as capture, \
                patch.object(snapshots, "recover", side_effect=[OSError("interrupted"), None]):
            with self.assertRaises(OSError):
                snapshots.restore(self.repo, self.args)
            receipt = json.loads((self.folder / snapshots.JOURNAL).read_text())
            self.assertEqual(receipt["safety"], "b" * 64)
            self.args.discard_current = True
            with self.assertRaisesRegex(ValueError, "in progress"):
                snapshots.restore(self.repo, self.args)
            self.args.discard_current = False
            snapshots.restore(self.repo, self.args)
            self.assertEqual((current.call_count, capture.call_count), (1, 1))
        self.assertFalse((self.folder / snapshots.JOURNAL).exists())

    def test_legacy_dumps_use_archived_tags(self):
        name = "20260201T120000Z"
        (self.folder / f"vidra-{name}.dump.gz").touch()
        (self.folder / "pre-deploy-2026-01-20T111111.dump.gz").touch()
        with tarfile.open(self.folder / f"vidra-config-{name}.tar.gz", "w:gz") as archive:
            source = b"VIDRA_CORE_TAG=v0.2.0\nJWT_SECRET=never-print"
            entry = tarfile.TarInfo("env/production.env")
            entry.size = len(source)
            archive.addfile(entry, io.BytesIO(source))
        with patch.dict(os.environ, {"BACKUP_DIR": str(self.folder)}):
            rows = snapshots.legacy(self.root)
        self.assertEqual({r["reason"]: r["release"] for r in rows}, {"nightly": "v0.2.0", "pre-deploy": "unknown"})
        self.assertNotIn("never-print", repr(rows))

    def test_lock_contention_and_inheritance(self):
        with maintenance_lock(self.root) as fd:
            with self.assertRaisesRegex(ValueError, "active"), maintenance_lock(self.root):
                pass
            with patch.dict(os.environ, {"VIDRA_MAINTENANCE_LOCK_FD": str(fd)}), maintenance_lock(self.root) as shared:
                self.assertEqual(shared, fd)

    def test_other_install_and_partial_stream_refused(self):
        repo = Repository(self.root)
        with patch.object(repo, "entries", return_value=[]), self.assertRaisesRegex(ValueError, "from this host"):
            repo.read("a" * 64)
        with patch.dict(os.environ, {"RESTIC_REPOSITORY": str(self.root / "backups/restic")}), self.assertRaisesRegex(ValueError, "outside"):
            repo.ready()

    def test_external_datastore_overrides_prevent_capture_and_restore(self):
        env = {"DATABASE_URL": "postgresql://u:p@postgres:5432/app", "REDIS_URL": "redis://redis:6379/0"}
        model = {"services": {"postgres": {"environment": {"POSTGRES_DB": "app"}}, "redis": {},
                              "api": {"environment": env}}}
        check_datastores(model)
        old = environment_digest(model)
        for endpoint in ("postgresql://u:p@elsewhere/app", "postgresql://u:p@postgres/wrong",
                         "postgresql://u:p@postgres/app?hostaddr=192.0.2.1"):
            with patch.dict(env, {"DATABASE_URL": endpoint}):
                with self.assertRaisesRegex(ValueError, "captured datastore"):
                    check_datastores(model)
                self.assertNotEqual(environment_digest(model), old)
        with patch.dict(env, {"REDIS_URL": "redis://remote:6379/0"}), self.assertRaises(ValueError):
            check_datastores(model)

    def test_explicit_replacement_recovers_without_healthy_current_pins(self):
        self.args.discard_current = True
        model = {"name": "lab", "services": {"api": {"environment": {}}}}
        with patch.object(snapshots, "config", return_value=model), patch.object(snapshots, "owned_containers", return_value=[]), \
                patch.object(snapshots, "current", side_effect=AssertionError), patch.object(snapshots, "prepare"), \
                patch.object(snapshots, "capture", side_effect=AssertionError), patch.object(snapshots, "recover") as recover:
            snapshots.restore(self.repo, self.args)
            recover.assert_called_once()

    def test_restore_bucket_replaces_every_local_assignment(self):
        path = self.root / "env/production.env"
        path.write_text("STORAGE_S3_BUCKET=old\nexport STORAGE_S3_BUCKET=older\nOTHER=a")
        snapshots.set_bucket(path, "restored-media")
        self.assertEqual(path.read_text(), "OTHER=a\nSTORAGE_S3_BUCKET=restored-media\n")
