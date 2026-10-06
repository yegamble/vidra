#!/usr/bin/env bash
# T6: does repo/gc respect a nocopy pin, and does unpin+gc actually reclaim the references?
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
CID=$(cat "$OUT/t5-cid.txt"); WANT=$(shasum -a 256 "$DATA/payload2.bin" | awk '{print $1}')
refs() { api "filestore/ls?enc=json" | grep -c payload2.bin || true; }

step "T6a repo/gc WITH the nocopy pin in place"
echo "refs before gc: $(refs)"
api "repo/gc?enc=json&quiet=true" > "$OUT/t6-gc1.json"; echo "gc removed $(grep -c . "$OUT/t6-gc1.json" || true) entries"
echo "refs after gc:  $(refs)"
curl -sS "$GW/ipfs/$CID" -o "$OUT/t6-a.bin" -w 'read after gc: http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t6-a.bin"|awk '{print $1}')" = "$WANT" ] && echo "SURVIVES GC: MATCH" || echo "BROKEN BY GC"
api "pin/ls?arg=$CID&type=recursive"; echo

step "T6b pin/rm then repo/gc"
api "pin/rm?arg=$CID"; echo
api "repo/gc?enc=json&quiet=true" > "$OUT/t6-gc2.json"; echo "gc removed $(grep -c . "$OUT/t6-gc2.json" || true) entries"
echo "refs after unpin+gc: $(refs)"
echo "--- does the gc output name the filestore refs it dropped? ---"; head -3 "$OUT/t6-gc2.json"
echo "--- read attempt (node is OFFLINE, so no network fallback exists) ---"
curl -sS "$GW/ipfs/$CID" -o "$OUT/t6-b.bin" -w 'http=%{http_code} size=%{size_download} time=%{time_total}s\n' --max-time 30 || true
LC_ALL=C head -c 200 "$OUT/t6-b.bin" | LC_ALL=C tr -c '[:print:]\n' '.' || true; echo
echo "--- RPC cat attempt ---"
curl -sS -X POST "$API/cat?arg=$CID" -D "$OUT/t6-b-hdr.txt" -o /dev/null -w 'http=%{http_code} size=%{size_download}\n' --max-time 30 || true
grep -Ei '^(HTTP/|X-Stream-Error)' "$OUT/t6-b-hdr.txt" || true
echo "--- repo/stat ---"; api repo/stat; echo
