"""Candidate manifests contain only the current generation's immutable native playback tree."""

import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / "deploy/ipfs-reference"
with patch.object(sys, "path", [str(DIRECTORY), *sys.path]):
    import prepare

VIDEO = "ea781054-a367-4be2-bd99-3071eb51d85a"
PREFIX = f"streaming-playlists/{VIDEO}/r12/"
MASTER = PREFIX + "master.m3u8"
TREE = {
    "master.m3u8": '#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-MEDIA:TYPE=AUDIO,URI="cmaf/audio.m3u8"\n'
                   '#EXT-X-STREAM-INF:BANDWIDTH=1,CODECS="avc1,mp4a"\ncmaf/video.m3u8\n',
    "cmaf/audio.m3u8": '#EXTM3U\n#EXT-X-MAP:URI="init-1.mp4"\n#EXTINF:2.0,\nchunk-1-00001.m4s\n#EXT-X-ENDLIST\n',
    "cmaf/video.m3u8": '#EXTM3U\n#EXT-X-MAP:URI="init-0.mp4"\n#EXTINF:2.0,\nchunk-0-00001.m4s\n#EXT-X-ENDLIST\n',
    "cmaf/init-0.mp4": "init zero", "cmaf/init-1.mp4": "init one",
    "cmaf/chunk-0-00001.m4s": "video fragment", "cmaf/chunk-1-00001.m4s": "audio fragment",
    "download/video.mp4": "supplementary download",
}


class Storage:
    def __init__(self):
        self.calls = []
        self.bodies = {PREFIX + k: v.encode() for k, v in TREE.items()}
        self.before = lambda key, version, span: None
        self.version = "v1"

    @contextlib.contextmanager
    def response(self, key, version=None, span=None):
        self.before(key, version, span)
        self.calls.append((key, version, span))
        data = self.bodies[key]
        reply = io.BytesIO(data[slice(span[0], span[1] + 1)] if span else b"")
        reply.status = 206 if span else 200
        headers = {"Content-Length": str(span[1] - span[0] + 1 if span else len(data)),
                   "x-amz-version-id": self.version}
        if span:
            headers["Content-Range"] = f"bytes {span[0]}-{span[1]}/{len(data)}"
        reply.getheader = headers.get
        with reply:
            yield reply


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.source = prepare.Source(self.storage)

    def manifest(self, lookup=lambda video: MASTER, max_bytes=1024**2):
        return json.loads(prepare.prepare(VIDEO, self.source, lookup, max_bytes, 30))

    def test_prepares_exact_versioned_native_tree_and_full_hashes(self):
        with patch.object(prepare, "CHUNK", 8):
            doc = self.manifest()
        keys = {item["key"] for item in doc["objects"]}
        self.assertEqual(keys, set(self.storage.bodies) - {PREFIX + "download/video.mp4"})
        for entry in doc["objects"]:
            key = entry["key"]
            self.assertEqual(entry["version_id"], "v1")
            self.assertEqual(entry["sha256"], hashlib.sha256(self.storage.bodies[key]).hexdigest())
            calls = [(v, span) for k, v, span in self.storage.calls if k == key]
            self.assertEqual((calls[0], calls[-1]), ((None, None), (None, None)))
            self.assertTrue(all(v == "v1" and span[1] - span[0] < 8 for v, span in calls[1:-1]))
        self.assertFalse(any("download" in k for k, _, _ in self.storage.calls))
        self.assertEqual(prepare.origin.check_manifest(doc, VIDEO, "live")[0], MASTER)

    def test_refuses_unversioned_objects_and_concurrent_rewrites(self):
        self.storage.version = "null"
        with self.assertRaises(ValueError):
            self.manifest()
        self.storage = Storage()
        self.source = prepare.Source(self.storage)

        def replaced(key, version, span):
            if any(oldkey == key and oldspan for oldkey, _, oldspan in self.storage.calls) and span is None:
                self.storage.version = "v2"

        self.storage.before = replaced
        with self.assertRaisesRegex(ValueError, "changed"):
            self.manifest()

    def test_stale_generation_and_byte_ceiling_do_not_produce_manifest(self):
        views = iter([MASTER, MASTER.replace("/r12/", "/r13/")])
        with self.assertRaisesRegex(ValueError, "generation"):
            self.manifest(lambda _: next(views))
        self.storage.calls.clear()
        with self.assertRaisesRegex(ValueError, "budget"):
            self.manifest(max_bytes=1)
        self.assertEqual(self.storage.calls, [(MASTER, None, None)])

    def test_refuses_altered_or_encrypted_playlists_before_reading_target(self):
        examples = [
            ("#EXT-X-STREAM-INF:BANDWIDTH=1\nhttps://other.example/v.m3u8", True),
            ("#EXT-X-STREAM-INF:BANDWIDTH=1\n../v.m3u8", True),
            ("#EXT-X-STREAM-INF:BANDWIDTH=1\nv.m3u8?secret=abc", True),
            ('#EXT-X-MEDIA:TYPE=AUDIO,URI=unquoted.m3u8', True),
            ('#EXT-X-MEDIA:TYPE=AUDIO,URI="a",URI="b"', True),
            ('#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key"', True),
            ('#EXT-X-KEY:METHOD=AES-128,URI="key"', False),
            ('#EXT-X-CONTENT-STEERING:SERVER-URI="https://other.example"', True),
            ('#EXT-X-DEFINE:NAME="x",VALUE="a"', False),
            ("#EXTINF:1,\nvideo-only.mp4\n#EXT-X-ENDLIST", False),
            ("#EXTINF:1,\nchunk-0-00001.m4s", False),
            ("#EXT-X-ENDLIST\n#EXTINF:1,\nchunk-0-00001.m4s", False),
            ("#EXTINF:1,\nseg_00001.ts\n#EXT-X-ENDLIST\nseg_00002.ts", False),
        ]
        for body, is_master in examples:
            with self.subTest(body=body), self.assertRaises(ValueError):
                prepare.references(MASTER, ("#EXTM3U\n" + body + "\n").encode(), is_master)

    def test_ts_and_native_iframe_paths(self):
        body = b"#EXTM3U\n#EXT-X-I-FRAMES-ONLY\n#EXTINF:4,\n#EXT-X-BYTERANGE:100@0\niframe.ts\n#EXT-X-ENDLIST\n"
        self.assertEqual(prepare.references(PREFIX + "240p/iframe.m3u8", body, False),
                         [PREFIX + "240p/iframe.ts"])
        body = b"#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:4,\nseg_00017.ts\n#EXT-X-ENDLIST\n"
        self.assertEqual(prepare.references(PREFIX + "240p/playlist.m3u8", body, False),
                         [PREFIX + "240p/seg_00017.ts"])

    def test_lookup_demands_exactly_one_native_master(self):
        with patch.object(prepare.origin, "read_view") as read:
            for result in ("", MASTER + "\n" + MASTER + "\n", PREFIX + "../master.m3u8\n", MASTER.upper() + "\n"):
                read.return_value = result
                with self.subTest(result=result), self.assertRaises(ValueError):
                    prepare.current_master(VIDEO)
            read.return_value = MASTER + "\n"
            self.assertEqual(prepare.current_master(VIDEO), MASTER)
            self.assertEqual(read.call_args.kwargs, dict(video=VIDEO))
        for bad in (VIDEO.upper(), "../" + VIDEO):
            with self.assertRaises(ValueError):
                prepare.prepare(bad, self.source, lambda _: MASTER, 10000, 30)
        self.assertEqual(self.storage.calls, [])


if __name__ == "__main__":
    unittest.main()
