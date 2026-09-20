#!/usr/bin/env bash
# T4d tail: redirect via gateway + does the pin heal once the origin behaves again.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
CID=$(cat "$OUT/t4-cid.txt"); WANT=$(shasum -a 256 "$DATA/t4.bin" | awk '{print $1}')
step "T4d gateway read through the 307"
origin_mode redirect; origin_mark t4dgw
curl -sS "$GW/ipfs/$CID" -o "$OUT/t4-d-gw.bin" -w 'http=%{http_code} size=%{size_download} time=%{time_total}s\n'
[ "$(shasum -a 256 "$OUT/t4-d-gw.bin"|awk '{print $1}')" = "$WANT" ] && echo "REDIRECT GATEWAY MATCH" || echo "REDIRECT GATEWAY MISMATCH"
echo "origin hits: $(origin_since t4dgw | grep -c Range= || true)  (307s: $(origin_since t4dgw | grep -c '> 307' || true), 206s: $(origin_since t4dgw | grep -c '> 206' || true))"
step "back to normal: does the pin heal with no operator action?"
origin_mode normal
curl -sS "$GW/ipfs/$CID" -o "$OUT/t4-final.bin" -w 'http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t4-final.bin"|awk '{print $1}')" = "$WANT" ] && echo "HEALED: MATCH (no re-add, no restart)" || echo "NOT HEALED"
step "filestore/verify for one known-good leaf after all that abuse"
curl -sS -X POST "$API/filestore/verify?arg=$(curl -sS -X POST "$API/filestore/ls?enc=json" | grep t4.bin | head -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["Key"]["/"])')&enc=json"; echo
