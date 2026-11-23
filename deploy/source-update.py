#!/usr/bin/env python3
"""Check for a recorded Vidra release, compile its Git sources, and deploy it."""
import argparse
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAPPING = runpy.run_path(str(ROOT / "deploy/release-mapping.py"))
UPSTREAM = "https://github.com/yegamble"
ROLES = ("core", "user", "search")
SERVICES = {"api": "core", "migrate": "core", "worker": "core",
            "frontend": "user", "search": "search", "search-migrate": "search"}
REGISTRY = "vidra-source.invalid"
HEX_ID = re.compile(r"[0-9a-f]{64}")
TAG = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def output(*args, cwd=None, **kwargs):
    return subprocess.check_output(args, cwd=cwd or ROOT, text=True, **kwargs).strip()


def run(*args, **kwargs):
    subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def value(env_file, key):
    return MAPPING["compose_value"](MAPPING["env_file_value"](env_file, key))


def semver(tag):
    require(TAG.fullmatch(tag), f"Expected a stable release tag, got {tag!r}")
    return tuple(map(int, tag[1:].split(".")))


def released(temp, requested):
    # main's merged release records are the installer's publication boundary.
    # The tag itself necessarily predates its own record's final image digests.
    meta = temp / "vidra"
    run("git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", "--depth=1",
        "--branch", "main", f"{UPSTREAM}/vidra.git", meta)
    revision = output("git", "rev-parse", "HEAD", cwd=meta)
    files = output("git", "ls-tree", "--name-only", f"{revision}:releases", cwd=meta)
    tags = [name[:-5] for name in files.splitlines() if name.endswith(".json") and TAG.fullmatch(name[:-5])]
    require(tags, "Upstream has no stable release records")
    target = requested or max(tags, key=semver)
    require(target in tags, f"{target} has no published release record")
    path = temp / f"{target}.json"
    path.write_text(output("git", "show", f"{revision}:releases/{target}.json", cwd=meta))
    _, problem = MAPPING["record_pairing"](path, target)
    require(not problem, problem)
    return json.loads(path.read_text())


def ref_for(role, tag, image_id):
    require(HEX_ID.fullmatch(image_id), f"Invalid local image ID for {role}")
    semver(tag)
    return f"{REGISTRY}/local/vidra-{role}:{tag}-{image_id}"


def check_meta(repo, record):
    tag = record["release"]
    run("git", "-C", repo, "fetch", "--quiet", "--depth=1", "origin", f"refs/tags/{tag}")
    commit = output("git", "rev-parse", "FETCH_HEAD^{commit}", cwd=repo)
    require(commit == record["meta_commit"], f"The meta tag {tag} moved relative to the release record")
    # Older releases always pull published images and cannot keep source mode across restarts.
    files = set(output("git", "ls-tree", "--name-only", "-r", commit, cwd=repo).splitlines())
    return {"docker-compose.source.yml", "deploy/source-update.py", "deploy/snapshots.py",
            "deploy/snapshot_lock.py"} <= files


def build_args(role, repo, component):
    if role == "user":
        return []  # the frontend selects its API at runtime
    args = [f"VERSION={component['tag']}", f"COMMIT={component['commit']}",
            "BUILD_DATE=" + output("git", "show", "-s", "--format=%cI", "HEAD", cwd=repo)]
    if role == "core":
        workflow = (repo / ".github/workflows/publish-container.yml").read_text()
        for key, pattern in (("YTDLP_VERSION", r"[0-9.]+"), ("YTDLP_SHA256", r"[a-f0-9]{64}")):
            hits = re.findall(rf"^ +{key}=({pattern})[ \t]*$", workflow, re.M)
            require(len(hits) == 1, f"The tagged core publish recipe lacks an unambiguous {key}")
            args.append(f"{key}={hits[0]}")
    return [arg for pair in (("--build-arg", item) for item in args) for arg in pair]


def compile_release(temp, record):
    ids = {}
    for role in ROLES:
        component = record["components"][role]
        repo = temp / f"vidra-{role}"
        run("git", "clone", "--quiet", "--depth=1", "--branch", component["tag"],
            f"{UPSTREAM}/vidra-{role}.git", repo)
        require(output("git", "rev-parse", "HEAD", cwd=repo) == component["commit"],
                f"The {role} tag moved relative to the release record")
        iid = temp / (role + ".iid")
        run("docker", "build", "--load", "--pull", "--iidfile", iid,
            "--label", "org.opencontainers.image.revision=" + component["commit"],
            "--label", "org.opencontainers.image.version=" + component["tag"],
            "--label", "io.vidra.meta-revision=" + record["meta_commit"],
            *build_args(role, repo, component), repo)
        image = iid.read_text().strip()
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", image), "Docker omitted the built image ID")
        # With a containerd-backed daemon the builder's IID can be a manifest
        # digest. Docker's .Id identifies the actual runtime configuration.
        image = output("docker", "image", "inspect", "--format", "{{.Id}}", image)
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", image), "Cannot identify local image")
        ids[role] = image[7:]
        local = ref_for(role, component["tag"], ids[role])
        run("docker", "tag", image, local)
        if role != "user":
            maximum = output("docker", "run", "--rm", "--network", "none", "--pull", "never",
                             local, "migrate", "embedded-max")
            require(maximum == str(record[f"{role}_schema_version"]),
                    f"{role} compiled a schema that differs from the recorded release")
    return ids


