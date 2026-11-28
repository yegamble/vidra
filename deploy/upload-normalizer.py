#!/usr/bin/env python3
"""Serve one systemd-accepted local connection to an isolated media processor."""
import fcntl
from http.server import BaseHTTPRequestHandler
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import socket
import subprocess
import sys
import time

MAX_INPUT = 20 << 30
MAX_OUTPUT = (2 << 30) - 3
FREE_RESERVE = 20 << 30
WORK = Path("/var/lib/vidra-upload-normalizer")
IMAGE = Path("/etc/vidra-upload-normalizer/core-image")


def core_image():
    value = IMAGE.read_text().strip()
    if not re.fullmatch(r"ghcr\.io/yegamble/vidra-core@sha256:[a-f0-9]{64}", value):
        raise ValueError("normalizer requires a pinned release image digest")
    return value


def copy_request(src, dst, size):
    while size:
        chunk = src.read(min(1024 * 1024, size))
        if not chunk:
            raise EOFError("short upload")
        dst.write(chunk)
        size -= len(chunk)


def container_name(work):
    if work.parent != WORK or not re.fullmatch(r"job-[0-9a-f]{24}", work.name):
        raise ValueError("invalid job directory")
    return "vidra-normalizer-" + work.name


def remove_encoder(work):
    name = container_name(work)
    filters = ["--filter", "name=^/" + name + "$", "--filter", "label=org.vidra.normalize.job=" + work.name]
    query = ["/usr/bin/docker", "ps", "-aq", "--no-trunc", *filters]
    found = subprocess.check_output(query, timeout=30).decode().strip()
    if found:
        if not re.fullmatch("[0-9a-f]{64}", found):
            raise RuntimeError("ambiguous container identity")
        removed = subprocess.run(["/usr/bin/docker", "rm", "-f", found], capture_output=True, timeout=45)
        if removed.returncode and subprocess.check_output(query, timeout=30).strip():
            raise RuntimeError("isolated container could not be removed")


def reap():
    # Called with the exclusive job lock. Interrupted private inputs and any
    # daemon-owned child survive SIGKILL, but cannot survive this sweep.
    for work in WORK.glob("job-*"):
        container_name(work)
        if work.is_symlink() or not work.is_dir() or work.stat().st_uid != os.getuid():
            raise RuntimeError("unexpected job directory")
        remove_encoder(work)
        shutil.rmtree(work)


def run_encoder(work, image, connection):
    source = work / "source"
    output = work / "processed.mp4"
    output.touch(mode=0o600, exist_ok=False)
    os.chown(output, 10001, 10001)
    source.chmod(0o444)
    args = [
        "/usr/bin/docker", "run", "--rm", "--name", container_name(work),
        "--label", "org.vidra.normalize.job=" + work.name, "--pull", "never",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "10001:10001",
        "--cpus", "2", "--memory", "2g", "--memory-swap", "2g", "--pids-limit", "96",
        "--ulimit", f"fsize={MAX_OUTPUT + 1}:{MAX_OUTPUT + 1}", "--log-driver", "none",
        "--no-healthcheck", "--init", "--mount", f"type=bind,src={source},dst=/input/source,readonly",
        "--mount", f"type=bind,src={output},dst=/output/processed.mp4",
        "--entrypoint", "/app/normalize-upload", image,
    ]
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
        deadline = time.monotonic() + 24 * 3600 + 60
        try:
            while child.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError("encoding deadline expired")
                if select.select([connection], [], [], 1)[0]:
                    raise ConnectionResetError("client left or sent another request")
        finally:
            if child.poll() is None:
                child.kill()
        if child.returncode:
            if child.returncode in (125, 126, 127, 137):
                raise RuntimeError("isolated processor unavailable")
            raise ValueError("video processing failed")
    if not 0 < output.stat().st_size <= MAX_OUTPUT:
        raise ValueError("invalid processed file length")
    return output


class Handler(BaseHTTPRequestHandler):
    server_version = "Vidra"
    sys_version = ""

    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/normalize":
            self.send_error(404)
            return
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
            self.send_error(400)
            return
        size = int(lengths[0])
        if not 0 < size <= MAX_INPUT:
            self.send_error(413)
            return
        streaming = False
        try:
            with (WORK / "busy.lock").open("ab") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                reap()
                if shutil.disk_usage(WORK).free < size + MAX_OUTPUT + FREE_RESERVE:
                    self.send_error(503)
                    return
                image = core_image()
                work = WORK / ("job-" + secrets.token_hex(12))
                work.mkdir(mode=0o700)
                try:
                    with (work / "source").open("xb") as source:
                        copy_request(self.rfile, source, size)
                    try:
                        output = run_encoder(work, image, self.connection)
                    except ValueError:
                        self.send_error(422)
                        return
                    with output.open("rb") as processed:
                        streaming = True
                        self.send_response(200)
                        self.send_header("Content-Type", "video/mp4")
                        self.send_header("Content-Length", str(os.fstat(processed.fileno()).st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        shutil.copyfileobj(processed, self.wfile, length=1024 * 1024)
                finally:
                    remove_encoder(work)
                    shutil.rmtree(work)
        except (BrokenPipeError, ConnectionResetError, EOFError):
            return
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            if not streaming:
                self.send_error(503)


if __name__ == "__main__":
    os.umask(0o077)
    if sys.argv[1:] == ["--clean"]:
        WORK.mkdir(mode=0o700, exist_ok=True)
        with (WORK / "busy.lock").open("ab") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                sys.exit(0)
            reap()
    elif len(sys.argv) == 1:
        with socket.socket(fileno=0) as connection:
            connection.settimeout(5 * 60)
            Handler(connection, ("local", 0), None)
    else:
        sys.exit(2)
