"""Encrypted restic streams. Only a committed manifest makes a restore point visible."""
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ID = re.compile(r"[a-f0-9]{64}")
MANIFEST = "vidra-install.json"


def run(*cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def output(*cmd, **kwargs):
    return run(*cmd, stdout=subprocess.PIPE, **kwargs).stdout


def private_dir(root):
    path = root / "backups"
    path.mkdir(exist_ok=True, mode=0o700)
    return path


class Repository:
    def __init__(self, root):
        self.root = root
        # The installation path and host identify destructive in-place restores.
        scope = socket.gethostname() + "\0" + str(root)
        self.tag = "vidra-install-" + hashlib.sha256(scope.encode()).hexdigest()[:24]

    def ready(self):
        repo = os.environ.get("RESTIC_REPOSITORY", "")
        if not repo:
            raise ValueError("Set RESTIC_REPOSITORY and a restic password file or command")
        if ":" not in repo or repo.startswith("local:"):
            path = Path(repo.removeprefix("local:")).resolve()
            if path == self.root or self.root in path.parents:
                raise ValueError("Choose a backup repository outside the installation")
        output("restic", "cat", "config")

    def separate_from_media(self, api):
        spec = os.environ.get("RESTIC_REPOSITORY", "")
        cache = os.environ.get("RESTIC_CACHE_DIR")
        if cache and self.root in (Path(cache).resolve(), *Path(cache).resolve().parents):
            raise ValueError("Choose a restic cache outside the installation tree")
        if api.get("STORAGE_BACKEND") == "s3" and spec.startswith("s3:"):
            target = spec[3:].lstrip("/")
            uri = urlsplit(target if "://" in target else "//" + target)
            bucket = api["STORAGE_S3_BUCKET"]
            if bucket == uri.path.lstrip("/").split("/", 1)[0] or (uri.hostname or "").split(".")[0] == bucket or (
                    uri.hostname or "").startswith(bucket + "."):
                raise ValueError("Use a separate restic repository bucket from the live media bucket")

    def entries(self):
        return json.loads(output("restic", "snapshots", "--json", "--tag", self.tag)) or []

    def read(self, ident):
        if not ID.fullmatch(ident) or ident not in {e["id"] for e in self.entries()}:
            raise ValueError("Choose a full install snapshot ID from this host's history")
        doc = json.loads(output("restic", "dump", ident, "/" + MANIFEST))
        if doc.get("format") != 1 or doc.get("install") != str(self.root):
            raise ValueError("Snapshot format or install path does not match")
        return doc

    def restore_tree(self, ident, target):
        if not ID.fullmatch(ident):
            raise ValueError("Invalid tree snapshot ID")
        run("restic", "restore", ident + ":" + str(self.root), "--target", target, "--verify")

    def extract(self, ident, name, consumer):
        if not ID.fullmatch(ident):
            raise ValueError("Invalid stream snapshot ID")
        with subprocess.Popen(["restic", "dump", ident, "/" + name], stdout=subprocess.PIPE) as reader:
            try:
                result = consumer(reader.stdout)
                if reader.stdout.read(1):
                    raise ValueError("Unconsumed bytes at end of snapshot stream")
            finally:
                reader.stdout.close()
            if reader.wait() != 0:
                raise ValueError("restic could not authenticate the complete snapshot stream")
            return result


class Capture:
    def __init__(self, repo):
        self.repo = repo
        self.group = "vidra-capture-" + uuid.uuid4().hex
        self.published = False
        self.sizes = {}

    def backup(self, args, *, producer=None, catalog=()):
        command = ["restic", "backup", "--json", "--tag", self.group]
        if catalog:
            command += ["--tag", self.repo.tag]
            for key, value in catalog:
                command += ["--tag", key + "=" + value]
        # A failed producer may still close its pipe cleanly. Never publish a
        # manifest unless BOTH ends succeeded and restic returned a snapshot ID.
        with tempfile.TemporaryFile() as result:
            with subprocess.Popen(command + args, stdin=subprocess.PIPE if producer else subprocess.DEVNULL,
                                  stdout=result) as process:
                if producer:
                    try:
                        producer(process.stdin)
                    finally:
                        process.stdin.close()
                if process.wait() != 0:
                    raise ValueError("restic did not finish capturing every byte")
            result.seek(0)
            summaries = [item for line in result
                         if (item := json.loads(line)).get("message_type") == "summary"]
        if len(summaries) != 1:
            raise ValueError("Missing restic snapshot receipt")
        records = json.loads(output("restic", "snapshots", "--json", summaries[0]["snapshot_id"]))
        if len(records) != 1 or not ID.fullmatch(records[0]["id"]):
            raise ValueError("Ambiguous restic snapshot receipt")
        size = summaries[0]["total_bytes_processed"]
        if type(size) is not int or size < 0:
            raise ValueError("Invalid archive size in restic receipt")
        self.sizes[records[0]["id"]] = size
        return records[0]["id"]

    def tree(self, binds):
        root = self.repo.root
        exclude = [arg for rel in ["backups", *binds] for arg in ("--exclude", str(root / rel))]
        return self.backup([*exclude, str(root)])

    def stream(self, name, producer):
        return self.backup(["--stdin", "--stdin-filename", name], producer=producer)

    def commit(self, manifest):
        manifest["group"] = self.group
        data = json.dumps(manifest, separators=(",", ":")).encode()
        tags = [(key, manifest[key]) for key in ("time", "reason", "release", "storage", "bucket")]
        tags.extend(manifest["components"].items())
        tags.append(("staging_bytes", str(manifest["staging_bytes"])))
        tags.extend((name + "_schema", str(version)) for name, version in manifest["schemas"].items())
        ident = self.backup(["--stdin", "--stdin-filename", MANIFEST],
                            producer=lambda sink: sink.write(data), catalog=tags)
        self.published = True
        return ident
