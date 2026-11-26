#!/usr/bin/env python3
"""Serve immutable S3 blocks to a private Kubo instance. See --help for deployment."""

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import threading
import time
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlsplit


BLOCK = 256 * 1024
MANIFEST_LIMIT = 2 * 1024 * 1024
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
DIGEST = r"[0-9a-f]{64}"
ROUTE = re.compile(rf"/v1/references/({UUID})/({DIGEST})")
SEGMENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,254}")


class Refusal(Exception):
    def __init__(self, status, **headers):
        self.status = status
        self.headers = headers


def object_id(video_id, master_key, obj):
    parts = (video_id, master_key, obj["key"], obj["version_id"], str(obj["size"]), obj["sha256"])
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def clean_key(key):
    return (isinstance(key, str) and len(key) <= 1024
            and all(SEGMENT.fullmatch(part) for part in key.split("/")))


def check_manifest(doc, video, mode):
    if (type(doc) is not dict or type(doc.get("schema")) is not int
            or doc["schema"] != 1 or doc.get("video_id") != video):
        raise ValueError("manifest metadata")
    master = doc["master_key"]
    if not clean_key(master):
        raise ValueError("master key")
    prefix = master.rsplit("/", 1)[0] + "/"
    if mode == "synthetic":
        valid = master == f"operator-readiness/ipfs-reference/{video}/master.m3u8"
    else:
        valid = re.fullmatch(rf"streaming-playlists/{video}/r[1-9][0-9]*/master\.m3u8", master)
    if not valid:
        raise ValueError("generation namespace")
    objects = doc["objects"]
    if type(objects) is not list or not 1 <= len(objects) <= 4096:
        raise ValueError("object count")
    by_id = {}
    keys = set()
    for obj in objects:
        key, version, size, digest = obj["key"], obj["version_id"], obj["size"], obj["sha256"]
        if (not clean_key(key) or not key.startswith(prefix) or key in keys
                or not isinstance(version, str) or not re.fullmatch(r"[!-~]{1,512}", version)
                or version.lower() == "null" or type(size) is not int or not 0 < size <= 5 * 1024**4
                or not isinstance(digest, str) or not re.fullmatch(DIGEST, digest)
                or obj["id"] != object_id(video, master, obj)):
            raise ValueError("object binding")
        by_id[obj["id"]] = obj
        keys.add(key)
    if master not in keys:
        raise ValueError("master absent")
    return master, by_id


def trusted(metadata):
    return metadata.st_uid in {0, os.geteuid()} and metadata.st_mode & 0o022 == 0


class Manifests:
    """Pin an operator-owned directory. Atomic rename/unlink changes the next lookup."""

    def __init__(self, directory, mode):
        if mode not in ("live", "synthetic"):
            raise ValueError("mode")
        self.mode = mode
        self.path = os.path.abspath(directory)
        self.directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if not trusted(os.fstat(self.directory)):
            os.close(self.directory)
            raise ValueError("untrusted manifest directory")

    def close(self):
        os.close(self.directory)

    def get(self, video, oid):
        if not re.fullmatch(UUID, video) or not re.fullmatch(DIGEST, oid):
            raise Refusal(404)
        try:
            pinned = os.fstat(self.directory)
            current = os.stat(self.path, follow_symlinks=False)
            if not trusted(pinned) or not os.path.samestat(pinned, current):
                raise ValueError("directory changed")
            fd = os.open(video + ".json", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                         dir_fd=self.directory)
            with os.fdopen(fd, "rb") as fh:
                meta = os.fstat(fd)
                if not trusted(meta) or not stat.S_ISREG(meta.st_mode) or meta.st_size > MANIFEST_LIMIT:
                    raise ValueError("untrusted manifest")
                data = fh.read(MANIFEST_LIMIT + 1)
                if not 0 < len(data) == meta.st_size:
                    raise ValueError("manifest length")
                master, entries = check_manifest(json.loads(data), video, self.mode)
                return master, entries[oid]
        except (OSError, KeyError, ValueError, TypeError, RecursionError):
            raise Refusal(404) from None


