#!/usr/bin/env bash
# Build payloads, start the logging Range origin, init + start an OFFLINE Kubo.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

step "payloads"
[ -f "$DATA/payload1.bin" ] || dd if=/dev/urandom of="$DATA/payload1.bin" bs=1m count=64 2>/dev/null
[ -f "$DATA/payload2.bin" ] || dd if=/dev/urandom of="$DATA/payload2.bin" bs=1m count=64 2>/dev/null
# T3 HLS tree. Disk names flatten '/' to '__'; origin.py maps the URL path back.
[ -f "$DATA/hls__master.m3u8" ] || python3 - "$DATA" <<'PY'
import os, sys
d = sys.argv[1]
m3u8 = ("#EXTM3U\n#EXT-X-VERSION:7\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=1280x720,CODECS=\"avc1.64001f,mp4a.40.2\"\n"
        "720p/index.m3u8\n") + "# pad " + "x" * 90 + "\n"
open(os.path.join(d, "hls__master.m3u8"), "w").write(m3u8)
open(os.path.join(d, "hls__720p__init.mp4"), "wb").write(os.urandom(700))
open(os.path.join(d, "hls__720p__seg-1.m4s"), "wb").write(os.urandom(3 * 1024 * 1024))
PY
ls -l "$DATA"

step "origin"
origin_mode normal
if ! nc -z 127.0.0.1 "$ORIGIN_PORT" 2>/dev/null; then
  nohup python3 "$SPIKE_DIR/origin.py" "$DATA" "$ORIGIN_PORT" "$ORIGIN_LOG" "$MODEFILE" \
        > "$OUT/origin-stdout.txt" 2>&1 &
  echo $! > "$OUT/origin.pid"
fi
wait_for "origin" curl -sf -o /dev/null -r 0-15 "http://127.0.0.1:$ORIGIN_PORT/payload1.bin"

step "kubo repo init + offline/no-routing config"
docker volume create "$KUBO_VOL" >/dev/null
kcfg() { docker run --rm -v "$KUBO_VOL:/data/ipfs" "$KUBO_IMAGE" "$@"; }
kcfg config --json Experimental.UrlstoreEnabled false >/dev/null 2>&1 || true
kcfg config Routing.Type none
kcfg bootstrap rm --all
kcfg config --json Swarm.DisableNatPortMap true
kcfg config Addresses.API /ip4/0.0.0.0/tcp/5001
kcfg config Addresses.Gateway /ip4/0.0.0.0/tcp/8080
kcfg config --json Addresses.Swarm '[]'
echo "--- bootstrap list (must be empty) ---"; kcfg bootstrap list
echo "--- routing ---"; kcfg config Routing.Type

step "kubo daemon (offline)"
docker rm -f "$KUBO_NAME" >/dev/null 2>&1 || true
docker run -d --name "$KUBO_NAME" \
  -v "$KUBO_VOL:/data/ipfs" \
  -p 127.0.0.1:15001:5001 -p 127.0.0.1:18080:8080 \
  "$KUBO_IMAGE" daemon --offline >/dev/null
wait_for "kubo rpc" curl -sf -X POST "$API/id"
api "version?all=true" | tee "$OUT/ipfs-version.txt"
curl --version | head -1 | tee "$OUT/curl-version.txt"
