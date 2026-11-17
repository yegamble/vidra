#!/usr/bin/env bash
# tests/peertube-interop/run.sh — bring up the PeerTube federation interop lab,
# prove the harness with the CONTROL, then run S1-S8 against vidra.
#
#   run.sh --control-only   PeerTube <-> PeerTube only; no vidra container exists
#   run.sh                  the control, then S1-S8 against vidra
#   run.sh --keep ...       leave the stack up afterwards for poking at
#   run.sh down             destroy both Compose projects and their volumes
#
# THE CONTROL IS NOT OPTIONAL AND IS NEVER SKIPPED. Everything vidra-specific in
# this lab sits on top of a private CA, DNS aliases on a Docker network, a TLS
# edge and PeerTube's SSRF guard being switched off. If any of those is wrong,
# EVERY vidra scenario fails, and it fails looking exactly like a vidra bug. So
# two stock PeerTube instances must follow each other and federate a video
# through the same edge first. If they cannot, this script stops there and says
# the harness is broken: a harness bug must never be read as a vidra bug.
#
# Exit codes: 0 every scenario that ran passed; 1 at least one vidra scenario
# failed (an expected outcome while the plan's gaps are open — read the table);
# 2 the control failed or the lab could not be built (nothing about vidra was
# measured).
set -euo pipefail

log() { printf '[pt-interop] %s\n' "$*"; }
die() { printf '[pt-interop] ERROR: %s\n' "$*" >&2; exit 2; }
step() { printf '\n[pt-interop] ===== %s =====\n' "$*"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
export LAB_OUT="${LAB_OUT:-$HERE/out}"
export EDGE_PORT="${EDGE_PORT:-8443}"
# Fixed literals, matching the `:-` defaults in docker-compose.yml. The stack
# holds no data and is destroyed on every run; see that file's header.
export PT_ROOT_PASSWORD="${PT_ROOT_PASSWORD:-lab-only-root-password}"

CONTROL_ONLY=0
KEEP=0
DOWN=0
for arg in "$@"; do
  case "$arg" in
    --control-only) CONTROL_ONLY=1 ;;
    --keep) KEEP=1 ;;
    down) DOWN=1 ;;
    *) die "unknown argument: $arg (usage: run.sh [--control-only] [--keep] | run.sh down)" ;;
  esac
done

LAB=(docker compose -f "$HERE/docker-compose.yml")
# An explicit -f chain, so the auto-loaded docker-compose.override.yml (which
# wires search in) is NOT loaded: the vidra under test is the root file plus the
# lab overlay and nothing else. --project-directory keeps the root file's
# relative build contexts resolving against the repo root.
VIDRA=(docker compose -p ptinterop-vidra --project-directory "$ROOT"
  -f "$ROOT/docker-compose.yml" -f "$HERE/docker-compose.vidra.yml"
  --env-file "$LAB_OUT/vidra.env" --profile core)

destroy() {
  # vidra first: its api is attached to the lab network, and Compose cannot
  # remove a network that still has an endpoint on it.
  if [ -f "$LAB_OUT/vidra.env" ] && [ -f "$LAB_OUT/ca/root.crt" ]; then
    "${VIDRA[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  mkdir -p "$LAB_OUT/ca"
  "${LAB[@]}" --profile vidra down -v --remove-orphans >/dev/null 2>&1 || true
}

if [ "$DOWN" -eq 1 ]; then
  step "destroying the lab"
  destroy
  log "both projects and their volumes are gone; $LAB_OUT is left for reading"
  exit 0
fi

# ---------------------------------------------------------------- preflight
step "preflight"
command -v docker >/dev/null || die "docker is not installed"
docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable — start it and re-run"
command -v node >/dev/null || die "node is not installed (the driver needs Node >= 18)"
command -v openssl >/dev/null || die "openssl is not installed (the lab CA is minted with it)"
command -v curl >/dev/null || die "curl is not installed"

# docker-compose.vidra.yml closes the base files' 0.0.0.0 publishes with
# `!reset`. Compose < 2.24 silently IGNORES that tag and would publish vidra's
# Postgres and Redis on every interface — the exact failure hard rule 4 names.
compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
compose_major="${compose_version%%.*}"
compose_rest="${compose_version#*.}"
compose_minor="${compose_rest%%.*}"
case "$compose_major$compose_minor" in
  ''|*[!0-9]*) die "cannot parse the Compose version from '$compose_version'" ;;
esac
if [ "$compose_major" -lt 2 ] || { [ "$compose_major" -eq 2 ] && [ "$compose_minor" -lt 24 ]; }; then
  die "Docker Compose >= 2.24 is required for the !reset merge tag (found $compose_version)"
fi

