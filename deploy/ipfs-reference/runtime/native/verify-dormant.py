#!/usr/bin/env python3
"""Check the local dormant HTTP origin and its private SQL role without publication."""
import argparse
import http.client
import json
from pathlib import Path
import secrets
import re
import subprocess
import sys
import uuid

if not __debug__:
    sys.exit("Run verification with Python assertions enabled")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--env-file", required=True)
parser.add_argument("--image-id-file", type=Path, required=True)
parser.add_argument("--project", default="vidra-native-reference")
parser.add_argument("--port", type=int, default=8786)
args = parser.parse_args()
compose = ["docker", "compose", "-p", args.project, "--env-file", str(Path(args.env_file).resolve()),
           "-f", str(Path(__file__).resolve().with_name("compose.yml"))]
cid = subprocess.check_output(compose + ["ps", "-q", "origin"], text=True).strip()
meta, = json.loads(subprocess.check_output(["docker", "inspect", cid]))
expected_id = args.image_id_file.read_text().strip()
if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_id) or meta["Image"] != expected_id:
    sys.exit("Running image does not match the reviewed image ID")
ports = meta["HostConfig"]["PortBindings"]
assert ports == {"8786/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(args.port)}]}, "Unexpected listener"
assert meta["HostConfig"]["ReadonlyRootfs"] and meta["HostConfig"]["CapDrop"] == ["ALL"]
assert meta["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
assert not meta["HostConfig"]["Privileged"] and all(m["Destination"] != "/var/run/docker.sock" for m in meta["Mounts"])
assert all(not m["RW"] for m in meta["Mounts"] if m["Type"] == "bind")
probe = """from pathlib import Path
import json,os
d=Path('/run/vidra-native')
assert not list(Path('/etc/vidra-native/approvals').iterdir())
assert json.loads((d/'scope.json').read_text())=={}
assert not any((d/s).exists() for s in ('b2.key-id','b2.read-key'))
assert 'AWS_ACCESS_KEY_ID' not in os.environ and 'AWS_SECRET_ACCESS_KEY' not in os.environ
"""
subprocess.run(["docker", "exec", cid, "python3", "-c", probe], check=True)
role, video = "vidra_native_reference_reader", str(uuid.uuid4())
query = f"""SELECT current_user, current_setting('default_transaction_read_only'),
 has_table_privilege(current_user, 'public.ipfs_public_reference_videos', 'SELECT'),
 has_table_privilege(current_user, 'public.users', 'SELECT'),
 has_table_privilege(current_user, 'public.videos', 'UPDATE'),
 NOT EXISTS(SELECT FROM public.ipfs_public_reference_videos WHERE video_id='{video}'::uuid);"""
cmd = ["docker", "exec", "-i", cid, "psql", "-XAtq", "--no-password", "-v", "ON_ERROR_STOP=1"]
result = subprocess.run(cmd, input=query, text=True, capture_output=True, check=True)
assert result.stdout.strip() == f"{role}|on|t|f|f|t"
denied = subprocess.run(cmd + ["-c", "SELECT 1 FROM public.users LIMIT 0"], capture_output=True)
assert denied.returncode and b"permission denied" in denied.stderr
for method in ("HEAD", "GET"):
    con = http.client.HTTPConnection("127.0.0.1", args.port, timeout=5)
    try:
        con.request(method, "/v1/references/" + video + "/" + secrets.token_hex(32))
        res = con.getresponse()
        assert res.status == 404 and res.getheader("Content-Length") == "0" and not res.read()
    finally:
        con.close()
print("Verified native reader, protected-table denial, empty approvals, no S3 key, loopback and 404 HEAD/GET")
