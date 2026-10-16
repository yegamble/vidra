#!/usr/bin/env bash
# T12: which NODE MAINTENANCE operations pull payload bytes back from the origin?
# Proxy for "does a periodic walk of the pinset re-download every video from S3".
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
clean_slate

step "fixtures: one 64 MiB nocopy pin + one nocopy HLS directory"
FCID=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload1.bin;filename=payload1.bin;headers=\"Abspath: $ORIGIN_BASE/payload1.bin\"" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
DCID=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false" \
  -F "file=@/dev/null;filename=hls;type=application/x-directory" \
  -F "file=@$DATA/hls__master.m3u8;filename=hls/master.m3u8;headers=\"Abspath: $ORIGIN_BASE/hls/master.m3u8\"" \
  -F "file=@/dev/null;filename=hls/720p;type=application/x-directory" \
  -F "file=@$DATA/hls__720p__init.mp4;filename=hls/720p/init.mp4;headers=\"Abspath: $ORIGIN_BASE/hls/720p/init.mp4\"" \
  -F "file=@$DATA/hls__720p__seg-1.m4s;filename=hls/720p/seg-1.m4s;headers=\"Abspath: $ORIGIN_BASE/hls/720p/seg-1.m4s\"" \
  | tail -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "file CID: $FCID"; echo "dir  CID: $DCID"
echo "filestore refs: $(api 'filestore/ls?enc=json' | grep -c . || true)"

# Count requests + bytes the origin served since a mark.
tally() { origin_since "$1" | python3 -c '
import sys,re
n=b=0
for l in sys.stdin:
    m=re.search(r"bytes=(\d+)$", l)
    if m: n+=1; b+=int(m.group(1))
print("%d request(s), %d bytes (%.2f MiB)" % (n,b,b/1048576))'; }

probe() { # probe <label> <curl args...>
  local label="$1"; shift
  origin_mark "$label"
  "$@" > "$OUT/t12-$label.out" 2>&1
  printf '  %-34s %s\n' "$label" "$(tally "$label")"
}

step "T12 maintenance operations (0 origin reads is the hoped-for answer)"
probe pin-ls-all        curl -sS -X POST "$API/pin/ls?type=recursive&enc=json"
probe pin-ls-one        curl -sS -X POST "$API/pin/ls?arg=$FCID&type=recursive&enc=json"
probe pin-verify        curl -sS -X POST "$API/pin/verify?enc=json"
probe repo-stat         curl -sS -X POST "$API/repo/stat"
probe repo-stat-sizeonly curl -sS -X POST "$API/repo/stat?size-only=true"
probe repo-gc           curl -sS -X POST "$API/repo/gc?enc=json&quiet=true"
probe refs-recursive    curl -sS -X POST "$API/refs?arg=$FCID&recursive=true&enc=json"
probe refs-dir-recursive curl -sS -X POST "$API/refs?arg=$DCID&recursive=true&enc=json"
probe dag-stat          curl -sS -X POST "$API/dag/stat?arg=$FCID&enc=json&progress=false"
probe files-stat        curl -sS -X POST "$API/files/stat?arg=/ipfs/$FCID&enc=json"
probe ls-dir            curl -sS -X POST "$API/ls?arg=$DCID&enc=json"
probe block-stat-root   curl -sS -X POST "$API/block/stat?arg=$FCID"
probe gateway-HEAD      curl -sS -I "$GW/ipfs/$FCID"
probe gateway-range-1k  curl -sS -r 0-1023 "$GW/ipfs/$FCID" -o "$OUT/t12-range.bin"
probe filestore-verify  curl -sS -X POST "$API/filestore/verify?enc=json"
probe filestore-ls      curl -sS -X POST "$API/filestore/ls?enc=json"

step "what did the 1 KiB ranged gateway GET actually ask the origin for?"
origin_since gateway-range-1k
echo "bytes returned to the client: $(wc -c < "$OUT/t12-range.bin" | tr -d ' ')"
echo "--- gateway HEAD response ---"; head -12 "$OUT/t12-gateway-HEAD.out"

step "reprovide / provide RPCs (node is OFFLINE — recorded as best-effort)"
for ep in "provide/stat" "routing/provide" "bitswap/stat" "stats/provide" "stats/repo"; do
  printf '  %-18s -> %s\n' "$ep" "$(curl -sS -X POST "$API/$ep" 2>&1 | head -c 200)"
done
echo "--- Reprovider config ---"; docker exec "$KUBO_NAME" ipfs config Reprovider || true
echo "--- dag/stat output (for the record) ---"; head -c 300 "$OUT/t12-dag-stat.out"; echo
echo "--- pin/verify output ---"; head -c 300 "$OUT/t12-pin-verify.out"; echo
