#!/usr/bin/env bash
# T10: Kubo keeps ONE filestore reference per block. What happens when the FIRST
# URL rots while a perfectly good second copy exists at another URL?
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
clean_slate

python3 -c "
import os
b=os.urandom(8*1024*1024)
open('$DATA/a__dup.bin','wb').write(b)   # served at /a/dup.bin
open('$DATA/b__dup.bin','wb').write(b)   # served at /b/dup.bin, byte-identical"
WANT=$(shasum -a 256 "$DATA/b__dup.bin" | awk '{print $1}')

# The uploaded BODY is always the twin file; only the Abspath URL varies, so
# breaking /a on disk cannot break the upload itself.
addfrom() { curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=$2&progress=false" \
  -F "file=@$DATA/b__dup.bin;filename=dup.bin;headers=\"Abspath: $ORIGIN_BASE/$1/dup.bin\""; }
# Scope every count to THIS test's blocks.
refsrc() { { api "filestore/ls?enc=json" | grep -F dup.bin || true; } | python3 -c '
import sys,json,collections
c=collections.Counter()
for l in sys.stdin:
    try: c[json.loads(l)["FilePath"]]+=1
    except Exception: pass
print("   (no dup.bin references)" if not c else "", end="")
for k,v in sorted(c.items()): print("   %4d refs -> %s" % (v,k))'; }
leaves() { api "refs?arg=$1&recursive=true&enc=json" | python3 -c '
import sys,json; print("\n".join(json.loads(l)["Ref"] for l in sys.stdin if l.strip()))'; }

step "T10.1 nocopy add, Abspath .../a/dup.bin, pinned"
X=$(addfrom a true | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "CID X = $X   (8 MiB => 32 chunks)"; echo "$X" > "$OUT/t10-cid.txt"; refsrc
# Capture the leaf set ONCE, while everything is healthy, and read it from the
# file afterwards (piping this into `head` trips SIGPIPE under `set -o pipefail`).
leaves "$X" > "$OUT/t10-leaves.txt"
L1=$(sed -n 1p "$OUT/t10-leaves.txt")
echo "leaf blocks: $(grep -c . "$OUT/t10-leaves.txt")   first: $L1"

step "T10.2 nocopy add of the SAME bytes, Abspath .../b/dup.bin"
addfrom b true | tee "$OUT/t10-second-add.json"
echo "reference sources after the second add:"; refsrc

step "T10.3 /a/dup.bin now 404s; /b/dup.bin still healthy"
mv "$DATA/a__dup.bin" "$DATA/a__dup.bin.hidden"
curl -s -o /dev/null -w "   origin /a/dup.bin -> %{http_code}\n" "http://127.0.0.1:$ORIGIN_PORT/a/dup.bin"
curl -s -o /dev/null -w "   origin /b/dup.bin -> %{http_code}\n" "http://127.0.0.1:$ORIGIN_PORT/b/dup.bin"
curl -sS "$GW/ipfs/$X" -o "$OUT/t10-broken.bin" -w '   gateway: http=%{http_code} size=%{size_download} time=%{time_total}s\n'
LC_ALL=C head -c 200 "$OUT/t10-broken.bin" | LC_ALL=C tr -c '[:print:]\n' '.' || true; echo

step "T10.3b filestore/verify: whole store vs a single root CID"
/usr/bin/time -p curl -sS -X POST "$API/filestore/verify?enc=json" -o "$OUT/t10-verify-all.json" 2>&1 | tail -3
echo "   lines: $(grep -c . "$OUT/t10-verify-all.json")   bad: $(grep -vc '\"Status\":0' "$OUT/t10-verify-all.json" || true)"
grep -v '"Status":0' "$OUT/t10-verify-all.json" | head -2
echo "   -- verify?arg=<root CID> --"
/usr/bin/time -p curl -sS -X POST "$API/filestore/verify?arg=$X&enc=json" -o "$OUT/t10-verify-root.json" 2>&1 | tail -3
cat "$OUT/t10-verify-root.json"
echo "   -- verify?arg=<one leaf key> --"
echo "   leaf: $L1"
curl -sS -X POST "$API/filestore/verify?arg=$L1&enc=json"; echo

step "T10.4-i heal attempt (i): plain nocopy re-add from /b, nothing else"
addfrom b true | tee "$OUT/t10-heal-i.json"
echo "reference sources after:"; refsrc
curl -sS "$GW/ipfs/$X" -o /dev/null -w '   gateway: http=%{http_code} size=%{size_download}\n'

step "T10.4-ii heal attempt (ii): block/rm while X is STILL PINNED"
echo "   block/rm (no force):"; api "block/rm?arg=$L1&enc=json"; echo
echo "   block/rm force=true:"; api "block/rm?arg=$L1&force=true&enc=json"; echo
echo "   leaf still in filestore/ls? $(api 'filestore/ls?enc=json' | grep -cF "$L1" || true)"

step "T10.4-iii does a SECOND pin (wrapping dir) keep block/rm refusing?"
DIR=$(curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false" \
  -F "file=@/dev/null;filename=wrap;type=application/x-directory" \
  -F "file=@$DATA/b__dup.bin;filename=wrap/dup.bin;headers=\"Abspath: $ORIGIN_BASE/b/dup.bin\"" \
  | tail -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "   wrapping dir CID: $DIR"
api "pin/rm?arg=$X"; echo "   (X unpinned; only the directory pin now covers the leaf)"
echo "   block/rm force:"; api "block/rm?arg=$L1&force=true&enc=json"; echo
echo "   leaf still present? $(api 'filestore/ls?enc=json' | grep -cF "$L1" || true)"

step "T10.4-iv unpin everything, block/rm ALL 32 leaves, re-add from /b"
api "pin/rm?arg=$DIR" >/dev/null; echo "   dir unpinned"
echo "   leaf count: $(grep -c . "$OUT/t10-leaves.txt")"
ARGS=$(python3 -c '
import sys; print("&".join("arg="+l.strip() for l in open(sys.argv[1]) if l.strip()))' "$OUT/t10-leaves.txt")
api "block/rm?force=true&enc=json&$ARGS" > "$OUT/t10-blockrm.json"
echo "   block/rm results: $(grep -c . "$OUT/t10-blockrm.json") lines, errors: $(grep -c 'Error' "$OUT/t10-blockrm.json" || true)"
head -2 "$OUT/t10-blockrm.json"
echo "   root block too:"; api "block/rm?arg=$X&force=true&enc=json"; echo
echo "reference sources after block/rm:"; refsrc
echo "   re-add from /b:"
X2=$(addfrom b true | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "   CID after heal: $X2"; [ "$X" = "$X2" ] && echo "   CID UNCHANGED" || echo "   CID CHANGED"
echo "reference sources after heal:"; refsrc
curl -sS "$GW/ipfs/$X" -o "$OUT/t10-healed.bin" -w '   gateway: http=%{http_code} size=%{size_download}\n'
[ "$(shasum -a 256 "$OUT/t10-healed.bin"|awk '{print $1}')" = "$WANT" ] \
  && echo "   HEALED: MATCH (no daemon restart needed)" || echo "   HEAL FAILED"
api "pin/ls?arg=$X2&type=recursive"; echo
mv "$DATA/a__dup.bin.hidden" "$DATA/a__dup.bin"
