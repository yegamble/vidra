#!/usr/bin/env python3
"""A local operator console for the dated snapshots managed by snapshots.py."""

import argparse
from collections import deque
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time


HERE = Path(__file__).resolve().parent
ASSETS = {
    "/": ("snapshot-ui.html", "text/html; charset=utf-8"),
    "/app.js": ("snapshot-ui.js", "text/javascript; charset=utf-8"),
    "/screen.css": ("snapshot-ui.css", "text/css; charset=utf-8"),
}
SNAPSHOT_ID = re.compile(r"[0-9a-f]{64}")
RELEASE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:@sha256:[0-9a-f]{64})?")
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.]+(?:Z|[+-][0-9]{2}:[0-9]{2})")
DATABASE = re.compile(r"(?:vidra-[0-9]{8}T[0-9]{6}Z|pre-deploy-[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6})\.dump\.gz")
BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def cli(*args):
    return [sys.executable, str(HERE / "snapshots.py"), *args]


def safe_catalog():
    # Compose renders may contain credentials. Never pass raw subprocess errors,
    # output or arbitrary metadata through to the operator's browser.
    try:
        raw = subprocess.check_output(cli("list", "--json"), stderr=subprocess.DEVNULL,
                                      timeout=90)
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise ValueError("invalid catalog")
        return [public_snapshot(entry) for entry in entries]
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as err:
        raise Problem("Could not read the snapshot repository. Run snapshots.py list on the host for details.", 503) from err


def public_snapshot(entry):
    def field(name, pattern, default=None):
        value = entry.get(name)
        if isinstance(value, str) and pattern.fullmatch(value):
            return value
        if default is not None:
            return default
        raise ValueError("invalid snapshot " + name)

    if not isinstance(entry, dict):
        raise ValueError("invalid snapshot")
    kind = field("kind", re.compile(r"install|database"))
    components = entry.get("components", {})
    if not isinstance(components, dict):
        raise ValueError("invalid component pins")
    return {
        "kind": kind,
        "id": field("id", SNAPSHOT_ID if kind == "install" else DATABASE),
        "time": field("time", STAMP),
        "reason": field("reason", re.compile(r"[a-zA-Z0-9_-]{1,40}"), "unspecified"),
        "release": field("release", RELEASE, "unrecorded"),
        "storage": field("storage", re.compile(r"local|s3") if kind == "install" else re.compile("database only")),
        "bucket": field("bucket", BUCKET, ""),
        "components": {key: value for key, value in components.items()
                       if key in ("core", "user", "search") and isinstance(value, str) and RELEASE.fullmatch(value)},
    }


def options(data, entry):
    preserve, bucket = data.get("preserve"), data.get("bucket", "")
    if type(preserve) is not bool or not isinstance(bucket, str):
        raise Problem("Choose a preservation mode and media destination.")
    if entry["storage"] == "s3":
        if not BUCKET.fullmatch(bucket) or ".." in bucket or bucket == entry["bucket"]:
            raise Problem("Enter the name of a separate empty S3 bucket.")
    elif bucket:
        raise Problem("This snapshot uses local media.")
    return preserve, bucket


def restore_args(identifier, preserve, bucket):
    args = ["restore", identifier]
    if not preserve:
        args.append("--discard-current")
    if bucket:
        args.extend(("--media-bucket", bucket))
    return args


def run_check(args):
    try:
        output = subprocess.check_output(cli(*args), stderr=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.SubprocessError) as err:
        raise Problem("The host declined this preview. Check the repository and snapshot on the host.", 409) from err
    # Expose counts from the host's actual plan, without forwarding its output.
    counts = re.search(rb"^Restore (\d+) volumes and (\d+) exact service images\.", output, re.M)
    if args[0] == "restore" and counts:
        return f"This recovery restores {int(counts[1])} volumes and {int(counts[2])} service images."
    parts = re.search(rb" (\d+) archive parts\s*$", output)
    if args[0] == "retire" and parts:
        return f"This recovery point includes {int(parts[1])} archive parts."
    return ""


