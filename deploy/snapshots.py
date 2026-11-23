#!/usr/bin/env python3
"""Create, browse and restore encrypted recovery points for a single Vidra installation."""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import snapshot_s3
from snapshot_lock import maintenance_lock
from snapshot_repo import Capture, Repository, output, private_dir, run
from snapshot_stack import (IMAGE_ID, SAFE_NAME, archive_volume, assert_volumes,
                            check_binds, check_datastores, compose, config, environment_digest, inspect, inventory, owned_containers,
                            restart_original, schema_versions, stop)

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ("time", "reason", "release", "components", "storage", "bucket")
JOURNAL = ".snapshot-recovery.json"


def step(text):
    print(text, file=sys.stderr, flush=True)


def env_file(root):
    path = Path(os.environ.get("ENV_FILE", "env/production.env"))
    if path.is_absolute():
        path = path.relative_to(ROOT)
    if ".." in path.parts or (root / path).is_symlink() or not (root / path).is_file():
        raise ValueError("Use a regular env file inside the install")
    return path


def write_json(path, doc):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(doc, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, path)


def current(root, repo):
    repo.ready()
    env_file(root)
    for gitdir in [root / ".git", *(root.glob("vidra-*/.git"))]:
        if gitdir.is_file() or gitdir.is_symlink():
            raise ValueError("Linked Git worktrees require a separate backup of their external metadata")
    manifest, api = inventory(root)
    repo.separate_from_media(api)
    if manifest["storage"] == "s3":
        snapshot_s3.preflight(api)
    return manifest, api


def capture(repo, manifest, api, reason):
    cap = Capture(repo)
    doc = dict(manifest, format=1, install=str(repo.root), reason=reason,
               time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               release=manifest["components"]["core"], env_file=str(env_file(repo.root)))
    try:
        step("Snapshot step: saving installation and configuration")
        doc["tree"] = cap.tree(doc["binds"])
        step("Snapshot step: saving exact service images")
        ids = sorted(set(doc["images"].values()))
        if not all(IMAGE_ID.fullmatch(image) for image in ids):
            raise ValueError("Unrecognized service image ID")
        doc["image_stream"] = cap.stream("images.tar", lambda dst: run("docker", "image", "save", *ids, stdout=dst))
        doc["volume_streams"] = {}
        step("Snapshot step: saving database and Docker volumes")
        for name in sorted(doc["volumes"]):
            doc["volume_streams"][name] = cap.stream("volume.tar", lambda dst: archive_volume(doc, name, dst))
        doc["bind_streams"] = {}
        for rel in doc["binds"]:
            mount = "type=bind,source=" + str(repo.root / rel) + ",target=/volume,readonly"
            doc["bind_streams"][rel] = cap.stream("bind.tar", lambda dst: run(
                "docker", "run", "--rm", "--network", "none", "--mount", mount,
                doc["helper"], "tar", "-cf", "-", "-C", "/volume", ".", stdout=dst))
        if doc["storage"] == "s3":
            step("Snapshot step: saving S3 media")
            doc["s3_stream"] = cap.stream("media", lambda dst: snapshot_s3.capture(api, dst))
        staged = [doc["tree"], *doc["volume_streams"].values(), *doc["bind_streams"].values()]
        doc["staging_bytes"] = sum(cap.sizes[ident] for ident in staged)
        step("Snapshot step: committing recovery point")
        return cap.commit(doc)
    except BaseException:
        # A repository outage also makes cleanup impossible. The exact group is
        # printed for repair and contains no committed restore point.
        step("Capture interrupted. Restic capture group " + cap.group)
        if not cap.published:
            try:
                members = json.loads(output("restic", "snapshots", "--json", "--tag", cap.group))
                if members:
                    run("restic", "forget", *(m["id"] for m in members), stdout=sys.stderr)
            except (OSError, ValueError, subprocess.SubprocessError):
                step("Cleanup deferred for " + cap.group)
        raise


def create(repo, reason):
    state, api = current(repo.root, repo)
    step("Snapshot step: stopping writers")
    try:
        stop(repo.root, state["project"])
        return capture(repo, state, api, reason)
    finally:
        restart_original(repo.root, state["running"])


