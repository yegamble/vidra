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
            summaries = [item["snapshot_id"] for line in result
                         if (item := json.loads(line)).get("message_type") == "summary"]
        if len(summaries) != 1:
            raise ValueError("Missing restic snapshot receipt")
        records = json.loads(output("restic", "snapshots", "--json", summaries[0]))
        if len(records) != 1 or not ID.fullmatch(records[0]["id"]):
            raise ValueError("Ambiguous restic snapshot receipt")
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
        ident = self.backup(["--stdin", "--stdin-filename", MANIFEST],
                            producer=lambda sink: sink.write(data), catalog=[
                                (key, manifest[key]) for key in ("time", "reason", "release", "storage", "bucket")
                            ] + list(manifest["components"].items()))
        self.published = True
        return ident
