import importlib.util
import io
import json
from pathlib import Path
import re
import threading
import types
import unittest
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / "deploy" / "snapshot_ui.py"
spec = importlib.util.spec_from_file_location("snapshot_ui", MODULE)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
ID = "a" * 64


def sample(**updates):
    return dict({"kind": "install", "id": ID, "time": "2026-11-20T22:01:45.127+00:00",
                 "reason": "manual", "release": "v0.7.27", "storage": "s3", "bucket": "live-media",
                 "components": {"core": "v0.7.27", "user": "v0.7.25"}}, **updates)


class Wire:
    def __init__(self, data):
        self.data = data
        self.sent = io.BytesIO()

    def makefile(self, *_):
        return io.BytesIO(self.data)

    def sendall(self, data):
        self.sent.write(data)


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.called = []
        self.entered = threading.Event()
        self.finish = threading.Event()
        self.addCleanup(self.finish.set)
        self.entries = [ui.public_snapshot(sample())]
        self.console = ui.Console(lambda: self.entries, self.called.append, self.operate)
        self.server = types.SimpleNamespace(server_port=8384, console=self.console, secret="only-local")
        self.selected = {"id": ID, "preserve": True, "bucket": "restored-media"}

    def operate(self, args, note):
        self.called.append(args)
        note("Capturing")
        self.entered.set()
        self.finish.wait(5)
        return 0

    def request(self, method="GET", path="/api/snapshots", headers=(), payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        header_list = list(headers)
        if body:
            header_list += ["Content-Type: application/json", "Content-Length: " + str(len(body))]
        wire = Wire(("\r\n".join([f"{method} {path} HTTP/1.1", *header_list]) + "\r\n\r\n").encode() + body)
        ui.Handler(wire, ("127.0.0.1", 123), self.server)
        head, _, data = wire.sent.getvalue().partition(b"\r\n\r\n")
        return int(head.split(b" ")[1]), head, data

    def test_host_and_key_required_even_for_snapshot_list(self):
        for headers in (
            ["Host: localhost:8384"],
            ["Host: example.org:8384", "X-Vidra-Key: only-local"],
            ["Host: localhost:8384", "Host: example.org", "X-Vidra-Key: only-local"],
            ["Host: localhost:8384", "X-Vidra-Key: only-local", "Origin: http://example.org:8384"],
            ["Host: localhost:8384", "X-Vidra-Key: only-local", "Origin: http://localhost:8500"],
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 403)
        good = ["Host: localhost:8384", "X-Vidra-Key: only-local"]
        self.assertEqual(self.request(headers=good)[0], 200)
        self.assertEqual(self.request(path="http://localhost:8384/api/snapshots", headers=good)[0], 403)
        self.assertEqual(self.request(method="POST", path="/api/create", headers=good)[0], 400)
        self.assertEqual(self.called, [])

    def test_static_shell_has_no_secrets_and_refuses_unlisted_files(self):
        status, headers, body = self.request(path="/", headers=["Host: 127.0.0.1:8384"])
        self.assertEqual(status, 200)
        self.assertIn(b"frame-ancestors 'none'", headers)
        self.assertIn(b"no-store", headers)
        self.assertNotIn(b"only-local", body)
        for path in ("/../env/production.env", "/api/restore?key=only-local"):
            self.assertNotEqual(self.request(path=path, headers=["Host: 127.0.0.1:8384"])[0], 200)

    def test_preview_binds_id_preservation_destination_release_and_date(self):
        plan = self.console.plan(self.selected)
        self.assertNotIn("--apply", self.called[0])
        self.assertEqual(plan["confirmation"], "v0.7.27 2026-11-20")
        confirm = {**self.selected, **plan}
        for edit in ({"preserve": 1}, {"preserve": False}, {"id": "b" * 64},
                     {"bucket": "someone-else"}, {"nonce": "stale"}, {"confirmation": "CONFIRM"}):
            with self.assertRaises(ui.Problem):
                self.console.start("restore", {**confirm, **edit})
        self.console.start("restore", confirm)
        self.assertTrue(self.entered.wait(2))
        self.assertEqual(self.called[-1], ["restore", ID, "--media-bucket", "restored-media", "--apply"])
        with self.assertRaises(ui.Problem):
            self.console.start("create", {})
        self.assertEqual(self.console.status()["events"][-1], "Capturing")

    def test_discard_requires_explicit_new_preview_and_no_shell_fragments(self):
        for bucket in ("live-media", "A", "bad\n--apply", "--profile"):
            with self.assertRaises(ui.Problem):
                self.console.plan({**self.selected, "bucket": bucket})
        discard = {**self.selected, "preserve": False}
        plan = self.console.plan(discard)
        self.console.start("restore", {**discard, **plan})
        self.assertTrue(self.entered.wait(2))
        self.assertIn("--discard-current", self.called[-1])

    def test_unknown_ids_and_database_archives_cannot_be_restored(self):
        row = ui.public_snapshot(sample(kind="database", id="vidra-20261123T010000Z.dump.gz",
                                        release="unknown", storage="database only", bucket=""))
        self.assertEqual(row["release"], "unrecorded")
        self.entries.append(row)
        for key in (row["id"], "a", "b" * 64, "/etc/passwd"):
            with self.assertRaises(ui.Problem):
                self.console.plan({**self.selected, "id": key})
        self.assertEqual(self.called, [])

    def test_retirement_requires_its_own_preview_and_exact_confirmation(self):
        restored = self.console.plan(self.selected)
        with self.assertRaises(ui.Problem):
            self.console.start("retire", {**self.selected, **restored})
        plan = self.console.plan({"id": ID}, "retire")
        self.assertEqual(self.called[-1], ["retire", ID])
        self.assertEqual(plan["confirmation"], "RETIRE " + ID[:12])
        confirmed = {"id": ID, **plan}
        with self.assertRaises(ui.Problem):
            self.console.start("restore", confirmed)
        with self.assertRaises(ui.Problem):
            self.console.start("retire", {**confirmed, "id": "f" * 64})
        self.console.start("retire", confirmed)
        self.assertTrue(self.entered.wait(2))
        self.assertEqual(self.called[-1], ["retire", ID, "--apply"])

    def test_private_fields_never_enter_catalog(self):
        row = ui.public_snapshot(sample(secret="a-secret", components={"core": "oops\na-secret", "secret": "x"}))
        self.assertNotIn("a-secret", json.dumps(row))
        self.assertEqual(row["components"], {})
        html = (ui.HERE / "snapshot-ui.html").read_text()
        script = (ui.HERE / "snapshot-ui.js").read_text()
        for ident in re.findall(r'byId\("([\w-]+)"\)', script):
            self.assertIn('id="' + ident + '"', html)
        self.assertNotIn("innerHTML", script)

    def test_previews_show_only_numeric_counts_from_host_output(self):
        with mock.patch.object(ui.subprocess, "check_output", return_value=b"secret\nRestore 12 volumes and 5 exact service images.\n"):
            self.assertEqual(ui.run_check(["restore", ID]), "This recovery restores 12 volumes and 5 service images.")
        with mock.patch.object(ui.subprocess, "check_output", return_value=b"private metadata  6 archive parts\n"):
            self.assertEqual(ui.run_check(["retire", ID]), "This recovery point includes 6 archive parts.")

    def test_staging_estimate_and_schema_ledgers_are_optional_numeric_fields(self):
        row = ui.public_snapshot(sample(staging_bytes=123456, schemas={"core": 191, "search": 21, "private": "hidden"}))
        self.assertEqual(row["staging_bytes"], 123456)
        self.assertEqual(row["schemas"], {"core": 191, "search": 21})
        old = ui.public_snapshot(sample(staging_bytes="unknown", schemas={"core": True}))
        self.assertNotIn("staging_bytes", old)
        self.assertEqual(old["schemas"], {})


if __name__ == "__main__":
    unittest.main()