def legacy(root):
    result = []
    folder = Path(os.environ.get("BACKUP_DIR", root / "backups"))
    for path in sorted(folder.glob("*.dump.gz")):
        if not re.fullmatch(r"(vidra-\d{8}T\d{6}Z|pre-deploy-\d{4}-\d{2}-\d{2}T\d{6})\.dump\.gz", path.name):
            continue
        tags = {}
        stamp = path.name.removesuffix(".dump.gz")
        if stamp.startswith("vidra-"):
            stamp = stamp[6:]
            when = datetime.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
            paired = folder / ("vidra-config-" + stamp + ".tar.gz")
            if paired.is_file():
                try:
                    with tarfile.open(paired) as archive:
                        envpath = str(env_file(root))
                        member = archive.getmember(envpath)
                        if member.isfile() and member.size <= 1024 * 1024:
                            for line in archive.extractfile(member).read().decode().splitlines():
                                match = re.fullmatch(r'VIDRA_(CORE|USER|SEARCH)_TAG=(v[0-9]+\.[0-9]+\.[0-9]+)', line)
                                if match:
                                    tags[match[1].lower()] = match[2]
                except (OSError, EOFError, tarfile.TarError, ValueError, KeyError):
                    pass
            reason = "nightly"
        else:
            when = datetime.datetime.strptime(stamp[11:], "%Y-%m-%dT%H%M%S")
            reason = "pre-deploy"
        result.append(dict(kind="database", id=path.name, time=when.isoformat() + "Z", components=tags,
                           release=tags.get("core", "unknown"), reason=reason, storage="database only", bucket=""))
    return result


def history(repo):
    rows = legacy(repo.root)
    if os.environ.get("RESTIC_REPOSITORY"):
        repo.ready()
        for entry in repo.entries():
            tags = dict(t.split("=", 1) for t in entry["tags"] if "=" in t)
            components = {k: tags[k] for k in ("core", "user", "search")}
            rows.append(dict(id=entry["id"], kind="install", components=components,
                             schemas={k: int(tags[k + "_schema"]) for k in ("core", "search") if k + "_schema" in tags},
                             staging_bytes=int(tags["staging_bytes"]) if "staging_bytes" in tags else None,
                             **{k: tags[k] for k in FIELDS if k != "components"}))
    return sorted(rows, key=lambda row: row["time"], reverse=True)


def set_bucket(envpath, bucket):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("Invalid recovery bucket name")
    text = envpath.read_text()
    lines = [line for line in text.splitlines() if not re.match(r"^\s*(export\s+)?STORAGE_S3_BUCKET\s*=", line)]
    envpath.write_text("\n".join([*lines, "STORAGE_S3_BUCKET=" + bucket, ""]))


def staged_config(tree, doc):
    env = dict(os.environ, ENV_FILE=doc["env_file"], COMPOSE_PROJECT_NAME=doc["project"])
    model = json.loads(compose(tree, "config", "--format", "json", env=env))
    if model["name"] != doc["project"] or not set(doc["images"]) == set(model["services"]):
        raise ValueError("Archived configuration and service inventory disagree")
    named = {value["name"]: key for key, value in model.get("volumes", {}).items()}
    if any(named.get(name) != key for name, key in doc["volumes"].items()):
        raise ValueError("Archived configuration names different volumes")
    return model


def stream_file(repo, ident, name, path):
    with path.open("wb") as f:
        repo.extract(ident, name, lambda src: shutil.copyfileobj(src, f))


def check_space(stage, size):
    reserve = int(os.environ.get("VIDRA_RESTORE_RESERVE_BYTES", 1024 ** 3))
    if type(size) is not int or size < 0 or reserve < 0:
        raise ValueError("Invalid staging size or free-space reserve")
    free = shutil.disk_usage(stage).free
    if free < size + reserve:
        raise ValueError(f"Restore staging needs {size:,} bytes plus a {reserve:,}-byte reserve. "
                         f"The staging filesystem has {free:,} bytes free")