def live_approval(video, master):
    # -X disables operator startup files. Bind both values as SQL literals, on stdin so
    # psql interpolates them. Pass only the connection settings needed by the reader.
    env = {k: v for k, v in os.environ.items() if k.startswith("PG") or k in ("PATH", "HOME")}
    env.update(PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=2000",
               PGCONNECT_TIMEOUT="2", PGAPPNAME="vidra-ipfs-origin")
    result = subprocess.run(
        ["psql", "-X", "--no-password", "-Atq", "-v", "ON_ERROR_STOP=1",
         "-v", "video=" + video, "-v", "master=" + master],
        input="SELECT 1 FROM public.ipfs_public_reference_videos "
              "WHERE video_id=:'video'::uuid AND master_key=:'master' LIMIT 1;\n",
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, timeout=4, check=True)
    return result.stdout == "1\n"


def bounds(headers, size, head):
    if not headers:
        if head or size <= BLOCK:
            return 200, 0, size - 1
    elif len(headers) == 1:
        match = re.fullmatch(r"bytes=([0-9]{1,15})-([0-9]{0,15})", headers[0])
        if match:
            start = int(match[1])
            end = min(int(match[2]), size - 1) if match[2] else size - 1
            if 0 <= start <= end and end - start + 1 <= BLOCK:
                return 206, start, end
    raise Refusal(416, **{"Content-Range": f"bytes */{size}"})


class ByteBudget:
    def __init__(self, per_minute):
        self.rate = per_minute
        self.balance = float(per_minute)
        self.at = time.monotonic()
        self.lock = threading.Lock()

    def reserve(self, count):
        with self.lock:
            now = time.monotonic()
            self.balance = min(self.rate, self.balance + (now - self.at) * self.rate / 60)
            self.at = now
            if self.balance < count:
                raise Refusal(429, **{"Retry-After": "60"})
            self.balance -= count


