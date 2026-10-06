#!/usr/bin/env bash
# T12b: confirm the two counterintuitive T12 results in isolation.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
F=bafybeibnsrbh65nrgdpsvlpwilk6ozx6phs6wunsmel7tu5mjsry4c5zsq
tally() { origin_since "$1" | python3 -c '
import sys,re
n=b=0
for l in sys.stdin:
    m=re.search(r"bytes=(\d+)$", l)
    if m: n+=1; b+=int(m.group(1))
print("%d request(s), %d bytes" % (n,b))'; }
run() { local l="$1"; shift; origin_mark "$l"; "$@" >/dev/null 2>&1; printf '  %-26s %s\n' "$l" "$(tally "$l")"; }
step "refs: recursive vs non-recursive vs edges"
run refs-nonrecursive curl -sS -X POST "$API/refs?arg=$F&enc=json"
run refs-recursive-2  curl -sS -X POST "$API/refs?arg=$F&recursive=true&enc=json"
run refs-unique       curl -sS -X POST "$API/refs?arg=$F&recursive=true&unique=true&enc=json"
step "gateway: HEAD, 1-byte range, 1 KiB range, mid-file range"
run gw-head-2   curl -sS -I "$GW/ipfs/$F"
run gw-1byte    curl -sS -r 0-0    "$GW/ipfs/$F" -o /dev/null
run gw-1kib     curl -sS -r 0-1023 "$GW/ipfs/$F" -o /dev/null
run gw-mid      curl -sS -r 33554432-33555455 "$GW/ipfs/$F" -o /dev/null
echo "--- exact origin ranges for the mid-file 1 KiB request ---"; origin_since gw-mid
echo "--- exact origin ranges for gw-1byte ---"; origin_since gw-1byte