def run_operation(args, note):
    # Read only fixed progress markers agreed by the CLI. An underlying tar,
    # Docker, S3 or restic error can contain paths, secrets or presigned URLs.
    phases = {
        "stopping writers": "Pausing services that write data",
        "saving installation and configuration": "Saving installation files and configuration",
        "saving exact service images": "Saving the running software images",
        "saving database and Docker volumes": "Saving the database and Docker volumes",
        "saving S3 media": "Saving media from S3",
        "committing recovery point": "Recording the recovery point",
        "verifying installation and images": "Checking archived files and images",
        "verifying database and Docker volumes": "Checking the database and archived volumes",
        "recovering S3 media to new bucket": "Recovering media into the new bucket",
        "restoring owned volumes": "Restoring Docker volumes",
        "restoring installation": "Restoring the installation",
        "checking restored media": "Verifying restored media",
        "starting saved services": "Starting saved services",
        "recovery complete": "Recovery complete",
    }
    steps = 0
    # Closing the browser or stopping the console should not interrupt a
    # database restore that the operator already confirmed.
    with subprocess.Popen(cli(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          start_new_session=True) as proc:
        while True:
            data = proc.stdout.readline(8192)
            if not data:
                break
            if data.startswith((b"Snapshot step: ", b"Restore step: ")):
                steps += 1
                phase = data.split(b": ", 1)[1].strip().decode("ascii", errors="replace")
                note(phases.get(phase, f"Host reached step {steps}"))
        return proc.wait()


class Console:
    def __init__(self, catalog=safe_catalog, check=run_check, operate=run_operation):
        self.catalog, self.check, self.operate = catalog, check, operate
        self.lock = threading.Lock()
        self.preview = None
        self.job = None

    def find(self, data):
        identifier = data.get("id")
        if not isinstance(identifier, str) or not SNAPSHOT_ID.fullmatch(identifier):
            raise Problem("Select a snapshot from the history.")
        matches = [s for s in self.catalog() if s["id"] == identifier]
        if len(matches) != 1:
            raise Problem("This snapshot is no longer available.", 404)
        return matches[0]

    def idle(self):
        if self.job and self.job["state"] == "running":
            raise Problem("An operation is already running.", 409)

    def plan(self, data, kind="restore"):
        with self.lock:
            self.idle()
        entry = self.find(data)
        if kind == "restore":
            preserve, bucket = options(data, entry)
            summary = self.check(restore_args(entry["id"], preserve, bucket))
            selection = {"id": entry["id"], "preserve": preserve, "bucket": bucket}
            phrase = f"{entry['release'].split('@')[0]} {entry['time'][:10]}"
        else:
            if set(data) != {"id"}:
                raise Problem("Retirement accepts only the selected snapshot.")
            summary = self.check(["retire", entry["id"]])
            selection = {"id": entry["id"]}
            phrase = "RETIRE " + entry["id"][:12]
        with self.lock:
            self.idle()
            nonce = secrets.token_urlsafe(24)
            self.preview = (kind, time.monotonic() + 600, {**selection, "nonce": nonce, "confirmation": phrase})
        result = {"nonce": nonce, "confirmation": phrase}
        if summary:
            result["summary"] = summary
        return result

    def start(self, kind, data):
        with self.lock:
            self.idle()
            if kind in ("restore", "retire"):
                saved = self.preview
                if not saved or kind != saved[0] or time.monotonic() >= saved[1] or data != saved[2]:
                    raise Problem("Preview the selected action again and enter its confirmation.", 409)
                if kind == "restore":
                    if type(data["preserve"]) is not bool:
                        raise Problem("Choose a preservation mode.", 409)
                    args = [*restore_args(data["id"], data["preserve"], data["bucket"]), "--apply"]
                else:
                    args = ["retire", data["id"], "--apply"]
            else:
                args = ["create", "--reason", "manual"]
            self.preview = None
            self.job = {"operation": kind, "id": secrets.token_hex(10), "started": time.time(),
                        "state": "running", "events": deque(maxlen=12)}
            self.job["events"].append({"create": "Starting snapshot capture", "restore": "Starting confirmed restore",
                                       "retire": "Removing the selected recovery point"}[kind])
            threading.Thread(target=self.worker, args=(args,), daemon=False).start()
            return {"accepted": True}

    def worker(self, args):
        def note(message):
            with self.lock:
                if self.job["events"][-1] != message:
                    self.job["events"].append(message)
        succeeded = False
        result = None
        try:
            result = self.operate(args, note)
            succeeded = result == 0
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            with self.lock:
                self.job["state"] = "succeeded" if succeeded else "failed"
                self.job["ended"] = time.time()
                if self.job["state"] == "failed":
                    reason = f"Host command exited with code {result}." if result is not None else "Host command failed to start."
                    self.job["events"].append(reason + " Check the installation before retrying.")

    def status(self):
        with self.lock:
            if not self.job:
                return {}
            return {**self.job, "events": list(self.job["events"])}


class Handler(BaseHTTPRequestHandler):
    server_version = "Vidra"
    sys_version = ""

    def log_message(self, *_):
        pass

    def reply(self, status, body, mime="application/json"):
        if mime == "application/json":
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; script-src 'self'; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def access(self):
        port = self.server.server_port
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
        host = self.headers.get_all("Host", [])
        if len(host) != 1 or host[0] not in hosts or not self.path.startswith("/"):
            raise Problem("Access denied.", HTTPStatus.FORBIDDEN)
        origins = self.headers.get_all("Origin", [])
        if origins and origins != ["http://" + host[0]]:
            raise Problem("Access denied.", HTTPStatus.FORBIDDEN)
        if self.path.startswith("/api/"):
            keys = self.headers.get_all("X-Vidra-Key", [])
            if len(keys) != 1 or not hmac.compare_digest(keys[0].encode(), self.server.secret.encode()):
                raise Problem("Open the private console link printed on the host.", HTTPStatus.FORBIDDEN)

    def payload(self):
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json"
                or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,4}", lengths[0]) or int(lengths[0]) > 4096):
            raise Problem("Invalid request body.")
        try:
            data = json.loads(self.rfile.read(int(lengths[0])))
        except (ValueError, UnicodeError) as err:
            raise Problem("Invalid JSON.") from err
        if not isinstance(data, dict):
            raise Problem("Invalid request.")
        return data

    def dispatch(self):
        self.access()
        console = self.server.console
        if self.command == "GET":
            if self.path in ASSETS:
                filename, mime = ASSETS[self.path]
                return self.reply(200, (HERE / filename).read_bytes(), mime)
            if self.path == "/api/snapshots":
                return self.reply(200, console.catalog())
            if self.path == "/api/status":
                return self.reply(200, console.status())
            if self.path == "/api/repository":
                return self.reply(200, {"configured": bool(os.environ.get("RESTIC_REPOSITORY"))})
        if self.command == "POST" and self.path in ("/api/create", "/api/preview", "/api/restore", "/api/preview-retire", "/api/retire"):
            data = self.payload()
            if self.path == "/api/preview":
                return self.reply(200, console.plan(data))
            if self.path == "/api/preview-retire":
                return self.reply(200, console.plan(data, "retire"))
            if self.path == "/api/create" and data:
                raise Problem("Snapshot creation takes no parameters.")
            return self.reply(202, console.start(self.path.rsplit("/", 1)[1], data))
        raise Problem("Route unavailable.", 404)

    def do_GET(self):
        try:
            self.dispatch()
        except Problem as err:
            self.reply(err.status, {"error": str(err)})
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_POST = do_GET


def server(port, console):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.secret = secrets.token_urlsafe(32)
    httpd.console = console
    return httpd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8384)
    args = parser.parse_args()
    if not (0 <= args.port <= 65535):
        parser.error("port must be between 0 and 65535")
    with server(args.port, Console()) as httpd:
        port = httpd.server_port
        print(f"On your computer, forward the port with ssh -N -L {port}:127.0.0.1:{port} USER@HOST", flush=True)
        print(f"Open the private link http://127.0.0.1:{port}/#key={httpd.secret}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            if httpd.console.status().get("state") == "running":
                print("The console is closing. Waiting for the active operation to finish.", flush=True)


if __name__ == "__main__":
    main()
