#!/usr/bin/env python3
"""Range-capable, request-logging HTTP origin for the reference-pinning spike.

WHY this exists: Python's stock http.server answers 200 to every request and
ignores Range, so it cannot stand in for S3/Spaces and cannot prove how many
ranged GETs Kubo issues. This one does Range, logs every request line plus its
Range header to a file, and can be switched into failure modes at runtime by
writing a word into MODE_FILE (no restart needed, so a single daemon run covers
T4a..T4d).

Modes (contents of ./mode.txt, read fresh on every request):
  normal    -> serve the real bytes (200, or 206 + Content-Range for a Range)
  404       -> answer 404 for every data path
  corrupt   -> serve bytes of the same length but different content
  redirect  -> 307 to /redir/<name>; /redir/<name> serves the real bytes
Usage: origin.py <root-dir> <port> <log-file> <mode-file>
"""
import os
import re
import sys
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT, PORT, LOGFILE, MODEFILE = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def mode():
    try:
        with open(MODEFILE) as fh:
            return fh.read().strip() or "normal"
    except OSError:
        return "normal"


def record(line):
    with open(LOGFILE, "a") as fh:
        fh.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="milliseconds"), line))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence stderr; we keep our own log
        pass

    _sent = 0

    def _emit(self, code, body=b"", extra=None):
        self._sent = len(body)
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)
        return code

    def handle_one(self):
        rng = self.headers.get("Range")
        m = mode()
        path = self.path
        redirected = path.startswith("/redir/")
        name = os.path.basename(path.split("?")[0])
        # Nested names (hls/720p/seg-1.m4s) are flattened on disk with '__'.
        rel = path.split("?")[0].lstrip("/")
        if redirected:
            rel = rel[len("redir/"):]
        disk = os.path.join(ROOT, rel.replace("/", "__"))

        if m == "404" and not redirected:
            code = self._emit(404, b"not found\n")
        elif m == "redirect" and not redirected:
            code = self._emit(307, b"", {"Location": "/redir/" + rel})
        elif not os.path.isfile(disk):
            code = self._emit(404, b"no such file\n")
        else:
            data = open(disk, "rb").read()
            if m == "corrupt" and not redirected:
                data = bytes((b ^ 0xFF) for b in data)  # same length, wrong bytes
            if rng and RANGE_RE.match(rng):
                a, b = RANGE_RE.match(rng).groups()
                if a == "":  # bytes=-N  (suffix)
                    start, end = max(0, len(data) - int(b)), len(data) - 1
                else:
                    start = int(a)
                    end = int(b) if b else len(data) - 1
                end = min(end, len(data) - 1)
                chunk = data[start:end + 1]
                code = self._emit(206, chunk, {
                    "Content-Range": "bytes %d-%d/%d" % (start, end, len(data))})
            else:
                code = self._emit(200, data)
        record('%s "%s %s" Range=%s mode=%s -> %d bytes=%d' % (
            self.client_address[0], self.command, path, rng if rng else "-", m, code, self._sent))

    do_GET = handle_one
    do_HEAD = handle_one


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    record("=== origin up root=%s port=%d ===" % (ROOT, PORT))
    srv.serve_forever()