@contextmanager
def socket_deadline(sock, seconds):
    # Socket inactivity timeouts alone allow slow peers to hold a slot indefinitely.
    def expire():
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    timer = threading.Timer(seconds, expire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


class S3:
    def __init__(self, endpoint, bucket, region, timeout):
        from botocore.auth import S3SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        url = urlsplit(endpoint)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.path not in ("", "/") or url.query or url.fragment
                or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)):
            raise ValueError("expected a fixed HTTPS endpoint and bucket")
        self.host = url.hostname
        self.port = url.port or 443
        self.base = "https://" + url.netloc
        self.bucket = bucket
        self.timeout = timeout
        credentials = Credentials(os.environ["AWS_ACCESS_KEY_ID"], os.environ["AWS_SECRET_ACCESS_KEY"],
                                  os.environ.get("AWS_SESSION_TOKEN"))
        self.signer = S3SigV4Auth(credentials, "s3", region)
        self.request = AWSRequest

    def read(self, obj, start, end, head=False):
        path = "/" + self.bucket + "/" + quote(obj["key"], safe="/")
        target = path + "?versionId=" + quote(obj["version_id"], safe="")
        method = "HEAD" if head else "GET"
        headers = {} if head else {"Range": f"bytes={start}-{end}"}
        request = self.request(method=method, url=self.base + target, headers=headers)
        self.signer.add_auth(request)
        with closing(http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout)) as conn:
            conn.connect()
            with socket_deadline(conn.sock, self.timeout):
                conn.request(method, target, headers=dict(request.headers))
                with conn.getresponse() as response:
                    return self.checked_body(response, obj, start, end, head)

    @staticmethod
    def checked_body(response, obj, start, end, head):
        size = obj["size"]
        length = size if head else end - start + 1
        if (response.status != (200 if head else 206)
                or response.getheader("x-amz-version-id") != obj["version_id"]
                or response.getheader("Content-Length") != str(length)
                or response.getheader("Transfer-Encoding") is not None
                or response.getheader("Content-Encoding", "identity") != "identity"
                or (not head and response.getheader("Content-Range") != f"bytes {start}-{end}/{size}")):
            raise Refusal(502)
        if head:
            return b""
        payload = response.read(length)
        if len(payload) != length or (length == size and hashlib.sha256(payload).hexdigest() != obj["sha256"]):
            raise Refusal(502)
        return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Opaque identifiers and request strings do not belong in system logs.

    def send_error(self, code, *args):
        self.respond(code, {"Content-Length": "0"})

    def respond(self, status, headers, body=b""):
        self.send_response(status)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Connection", "close")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def approved(self, video, oid):
        master, obj = self.server.manifests.get(video, oid)
        if not self.server.approve(video, master):
            raise Refusal(404)
        return obj

    def serve(self, head):
        try:
            # BaseHTTPRequestHandler normalizes //, so inspect the original request-target.
            target = self.requestline.split()[1]
            route = ROUTE.fullmatch(target)
            if not route:
                raise Refusal(404)
            video, oid = route.groups()
            obj = self.approved(video, oid)
            size = obj["size"]
            status, start, end = bounds(self.headers.get_all("Range"), size, head)
            length = end - start + 1
            if not head:
                self.server.budget.reserve(length)
            body = self.server.storage.read(obj, start, end, head=head)
            self.approved(video, oid)  # Stop delivery if an operator withdrew approval during S3 I/O.
            headers = {"Content-Length": str(length), "Accept-Ranges": "bytes",
                       "Content-Type": "application/octet-stream"}
            if status == 206:
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        except Refusal as refusal:
            status, headers, body = refusal.status, {"Content-Length": "0", **refusal.headers}, b""
        except Exception:
            status, headers, body = 503, {"Content-Length": "0"}, b""
        self.respond(status, headers, body)

    def do_GET(self):
        self.serve(False)

    def do_HEAD(self):
        self.serve(True)


class Server(ThreadingHTTPServer):
    def __init__(self, addr, manifests, approve, storage, concurrency, byte_rate, timeout):
        ip = ipaddress.IPv4Address(addr[0])
        networks = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
        if not any(ip in ipaddress.ip_network(net) for net in networks):
            raise ValueError("bind a loopback or private IPv4 address")
        self.manifests, self.approve, self.storage = manifests, approve, storage
        self.budget = ByteBudget(byte_rate)
        self.slots = threading.BoundedSemaphore(concurrency)
        self.network_timeout = timeout
        super().__init__(addr, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            request.settimeout(self.network_timeout)
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            with socket_deadline(request, self.network_timeout):
                super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Peer disconnects may race the deadline.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("live", "synthetic"))
    parser.add_argument("--manifest-dir", required=True, help="trusted local directory of <video-uuid>.json files")
    parser.add_argument("--endpoint", required=True, help="fixed HTTPS S3 endpoint (path-style)")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--bind", default="127.0.0.1", help="literal loopback or private IPv4 address")
    parser.add_argument("--port", type=int, default=8785)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--bytes-per-minute", type=int, default=64 * 1024**2)
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()
    if not (1 <= args.concurrency <= 32 and BLOCK <= args.bytes_per_minute <= 1024**3
            and 1 <= args.timeout <= 60 and 1 <= args.port <= 65535):
        parser.error("invalid concurrency, byte, timeout or port limit")
    if args.mode == "live" and not shutil.which("psql"):
        parser.error("live mode requires the PostgreSQL psql client")
    approve = live_approval if args.mode == "live" else lambda video, master: True
    storage = S3(args.endpoint, args.bucket, args.region, args.timeout)
    with closing(Manifests(args.manifest_dir, args.mode)) as manifests:
        with Server((args.bind, args.port), manifests, approve, storage,
                    args.concurrency, args.bytes_per_minute, args.timeout) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