# Headroom, not a measurement of need: sampled mid-run the whole lab held about
# 1.1 GiB resident, but the vidra image build and PeerTube's ffmpeg jobs spike
# well above that. Refusing here names the cause; an OOM-killed PeerTube
# mid-scenario would read as a federation failure.
mem_bytes="$(docker info --format '{{.MemTotal}}')"
need_bytes=$((3 * 1024 * 1024 * 1024))
[ "$CONTROL_ONLY" -eq 1 ] || need_bytes=$((5 * 1024 * 1024 * 1024))
if [ "$mem_bytes" -lt "$need_bytes" ]; then
  die "Docker has $((mem_bytes / 1024 / 1024)) MiB of memory; this run needs at least $((need_bytes / 1024 / 1024)) MiB"
fi
log "docker ok: compose $compose_version, $((mem_bytes / 1024 / 1024)) MiB"

if [ "$CONTROL_ONLY" -eq 0 ]; then
  [ -f "$ROOT/vidra-core/docker-compose.yml" ] \
    || die "no nested vidra-core checkout at $ROOT/vidra-core — run ./bootstrap.sh first"
  # The evidence note names the commit it measured. A dirty checkout has no
  # name, so say so loudly rather than attribute its behaviour to a SHA.
  core_sha="$(git -C "$ROOT/vidra-core" rev-parse HEAD)"
  core_dirty="$(git -C "$ROOT/vidra-core" status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
  log "vidra-core under test: $core_sha (tracked files modified: $core_dirty)"
fi

# ------------------------------------------------------------------ clean slate
# Federation state is durable on both sides (follows, actors, cached keys). A
# second run on yesterday's volumes would pass S1 because the follow already
# exists, having sent nothing. Every run starts from nothing.
step "destroying any previous lab"
destroy
rm -rf "$LAB_OUT"
mkdir -p "$LAB_OUT/ca" "$LAB_OUT/logs"