def config():
    return json.loads(output("bash", "deploy/compose.sh", "config", "--format", "json"))


def live_schema(record):
    # The bundled database is also required by the install snapshot mechanism.
    for role, table in (("core", "schema_migrations"), ("search", "vidra_search_migrations")):
        row = output("bash", "deploy/compose.sh", "exec", "-T", "postgres", "sh", "-ec",
                     'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 -c "$1"',
                     "sh", f"SELECT version, dirty FROM {table}")
        match = re.fullmatch(r"([0-9]+)\|f", row)
        require(match and int(match[1]) <= record[f"{role}_schema_version"],
                f"{role} database ledger is dirty, unreadable or newer than the target release")


def meta_commit():
    if (ROOT / ".git").exists():
        return output("git", "rev-parse", "HEAD")
    manifest = MAPPING["bundle_manifest"](ROOT / "vidra-bundle.manifest")
    return manifest.get("meta_commit", "")


def verify(env, running=False):
    model = config()["services"]
    expected = set(SERVICES) - {"worker"}
    require(expected <= model.keys(), f"Missing source services: {sorted(expected - model.keys())}")
    for name, service in model.items():
        repo = service.get("image", "").rsplit("/", 1)[-1].split(":", 1)[0]
        if repo in {f"vidra-{role}" for role in ROLES}:
            require(name in SERVICES, f"Source mode has no verified build for service {name}")
    for role in ROLES:
        tag = value(env, f"VIDRA_{role.upper()}_TAG")
        iid = value(env, f"VIDRA_SOURCE_{role.upper()}_ID")
        ref = ref_for(role, tag, iid)
        image = json.loads(output("docker", "image", "inspect", ref))[0]
        labels = image["Config"]["Labels"]
        require(image["Id"] == f"sha256:{iid}" and labels["org.opencontainers.image.version"] == tag
                and labels["io.vidra.meta-revision"] == meta_commit(), f"Wrong {role} source image")
        checkout = ROOT / f"vidra-{role}"
        if (checkout / ".git").exists():
            require(output("git", "rev-parse", "HEAD", cwd=checkout) == labels["org.opencontainers.image.revision"],
                    f"Installed {role} checkout and compiled image differ")
        elif role == "core" and (ROOT / "vidra-bundle.manifest").exists():
            manifest = MAPPING["bundle_manifest"](ROOT / "vidra-bundle.manifest")
            require(labels["org.opencontainers.image.revision"] == manifest.get("core_commit"),
                    "Installed bundle and compiled core commit differ")
        for name, service in model.items():
            if SERVICES.get(name) != role:
                continue
            require(service.get("image") == ref and service.get("pull_policy") == "never"
                    and not service.get("build"), f"Compose could substitute another image for {name}")
            if running and name not in ("migrate", "search-migrate"):
                containers = output("bash", "deploy/compose.sh", "ps", "-q", name).splitlines()
                require(containers and all(output("docker", "inspect", "--format", "{{.Image}}", cid)
                                           == image["Id"] for cid in containers),
                        f"{name} is not serving the verified source image")


def activate(env, ids, text=None):
    updates = {f"VIDRA_SOURCE_{role.upper()}_ID": ids[role] for role in ROLES}
    # A checkout accidentally downgraded below source support must fail its
    # pull, instead of silently going back to the upstream registry.
    updates.update(VIDRA_SOURCE_BUILD="true", VIDRA_IMAGE_REGISTRY=REGISTRY, VIDRA_IMAGE_OWNER="local")
    text = env.read_text() if text is None else text
    for key in updates:
        text = re.sub(rf"^[ \t]*(?:export[ \t]+)?{key}[ \t]*=.*(?:\n|$)", "", text, flags=re.M)
    with tempfile.NamedTemporaryFile("w", dir=env.parent, delete=False) as out:
        staged = Path(out.name)
        try:
            out.write(text.rstrip("\n") + "\n" + "".join(f"{k}={v}\n" for k, v in updates.items()))
            out.flush()
            os.fsync(out.fileno())
            os.replace(staged, env)
        finally:
            staged.unlink(missing_ok=True)


