#!/usr/bin/env bash
# T7 chunk size, T8 rough throughput, T9 concurrency.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
WANT=$(shasum -a 256 "$DATA/payload1.bin" | awk '{print $1}')
tally() { origin_since "$1" | python3 -c '
import sys,re
n=b=0
for l in sys.stdin:
    m=re.search(r"bytes=(\d+)$", l)
    if m: n+=1; b+=int(m.group(1))
print("%d request(s), %d bytes" % (n,b))'; }

step "T7 chunk size: 256 KiB default vs size-1048576"
DEF=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload1.bin;filename=payload1.bin;headers=\"Abspath: $ORIGIN_BASE/payload1.bin\"" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
BIG=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false&chunker=size-1048576" \
  -F "file=@$DATA/payload1.bin;filename=payload1.bin;headers=\"Abspath: $ORIGIN_BASE/payload1.bin\"" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "  256 KiB chunker CID: $DEF"
echo "  1 MiB   chunker CID: $BIG"
[ "$DEF" = "$BIG" ] && echo "  CIDs IDENTICAL (unexpected)" || echo "  CIDs DIFFER (expected: chunking is part of the CID)"
echo "  filestore entries for the 1 MiB variant: $(api 'filestore/ls?enc=json' | grep -c '"Size":1048576' || true)"
origin_mark t7def; curl -sS "$GW/ipfs/$DEF" -o "$OUT/t7-def.bin"; echo "  full read @256 KiB: $(tally t7def)"
origin_mark t7big; curl -sS "$GW/ipfs/$BIG" -o "$OUT/t7-big.bin"; echo "  full read @1 MiB:   $(tally t7big)"
for f in t7-def t7-big; do
  [ "$(shasum -a 256 "$OUT/$f.bin"|awk '{print $1}')" = "$WANT" ] && echo "  $f bytes MATCH" || echo "  $f MISMATCH"
done

step "T8 rough throughput: gateway read of 64 MiB, copy mode vs nocopy"
COPY=$(curl -sS -X POST "$API/add?cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload2.bin;filename=payload2.bin" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "  copy-mode CID: $COPY   nocopy CID: $DEF"
med() { python3 -c '
import sys
v=sorted(float(x) for x in sys.argv[1:]); n=len(v)
print("median %.3fs  (runs: %s)" % (v[n//2], ", ".join("%.3f"%x for x in v)))' "$@"; }
C=(); N=()
for i in 1 2 3; do
  C+=("$(curl -sS "$GW/ipfs/$COPY" -o /dev/null -w '%{time_total}')")
  N+=("$(curl -sS "$GW/ipfs/$DEF"  -o /dev/null -w '%{time_total}')")
done
echo "  copy mode : $(med "${C[@]}")"
echo "  nocopy    : $(med "${N[@]}")"
echo "  NOTE: the origin is on localhost. This says NOTHING about S3/Spaces latency."

step "T9 concurrency: 8 parallel gateway range reads of the nocopy file"
origin_mark t9
pids=(); rc=0
for i in 0 1 2 3 4 5 6 7; do
  S=$((i * 8388608)); E=$((S + 1048575))
  ( curl -sS -r "$S-$E" "$GW/ipfs/$DEF" -o "$OUT/t9-$i.bin" -w "range $i http=%{http_code} size=%{size_download}\n" ) &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p" || rc=1; done
echo "  all curls exited 0: $([ $rc -eq 0 ] && echo yes || echo NO)"
for i in 0 1 2 3 4 5 6 7; do
  S=$((i * 8388608))
  A=$(dd if="$DATA/payload1.bin" bs=1 skip=$S count=1048576 2>/dev/null | shasum -a 256 | awk '{print $1}')
  B=$(shasum -a 256 "$OUT/t9-$i.bin" | awk '{print $1}')
  [ "$A" = "$B" ] && echo "  range $i: MATCH ($(wc -c < "$OUT/t9-$i.bin" | tr -d ' ') bytes)" || echo "  range $i: MISMATCH"
done
echo "  origin traffic for the 8 parallel reads: $(tally t9)"
echo "--- kubo daemon log: any errors during the spike? ---"
docker logs "$KUBO_NAME" 2>&1 | grep -iE 'error|panic|fatal|warn' | tail -15 || echo "  (no error/warn lines)"
