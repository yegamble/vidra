#!/usr/bin/env bash
#
# Copy the ONE certificate + key the RTMPS front needs out of Caddy's data
# volume into RTMPS_CERT_DIR, then reload the rtmps proxy so a renewal takes
# effect without dropping the process.
#
#   ./deploy/sync-rtmps-certs.sh
#   ENV_FILE=env/staging.env ./deploy/sync-rtmps-certs.sh
#
# WHY A COPY and not a mount: the rtmps proxy is internet-facing. Mounting
# Caddy's whole `caddy_data` volume into it (even read-only) would put the ACME
# account key and any internal-CA key one nginx bug away from a remote reader.
# Copying exactly two files keeps the blast radius to the one host name's key.
# (Compose `volumes.subpath` would also work but needs Compose >= 2.27, above
# this repo's 2.24 floor.)
#
# WHY A TIMER: Caddy renews certificates roughly every 60 days and the proxy
# reads them only at start/reload, so without this the RTMPS listener would
# silently serve an expired certificate and every encoder would start failing
# TLS. deploy/vidra-rtmps-certs.timer runs this daily; it is idempotent and only
# reloads when the bytes actually changed.
#
# Source host name: RTMPS_CERT_HOST, else the host in LIVE_RTMPS_URL. It must be
# a name Caddy serves (so Caddy holds a certificate for it). Destination:
# RTMPS_CERT_DIR (default deploy/rtmps-certs), files fullchain.pem / privkey.pem,
# mode 0640. If you supply your own certificate instead, do not run this.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-env/production.env}"

log() { printf '[rtmps-certs] %s\n' "$*"; }
die() { printf '[rtmps-certs] ERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"

# shellcheck source=deploy/lib.sh
. "$REPO_ROOT/deploy/lib.sh"

HOST="$(env_get RTMPS_CERT_HOST "")"
if [ -z "$HOST" ]; then
  url="$(env_get LIVE_RTMPS_URL "")"
  [ -n "$url" ] || die "set RTMPS_CERT_HOST (or LIVE_RTMPS_URL) in $ENV_FILE - no host name to copy a certificate for"
  HOST="${url#*://}"; HOST="${HOST%%/*}"; HOST="${HOST%%:*}"
fi
# The name becomes a path component inside the caddy container: allow only what
# a DNS name contains, so a typo cannot walk out of the certificates directory.
case "$HOST" in
  ''|*[!A-Za-z0-9.-]*|.*|*..*) die "refusing suspicious host name '$HOST'" ;;
esac

DEST="$(env_get RTMPS_CERT_DIR "deploy/rtmps-certs")"
case "$DEST" in /*) ;; *) DEST="$REPO_ROOT/$DEST" ;; esac
mkdir -p "$DEST"

compose() { "$REPO_ROOT/deploy/compose.sh" "$@"; }

# The issuer directory differs (ACME CA vs Caddy's internal CA), so find the
# file by host name instead of hard-coding the issuer.
crt_path="$(compose exec -T caddy find /data/caddy/certificates -type f -name "$HOST.crt" 2>/dev/null | head -n1 | tr -d '\r')"
[ -n "$crt_path" ] || die "caddy holds no certificate for $HOST yet (is it in the Caddyfile and has it been requested?)"
key_path="${crt_path%.crt}.key"

umask 077
tmp="$(mktemp -d "$DEST/.sync.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
compose exec -T caddy cat "$crt_path" > "$tmp/fullchain.pem" || die "could not read $crt_path"
compose exec -T caddy cat "$key_path" > "$tmp/privkey.pem" || die "could not read $key_path"
[ -s "$tmp/fullchain.pem" ] && [ -s "$tmp/privkey.pem" ] || die "copied certificate or key is empty"
chmod 0640 "$tmp/fullchain.pem" "$tmp/privkey.pem"

changed=0
for f in fullchain.pem privkey.pem; do
  if ! cmp -s "$tmp/$f" "$DEST/$f" 2>/dev/null; then
    mv -f "$tmp/$f" "$DEST/$f"   # same filesystem: atomic replace
    changed=1
  fi
done

if [ "$changed" -eq 0 ]; then
  log "certificate for $HOST unchanged"
  exit 0
fi
log "updated certificate for $HOST in $DEST"

# Reload only if the proxy is up; first install runs this BEFORE starting it.
if [ -n "$(compose ps -q rtmps 2>/dev/null)" ]; then
  compose exec -T rtmps nginx -s reload || die "certificate copied but 'nginx -s reload' failed"
  log "rtmps reloaded"
else
  log "rtmps is not running; it will read the new certificate when started"
fi