def apply(env, record, temp):
    require(os.geteuid() != 0 and ROOT.stat().st_uid == os.geteuid(), "Run as the install owner")
    require((ROOT / "deploy/snapshots.py").is_file(), "Install snapshot support before a source upgrade")
    try:
        from snapshot_lock import maintenance_lock
    except ImportError as exc:
        raise ValueError("The installed snapshot maintenance lock is missing") from exc
    require(env.is_file() and not env.is_symlink() and env.stat().st_uid == os.geteuid(),
            "The env file must be a regular file owned by the install user")
    keys = ["VIDRA_IMAGE_REGISTRY", "VIDRA_IMAGE_OWNER", "VIDRA_SOURCE_BUILD"]
    for role in ROLES:
        keys.extend([f"VIDRA_{role.upper()}_TAG", f"VIDRA_SOURCE_{role.upper()}_ID"])
    require(not any(k in os.environ for k in keys), "Unset shell overrides for release and source image pins")
    with maintenance_lock(ROOT):
        if (value(env, "VIDRA_SOURCE_BUILD") == "true" and meta_commit() == record["meta_commit"]
                and all(value(env, f"VIDRA_{r.upper()}_TAG") == record["components"][r]["tag"] for r in ROLES)):
            verify(env, running=True)
            print("The requested source release is already running.")
            return
    live_schema(record)
    ids = compile_release(temp, record)
    with maintenance_lock(ROOT) as fd:
        plan(env, record, applying=True)
        live_schema(record)
        # A checkout with tracked local edits can mix a released compose model
        # with local deployment code even when checkout --detach succeeds.
        for repo in [ROOT] + [ROOT / f"vidra-{role}" for role in ROLES]:
            if (repo / ".git").exists():
                require(not output("git", "status", "--porcelain", "--untracked-files=no", cwd=repo),
                        f"Commit or move local tracked edits in {repo}")
                require(not output("git", "ls-files", "--others", "--", "migrations", cwd=repo),
                        f"Untracked migration files in {repo} could change the schema assertion")
        child = dict(pass_fds=(fd,), env=dict(os.environ, VIDRA_MAINTENANCE_LOCK_FD=str(fd)))
        snapshot = output(sys.executable, ROOT / "deploy/snapshots.py", "create", "--reason", "pre-upgrade", **child)
        require(HEX_ID.fullmatch(snapshot), "Snapshot command did not return a complete snapshot ID")
        print(f"Preview recovery with: python3 deploy/snapshots.py restore {snapshot}", flush=True)
        # pin-release also advances the deployment tree. Stage its tag rewrites
        # on a private copy so a failed checkout/pin or interrupted build never
        # exposes a live configuration with new tags and old source image IDs.
        staged_env = temp / "pins" / env.name
        staged_env.parent.mkdir(mode=0o700)
        before = env.read_bytes()
        staged_env.write_bytes(before)
        staged_env.chmod(0o600)
        pin_env = dict(child["env"], ENV_FILE=str(staged_env))
        run("bash", "deploy/pin-release.sh", record["release"],
            *(arg for role in ROLES for arg in ("--component-tag", f"{role}={record['components'][role]['tag']}")),
            pass_fds=(fd,), env=pin_env)
        require(meta_commit() == record["meta_commit"], "Pinned deployment differs from the verified meta commit")
        for role in ROLES:
            require(value(staged_env, f"VIDRA_{role.upper()}_TAG") == record["components"][role]["tag"],
                    f"Pinned {role} tag differs from the compiled release")
        require(before == env.read_bytes(), "The live configuration changed during pinning. Source images were not activated.")
        activate(env, ids, staged_env.read_text())
        run("bash", "deploy/deploy.sh", **child)
        verify(env, running=True)
    print(f"Serving {record['release']} from verified local images.")


def plan(env, record, applying=False):
    current = {role: value(env, f"VIDRA_{role.upper()}_TAG").split("@")[0] for role in ROLES}
    target = {role: record["components"][role]["tag"] for role in ROLES}
    print(f"Recorded release {record['release']}. Configured -> target", flush=True)
    for role in ROLES:
        print(f"  {role}: {current[role]} -> {target[role]} ({record['components'][role]['commit']})", flush=True)
    if any(semver(current[r]) > semver(target[r]) for r in ROLES):
        require(not applying, "A component is newer than the target. Select a backup for a rollback.")
        print("An installed component is ahead of this release.", flush=True)
        return
    print("Already configured for this release." if current == target else "Upgrade available.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--tag", metavar="vX.Y.Z")
    commands.add_parser("verify", help="check the installed source image identities")
    args = parser.parse_args()
    env = ROOT / os.environ.get("ENV_FILE", "env/production.env")
    if args.command == "verify":
        verify(env)
        return
    with tempfile.TemporaryDirectory(prefix="vidra-source-") as scratch:
        temp = Path(scratch)
        if args.tag:
            semver(args.tag)
        record = released(temp, args.tag)
        plan(env, record, applying=args.command == "apply")
        if not check_meta(temp / "vidra", record):
            message = f"{record['release']} predates source deployment support. Its published images are available through vidra update."
            require(args.command == "check", message)
            print(message)
            return
        if args.command == "apply":
            apply(env, record, temp)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        sys.exit(f"Source update stopped. {exc}")
