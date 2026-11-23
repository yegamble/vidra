import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vidra_source_update", BASE / "deploy/source-update.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
HEX = "1" * 64
RECORD = json.loads((BASE / "releases/v0.7.26.json").read_text())


class SourceUpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = self.root / "production.env"
        self.env.write_text("SECRET=keep\n" + "".join(
            f"VIDRA_{r.upper()}_TAG=v0.7.25\n" for r in source.ROLES))

    def test_source_mode_activation_is_atomic_and_private(self):
        self.env.write_text(self.env.read_text() + "VIDRA_IMAGE_REGISTRY=mirror.old\n")
        ids = {r: HEX for r in source.ROLES}
        source.activate(self.env, ids)
        source.activate(self.env, ids)
        content = self.env.read_text()
        self.assertIn("SECRET=keep\n", content)
        self.assertNotIn("mirror.old", content)
        self.assertEqual(content.count("VIDRA_SOURCE_BUILD="), 1)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        for role in source.ROLES:
            self.assertEqual(source.value(self.env, f"VIDRA_SOURCE_{role.upper()}_ID"), HEX)

    def test_moved_source_tag_never_reaches_docker_build(self):
        with patch.object(source, "run") as run, patch.object(source, "output", return_value="a" * 40):
            with self.assertRaisesRegex(ValueError, "tag moved"):
                source.compile_release(self.root, RECORD)
        self.assertEqual([call.args[0] for call in run.call_args_list], ["git"])

    def test_dirty_or_newer_ledger_refuses_before_compiling(self):
        for ledger in ("193|f", "191|t", "", "191|f\n192|f"):
            with self.subTest(ledger=ledger), patch.object(source, "output", return_value=ledger):
                with self.assertRaisesRegex(ValueError, "ledger"):
                    source.live_schema(RECORD)
        with patch.object(source, "output", side_effect=["191|f", "21|f"]):
            source.live_schema(RECORD)

    def test_build_args_match_tagged_release(self):
        workflow = self.root / ".github/workflows/publish-container.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("  YTDLP_VERSION=2026.07.04\n  YTDLP_SHA256=" + HEX + "\n")
        with patch.object(source, "output", return_value="2026-11-23"):
            component = RECORD["components"]["core"]
            args = source.build_args("core", self.root, component)
            self.assertIn("YTDLP_SHA256=" + HEX, args)
            self.assertIn("COMMIT=" + component["commit"], args)
            self.assertEqual(source.build_args("user", self.root, component), [])
            workflow.write_text("  YTDLP_VERSION=latest\n")
            with self.assertRaisesRegex(ValueError, "publish recipe"):
                source.build_args("core", self.root, component)

    def test_source_verify_refuses_retagging_or_pulled_migrator(self):
        ids = {r: HEX for r in source.ROLES}
        source.activate(self.env, ids)
        labels = {"org.opencontainers.image.version": "v0.7.25", "io.vidra.meta-revision": "test"}
        image = {"Id": f"sha256:{HEX}", "Config": {"Labels": labels}}
        model = {"services": {name: {"image": source.ref_for(r, "v0.7.25", HEX), "pull_policy": "never"}
                              for name, r in source.SERVICES.items()}}
        with patch.object(source, "ROOT", self.root), patch.object(source, "meta_commit", return_value="test"), \
             patch.object(source, "config", return_value=model), patch.object(source, "output") as out:
            out.return_value = json.dumps([image])
            source.verify(self.env)
            model["services"]["search-migrate"]["pull_policy"] = "always"
            with self.assertRaisesRegex(ValueError, "search-migrate"):
                source.verify(self.env)
            image["Id"] = "sha256:" + "2" * 64
            out.return_value = json.dumps([image])
            with self.assertRaisesRegex(ValueError, "Wrong core"):
                source.verify(self.env)

    def test_gaps_in_the_service_model_cannot_verify_as_a_live_upgrade(self):
        with patch.object(source, "config", return_value={"services": {}}):
            with self.assertRaisesRegex(ValueError, "Missing source services"):
                source.verify(self.env, running=True)

    def exercise_apply(self, failed):
        (self.root / "deploy").mkdir()
        (self.root / "deploy/snapshots.py").touch()
        lock = types.SimpleNamespace(maintenance_lock=lambda root: nullcontext(3))
        events = []
        def command(*args, **kwargs):
            label = Path(args[1]).name
            events.append(label)
            if label == failed:
                raise subprocess.CalledProcessError(1, label)
            if label == "pin-release.sh":
                stage = Path(kwargs["env"]["ENV_FILE"])
                stage.write_text(stage.read_text().replace("v0.7.25", "v0.7.26"))
            return HEX
        with patch.dict(sys.modules, snapshot_lock=lock), patch.object(source, "ROOT", self.root), \
             patch.object(source.os, "geteuid", return_value=1234 if os.getuid() == 0 else os.getuid()), \
             patch("pathlib.Path.stat", autospec=True, side_effect=self.stat_override()), \
             patch.object(source, "compile_release", return_value={r: HEX for r in source.ROLES}), \
             patch.object(source, "output", side_effect=command), patch.object(source, "run", side_effect=command), \
             patch.object(source, "live_schema"), patch.object(source, "meta_commit", return_value=RECORD["meta_commit"]), \
             patch.object(source, "verify") as verify:
            if failed:
                with self.assertRaises(subprocess.CalledProcessError):
                    source.apply(self.env, RECORD, self.root)
                verify.assert_not_called()
            else:
                source.apply(self.env, RECORD, self.root)
                verify.assert_called_once_with(self.env, running=True)
        return events

    def stat_override(self):
        real_stat = Path.stat
        def stat(path, **kwargs):
            result = real_stat(path, **kwargs)
            if os.getuid() == 0:
                fields = list(result)
                fields[4] = 1234
                return os.stat_result(fields)
            return result
        return stat

    def test_failed_snapshot_never_changes_pins(self):
        before = self.env.read_bytes()
        self.assertEqual(self.exercise_apply("snapshots.py"), ["snapshots.py"])
        self.assertEqual(self.env.read_bytes(), before)

    def test_partial_pin_keeps_live_env(self):
        before = self.env.read_bytes()
        self.assertEqual(self.exercise_apply("pin-release.sh"), ["snapshots.py", "pin-release.sh"])
        self.assertEqual(self.env.read_bytes(), before)

    def test_activation_uses_full_snapshot_then_normal_deploy(self):
        self.assertEqual(self.exercise_apply(None), ["snapshots.py", "pin-release.sh", "deploy.sh"])
        self.assertEqual(source.value(self.env, "VIDRA_IMAGE_REGISTRY"), source.REGISTRY)


if __name__ == "__main__":
    unittest.main()