def prepare(repo, doc, stage, bucket, live):
    step("Restore step: verifying installation and images")
    check_space(stage, doc["staging_bytes"])
    tree = stage / "tree"
    repo.restore_tree(doc["tree"], tree)
    model = staged_config(tree, doc)
    check_datastores(model)
    if environment_digest(model) != doc["environment_digest"]:
        raise ValueError("Archived service environments differ from those captured on the running install")
    check_binds(repo.root, doc["project"], doc["binds"])
    for image in set(doc["images"].values()):
        if not IMAGE_ID.fullmatch(image):
            raise ValueError("Invalid archived image ID")
    repo.extract(doc["image_stream"], "images.tar", lambda src: run("docker", "load", stdin=src, stdout=sys.stderr))
    actual = {item["Id"] for item in inspect("image", list(set(doc["images"].values())))}
    if actual != set(doc["images"].values()):
        raise ValueError("Loaded images do not match the captured IDs")
    step("Restore step: verifying database and Docker volumes")
    assert_volumes(doc["project"], doc["volumes"], allow_missing=True)
    if set(doc["volumes"]) != set(doc["volume_streams"]):
        raise ValueError("Volume inventory is incomplete")
    for name, ident in doc["volume_streams"].items():
        path = stage / (name + ".tar")
        stream_file(repo, ident, "volume.tar", path)
        with path.open("rb") as f:
            run("docker", "run", "--rm", "-i", "--network", "none", doc["helper"], "tar", "-tf", "-",
                stdin=f, stdout=subprocess.DEVNULL)
    for index, rel in enumerate(doc["binds"]):
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("data",) or len(path.parts) < 2:
            raise ValueError("Invalid writable bind mount in archive")
        stream_file(repo, doc["bind_streams"][rel], "bind.tar", stage / f"bind-{index}.tar")
    if doc["storage"] == "s3":
        step("Restore step: recovering S3 media to new bucket")
        api = model["services"]["api"]["environment"]
        if api["STORAGE_S3_BUCKET"] != doc["bucket"] or os.environ.get("STORAGE_S3_BUCKET"):
            raise ValueError("Archived S3 configuration or process override disagrees with recovery")
        protected = [live["bucket"], doc["bucket"]]
        snapshot_s3.preflight_restore(api, bucket, protected_buckets=protected)
        repo.extract(doc["s3_stream"], "media",
                     lambda src: snapshot_s3.restore(api, src, bucket, protected_buckets=protected))
        set_bucket(tree / doc["env_file"], bucket)
        if staged_config(tree, doc)["services"]["api"]["environment"]["STORAGE_S3_BUCKET"] != bucket:
            raise ValueError("Recovered installation did not select the new bucket")


def recover(repo, doc, stage):
    root = repo.root
    project = doc["project"]
    # On a retry the host may have partially started the restored stack.
    containers = owned_containers(root, project)
    if containers:
        ids = [c["Id"] for c in containers]
        run("docker", "stop", "--time", "120", *ids, stdout=subprocess.DEVNULL)
        run("docker", "rm", *ids, stdout=subprocess.DEVNULL)
    assert_volumes(project, doc["volumes"], allow_missing=True)
    check_binds(root, project, doc["binds"])
    step("Restore step: restoring owned volumes")
    for name, key in doc["volumes"].items():
        run("docker", "volume", "create", "--label", "com.docker.compose.project=" + project,
            "--label", "com.docker.compose.volume=" + key, name, stdout=subprocess.DEVNULL)
        # Only this project's labeled, exclusive volume is mounted. Clearing it
        # avoids mixing two PostgreSQL data directories or reviving newer files.
        with (stage / (name + ".tar")).open("rb") as f:
            run("docker", "run", "--rm", "-i", "--network", "none", "-v", name + ":/volume", doc["helper"],
                "sh", "-ec", "cd /volume && find . -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xpf -", stdin=f)
    step("Restore step: restoring installation")
    state = json.loads((stage.parent / JOURNAL).read_text())
    excludes = ["--exclude=/" + rel for rel in ["backups", *doc["binds"], *state["retained_binds"]]]
    run("rsync", "-aH", "--delete", *excludes, str(stage / "tree") + "/", str(root) + "/")
    for index, rel in enumerate(doc["binds"]):
        path = root / rel
        if path != path.resolve() or root / "data" not in path.parents:
            raise ValueError("Recovered bind mount escaped its data directory")
        path.mkdir(parents=True, exist_ok=True)
        with (stage / f"bind-{index}.tar").open("rb") as f:
            run("docker", "run", "--rm", "-i", "--network", "none", "--mount",
                "type=bind,source=" + str(path) + ",target=/volume", doc["helper"], "sh", "-ec",
                "cd /volume && find . -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xpf -", stdin=f)
    env = dict(os.environ, ENV_FILE=doc["env_file"], COMPOSE_PROJECT_NAME=project)
    model = config(root)
    check_datastores(model)
    if environment_digest(model, doc["bucket"] if doc["storage"] == "s3" else None) != doc["environment_digest"]:
        raise ValueError("The restored service environments differ from the archived configuration")
    overrides = {}
    for svc, image in doc["images"].items():
        alias = "vidra-recovery/" + project + ":" + image.split(":")[1]
        configured = model["services"][svc]["image"]
        if configured.startswith("vidra-source.invalid/"):
            expected = r"vidra-source\.invalid/local/vidra-(?:core|user|search):v\d+\.\d+\.\d+-" + image.split(":")[1]
            if not re.fullmatch(expected, configured):
                raise ValueError("Source image alias disagrees with the archived image ID")
            run("docker", "image", "tag", image, configured)
        run("docker", "image", "tag", image, alias)
        overrides[svc] = {"image": alias, "pull_policy": "never",
                          "labels": {"io.vidra.snapshot-image": model["services"][svc]["image"]}}
    overlay = stage / "images.json"
    write_json(overlay, {"services": overrides})
    args = ["-f", str(overlay)]
    step("Restore step: checking restored media")
    compose(root, *args, "up", "-d", "--no-build", "--pull", "never", "--no-deps", "--wait", "postgres", "redis", env=env)
    if schema_versions(root, model, options=args, environ=env) != doc["schemas"]:
        raise ValueError("Restored database migration ledgers differ from the captured versions")
    report = json.loads(compose(root, *args, "run", "--rm", "--no-deps", "api",
                                "verify-blobs", "--hash", "--deep", "--json", "--timeout=4h", env=env))
    if type(report.get("deep_verification_version")) is not int or report["deep_verification_version"] != 1:
        raise ValueError("The recovered release could not verify exact media dependencies")
    step("Restore step: starting saved services")
    compose(root, *args, "up", "-d", "--no-build", "--pull", "never", "--wait", *doc["running"], env=env)


