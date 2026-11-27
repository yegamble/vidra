"""Bridge-only adapter for one explicitly selected native HLS generation."""
from contextlib import closing
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import uuid

import origin
import prepare

ROOT = Path("/run/vidra-native")
APPROVALS = Path("/etc/vidra-native/approvals")


def main():
    mode, = sys.argv[1:2] or ["serve"]
    if mode == "psql":
        os.execvp("psql", ["psql", "-X", "--no-password", "-v", "ON_ERROR_STOP=1", *sys.argv[2:]])
    if mode not in {"serve", "prepare"} or len(sys.argv) > 2:
        sys.exit("Expected serve, prepare, or psql")
    # Loading an empty configuration never constructs an S3 client or uses a key.
    scope = json.loads((ROOT / "scope.json").read_text())
    approved_id, master, storage = None, None, None
    if scope:
        approved_id = scope["video_id"]
        generation = scope["generation"]
        if str(uuid.UUID(approved_id)) != approved_id or type(generation) is not int or generation < 1:
            sys.exit("Invalid native generation scope")
        master = f"streaming-playlists/{approved_id}/r{generation}/master.m3u8"
        for key, name in (("AWS_ACCESS_KEY_ID", "b2.key-id"), ("AWS_SECRET_ACCESS_KEY", "b2.read-key")):
            os.environ[key] = (ROOT / name).read_text().strip()
        storage = origin.S3(scope["endpoint"], scope["bucket"], scope["region"], 10)

    if mode == "prepare":
        if not approved_id:
            sys.exit("No selected native generation")
        def current(video):
            value = prepare.current_master(video)
            if value != master:
                raise prepare.CandidateError("Selected generation is no longer eligible")
            return value
        report = prepare.prepare(approved_id, prepare.Source(storage), current, 16 * 1024**3, 3600)
        sys.stdout.write(report)
        return

    def allowed(video, generation_key):
        return video == approved_id and generation_key == master and origin.live_approval(video, generation_key)

    addr, = sorted(set(socket.gethostbyname_ex(socket.gethostname())[2]))
    if not ipaddress.IPv4Address(addr).is_private:
        sys.exit("Expected a private container bridge")
    with closing(origin.Manifests(APPROVALS, "live")) as manifests:
        with origin.Server((addr, 8786), manifests, allowed, storage, 4, 64 * 1024**2, 10) as server:
            server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit("Native origin command failed (" + type(exc).__name__ + ")")
