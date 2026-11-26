#!/usr/bin/env python3
"""Switch the dedicated synthetic node between offline and approved single-root peering."""
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
BACKUP = APP / "node.offline.json"
UNIT = "vidra-reference-node.service"
DROP = Path("/etc/systemd/system") / (UNIT + ".d") / "10-synthetic-network.conf"
KUBO = "/usr/local/lib/vidra-ipfs-reference/kubo-v0.43.0"
ONLINE = f"[Service]\nExecStart=\nExecStart={KUBO} daemon --enable-gc=false\nIPAddressDeny=\nIPAddressAllow=\n"


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


def multihash(cid):
    if cid.startswith("Qm"):
        number = 0
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        for char in cid:
            number = number * 58 + alphabet.index(char)
        return number.to_bytes((number.bit_length() + 7) // 8, "big")
    if not cid.startswith("b"):
        raise ValueError("unexpected CID encoding")
    body = base64.b32decode(cid[1:].upper() + "=" * (-(len(cid) - 1) % 8))
    if len(body) < 4 or body[0] != 1 or body[1] not in (0x55, 0x70):
        raise ValueError("unexpected CID version or codec")
    return body[2:]


def block_inventory(command):
    results = set()
    for line in rpc(command).splitlines():
        item = json.loads(line)
        if item.get("Err") or not item.get("Ref"):
            raise ValueError("could not inspect all local blocks")
        results.add(multihash(item["Ref"]))
    return results


def approved_root(video_id, cid):
    if str(uuid.UUID(video_id)) != video_id or not re.fullmatch(r"b[a-z2-7]{30,180}", cid):
        raise ValueError("invalid fixture UUID or CID")
    path = APP / "approvals" / (video_id + ".json")
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError("approval must be root-controlled")
    manifest = json.loads(path.read_bytes())
    master = f"operator-readiness/ipfs-reference/{video_id}/master.m3u8"
    if manifest.get("video_id") != video_id or manifest.get("master_key") != master:
        raise ValueError("expected an approved synthetic fixture")
    pins = json.loads(rpc("pin/ls?type=recursive")).get("Keys", {})
    direct = json.loads(rpc("pin/ls?type=direct")).get("Keys", {})
    if set(pins) != {cid} or direct:
        raise ValueError("expected only the approved root to be pinned")
    base = "http://127.0.0.1:8785/v1/references/" + video_id + "/"
    expected = {base + obj["id"] for obj in manifest["objects"]}
    actual = {json.loads(line)["FilePath"] for line in rpc("filestore/ls").splitlines() if line}
    if not actual or actual != expected:
        raise ValueError("reference set does not equal the approved manifest")
    # Providing policy limits advertisements. A peer that knows a block can
    # still request it, so every local block must belong to the approved DAG.
    allowed = block_inventory("refs?arg=" + cid + "&recursive=true&unique=true")
    allowed.add(multihash(cid))
    allowed.add(multihash("QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn"))
    if block_inventory("refs/local") - allowed:
        raise ValueError("unexpected blocks outside the approved synthetic DAG")


def configure(mode, video_id, cid, port, check_only):
    if mode == "online":
        approved_root(video_id, cid)
    if DROP.exists() and DROP.read_text() != ONLINE:
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
    parser.add_argument("--swarm-port", type=int, default=4201)
    parser.add_argument("--check-only", action="store_true", help="validate the current state without writing")
    args = parser.parse_args()
    if args.mode == "online" and (not args.video_id or not args.cid):
        parser.error("online requires the approved synthetic --video-id and --cid")
    if not 1024 <= args.swarm_port <= 65535 or args.swarm_port in (5181, 8185, 8785):
        parser.error("choose a separate unprivileged swarm port")
    configure(args.mode, args.video_id, args.cid, args.swarm_port, args.check_only)
