#!/usr/bin/env python3
"""Initialize only an empty, dedicated offline Kubo repo. Pass the RPC token on stdin."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    os.umask(0o077)
    repo = Path(os.environ["IPFS_PATH"])
    if not repo.is_dir() or any(repo.iterdir()):
        raise SystemExit("The dedicated repository must be an existing empty directory.")
    token = sys.stdin.read().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
        raise SystemExit("Expected a random bearer token on stdin.")
    kubo = "/usr/local/lib/vidra-ipfs-reference/kubo-v0.43.0"
    version = subprocess.check_output([kubo, "version"], text=True).strip()
    if version != "ipfs version 0.43.0":
        raise SystemExit("Expected Kubo 0.43.0.")
    subprocess.run([kubo, "init", "--empty-repo", "--profile=server"], check=True, stdout=subprocess.DEVNULL)
    config = repo / "config"
    values = json.loads(config.read_text())
    values["Addresses"].update({
        "API": "/ip4/127.0.0.1/tcp/5181", "Gateway": "/ip4/127.0.0.1/tcp/8185", "Swarm": [],
    })
    values["Bootstrap"] = []
    values.setdefault("AutoConf", {})["Enabled"] = False
    values.setdefault("AutoTLS", {})["Enabled"] = False
    values.setdefault("Discovery", {}).setdefault("MDNS", {})["Enabled"] = False
    values.setdefault("Gateway", {}).update({"NoFetch": True, "NoDNSLink": True})
    values.setdefault("Provide", {})["Strategy"] = "pinned"
    values.setdefault("Experimental", {}).update({"UrlstoreEnabled": True, "FilestoreEnabled": False})
    values.setdefault("API", {})["Authorizations"] = {"reference-operator": {
        "AuthSecret": "bearer:" + token,
        "AllowedPaths": ["/api/v0/" + cmd for cmd in (
            "add", "pin/add", "pin/rm", "pin/ls", "repo/stat", "id", "cat", "ls",
            "block/stat", "dag/stat", "refs", "filestore/ls", "swarm/peers", "routing/findprovs",
        )],
    }}
    temporary = repo / "config.reference-init"
    with temporary.open("x") as handle:
        json.dump(values, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(config)


if __name__ == "__main__":
    main()
