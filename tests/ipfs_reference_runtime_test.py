import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "deploy/ipfs-reference/runtime/network-mode.py"
spec = importlib.util.spec_from_file_location("reference_network_mode", SOURCE)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def cid(value, codec):
    mh = b"\x12\x20" + hashlib.sha256(value).digest()
    return "b" + base64.b32encode(bytes((1, codec)) + mh).decode().rstrip("=").lower()


class SyntheticReferenceInventory(unittest.TestCase):
    def test_all_local_blocks_must_belong_to_the_approved_directory(self):
        video = "11860899-ee5e-41f0-b896-095bc740896d"
        root = cid(b"root", 0x70)
        raw = cid(b"media", 0x55)
        extra = cid(b"unrelated", 0x55)
        oid = "a" * 64
        ref = f"http://127.0.0.1:8785/v1/references/{video}/{oid}"

        def records(entries):
            return "\n".join(json.dumps(entry) for entry in entries).encode()

        responses = {
            "pin/ls?type=recursive": json.dumps({"Keys": {root: {"Type": "recursive"}}}).encode(),
            "pin/ls?type=direct": b"{}",
            "filestore/ls": records([{"Key": {"/": raw}, "Status": 0, "FilePath": ref}]),
            f"refs?arg={root}&recursive=true&unique=true": records([{"Ref": raw}]),
            "refs/local": records([{"Ref": root}, {"Ref": raw}]),
        }
        manifest = {"video_id": video, "master_key": f"operator-readiness/ipfs-reference/{video}/master.m3u8",
                    "objects": [{"id": oid}]}
        with tempfile.TemporaryDirectory() as directory:
            approvals = Path(directory) / "approvals"
            approvals.mkdir()
            path = approvals / (video + ".json")
            path.write_text(json.dumps(manifest))
            original = Path.stat

            def operator_owned(target, *args, **kwargs):
                result = original(target, *args, **kwargs)
                if target == path and kwargs.get("follow_symlinks", True):
                    return mock.Mock(st_uid=0, st_mode=0o100444)
                return result

            with mock.patch.object(runtime, "APP", Path(directory)), \
                 mock.patch.object(runtime, "rpc", side_effect=responses.__getitem__), \
                 mock.patch.object(Path, "stat", operator_owned):
                runtime.approved_root(video, root)
                responses["refs/local"] = records([{"Ref": root}, {"Ref": raw}, {"Ref": extra}])
                with self.assertRaisesRegex(ValueError, "unexpected blocks"):
                    runtime.approved_root(video, root)
                responses["refs/local"] = records([{"Ref": root}, {"Ref": raw}])
                responses["filestore/ls"] = records([{"Key": {"/": raw}, "Status": 0, "FilePath": ref},
                                                      {"Key": {"/": extra}, "Status": 0, "FilePath": ref + "1"}])
                with self.assertRaisesRegex(ValueError, "reference set"):
                    runtime.approved_root(video, root)

    def test_two_roots_must_use_their_own_exact_referenced_leaves(self):
        video = "11860899-ee5e-41f0-b896-095bc740896d"
        native = "61109038-d799-4247-b4ea-7f983e5eccbf"
        roots = [cid(f"root{i}".encode(), 0x70) for i in range(2)]
        leaves = [cid(f"leaf{i}".encode(), 0x55) for i in range(2)]
        urls = [f"http://127.0.0.1:{port}/v1/references/{vid}/" + str(i) * 64
                for i, (port, vid) in enumerate(((8785, video), (8786, native)))]
        def rows(items):
            return b"\n".join(json.dumps(item).encode() for item in items)
        entries = [{"FilePath": url, "Key": {"/": leaf}, "Status": 0, "ErrorMsg": ""}
                   for url, leaf in zip(urls, leaves)]
        replies = {
            "pin/ls?type=recursive": json.dumps({"Keys": dict.fromkeys(roots)}).encode(),
            "pin/ls?type=direct": b"{}",
            "filestore/ls": rows(entries),
            "refs/local": rows({"Ref": k} for k in roots + leaves),
        }
        for root, leaf in zip(roots, leaves):
            replies[f"refs?arg={root}&recursive=true&unique=true"] = rows([{"Ref": leaf}])
        selected = (native, "1", roots[1])
        with tempfile.TemporaryDirectory() as tmp:
            source, second = Path(tmp) / "synthetic", Path(tmp) / "native"
            for i, (location, vid, master) in enumerate((
                    (source, video, f"operator-readiness/ipfs-reference/{video}/master.m3u8"),
                    (second, native, f"streaming-playlists/{native}/r1/master.m3u8"))):
                (location / "approvals").mkdir(parents=True)
                (location / "approvals" / (vid + ".json")).write_text(json.dumps({
                    "video_id": vid, "master_key": master, "objects": [{"id": str(i) * 64}],
                }))
            # Fixture files belong to the test runner. Production checks UID zero.
            original = Path.stat
            def operator_owned(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                if path.suffix == ".json" and kwargs.get("follow_symlinks", True):
                    return mock.Mock(st_uid=0, st_mode=0o100440)
                return result
            with mock.patch.object(runtime, "APP", source), mock.patch.object(runtime, "NATIVE", second), \
                 mock.patch.object(Path, "stat", operator_owned), mock.patch.object(runtime, "rpc", side_effect=replies.__getitem__):
                runtime.approved_root(video, roots[0], selected)
                with self.assertRaisesRegex(ValueError, "master"):
                    runtime.approved_root(video, roots[0], (native, "2", roots[1]))
                with self.assertRaisesRegex(ValueError, "pins"):
                    runtime.approved_root(video, roots[0])
                swaps = [dict(entry, Key=entries[1 - i]["Key"]) for i, entry in enumerate(entries)]
                replies["filestore/ls"] = rows(swaps)
                with self.assertRaisesRegex(ValueError, "reference set"):
                    runtime.approved_root(video, roots[0], selected)
                replies["filestore/ls"] = rows(entries)
                extra = cid(b"unreferenced media", 0x55)
                replies[f"refs?arg={roots[1]}&recursive=true&unique=true"] = rows({"Ref": k} for k in [leaves[1], extra])
                with self.assertRaisesRegex(ValueError, "URLStore"):
                    runtime.approved_root(video, roots[0], selected)

    def test_block_inventory_accepts_equivalent_multihashes_and_rejects_rpc_errors(self):
        _, digest = runtime.decode_cid("QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn")
        equivalent = "b" + base64.b32encode(b"\x01\x55" + digest).decode().rstrip("=").lower()
        self.assertEqual(runtime.decode_cid(equivalent)[1], digest)
        with mock.patch.object(runtime, "rpc", return_value=b'{"Err":"missing block"}\n'):
            with self.assertRaisesRegex(ValueError, "inspect all"):
                runtime.block_inventory("refs/local")
