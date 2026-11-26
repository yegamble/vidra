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
            "filestore/ls": records([{"FilePath": ref}]),
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
                responses["filestore/ls"] = records([{"FilePath": ref}, {"FilePath": ref + "1"}])
                with self.assertRaisesRegex(ValueError, "reference set"):
                    runtime.approved_root(video, root)

    def test_block_inventory_accepts_equivalent_multihashes_and_rejects_rpc_errors(self):
        digest = runtime.multihash("QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn")
        equivalent = "b" + base64.b32encode(b"\x01\x55" + digest).decode().rstrip("=").lower()
        self.assertEqual(runtime.multihash(equivalent), digest)
        with mock.patch.object(runtime, "rpc", return_value=b'{"Err":"missing block"}\n'):
            with self.assertRaisesRegex(ValueError, "inspect all"):
                runtime.block_inventory("refs/local")
