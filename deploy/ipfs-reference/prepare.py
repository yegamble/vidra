#!/usr/bin/env python3
"""Prepare one reviewable manifest for native, publicly eligible Vidra VOD."""

import argparse
import collections
import hashlib
import http.client
import json
import posixpath
import re
import subprocess
import sys
import time

import origin


CHUNK = 4 * 1024**2
PLAYLIST_LIMIT = 2 * 1024**2
ATTR = re.compile(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^",\s]+)(,|$)')
SEGMENT = re.compile(r"(?:seg_[0-9]+\.ts|chunk-[0-9]+-[0-9]+\.m4s)")
IFRAME = re.compile(r"(?:iframe\.ts|iframe-[0-9]+\.mp4)")
INIT = re.compile(r"init-[0-9]+\.mp4")


class CandidateError(ValueError):
    """A non-sensitive reason an operator can use to correct the candidate."""


def attrs(value):
    parsed = {}
    pos = 0
    while pos < len(value):
        m = ATTR.match(value, pos)
        if not m or m[1] in parsed or (m[3] and m.end() == len(value)):
            raise CandidateError("malformed playlist attributes")
        parsed[m[1]] = m[2]
        pos = m.end()
    return parsed


def href(attributes):
    value = attributes.get("URI", "")
    if len(value) < 3 or not (value.startswith('"') and value.endswith('"')):
        raise CandidateError("expected quoted playlist URI")
    return value[1:-1]


def playback_key(parent, ref, kind):
    if not origin.clean_key(ref):
        raise CandidateError("expected a relative native playback path")
    name = posixpath.basename(ref)
    if kind == "playlist":
        allowed = name.endswith(".m3u8")
    elif kind == "init":
        allowed = INIT.fullmatch(name) or IFRAME.fullmatch(name)
    else:
        allowed = (IFRAME if kind == "iframe" else SEGMENT).fullmatch(name)
    key = posixpath.join(posixpath.dirname(parent), ref)
    if not allowed or not origin.clean_key(key):
        raise CandidateError("object is outside the supported native playback layout")
    return key


def references(key, raw, master):
    lines = raw.decode("utf-8", errors="strict").replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "#EXTM3U":
        raise CandidateError("invalid HLS header")
    refs = []
    pending = None
    segments = 0
    variants = 0
    ended = False
    iframe = False
    for line in lines[1:]:
        if not line:
            continue
        if ended or line != line.strip() or any(ord(c) < 32 or ord(c) == 127 for c in line):
            raise CandidateError("malformed HLS line")
        if not line.startswith("#"):
            if pending is None:
                raise CandidateError("unexpected HLS URI")
            refs.append(playback_key(key, line, pending))
            pending = None
            continue
        if not line.startswith("#EXT"):
            continue
        tag, _, value = line.partition(":")
        if tag in ("#EXT-X-VERSION", "#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE"):
            if not value.isascii() or not value.isdigit():
                raise CandidateError("malformed playlist number")
        elif tag == "#EXT-X-INDEPENDENT-SEGMENTS" and not value:
            pass
        elif master and tag == "#EXT-X-STREAM-INF" and pending is None:
            fields = attrs(value)
            if "URI" in fields or not re.fullmatch("[1-9][0-9]*", fields.get("BANDWIDTH", "")):
                raise CandidateError("invalid variant")
            variants += 1
            pending = "playlist"
        elif master and tag in ("#EXT-X-MEDIA", "#EXT-X-I-FRAME-STREAM-INF") and pending is None:
            fields = attrs(value)
            if tag == "#EXT-X-MEDIA" and fields.get("TYPE") != "AUDIO":
                raise CandidateError("unsupported native media group")
            refs.append(playback_key(key, href(fields), "playlist"))
        elif not master and tag == "#EXT-X-MAP" and pending is None:
            fields = attrs(value)
            if (set(fields) - {"URI", "BYTERANGE"} or ("BYTERANGE" in fields and not
                    re.fullmatch(r'"[1-9][0-9]*(?:@[0-9]+)?"', fields["BYTERANGE"]))):
                raise CandidateError("invalid init attributes")
            refs.append(playback_key(key, href(fields), "init"))
        elif not master and tag == "#EXT-X-PLAYLIST-TYPE" and value == "VOD":
            pass
        elif not master and tag == "#EXT-X-I-FRAMES-ONLY" and not value and not segments:
            iframe = True
        elif not master and tag == "#EXTINF" and pending is None:
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?,[^,\r\n]*", value):
                raise CandidateError("invalid segment duration")
            segments += 1
            pending = "iframe" if iframe else "segment"
        elif not master and tag == "#EXT-X-BYTERANGE" and pending is not None:
            if not re.fullmatch(r"[1-9][0-9]*(?:@[0-9]+)?", value):
                raise CandidateError("invalid segment byte range")
        elif not master and tag == "#EXT-X-DISCONTINUITY" and not value and not pending:
            pass
        elif not master and tag == "#EXT-X-ENDLIST" and not value and not pending:
            ended = True
        else:
            # Unknown tags can carry keys, variable expansion or external URLs.
            raise CandidateError("unsupported native HLS tag")
    if pending or (master and not variants) or (not master and (not ended or not segments)):
        raise CandidateError("incomplete master or non-VOD media playlist")
    return refs


def current_master(video):
    result = origin.read_view("SELECT master_key FROM public.ipfs_public_reference_videos "
                              "WHERE video_id=:'video'::uuid LIMIT 2;", video=video)
    rows = result.splitlines()
    if len(rows) != 1 or not re.fullmatch(rf"streaming-playlists/{video}/r[1-9][0-9]*/master\.m3u8", rows[0]):
        raise CandidateError("no single eligible native generation")
    return rows[0]


class Source:
    def __init__(self, storage):
        self.storage = storage

    def current(self, key):
        with self.storage.response(key) as reply:
            version = reply.getheader("x-amz-version-id", "")
            length = reply.getheader("Content-Length", "")
            if (reply.status != 200 or not re.fullmatch(r"[!-~]{1,512}", version)
                    or version.lower() == "null" or not re.fullmatch(r"[1-9][0-9]{0,14}", length)):
                raise CandidateError("object has no immutable current version")
            return dict(key=key, version_id=version, size=int(length))

    def read(self, entry, deadline, keep):
        digest = hashlib.sha256()
        playlist = bytearray()
        for start in range(0, entry["size"], CHUNK):
            deadline()
            end = min(start + CHUNK, entry["size"]) - 1
            with self.storage.response(entry["key"], entry["version_id"], (start, end)) as reply:
                length = origin.S3.checked_length(reply, entry, start, end, False)
                data = reply.read(length)
                if len(data) != length:
                    raise CandidateError("short object read")
                digest.update(data)
                if keep:
                    playlist.extend(data)
        return digest.hexdigest(), playlist


def prepare(video, source, lookup, max_bytes, max_seconds):
    if not re.fullmatch(origin.UUID, video):
        raise CandidateError("expected one canonical lowercase video UUID")
    stop_at = time.monotonic() + max_seconds

    def deadline():
        if time.monotonic() >= stop_at:
            raise CandidateError("preparation time budget exceeded")

    master = lookup(video)
    if not re.fullmatch(rf"streaming-playlists/{video}/r[1-9][0-9]*/master\.m3u8", master):
        raise CandidateError("ineligible native master")
    pending = collections.deque([master])
    seen = {master}
    entries = []
    total = 0
    while pending:
        deadline()
        key = pending.popleft()
        entry = source.current(key)
        total += entry["size"]
        playlist = key.endswith(".m3u8")
        if total > max_bytes or (playlist and entry["size"] > PLAYLIST_LIMIT):
            raise CandidateError("preparation byte budget exceeded")
        entry["sha256"], content = source.read(entry, deadline, playlist)
        entry["id"] = origin.object_id(video, master, entry)
        entries.append(entry)
        if playlist:
            for ref in references(key, content, key == master):
                if ref == master:
                    raise CandidateError("playlist cycle")
                if ref not in seen:
                    seen.add(ref)
                    if len(seen) > 4096:
                        raise CandidateError("manifest object limit exceeded")
                    pending.append(ref)
    # Versioned reads alone can mix individually valid objects across a concurrent rewrite.
    for entry in reversed(entries):
        deadline()
        current = source.current(entry["key"])
        if (entry["version_id"], entry["size"]) != (current["version_id"], current["size"]):
            raise CandidateError("source object changed during preparation")
    if lookup(video) != master:
        raise CandidateError("generation or visibility changed during preparation")
    deadline()
    doc = dict(schema=1, video_id=video, master_key=master, objects=entries)
    origin.check_manifest(doc, video, "live")
    encoded = json.dumps(doc, separators=(",", ":")) + "\n"
    if len(encoded.encode()) > origin.MANIFEST_LIMIT:
        raise CandidateError("manifest exceeds origin limit")
    return encoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="one canonical lowercase Vidra video UUID")
    parser.add_argument("--endpoint", required=True, help="fixed HTTPS S3 endpoint (path-style)")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--max-bytes", type=int, default=16 * 1024**3)
    parser.add_argument("--max-seconds", type=int, default=3600)
    args = parser.parse_args()
    if not (0 < args.max_bytes <= 64 * 1024**3 and 0 < args.max_seconds <= 14400):
        parser.error("invalid preparation budget")
    try:
        storage = origin.S3(args.endpoint, args.bucket, args.region, 15)
        result = prepare(args.video, Source(storage), current_master, args.max_bytes, args.max_seconds)
    except CandidateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, ImportError, http.client.HTTPException,
            subprocess.SubprocessError, origin.Refusal) as exc:
        # Avoid including upstream response bodies, connection arguments or credentials.
        print("Manifest preparation failed (" + type(exc).__name__ + ").", file=sys.stderr)
        return 1
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