# ---------------------------------------------------------------------- lab CA
step "minting the throwaway lab CA"
# A config file, not -addext: macOS ships LibreSSL, whose `req` has no -addext.
cat > "$LAB_OUT/ca/openssl.cnf" <<'CNF'
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[dn]
CN = vidra peertube-interop lab root (throwaway)
[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
CNF
openssl ecparam -name prime256v1 -genkey -noout -out "$LAB_OUT/ca/root.key" 2>/dev/null \
  || die "openssl could not generate the CA key"
openssl req -x509 -new -key "$LAB_OUT/ca/root.key" -sha256 -days 30 \
  -config "$LAB_OUT/ca/openssl.cnf" -out "$LAB_OUT/ca/root.crt" 2>/dev/null \
  || die "openssl could not self-sign the CA certificate"
# Caddy runs as root in its image; PeerTube and vidra run unprivileged and read
# only the certificate, which is public by nature.
chmod 644 "$LAB_OUT/ca/root.crt"
log "CA: $(openssl x509 -in "$LAB_OUT/ca/root.crt" -noout -subject -enddate | tr '\n' ' ')"

# -------------------------------------------------------------- collect logs
# On EVERY exit, pass or fail: the logs are the product. PeerTube says why it
# dropped an object only in its debug log, and that log dies with the container.
# shellcheck disable=SC2329  # invoked by the EXIT trap below
collect() {
  local rc=$?
  trap - EXIT
  step "collecting logs into $LAB_OUT/logs"
  local svc
  for svc in pt ctl edge vidra-caddy; do
    "${LAB[@]}" --profile vidra logs --no-color --no-log-prefix "$svc" > "$LAB_OUT/logs/$svc.log" 2>&1 || true
  done
  if [ -f "$LAB_OUT/vidra.env" ]; then
    "${VIDRA[@]}" logs --no-color --no-log-prefix api > "$LAB_OUT/logs/vidra-api.log" 2>&1 || true
  fi
  if [ "$KEEP" -eq 1 ]; then
    log "--keep: the stack is still up. Destroy it with: $0 down"
  else
    step "tearing the lab down"
    destroy
  fi
  log "results: $LAB_OUT/results-*.json   logs: $LAB_OUT/logs/"
  exit "$rc"
}
trap collect EXIT

# Reach an app the way the driver does: the edge's loopback port, with the
# app's own name for SNI and Host, trusting only the lab CA.
edge_curl() {
  local host="$1" path="$2"
  curl -fsS --max-time 10 --cacert "$LAB_OUT/ca/root.crt" \
    --resolve "$host:$EDGE_PORT:127.0.0.1" "https://$host:$EDGE_PORT$path"
}

wait_for() {
  local what="$1" host="$2" path="$3" tries="$4" n=0
  until edge_curl "$host" "$path" >/dev/null 2>&1; do
    n=$((n + 1))
    [ "$n" -lt "$tries" ] || return 1
    sleep 3
  done
  log "$what is answering at https://$host$path"
}

# -------------------------------------------------------------- PeerTube up
step "starting PeerTube v8.3.2 (pt), the control PeerTube (ctl) and the edge"
"${LAB[@]}" up -d edge pt ctl
# First boot runs every PeerTube migration against an empty database.
wait_for "pt" pt.interop.test /api/v1/ping 80 \
  || { "${LAB[@]}" logs --tail=60 pt >&2; die "pt never answered /api/v1/ping through the edge"; }
wait_for "ctl" ctl.interop.test /api/v1/ping 80 \
  || { "${LAB[@]}" logs --tail=60 ctl >&2; die "ctl never answered /api/v1/ping through the edge"; }

# THE trust check, from INSIDE a PeerTube container and with PeerTube's own
# runtime: if Node there cannot complete a handshake with the other instance,
# no amount of ActivityPub will work, and the failure would otherwise surface
# as a follow that sits in `pending` forever.
"${LAB[@]}" exec -T pt node -e '
  fetch("https://ctl.interop.test/api/v1/ping").then(r => { if (!r.ok) throw new Error("HTTP " + r.status); })
    .catch(e => { console.error(e.cause ? e.cause.message : e.message); process.exit(1); });
' || die "pt cannot reach https://ctl.interop.test with the lab CA trusted — the harness TLS/DNS wiring is broken"
log "pt -> ctl over https verifies against the lab CA from inside the container"

# ------------------------------------------------------------------- fixture
step "generating the video fixture"
# No fixture is committed (none should be), and the PeerTube image already
# carries ffmpeg, so the lab needs none on the host. 4 s, 320x240, WITH an audio
# stream: vidra's CMAF packager treats a missing audio track as a failure.
"${LAB[@]}" exec -T pt ffmpeg -nostdin -loglevel error -y \
  -f lavfi -i testsrc2=size=320x240:rate=30 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -t 4 -c:v libx264 -pix_fmt yuv420p -preset veryfast -c:a aac -b:a 96k \
  -movflags +faststart /tmp/interop-fixture.mp4 \
  || die "ffmpeg inside the pt container could not produce the fixture"
"${LAB[@]}" cp pt:/tmp/interop-fixture.mp4 "$LAB_OUT/fixture.mp4" >/dev/null
[ -s "$LAB_OUT/fixture.mp4" ] || die "the fixture is empty"
log "fixture: $(wc -c < "$LAB_OUT/fixture.mp4" | tr -d ' ') bytes"

export LAB_FIXTURE="$LAB_OUT/fixture.mp4"
export LAB_CA_FILE="$LAB_OUT/ca/root.crt"
export LAB_COMPOSE_FILE="$HERE/docker-compose.yml"

# ------------------------------------------------------------------- control
step "CONTROL: PeerTube <-> PeerTube follow plus a federated video"
if ! node "$HERE/driver.mjs" control; then
  die "THE CONTROL FAILED. Two stock PeerTube instances could not federate through this lab, so the harness (CA, DNS, edge, PeerTube settings) is broken. No vidra scenario was run and NOTHING here is evidence about vidra. See $LAB_OUT/logs/"
fi
log "control passed: the harness federates PeerTube to PeerTube"

if [ "$CONTROL_ONLY" -eq 1 ]; then
  log "--control-only: stopping here"
  exit 0
fi

# --------------------------------------------------------------------- vidra
step "writing the lab vidra env file"
# Throwaway values generated per run. Every key has a consumer in
# vidra-core/docker-compose.yml's allow-list — there is no wildcard passthrough,
# so a key that file does not name would be silently dead.
OWNER_CLAIM_TOKEN="$(openssl rand -hex 24)"
export OWNER_CLAIM_TOKEN
cat > "$LAB_OUT/vidra.env" <<ENV
# NOT production: production boot REFUSES HTTP_IMPORT_ALLOW_PRIVATE_URLS and
# OWNER_CLAIM_TOKEN (internal/config), and the lab cannot run without the
# first — every address here is a Docker one. The plan asked for "staging";
# vidra-core accepts only development|test|production and exits on anything
# else, and "test" differs from production in nothing but those refusals.
VIDRA_ENV=test
PUBLIC_BASE_URL=https://vidra.interop.test
CORS_ALLOWED_ORIGINS=https://vidra.interop.test
JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')
MFA_KEY_KEK=$(openssl rand -base64 32 | tr -d '\n')
POSTGRES_USER=vidra
POSTGRES_PASSWORD=$(openssl rand -hex 16)
POSTGRES_DB=vidra
STORAGE_BACKEND=local
MAIL_ENABLED=false
METRICS_ENABLED=true
LOG_FORMAT=json
# debug: the vidra half of every failing scenario's evidence.
LOG_LEVEL=debug
# Required by a \`:?\` on the search service even though the lab never starts it.
SEARCH_INTERNAL_SECRET=$(openssl rand -hex 32)
# --- what this lab is for -------------------------------------------------
FEDERATION_ENABLED=true
# Throwaway. On a real instance this key is permanent and destructive to rotate.
FEDERATION_KEY_KEK=$(openssl rand -base64 32 | tr -d '\n')
# LAB ONLY: this one switch relaxes the importer's AND federation's SSRF guard
# (plan gap G14). With it on, the lab proves nothing about SSRF.
HTTP_IMPORT_ALLOW_PRIVATE_URLS=true
# Deterministic owner bootstrap, so the driver does not scrape a token out of a
# log. Dev/test only by construction; production refuses it.
OWNER_CLAIM_TOKEN=$OWNER_CLAIM_TOKEN
# --- same reasons as the stack-e2e lane -----------------------------------
TRANSCODING_ENABLED=true
TRANSCODING_MIN_FREE_SCRATCH_MB=256
MALWARE_SCAN_MODE=disabled
RATE_LIMIT_ENABLED=false
REGISTRATION_ENABLED=false
ENV
chmod 600 "$LAB_OUT/vidra.env"

step "rendering the real deploy/Caddyfile for the lab"
# ONE substitution: the site address. `http://` because the edge has already
# terminated TLS, exactly as a deployment behind Cloudflare or an external load
# balancer would run this file. Every route, matcher and upstream below that
# line is the shipped one — that is the thing under test.
sed 's|^example\.com {$|http://vidra.interop.test {|' "$ROOT/deploy/Caddyfile" > "$LAB_OUT/Caddyfile.vidra"
grep -q '^http://vidra\.interop\.test {$' "$LAB_OUT/Caddyfile.vidra" \
  || die "deploy/Caddyfile no longer has an 'example.com {' site line — the lab render matched nothing"
# The same guard deploy.sh applies: no placeholder may survive outside comments.
if grep -v '^[[:space:]]*#' "$LAB_OUT/Caddyfile.vidra" | grep -q 'example\.com'; then
  die "the rendered Caddyfile still names example.com on a non-comment line"
fi

step "building and starting vidra (postgres, redis, migrate, api) from this repo's compose files"
"${VIDRA[@]}" up -d --build --wait api \
  || { "${VIDRA[@]}" logs --tail=80 api migrate >&2; die "vidra's api did not become healthy"; }

# Assert the lab's own rule instead of trusting the overlay: one published
# port in the whole lab, and it is loopback.
published="$(docker ps --filter 'label=com.docker.compose.project=ptinterop' \
  --filter 'label=com.docker.compose.project=ptinterop-vidra' --format '{{.Ports}}' \
  | tr ',' '\n' | grep -- '->' | grep -v '^ *127\.0\.0\.1:' || true)"
[ -z "$published" ] || die "a lab container publishes off loopback: $published"

"${LAB[@]}" --profile vidra up -d vidra-caddy
wait_for "vidra (through the shipped Caddyfile)" vidra.interop.test /readyz 40 \
  || die "vidra never answered /readyz through edge -> deploy/Caddyfile -> api"
"${LAB[@]}" exec -T pt node -e '
  fetch("https://vidra.interop.test/.well-known/nodeinfo").then(r => { if (!r.ok) throw new Error("HTTP " + r.status); })
    .catch(e => { console.error(e.cause ? e.cause.message : e.message); process.exit(1); });
' || die "pt cannot fetch vidra's NodeInfo discovery document — federation routes are not mounted or not reachable"
"${VIDRA[@]}" exec -T api wget -qO- https://pt.interop.test/api/v1/ping >/dev/null \
  || die "vidra's api cannot reach https://pt.interop.test with the lab CA trusted"
log "vidra and pt reach each other over https in both directions"

step "S1-S8 against vidra"
export LAB_VIDRA_PROJECT=ptinterop-vidra
set +e
node "$HERE/driver.mjs" vidra
driver_rc=$?
set -e
# 1 = scenarios failed (a finding); anything else non-zero = the driver itself
# broke, which is a harness failure and must not be reported as a finding.
case "$driver_rc" in
  0) log "every scenario passed" ;;
  1) log "at least one scenario FAILED — read $LAB_OUT/results-vidra.json and the logs" ;;
  *) die "the driver crashed (exit $driver_rc) — this is a harness failure, not a vidra result" ;;
esac
exit "$driver_rc"