def restore(repo, args):
    repo.ready()
    doc = repo.read(args.ident)
    bucket = args.media_bucket
    if bucket and doc["storage"] != "s3":
        raise ValueError("A destination bucket applies only to an S3 snapshot")
    print(f"{doc['time']}  core {doc['release']}  {doc['reason']}  {doc['storage']}\n"
          f"Restore {len(doc['volumes'])} volumes and {len(doc['images'])} exact service images. "
          + ("Current state will be replaced without a safety snapshot." if args.discard_current
             else "Current state will be saved as a separate recovery point."), flush=True)
    if "staging_bytes" in doc:
        print(f"Local staging estimate: {doc['staging_bytes']:,} bytes before filesystem overhead.")
    if "schemas" in doc:
        print("Database schemas: core {core}, search {search}.".format(**doc["schemas"]))
    if not args.apply:
        if doc["storage"] == "s3":
            print("Applying this snapshot requires a separately provisioned, empty destination bucket.")
        return
    if doc["storage"] == "s3" and not bucket:
        raise ValueError("Provide a new empty --media-bucket for the recovered media")
    folder = private_dir(repo.root)
    journal = folder / JOURNAL
    previous = json.loads(journal.read_text()) if journal.exists() else None
    same_job = previous and (previous["id"], previous["bucket"], previous["discard"]) == (
        args.ident, bucket, args.discard_current)
    if same_job:
        job = previous
        stage = folder / job["stage"]
        if stage.parent != folder or not stage.is_dir() or stage.is_symlink():
            raise ValueError("Recovery staging directory is missing")
    else:
        if previous and (args.ident != previous["safety"] or not args.discard_current):
            raise ValueError("A recovery is in progress. Resume it or select its safety snapshot with --discard-current")
        if args.discard_current:
            # A failed migration can leave mixed image pins or no API. In explicit
            # replacement mode the deployment need not be healthy to recover it.
            model = config(repo.root)
            api = model["services"]["api"]["environment"]
            clients = owned_containers(repo.root, model["name"])
            live = dict(project=model["name"], bucket=api.get("STORAGE_S3_BUCKET", ""),
                        running=[c["Config"]["Labels"]["com.docker.compose.service"] for c in clients
                                 if c["State"]["Running"]],
                        volumes={v["name"]: k for k, v in model.get("volumes", {}).items()})
        else:
            live, api = current(repo.root, repo)
        if live["project"] != doc["project"] or str(env_file(repo.root)) != doc["env_file"]:
            raise ValueError("The project or active environment file differs from this snapshot")
        stage = Path(tempfile.mkdtemp(prefix=".vidra-restore-", dir=folder))
        frozen = False
        try:
            prepare(repo, doc, stage, bucket, live)
            safety = None
            if not args.discard_current:
                step("Restore step: stopping writers")
                frozen = True
                stop(repo.root, live["project"])
                safety = capture(repo, live, api, "before-restore")
                step("Saved current state as " + safety)
            job = dict(id=args.ident, bucket=bucket, discard=args.discard_current,
                       stage=stage.name, safety=safety,
                       previous_bucket=live.get("bucket", ""),
                       inactive_volumes=sorted(set(live.get("volumes", {})) - set(doc["volumes"])),
                       retained_binds=sorted(set(live.get("binds", [])) - set(doc.get("binds", []))))
            if previous:
                job["superseded_stage"] = previous["stage"]
            write_json(journal, job)
        except BaseException:
            if frozen:
                restart_original(repo.root, live["running"])
            shutil.rmtree(stage)
            if bucket:
                step("Check the separate destination bucket before retrying. A partial copy needs a fresh empty destination.")
            raise
    try:
        recover(repo, doc, stage)
    except BaseException:
        step("Recovery paused. Keep the staging directory and repeat the same restore command to resume.")
        raise
    write_json(folder / "last-install-recovery.json", job)
    journal.unlink()
    shutil.rmtree(stage)
    old_stage = job.get("superseded_stage", "")
    if re.fullmatch(r"\.vidra-restore-[A-Za-z0-9_-]+", old_stage):
        shutil.rmtree(folder / old_stage, ignore_errors=True)
    if job["inactive_volumes"]:
        step("Inactive volumes retained for review: " + ", ".join(job["inactive_volumes"]))
    if job["previous_bucket"]:
        step("Previous media bucket retained for review: " + job["previous_bucket"])
    step("Restore step: recovery complete")


