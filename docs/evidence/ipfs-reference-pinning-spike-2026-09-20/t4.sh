#!/usr/bin/env bash
# T4: what a nocopy pin does when the origin misbehaves.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

python3 -c "import os;open('$DATA/t4.bin','wb').write(os.urandom(4*1024*1024))"
WANT=$(shasum -a 256 "$DATA/t4.bin" | awk '{print $1}')
CID=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/t4.bin;filename=t4.bin;headers=\"Abspath: $ORIGIN_BASE/t4.bin\"" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "t4 CID: $CID (4 MiB, 16 chunks)"; echo "$CID" > "$OUT/t4-cid.txt"
origin_mode normal
curl -sS "$GW/ipfs/$CID" -o "$OUT/t4-ok.bin" -w 'sanity read http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t4-ok.bin" | awk '{print $1}')" = "$WANT" ] && echo "sanity: MATCH"

trycat() { # trycat <label>
  echo "--- RPC cat ---"
  /usr/bin/time -p curl -sS -X POST "$API/cat?arg=$CID" -D "$OUT/t4-$1-hdr.txt" \
    -o "$OUT/t4-$1.bin" -w 'http=%{http_code} size=%{size_download}\n' 2>&1 | tail -6
  echo "response head:"; grep -Ei '^(HTTP/|X-Stream-Error|Trailer)' "$OUT/t4-$1-hdr.txt" || true
  echo "body (first 400 bytes, may be partial data + error):"
  LC_ALL=C head -c 400 "$OUT/t4-$1.bin" | LC_ALL=C tr -c '[:print:]\n' '.' || true; echo
  echo "--- gateway ---"
  /usr/bin/time -p curl -sS "$GW/ipfs/$CID" -o "$OUT/t4-$1-gw.bin" \
    -w 'http=%{http_code} size=%{size_download}\n' 2>&1 | tail -6
  LC_ALL=C head -c 300 "$OUT/t4-$1-gw.bin" | LC_ALL=C tr -c '[:print:]\n' '.' || true; echo
}

step "T4a origin STOPPED"
kill "$(cat "$OUT/origin.pid")" 2>/dev/null || true
wait_for "origin down" bash -c "! nc -z 127.0.0.1 $ORIGIN_PORT"
trycat a-down
echo "--- filestore/verify (whole store) while origin is down, first 8 lines ---"
/usr/bin/time -p curl -sS -X POST "$API/filestore/verify?enc=json" -o "$OUT/t4-verify-down.json" 2>&1 | tail -4
head -c 900 "$OUT/t4-verify-down.json"; echo
echo "status histogram:"; python3 - "$OUT/t4-verify-down.json" <<'PY'
import json,sys,collections
c=collections.Counter()
for l in open(sys.argv[1]):
    l=l.strip()
    if not l: continue
    try: d=json.loads(l)
    except Exception: continue
    c[(d.get("Status"), (d.get("ErrorMsg") or "")[:60])]+=1
for k,v in c.most_common(): print(v,k)
PY

step "T4a-recover: restart origin, no re-add"
nohup python3 "$SPIKE_DIR/origin.py" "$DATA" "$ORIGIN_PORT" "$ORIGIN_LOG" "$MODEFILE" \
      > "$OUT/origin-stdout.txt" 2>&1 & echo $! > "$OUT/origin.pid"
wait_for "origin up" curl -sf -o /dev/null -r 0-15 "http://127.0.0.1:$ORIGIN_PORT/t4.bin"
curl -sS "$GW/ipfs/$CID" -o "$OUT/t4-recover.bin" -w 'http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t4-recover.bin" | awk '{print $1}')" = "$WANT" ] \
  && echo "RECOVERED without re-add: MATCH" || echo "STILL BROKEN after origin restart"

step "T4b origin serves DIFFERENT bytes at the same URL"
origin_mode corrupt
trycat b-corrupt
echo "--- filestore/verify for just this CID ---"
curl -sS -X POST "$API/filestore/verify?arg=$CID&enc=json" -o "$OUT/t4-verify-corrupt.json"
head -c 600 "$OUT/t4-verify-corrupt.json"; echo

step "T4c origin returns 404"
origin_mode 404
trycat c-404

step "T4d origin returns 307 to a path that serves the right bytes"
origin_mode redirect
origin_mark t4d
trycat d-redirect
echo "--- origin log for the redirect test (does Range survive?) ---"
origin_since t4d | head -12

step "back to normal + does it heal by itself?"
origin_mode normal
curl -sS "$GW/ipfs/$CID" -o "$OUT/t4-final.bin" -w 'http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t4-final.bin" | awk '{print $1}')" = "$WANT" ] && echo "HEALED: MATCH" || echo "NOT HEALED"
