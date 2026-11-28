#!/usr/bin/env python3
"""Switch the reference node between offline and peering for its explicitly approved roots."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request
import uuid

CONFIG = Path("/var/lib/vidra-ipfs-reference/node/config")
APP = Path("/etc/vidra-ipfs-reference")
NATIVE = Path("/etc/vidra-native-reference")
BACKUP = APP / "node.offline.json"
UNIT = "vidra-reference-node.service"
DROP = Path("/etc/systemd/system") / (UNIT + ".d") / "10-synthetic-network.conf"
KUBO = "/usr/local/lib/vidra-ipfs-reference/kubo-v0.43.0"
ONLINE_V1 = f"[Service]\nExecStart=\nExecStart={KUBO} daemon --enable-gc=false\nIPAddressDeny=\nIPAddressAllow=\n"
# The Go network stack reads route/interface information through AF_NETLINK.
# Keep the offline unit tighter and grant the online node no Linux capabilities.
ONLINE = ONLINE_V1 + "RestrictAddressFamilies=\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK\n"


def atomic(path, data, uid, gid, mode):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(fd, mode)
            os.fchown(fd, uid, gid)
            handle.write(data)
            handle.flush()
            os.fsync(fd)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def rpc(command):
    token = (APP / "rpc.token").read_text().strip()
    request = urllib.request.Request("http://127.0.0.1:5181/api/v0/" + command,
        method="POST", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.read()


def decode_cid(cid):
    if cid.startswith("Qm"):
        number = 0
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        for char in cid:
            number = number * 58 + alphabet.index(char)
        codec, digest = 0x70, number.to_bytes((number.bit_length() + 7) // 8, "big")
    elif re.fullmatch(r"b[a-z2-7]+", cid):
        body = base64.b32decode(cid[1:].upper() + "=" * (-(len(cid) - 1) % 8))
        if len(body) < 4 or body[0] != 1:
            raise ValueError("unexpected CID version")
        codec, digest = body[1], body[2:]
    else:
        raise ValueError("unexpected CID encoding")
    if codec not in (0x55, 0x70) or len(digest) != 34 or digest[:2] != b"\x12\x20":
        raise ValueError("unexpected codec or multihash")
    return codec, digest


def block_inventory(command):
    results = set()
    for line in rpc(command).splitlines():
        item = json.loads(line)
        if item.get("Err") or not item.get("Ref"):
            raise ValueError("could not inspect all local blocks")
        results.add(decode_cid(item["Ref"]))
    return results


def manifest_references(directory, video, cid, master, port):
    if str(uuid.UUID(video)) != video or decode_cid(cid)[0] != 0x70:
        raise ValueError("invalid video UUID or directory CID")
    path = directory / "approvals" / (video + ".json")
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError("approval must be root-controlled")
    manifest = json.loads(path.read_bytes())
    if manifest.get("video_id") != video or manifest.get("master_key") != master:
        raise ValueError("unexpected approved master")
    ids = {obj["id"] for obj in manifest["objects"]}
    if not ids or any(not re.fullmatch(r"[a-f0-9]{64}", oid) for oid in ids):
        raise ValueError("invalid reference object IDs")
    return {f"http://127.0.0.1:{port}/v1/references/{video}/{oid}" for oid in ids}


def approved_root(video_id, cid, native=None):
    master = f"operator-readiness/ipfs-reference/{video_id}/master.m3u8"
    expected = {cid: manifest_references(APP, video_id, cid, master, 8785)}
    if native:
        video, generation, root = native
        if video == video_id or root == cid or not re.fullmatch(r"[1-9][0-9]*", generation):
            raise ValueError("invalid additional native generation")
        master = f"streaming-playlists/{video}/r{generation}/master.m3u8"
        expected[root] = manifest_references(NATIVE, video, root, master, 8786)
    pins = json.loads(rpc("pin/ls?type=recursive")).get("Keys", {})
    direct = json.loads(rpc("pin/ls?type=direct")).get("Keys", {})
    if set(pins) != set(expected) or direct:
        raise ValueError("pins differ from the approved roots")

    # A global union of URLs and hashes could admit a locally copied media block,
    # or accept the second root's S3 objects under the first video's identity.
    locations = {}
    for line in rpc("filestore/ls").splitlines():
        entry = json.loads(line)
        codec, digest = decode_cid(entry["Key"]["/"])
        if codec != 0x55 or entry["Status"] != 0 or entry.get("ErrorMsg") or digest in locations:
            raise ValueError("unexpected URLStore entry")
        locations[digest] = entry["FilePath"]
    allowed = {decode_cid("QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn")[1]}
    all_leaves = set()
    for root, urls in expected.items():
        blocks = block_inventory(f"refs?arg={root}&recursive=true&unique=true")
        leaves = {digest for codec, digest in blocks if codec == 0x55}
        if leaves - locations.keys():
            raise ValueError("raw media is missing its URLStore reference")
        if {locations[digest] for digest in leaves} != urls:
            raise ValueError("reference set differs from the approved manifest")
        all_leaves.update(leaves)
        allowed.update(digest for _, digest in blocks)
        allowed.add(decode_cid(root)[1])
    if set(locations) != all_leaves:
        raise ValueError("reference set includes unapproved blocks")
    # refs/local can report a CIDv0 for the same stored multihash.
    if {digest for _, digest in block_inventory("refs/local")} - allowed:
        raise ValueError("unexpected blocks outside the approved DAGs")


def configure(mode, video_id, cid, port, check_only, native=None):
    if mode == "online":
        approved_root(video_id, cid, native)
    if DROP.exists() and DROP.read_text() not in (ONLINE, ONLINE_V1):
        raise ValueError("unrecognized networking override")
    current = CONFIG.read_bytes()
    if not BACKUP.exists() and DROP.exists():
        raise ValueError("offline rollback config is absent")
    baseline = BACKUP.read_bytes() if BACKUP.exists() else current
    conf = json.loads(baseline)
    if (conf["Addresses"]["Swarm"] or conf["Bootstrap"] or not conf["Gateway"]["NoFetch"]
            or conf["Provide"]["Strategy"] != "pinned" or conf["Experimental"]["FilestoreEnabled"]
            or not conf["Experimental"]["UrlstoreEnabled"] or not conf["API"]["Authorizations"]
            or conf["Addresses"]["API"] != "/ip4/127.0.0.1/tcp/5181"
            or conf["Addresses"]["Gateway"] != "/ip4/127.0.0.1/tcp/8185"):
        raise ValueError("unexpected offline baseline")
    if check_only:
        return
    if mode == "offline" and not DROP.exists() and current == baseline:
        return
    metadata = CONFIG.stat()
    if not BACKUP.exists():
        atomic(BACKUP, baseline, 0, 0, 0o600)
    def write_config(data):
        atomic(CONFIG, data, metadata.st_uid, metadata.st_gid, 0o600)
    def start():
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "start", UNIT], check=True)
        for _ in range(40):
            try:
                rpc("id")
                return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("dedicated node RPC did not become ready")
    subprocess.run(["systemctl", "stop", UNIT], check=True)
    try:
        if mode == "online":
            conf["Addresses"]["Swarm"] = [f"/ip4/0.0.0.0/tcp/{port}"]
            conf["Bootstrap"] = ["auto"]
            conf["AutoConf"]["Enabled"] = True
            write_config(json.dumps(conf).encode())
            DROP.parent.mkdir(exist_ok=True)
            atomic(DROP, ONLINE.encode(), 0, 0, 0o644)
        else:
            write_config(baseline)
            DROP.unlink(missing_ok=True)
        start()
    except Exception:
        subprocess.run(["systemctl", "stop", UNIT], check=True)
        write_config(baseline)
        DROP.unlink(missing_ok=True)
        start()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["online", "offline"])
    parser.add_argument("--video-id")
    parser.add_argument("--cid")
    parser.add_argument("--native", nargs=3, metavar=("UUID", "GENERATION", "CID"),
                        help="also admit this explicitly approved native generation")
    parser.add_argument("--swarm-port", type=int, default=4201)
    parser.add_argument("--check-only", action="store_true", help="validate the current state without writing")
    args = parser.parse_args()
    if args.mode == "online" and (not args.video_id or not args.cid):
        parser.error("online requires the approved synthetic --video-id and --cid")
    if args.native and args.mode != "online":
        parser.error("--native applies only to online admission")
    if not 1024 <= args.swarm_port <= 65535 or args.swarm_port in (5181, 8185, 8785):
        parser.error("choose a separate unprivileged swarm port")
    configure(args.mode, args.video_id, args.cid, args.swarm_port, args.check_only, args.native)
