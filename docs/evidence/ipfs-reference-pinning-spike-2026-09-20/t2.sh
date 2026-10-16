#!/usr/bin/env bash
# T2: read the nocopy file back via RPC cat and via the gateway; audit origin traffic.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
CID=$(cat "$OUT/t1-cid.txt")
WANT=$(shasum -a 256 "$DATA/payload1.bin" | awk '{print $1}')
echo "payload sha256: $WANT   cid: $CID"

step "cat via RPC"
origin_mark t2rpc
curl -sS -X POST "$API/cat?arg=$CID" -o "$OUT/t2-rpc.bin" -w 'http=%{http_code} time=%{time_total}s size=%{size_download}\n'
GOT=$(shasum -a 256 "$OUT/t2-rpc.bin" | awk '{print $1}')
echo "rpc sha256: $GOT"; [ "$GOT" = "$WANT" ] && echo "RPC MATCH" || echo "RPC MISMATCH"
origin_since t2rpc > "$OUT/t2-origin-rpc.txt"
echo "origin requests: $(grep -c 'Range=' "$OUT/t2-origin-rpc.txt" || true)"
echo "with Range: $(grep -c 'Range=bytes' "$OUT/t2-origin-rpc.txt" || true)   without Range: $(grep -c 'Range=- ' "$OUT/t2-origin-rpc.txt" || true)"
echo "--- distinct Range spans requested (size histogram) ---"
grep -o 'Range=bytes=[0-9]*-[0-9]*' "$OUT/t2-origin-rpc.txt" \
 | sed 's/Range=bytes=//' | awk -F- '{print $2-$1+1}' | sort -n | uniq -c
echo "--- first 3 / last 2 request lines ---"; head -3 "$OUT/t2-origin-rpc.txt"; tail -2 "$OUT/t2-origin-rpc.txt"

step "cat via gateway"
origin_mark t2gw
curl -sS "$GW/ipfs/$CID" -o "$OUT/t2-gw.bin" -w 'http=%{http_code} time=%{time_total}s size=%{size_download}\n'
GOT2=$(shasum -a 256 "$OUT/t2-gw.bin" | awk '{print $1}')
echo "gw sha256: $GOT2"; [ "$GOT2" = "$WANT" ] && echo "GATEWAY MATCH" || echo "GATEWAY MISMATCH"
origin_since t2gw > "$OUT/t2-origin-gw.txt"
echo "origin requests: $(grep -c 'Range=' "$OUT/t2-origin-gw.txt" || true)"
echo "non-Range requests: $(grep -c 'Range=- ' "$OUT/t2-origin-gw.txt" || true)"
grep -o 'Range=bytes=[0-9]*-[0-9]*' "$OUT/t2-origin-gw.txt" \
 | sed 's/Range=bytes=//' | awk -F- '{print $2-$1+1}' | sort -n | uniq -c
