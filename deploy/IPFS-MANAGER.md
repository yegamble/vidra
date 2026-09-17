# Managed public IPFS node

The optional manager gives the core a Unix HTTP interface to one fixed Compose
`ipfs` service. It never accepts a Docker command, image, path, environment,
network, or volume from an HTTP request. API and worker containers receive only
`/run/vidra-ipfs-control` read-only, with a root-owned 0660 socket for their
uid/gid 10001. The host daemon verifies Linux peer credentials. The Docker
socket is never mounted into those application containers.

Enable this only on a Linux/systemd Docker host whose public node uses the
reference `ipfs/kubo:v0.43.0` image and local `ipfs_data` volume. Configure
`IPFS_MANAGED_NODE=true` in the production env, then run:

```sh
sudo ENV_FILE=/opt/vidra/env/production.env /opt/vidra/deploy/install-ipfs-manager.sh --yes
# Or re-run sudo deploy/provision.sh, which installs it when the flag is enabled.
./deploy/deploy.sh
```

The installer renders the production model in memory and saves only the fixed
project, volume, network and numeric ports. It does not copy application secrets
into the manager. Root-owned files live in `/etc/vidra-ipfs-control`; the durable
operation ledger and rollback snapshots live in `/var/lib/vidra-ipfs-control`.
Re-running the installer updates the program/unit but refuses to retarget an
existing manager to another node. The binary and Compose snapshot are owned by
root, outside the deploy user's source tree. Docker's image must already have
been pulled by the installer; API operations never pull or select images.

The manager is dormant until an explicit admin apply. Do not keep `ipfs` or
`full` in `EXTRA_COMPOSE_PROFILES` when managed mode owns the node; the managed
overlay parks the ordinary service on a separate profile so routine stack
updates cannot replace its configuration. Only API/worker socket mounts change
on a normal deploy. Installation does not open a firewall, start Kubo, change
public gateway routes, restart the application, or publish media.

Before enabling public delivery, install the site block in
`Caddyfile.ipfs-managed.example` at the actual gateway hostname. It allows only
GET/HEAD `/ipfs/` requests, asks core's ledger/eligibility gate before every read,
overwrites forwarded URI/method headers, strips credentials to both upstreams,
and defers `Cache-Control: no-store` until every response is written, including
denials. Use DNS-only routing or a verified cache-bypass rule for this hostname;
an edge rule must never override withdrawal authorization. Keep the gateway's loopback origin inaccessible from
the internet, and remove any direct route around the gate. The API must be at
the release that implements `/api/v1/ipfs/gateway/authorize`; an older API fails
closed. `Gateway.NoFetch=true` prevents remote fetching but does not authorize
cached bytes: the gateway gate is required for prompt privacy withdrawal. Copies
already held by other public IPFS peers cannot be revoked.

Choose publication policy in the admin UI. A starting beta budget is 20 GiB,
with 20 GiB free-space floor, one copy worker and 2 MiB/s copy throughput;
catalogue backfill stays disabled. These are deployment choices, not global
manager defaults. The manager configures Kubo's *soft* StorageMax threshold and
reports actual repository and host-filesystem usage. Core enforces admission,
reservations, removal priority and copy pacing; a full repository's pinned bytes
are not automatically collectible. The copy-rate limit does not limit total
swarm traffic. B2 and its existing Cloudflare endpoint remain authoritative.

A persisted private/swarm-key or local-only repository is refused before it is
stopped or reconfigured. The manager does not inspect the application DB and
therefore does not try to prove those unknown pins public. Use an operator-
reviewed, separate empty public volume instead; never delete or convert the
private volume to silence the refusal. An already-public node retains its
identity, volume and public pins. Empty volumes are initialized offline, then
configured for public providing with NoFetch enabled before the daemon starts.
Pausing admissions (`enabled=false`) retains serving and privacy withdrawals;
it does not stop Kubo.

Operations use a SQLite durable ledger: request IDs are idempotent, changed-body
reuse conflicts, and accepted sequence/config revisions cannot move backward.
A process lock excludes a second host manager. An interrupted operation is
replayed with its original identity. The fixed apply stops only `ipfs`, atomically
updates the repository config, starts only `ipfs`, and checks readiness. Failure
restores the prior config and running state without deleting data. Status never
returns command output or configuration secrets; unknown observations have null
capacity and stale timestamps are not refreshed by polling.

Docker restarts the node after crashes/reboot. The manager's watchdog makes at
most three additional recovery attempts, with 60/120/240-second backoff. That
budget survives manager restarts and resets only after an explicit new admin
operation. Exhaustion is visible as `ipfs_recovery_exhausted`; inspect
`journalctl -u vidra-ipfs-manager` and the fixed `ipfs` container before retrying.
The manager itself has bounded systemd restart limits.

Back up the root-owned manager configuration and state together with the normal
application/host backups. Rollback snapshots include the IPFS peer identity and
must remain private. Do not copy a live SQLite file alone: use SQLite's online
backup API or stop the manager while taking the host snapshot. Restore its
monotonic operation ledger together with the corresponding core DB. A mismatched
or older DB must not reset the host ledger; sequence conflicts deliberately pause
control until an operator reconciles recovery state. The IPFS cache does not
replace the B2/application backups.

Protocol v1: `GET /v1/status`, `POST /v1/apply`, `POST /v1/restart`. Requests are
limited to 8 KiB, have a three-second socket deadline and exact schemas. Positive
signed-int64 sequence/revision values are required. Budget is 1 MiB–1 PiB, free
floor 0–1 PiB, copy rate 64 KiB–1 GiB/s, workers 1–8. Capacity is measured from the
actual local Docker-volume filesystem, not the web container's overlay. External
nodes and Docker user-namespace remapping are not managed by this installer.

Verification: `python3 -m unittest discover -s tests -p '*_test.py'` includes the
manager protocol, durable fencing, recovery and rollback unit tests. On a
disposable Linux Docker host, `sudo python3 tests/ipfs_manager_smoke.py` exercises
real Kubo init/apply/restart/rollback and the Caddy gate using only unique test
resources. Its Kubo network is internal, so no content is globally published.
The harness removes its own containers, network and empty test volume, and
refuses to report success when Linux/root prerequisites are missing.
`python3 tests/ipfs_manager_smoke.py --gateway-only` runs the Caddy portion on
Docker Desktop too; that narrower result does not certify host lifecycle.