def retire(repo, ident, apply):
    repo.ready()
    folder = private_dir(repo.root)
    if (folder / JOURNAL).exists():
        raise ValueError("Finish the active recovery before retiring a snapshot")
    journal = folder / ".snapshot-retirement.json"
    if journal.exists():
        receipt = json.loads(journal.read_text())
        if receipt["id"] != ident:
            raise ValueError("Finish retiring the recovery point " + receipt["id"])
    else:
        doc = repo.read(ident)
        group = doc["group"]
        if not re.fullmatch(r"vidra-capture-[a-f0-9]{32}", group):
            raise ValueError("Invalid capture group")
        receipt = dict(id=ident, group=group, time=doc["time"], release=doc["release"], reason=doc["reason"])
    rows = json.loads(output("restic", "snapshots", "--json", "--tag", receipt["group"])) or []
    catalog = [row["id"] for row in rows if repo.tag in row["tags"]]
    if catalog != [ident] and not (journal.exists() and not catalog):
        raise ValueError("Recovery point does not uniquely own its capture group")
    print(f"{receipt['time']}  {receipt['release']}  {receipt['reason']}  {len(rows)} archive parts")
    if not apply:
        print("Preview only. Use --apply to retire this entire recovery point.")
        return
    # Retain the group name across interruptions. Removing the catalog first
    # prevents advertising a restore point with missing data.
    write_json(journal, receipt)
    if catalog:
        run("restic", "forget", ident)
    parts = [r["id"] for r in rows if r["id"] != ident]
    if parts:
        run("restic", "forget", *parts)
    journal.unlink()
    print("Recovery point retired. Restic prune can reclaim unreferenced storage.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show dated install snapshots and local database dumps").add_argument("--json", action="store_true")
    sub.add_parser("create").add_argument("--reason", choices=["manual", "scheduled", "pre-upgrade"], default="manual")
    forget = sub.add_parser("retire", help="preview or retire an entire encrypted recovery point")
    forget.add_argument("ident")
    forget.add_argument("--apply", action="store_true")
    back = sub.add_parser("restore", help="preview a snapshot or restore it with --apply")
    back.add_argument("ident")
    back.add_argument("--apply", action="store_true")
    back.add_argument("--discard-current", action="store_true")
    back.add_argument("--media-bucket")
    args = parser.parse_args()
    repo = Repository(ROOT)
    if args.command == "list":
        rows = history(repo)
        if args.json:
            print(json.dumps(rows))
        else:
            print("UTC time  |  version  |  reason  |  coverage  |  ID")
            for row in rows:
                print("  |  ".join(row[k] for k in ("time", "release", "reason", "storage", "id")))
        return
    with maintenance_lock(ROOT):
        if args.command == "create":
            if (private_dir(ROOT) / JOURNAL).exists():
                raise ValueError("Finish the interrupted restore before creating another snapshot")
            print(create(repo, args.reason), flush=True)
        elif args.command == "retire":
            retire(repo, args.ident, args.apply)
        else:
            restore(repo, args)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit("vidra snapshots: " + str(exc))
