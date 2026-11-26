"""Private origin wire behavior and manifest/storage boundaries, with synthetic media."""

import hashlib
import http.client
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch


PATH = Path(__file__).resolve().parents[1] / "deploy/ipfs-reference/origin.py"
SPEC = importlib.util.spec_from_file_location("reference_origin", PATH)
origin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(origin)
VIDEO = "ea781054-a367-4be2-bd99-3071eb51d85a"
SYNTHETIC = "operator-readiness/ipfs-reference/" + VIDEO + "/master.m3u8"
LIVE = "streaming-playlists/" + VIDEO + "/r2/master.m3u8"
PAYLOAD = b"#EXTM3U\n"


def make_obj(key, master, data=PAYLOAD, version="immutable+/=1"):
    obj = dict(key=key, version_id=version, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    obj["id"] = origin.object_id(VIDEO, master, obj)
    return obj


def make_manifest(master):
    return dict(schema=1, video_id=VIDEO, master_key=master, objects=[make_obj(master, master)])


class Store:
    def __init__(self):
        self.calls = []
        self.after_read = lambda: None

    def read(self, obj, start, end, head=False):
        self.calls.append((obj["version_id"], start, end, head))
        self.after_read()
        return b"" if head else PAYLOAD[start:end + 1]


class OriginHTTPTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / (VIDEO + ".json")
        self.doc = make_manifest(SYNTHETIC)
        self.url = "/v1/references/" + VIDEO + "/" + self.doc["objects"][0]["id"]
        self.save()
        self.manifests = origin.Manifests(directory.name, "synthetic")
        self.addCleanup(self.manifests.close)
        self.store = Store()
        self.server = origin.Server(("127.0.0.1", 0), self.manifests, lambda *_: True,
                                    self.store, 2, 1024**2, 5)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def save(self):
        temp = self.file.with_suffix(".new")
        temp.write_text(json.dumps(self.doc))
        temp.chmod(0o640)
        temp.replace(self.file)

    def request(self, method="GET", url=None, ranges=()):
        with closing(http.client.HTTPConnection(*self.server.server_address, timeout=3)) as conn:
            conn.putrequest(method, url or self.url)
            for value in ranges:
                conn.putheader("Range", value)
            conn.endheaders()
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_whole_small_and_bounded_get_and_head(self):
        for method in ("GET", "HEAD"):
            for value, status, start, end in [(None, 200, 0, 7), ("bytes=1-4", 206, 1, 4),
                                               ("bytes=6-", 206, 6, 7)]:
                with self.subTest(method=method, value=value):
                    result, headers, data = self.request(method, ranges=[value] if value else [])
                    self.assertEqual(result, status)
                    self.assertEqual(headers.get("Content-Range"), f"bytes {start}-{end}/8" if value else None)
                    self.assertEqual(headers["Content-Length"], str(end - start + 1))
                    self.assertEqual(data, b"" if method == "HEAD" else PAYLOAD[start:end + 1])
                    self.assertEqual(self.store.calls[-1], ("immutable+/=1", start, end, method == "HEAD"))
                    self.assertIn("no-store", headers["Cache-Control"])

    def test_invalid_ranges_do_not_open_s3(self):
        for ranges in (["bytes=8-9"], ["bytes=3-2"], ["bytes=1-2,4-5"], ["bytes=-2"],
                       ["bytes=1-2", "bytes=1-2"]):
            with self.subTest(ranges=ranges):
                status, headers, body = self.request(ranges=ranges)
                self.assertEqual((status, headers["Content-Range"], body), (416, "bytes */8", b""))
        self.assertEqual(self.store.calls, [])

    def test_refuses_unlisted_ids_and_user_supplied_targets(self):
        for path in (self.url + "?versionId=mine", self.url + "/", "/" + self.url,
                     self.url.replace(VIDEO, VIDEO.upper()), self.url[:-64] + "1" * 64,
                     "https://example.test" + self.url):
            self.assertEqual(self.request(url=path)[0], 404)
        self.assertEqual(self.request("POST")[0], 501)
        self.assertEqual(self.store.calls, [])

    def test_unlink_and_permission_changes_take_effect_immediately(self):
        self.assertEqual(self.request()[0], 200)
        self.store.after_read = self.file.unlink
        status, _, body = self.request()
        self.assertEqual((status, body), (404, b""))
        self.assertEqual(self.request()[0], 404)
        self.assertEqual(len(self.store.calls), 2)
        self.save()
        self.file.chmod(0o666)
        self.assertEqual(self.request()[0], 404)
        self.file.unlink()
        self.file.symlink_to(self.file.with_suffix(".target"))
        self.file.resolve().write_text(json.dumps(self.doc))
        self.assertEqual(self.request()[0], 404)
        self.assertEqual(len(self.store.calls), 2)

    def test_visibility_is_rechecked_after_s3_and_outages_fail_closed(self):
        self.server.approve = MagicMock(side_effect=[True, False])
        status, _, data = self.request()
        self.assertEqual((status, data), (404, b""))
        self.assertEqual(self.server.approve.call_count, 2)
        self.server.approve.side_effect = RuntimeError("service unavailable")
        self.assertEqual(self.request()[0], 503)
        self.assertEqual(len(self.store.calls), 1)

    def test_connection_limit_rejects_excess_before_storage(self):
        entering = threading.Barrier(3)
        release = threading.Event()

        def hold_read():
            entering.wait(2)
            release.wait(2)

        self.store.after_read = hold_read
        with ThreadPoolExecutor(max_workers=2) as pool:
            clients = [pool.submit(self.request) for _ in range(2)]
            try:
                entering.wait(2)
                with self.assertRaises((http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError)):
                    self.request()
            finally:
                release.set()
            self.assertEqual([client.result()[0] for client in clients], [200, 200])
        self.assertEqual(len(self.store.calls), 2)

    def test_throttled_payload_is_not_read(self):
        self.server.budget = origin.ByteBudget(1)
        result, headers, data = self.request()
        self.assertEqual((result, data), (429, b""))
        self.assertIn("Retry-After", headers)
        self.assertEqual(self.store.calls, [])


class ContractTest(unittest.TestCase):
    def test_generation_and_immutable_binding(self):
        for mode, master in (("synthetic", SYNTHETIC), ("live", LIVE)):
            doc = make_manifest(master)
            obj = doc["objects"][0]
            self.assertEqual(origin.check_manifest(doc, VIDEO, mode)[1][obj["id"]], obj)
            for field, value in (("size", 20), ("version_id", "changed"), ("sha256", "0" * 64),
                                 ("id", "a" * 64), ("key", "master.m3u8")):
                changed = dict(obj, **{field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    origin.check_manifest(dict(doc, objects=[changed]), VIDEO, mode)

    def test_refuses_outside_generation_even_with_correct_object_id(self):
        for mode, master in (("live", SYNTHETIC), ("synthetic", LIVE),
                             ("synthetic", SYNTHETIC.replace("/master.", "/nested/master.")),
                             ("live", LIVE.replace("/r2/", "/r0/")),
                             ("live", LIVE.replace("/r2/", "/r2/child/"))):
            with self.subTest(master=master), self.assertRaises(ValueError):
                origin.check_manifest(make_manifest(master), VIDEO, mode)
        for key in (LIVE.replace("/r2/", "/r3/"), LIVE + "/../x", LIVE + "/%2e%2e",
                    LIVE + "/sub?x", LIVE + "/.hidden", LIVE + "/bad\\file"):
            doc = make_manifest(LIVE)
            doc["objects"].append(make_obj(key, LIVE))
            with self.subTest(key=key), self.assertRaises(ValueError):
                origin.check_manifest(doc, VIDEO, "live")
        for version in ("", "null", "Null", "x\nx"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                origin.check_manifest(dict(make_manifest(LIVE), objects=[make_obj(LIVE, LIVE, version=version)]),
                                      VIDEO, "live")

    def test_requires_one_qualified_master_version(self):
        doc = make_manifest(LIVE)
        child = make_obj(LIVE.replace("master.m3u8", "720p/0001.m4s"), LIVE)
        doc["objects"].append(child)
        self.assertEqual(len(origin.check_manifest(doc, VIDEO, "live")[1]), 2)
        for objects in ([], [child], [*doc["objects"], child]):
            with self.subTest(count=len(objects)), self.assertRaises(ValueError):
                origin.check_manifest(dict(doc, objects=objects), VIDEO, "live")

    def test_large_payload_requires_bounded_range_except_head(self):
        size = 2 * origin.BLOCK
        self.assertEqual(origin.bounds(None, size, True), (200, 0, size - 1))
        self.assertEqual(origin.bounds(["bytes=262144-"], size, False), (206, 262144, size - 1))
        for headers in (None, ["bytes=0-"], ["bytes=0-262144"]):
            with self.subTest(headers=headers), self.assertRaises(origin.Refusal):
                origin.bounds(headers, size, False)

    def test_rejects_public_wildcard_and_untrusted_approval_directory(self):
        for bind in ("0.0.0.0", "8.8.8.8", "169.254.2.3", "::"):
            with self.subTest(bind=bind), self.assertRaises(ValueError):
                origin.Server((bind, 0), None, None, None, 2, origin.BLOCK, 3)
        with tempfile.TemporaryDirectory() as path:
            os.chmod(path, 0o777)
            with self.assertRaises(ValueError):
                origin.Manifests(path, "synthetic")

    def test_live_approval_uses_fixed_readonly_query_and_exact_pair(self):
        with patch.object(origin.subprocess, "run") as run:
            run.return_value.stdout = ""
            self.assertFalse(origin.live_approval(VIDEO, LIVE))
            run.return_value.stdout = "1\n"
            self.assertTrue(origin.live_approval(VIDEO, LIVE))
        options = run.call_args.kwargs
        self.assertIn("public.ipfs_public_reference_videos", options["input"])
        self.assertNotIn(VIDEO, options["input"])
        self.assertIn("default_transaction_read_only=on", options["env"]["PGOPTIONS"])
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", options["env"])
        self.assertIn("master=" + LIVE, run.call_args.args[0])
        self.assertEqual(options["timeout"], 4)


class S3BoundaryTest(unittest.TestCase):
    def setUp(self):
        self.obj = make_obj(LIVE, LIVE)

    def response(self, data=PAYLOAD, status=206, **changed):
        hdrs = {"x-amz-version-id": self.obj["version_id"], "Content-Length": "8", "Content-Range": "bytes 0-7/8"}
        hdrs.update(changed)
        reply = io.BytesIO(data)
        reply.status = status
        reply.getheader = hdrs.get
        return reply

    def test_connector_sends_only_version_qualified_request_to_fixed_endpoint(self):
        storage = origin.S3.__new__(origin.S3)
        storage.host, storage.port = "objects.example.test", 443
        storage.base, storage.bucket = "https://objects.example.test", "private-media"
        storage.timeout, storage.signer, storage.request = 10, MagicMock(), MagicMock()
        storage.request.return_value.headers = {"Authorization": "synthetic-signature"}
        with patch.object(origin.http.client, "HTTPSConnection") as factory:
            conn = factory.return_value
            conn.getresponse.return_value.__enter__.return_value = self.response()
            self.assertEqual(storage.read(self.obj, 0, 7), PAYLOAD)
        factory.assert_called_once_with("objects.example.test", 443, timeout=10)
        path = "/private-media/" + LIVE + "?versionId=immutable%2B%2F%3D1"
        storage.request.assert_called_once_with(method="GET", url=storage.base + path, headers={"Range": "bytes=0-7"})
        storage.signer.add_auth.assert_called_once_with(storage.request.return_value)
        conn.request.assert_called_once_with("GET", path, headers={"Authorization": "synthetic-signature"})

    def test_exact_headers_and_complete_small_hash(self):
        self.assertEqual(origin.S3.checked_body(self.response(), self.obj, 0, 7, False), PAYLOAD)
        self.assertEqual(origin.S3.checked_body(self.response(status=200), self.obj, 1, 3, True), b"")
        for reply in (self.response(status=302), self.response(status=200), self.response(data=b"x"),
                      self.response(data=b"aaaaaaaa"), self.response(**{"x-amz-version-id": "another"}),
                      self.response(**{"Content-Length": "9"}), self.response(**{"Content-Range": "bytes 1-7/8"}),
                      self.response(**{"Transfer-Encoding": "chunked"})):
            with self.subTest(code=reply.status), self.assertRaises(origin.Refusal):
                origin.S3.checked_body(reply, self.obj, 0, 7, False)


if __name__ == "__main__":
    unittest.main()
