import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REFERENCE = Path(__file__).resolve().parents[1] / "deploy/ipfs-reference"
with mock.patch.object(sys, "path", [str(REFERENCE), *sys.path]):
    spec = importlib.util.spec_from_file_location("native_reference", REFERENCE / "runtime/native/run-native.py")
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)

VIDEO = "10000000-0000-4000-8000-000000000001"
OTHER = "20000000-0000-4000-8000-000000000001"
MASTER = f"streaming-playlists/{VIDEO}/r2/master.m3u8"


class NativeOriginTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        tmp = stack.enter_context(tempfile.TemporaryDirectory())
        self.directory = Path(tmp)
        self.approvals = self.directory / "approvals"
        self.approvals.mkdir()
        for name, path in (("ROOT", self.directory), ("APPROVALS", self.approvals)):
            stack.enter_context(mock.patch.object(native, name, path))
        stack.enter_context(mock.patch.dict(native.os.environ))
        stack.enter_context(mock.patch.object(native.socket, "gethostbyname_ex", return_value=("", [], ["172.18.0.2"])))
        self.storage = stack.enter_context(mock.patch.object(native.origin, "S3"))
        self.service = stack.enter_context(mock.patch.object(native.origin, "Server"))
        self.live = stack.enter_context(mock.patch.object(native.origin, "live_approval", return_value=True))
        self.scope = self.directory / "scope.json"
        self.scope.write_text("{}")

    def run_mode(self, mode):
        with mock.patch.object(sys, "argv", ["native", mode]):
            native.main()

    def select(self):
        self.scope.write_text(json.dumps(dict(video_id=VIDEO, generation=2, endpoint="https://fixture.invalid",
                                              bucket="fixture", region="test")))
        for f in ("b2.key-id", "b2.read-key"):
            (self.directory / f).write_text("fixture-only")

    def test_dormant_state_reads_no_credentials_and_refuses_every_reference(self):
        self.run_mode("serve")
        allowed = self.service.call_args.args[2]
        self.assertFalse(allowed(VIDEO, MASTER))
        self.storage.assert_not_called()
        self.live.assert_not_called()
        with self.assertRaisesRegex(SystemExit, "No selected"):
            self.run_mode("prepare")

    def test_selected_video_and_generation_and_live_lookup_all_required(self):
        self.select()
        self.run_mode("serve")
        allowed = self.service.call_args.args[2]
        self.assertFalse(allowed(OTHER, MASTER))
        self.assertFalse(allowed(VIDEO, MASTER.replace("/r2/", "/r1/")))
        self.live.assert_not_called()
        self.assertTrue(allowed(VIDEO, MASTER))
        self.live.return_value = False
        self.assertFalse(allowed(VIDEO, MASTER))

    def test_preparation_preserves_reviewed_manifest_and_rechecks_selected_generation(self):
        self.select()
        encoded = json.dumps({"video_id": VIDEO, "master_key": MASTER}) + "\n"
        def prepare(video, source, lookup, max_bytes, max_seconds):
            self.assertEqual(lookup(video), MASTER)
            return encoded
        out = io.StringIO()
        with mock.patch.object(native.prepare, "prepare", side_effect=prepare), \
             mock.patch.object(native.prepare, "current_master", return_value=MASTER) as current, \
             contextlib.redirect_stdout(out):
            self.run_mode("prepare")
            self.assertEqual(out.getvalue(), encoded)
            current.return_value = MASTER.replace("/r2/", "/r3/")
            with self.assertRaises(native.prepare.CandidateError):
                self.run_mode("prepare")
            self.assertEqual(out.getvalue(), encoded)
