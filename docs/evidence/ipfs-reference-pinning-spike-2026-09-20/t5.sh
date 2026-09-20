#!/usr/bin/env bash
# T5: migrating an ALREADY-COPIED pin to references. Does a nocopy re-add convert it?
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
WANT=$(shasum -a 256 "$DATA/payload2.bin" | awk '{print $1}')
show() { printf '%-42s RepoSize=%s  NumObjects=%s\n' "$1" "$(api repo/stat | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["RepoSize"])')" "$(api repo/stat | python3 -c 'import json,sys;print(json.load(sys.stdin)["NumObjects"])')"; }
refs_for() { api "filestore/ls?enc=json" | grep -c "$1" || true; }

show "0. before anything"
step "T5.1 COPY-mode add of payload2 (64 MiB), pinned"
CID=$(curl -sS -X POST "$API/add?cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload2.bin;filename=payload2.bin" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "copy-mode CID: $CID"; echo "$CID" > "$OUT/t5-cid.txt"
show "1. after copy add"
echo "filestore refs mentioning payload2.bin: $(refs_for payload2.bin)"

step "T5.2 nocopy RE-ADD of the very same bytes with a URL Abspath"
origin_mark t5
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload2.bin;filename=payload2.bin;headers=\"Abspath: $ORIGIN_BASE/payload2.bin\"" \
  | tee "$OUT/t5-readd.json"
show "2. after nocopy re-add"
echo "filestore refs mentioning payload2.bin: $(refs_for payload2.bin)"
echo "--- filestore/dups ---"; api "filestore/dups?enc=json" | head -5; echo "dups lines: $(api 'filestore/dups?enc=json' | grep -c . || true)"
echo "--- origin hits during the re-add ---"; origin_since t5 | head -3
echo "count: $(origin_since t5 | grep -c Range= || true)"

step "T5.3 pin/rm"
api "pin/rm?arg=$CID" ; echo
show "3. after pin/rm"
echo "filestore refs mentioning payload2.bin: $(refs_for payload2.bin)"

step "T5.4 repo/gc"
api "repo/gc?enc=json&quiet=true" > "$OUT/t5-gc.json"
echo "gc removed $(grep -c . "$OUT/t5-gc.json" || true) entries"
show "4. after repo/gc"
echo "filestore refs mentioning payload2.bin: $(refs_for payload2.bin)"

step "T5.5 nocopy re-add after the blocks are gone"
origin_mark t5b
CID2=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload2.bin;filename=payload2.bin;headers=\"Abspath: $ORIGIN_BASE/payload2.bin\"" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "CID after migration: $CID2"
[ "$CID" = "$CID2" ] && echo "CID UNCHANGED across the migration" || echo "CID CHANGED: $CID -> $CID2"
show "5. after nocopy re-add"
echo "filestore refs mentioning payload2.bin: $(refs_for payload2.bin)"
echo "origin hits during migration re-add: $(origin_since t5b | grep -c Range= || true)"
echo "--- pin still there? ---"; api "pin/ls?arg=$CID2&type=recursive"; echo
echo "--- readback ---"
curl -sS "$GW/ipfs/$CID2" -o "$OUT/t5-read.bin" -w 'http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t5-read.bin"|awk '{print $1}')" = "$WANT" ] && echo "READBACK MATCH" || echo "READBACK MISMATCH"
