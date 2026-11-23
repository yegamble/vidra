"""Identify the actual Compose project, its writers, image IDs and owned volumes."""
import json
import os
import re
import sys
from pathlib import Path

from snapshot_repo import output, run

SAFE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
COMPONENTS = {"core": "api", "user": "frontend", "search": "search"}


def compose(root, *args, **kwargs):
    return output("bash", root / "deploy/compose.sh", *args, cwd=root, **kwargs)


def config(root):
    # lib.sh emits its informational profile notes before the actual render.
    raw = compose(root, "config", "--format", "json").decode()
    return json.loads(raw[raw.index("{"):])


def inspect(kind, names):
    if not names:
        return []
    return json.loads(output("docker", kind, "inspect", *names))


def project_containers(project):
    ids = output("docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project).split()
    return inspect("container", list(map(bytes.decode, ids)))


def owned_containers(root, project):
    containers = project_containers(project)
    for c in containers:
        workdir = c["Config"]["Labels"].get("com.docker.compose.project.working_dir", "")
        if Path(workdir).resolve() != root:
            raise ValueError("A different installation is using the same Compose project name")
    return containers


def assert_volumes(project, names, allow_missing=False):
    existing = set(output("docker", "volume", "ls", "-q").decode().splitlines())
    for name in names:
        if not SAFE_NAME.fullmatch(name):
            raise ValueError("Invalid Docker volume name")
        if name not in existing and allow_missing:
            continue
        info, = inspect("volume", [name])
        if ((info.get("Labels") or {}).get("com.docker.compose.project") != project
                or info["Driver"] != "local" or info.get("Options")):
            raise ValueError("Volume is shared, external or uses driver options: " + name)
        clients = output("docker", "ps", "-aq", "--filter", "volume=" + name).decode().split()
        for client in inspect("container", clients):
            if client["Config"]["Labels"].get("com.docker.compose.project") != project:
                raise ValueError("Another Docker project has mounted " + name)


def inventory(root):
    model = config(root)
    project = model["name"]
    services = model["services"]
    api = services["api"]["environment"]
    if "postgres" not in services or "redis" not in services or api.get("VIDRA_EXTERNAL_POSTGRES") == "true":
        raise ValueError("The snapshot requires Vidra-managed PostgreSQL and Redis")
    if api.get("STORAGE_MIGRATION_TARGET_BACKEND") or api.get("PEERTUBE_IMPORT_MEDIA_MODE") == "reference":
        raise ValueError("Finish the storage migration or copy referenced PeerTube objects first")
    backend = api.get("STORAGE_BACKEND", "local")
    if backend not in {"s3", "local"}:
        raise ValueError("Unsupported media backend")
    images, active, volumes, mounted, binds = {}, [], {}, set(), set()
    containers = owned_containers(root, project)
    for container in containers:
        labels = container["Config"]["Labels"]
        service = labels["com.docker.compose.service"]
        if (service not in services or labels.get("com.docker.compose.oneoff", "").lower() == "true"
                or service in images):
            raise ValueError("Unexpected container, replica or one-off job in project: " + service)
        expected = services[service]["image"]
        if container["Config"]["Image"] != expected:
            # A previous restore recreates containers using immutable local aliases.
            if not container["Config"]["Image"].startswith("vidra-recovery/") or not labels.get("io.vidra.snapshot-image"):
                raise ValueError("Running container disagrees with the configured image: " + service)
            if labels["io.vidra.snapshot-image"] != expected:
                raise ValueError("Release pins have changed since the restored container started")
        if not IMAGE_ID.fullmatch(container["Image"]):
            raise ValueError("Invalid Docker image ID")
        images[service] = container["Image"]
        if container["State"]["Running"]:
            active.append(service)
        for mount in container["Mounts"]:
            if mount["Type"] == "volume":
                name = mount["Name"]
                key = next((k for k, v in model.get("volumes", {}).items() if v["name"] == name), None)
                if not key:
                    raise ValueError("Unrecognized or anonymous volume: " + name)
                volumes[name] = key
                mounted.add((service, mount["Destination"]))
            elif mount["Type"] == "bind":
                source = next((v["source"] for v in services[service].get("volumes", [])
                               if v["type"] == "bind" and v["target"] == mount["Destination"]), None)
                if not source:
                    raise ValueError("Unknown bind mount on " + service)
                path = Path(source).resolve()
                daemon_paths = {str(path)}
                if sys.platform == "darwin":
                    daemon_paths.add("/host_mnt" + str(path))
                if mount["Source"] not in daemon_paths or root not in path.parents or root / "backups" in (path, *path.parents):
                    raise ValueError("Bind mount outside the install snapshot: " + str(path))
                if mount["RW"]:
                    if root / "data" not in path.parents or not path.is_dir() or "," in str(path):
                        raise ValueError("Writable bind mount needs a dedicated directory under data/: " + str(path))
                    binds.add(str(path.relative_to(root)))
                mounted.add((service, mount["Destination"]))
            elif mount["Type"] != "tmpfs":
                raise ValueError("Unsupported mount type: " + mount["Type"])
    if not set(COMPONENTS.values()) | {"postgres"} <= set(images):
        raise ValueError("Install the core, frontend, search and PostgreSQL services first")
    if "postgres" not in active:
        raise ValueError("PostgreSQL must be running to establish a recovery point")
    pgmounts = [dest for svc, dest in mounted if svc == "postgres"]
    if not any(Path(dest) in (Path("/var/lib/postgresql/data"), Path("/var/lib/postgresql")) for dest in pgmounts):
        raise ValueError("PostgreSQL data is outside a captured mount")
    if backend == "local":
        media = Path(api.get("STORAGE_LOCAL_ROOT", "/app/data/media"))
        if not any(svc == "api" and Path(dest) in (media, *media.parents) for svc, dest in mounted):
            raise ValueError("Local media is outside the API's captured mounts")
    # Dependencies that only ran as one-shots may have had their containers removed.
    for name, spec in services.items():
        if name not in images:
            images[name] = inspect("image", [spec["image"]])[0]["Id"]
    helper = images["prep-volumes"]
    assert_volumes(project, volumes)
    variables = dict(line.split("=", 1) for line in compose(root, "config", "--environment").decode().splitlines()
                     if "=" in line)
    tags = {key: variables.get("VIDRA_" + key.upper() + "_TAG", "") for key in COMPONENTS}
    if not all(re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:@sha256:[0-9a-f]{64})?", tag) for tag in tags.values()):
        raise ValueError("Configure released Vidra component tags before taking an install snapshot")
    return {"project": project, "images": images, "helper": helper, "volumes": volumes,
            "binds": sorted(binds), "running": sorted(active), "components": tags, "storage": backend,
            "bucket": api.get("STORAGE_S3_BUCKET", "") if backend == "s3" else ""}, api


def stop(root, project):
    owned_containers(root, project)
    compose(root, "stop", "--timeout", "120")
    for container in project_containers(project):
        if container["State"]["Running"] or container["State"].get("ExitCode") == 137:
            raise ValueError("Could not prove a clean shutdown of " + container["Name"])


def restart_original(root, running):
    if running:
        compose(root, "start", *running)


def archive_volume(manifest, name, sink):
    run("docker", "run", "--rm", "--network", "none", "-v", name + ":/volume:ro",
        manifest["helper"], "tar", "-cf", "-", "-C", "/volume", ".", stdout=sink)
