#!/usr/bin/env bash
# T1: enable urlstore, nocopy-add 64 MiB by streaming, measure repo growth + CID identity.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

step "enable Experimental.UrlstoreEnabled and restart"
docker exec "$KUBO_NAME" ipfs config --json Experimental.UrlstoreEnabled true
docker restart "$KUBO_NAME" >/dev/null
wait_for "kubo rpc" curl -sf -X POST "$API/id"
docker exec "$KUBO_NAME" ipfs config Experimental | tee "$OUT/t1-experimental.txt"

step "copy-mode reference CID (only-hash, writes nothing)"
ONLY=$(curl -sS -X POST "$API/add?only-hash=true&cid-version=1&raw-leaves=true&progress=false" \
  -F "file=@$DATA/payload1.bin;filename=payload1.bin" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["Hash"])')
echo "only-hash CID: $ONLY" | tee "$OUT/t1-onlyhash.txt"

step "repo/stat BEFORE"
BEFORE=$(reposize); api repo/stat | tee "$OUT/t1-repostat-before.txt"; echo

step "nocopy add (streamed body + URL Abspath)"
origin_mark t1
T0S=$(python3 -c 'import time;print(time.time())')
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload1.bin;filename=payload1.bin;headers=\"Abspath: $ORIGIN_BASE/payload1.bin\"" \
  -o "$OUT/t1-add.json" -w 'http=%{http_code} time=%{time_total}s\n' | tee "$OUT/t1-addstatus.txt"
T1S=$(python3 -c 'import time;print(time.time())')
cat "$OUT/t1-add.json"; echo
NOCOPY=$(python3 -c 'import json;print(json.load(open("'"$OUT"'/t1-add.json"))["Hash"])' 2>/dev/null || echo "NONE")
echo "nocopy CID: $NOCOPY"
echo "$NOCOPY" > "$OUT/t1-cid.txt"
python3 -c "print('wall seconds: %.2f' % ($T1S-$T0S))"

step "CID identity"
if [ "$ONLY" = "$NOCOPY" ]; then echo "IDENTICAL: nocopy CID == copy-mode CID ($ONLY)";
else echo "DIFFERENT: only-hash=$ONLY nocopy=$NOCOPY"; fi

step "repo/stat AFTER"
AFTER=$(reposize); api repo/stat | tee "$OUT/t1-repostat-after.txt"; echo
python3 -c "
b,a=$BEFORE,$AFTER; d=a-b; p=64*1024*1024
print('RepoSize before %d  after %d  delta %d bytes (%.3f MiB) = %.4f%% of 64 MiB payload' % (b,a,d,d/1048576,100.0*d/p))"

step "filestore/ls (first 5 + count)"
api "filestore/ls?enc=json" > "$OUT/t1-filestore-ls.json"
head -c 1200 "$OUT/t1-filestore-ls.json"; echo
echo "entries: $(grep -c '"Key"' "$OUT/t1-filestore-ls.json" || true)"

step "did Kubo contact the origin AT ADD TIME?"
origin_since t1 | tee "$OUT/t1-origin.txt"
echo "origin request count during add: $(origin_since t1 | grep -c Range= || true)"
