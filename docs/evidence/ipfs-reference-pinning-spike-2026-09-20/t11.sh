#!/usr/bin/env bash
# T11: can one tree hold REAL blocks (small shared files) and REFERENCES (big
# segments) at once? That decides whether playlists/init segments/VTTs can be
# kept independent of the origin.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal
clean_slate

python3 - "$DATA" <<'PY'
import os, sys
d = sys.argv[1]
open(os.path.join(d, "mix__master.m3u8"), "wb").write(b"#EXTM3U\n#EXT-X-VERSION:7\n" + os.urandom(100).hex().encode()[:270])
open(os.path.join(d, "mix__720p__init.mp4"), "wb").write(os.urandom(700))
open(os.path.join(d, "mix__720p__seg-1.m4s"), "wb").write(os.urandom(2 * 1024 * 1024))
PY
PL="$DATA/mix__master.m3u8"; echo "playlist is $(wc -c < "$PL" | tr -d ' ') bytes"
isref() { api "filestore/ls?enc=json" | grep -cF "$1" || true; }

tree_add() { # tree_add <playlist-abspath: yes|no>
  local -a A
  A=(-F "file=@/dev/null;filename=mix;type=application/x-directory")
  if [ "$1" = yes ]; then
    A+=(-F "file=@$PL;filename=mix/master.m3u8;headers=\"Abspath: $ORIGIN_BASE/mix/master.m3u8\"")
  else
    A+=(-F "file=@$PL;filename=mix/master.m3u8")   # deliberately NO Abspath
  fi
  A+=(-F "file=@/dev/null;filename=mix/720p;type=application/x-directory")
  A+=(-F "file=@$DATA/mix__720p__init.mp4;filename=mix/720p/init.mp4;headers=\"Abspath: $ORIGIN_BASE/mix/720p/init.mp4\"")
  A+=(-F "file=@$DATA/mix__720p__seg-1.m4s;filename=mix/720p/seg-1.m4s;headers=\"Abspath: $ORIGIN_BASE/mix/720p/seg-1.m4s\"")
  curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false" \
    "${A[@]}" -w '\nhttp=%{http_code}\n'
}

step "T11a nocopy directory add with ONE part missing its Abspath"
tree_add no | tee "$OUT/t11a.txt"
echo "--- resulting filestore refs mentioning mix/ ---"
{ api "filestore/ls?enc=json" | grep -F '/mix/' || true; } | python3 -c '
import sys,json,collections
c=collections.Counter()
for l in sys.stdin:
    try: c[json.loads(l)["FilePath"]]+=1
    except Exception: pass
print("   (none)") if not c else [print("   %4d -> %s"%(v,k)) for k,v in sorted(c.items())]'

step "T11b the pre-copy trick"
clean_slate
echo "--- 1. add the playlist ALONE in copy mode, pin=false ---"
PLCID=$(curl -sS -X POST "$API/add?cid-version=1&raw-leaves=true&pin=false&progress=false" \
  -F "file=@$PL;filename=master.m3u8" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Hash"])')
echo "playlist CID: $PLCID"
echo "   in filestore/ls? $(isref "$PLCID")  (0 == it is a real block)"
echo "--- 2. full nocopy tree add, Abspath on EVERY part including the playlist ---"
tree_add yes | tee "$OUT/t11b.txt"
ROOT=$(python3 - "$OUT/t11b.txt" <<'PY'
import json,sys
ls=[json.loads(l) for l in open(sys.argv[1]) if l.strip().startswith("{")]
print(ls[-1]["Hash"])
PY
)
echo "tree root: $ROOT"
echo "   playlist CID in the tree == standalone CID? $([ "$(api "ls?arg=$ROOT/mix&enc=json" | grep -c "$PLCID")" != 0 ] && echo yes || echo NO)"
echo "   playlist in filestore/ls? $(isref "$PLCID")  (0 == still a real block)"
echo "   seg-1 refs: $( { api "filestore/ls?enc=json" | grep -cF 'mix/720p/seg-1.m4s'; } || true)"
echo "   init.mp4 refs: $( { api "filestore/ls?enc=json" | grep -cF 'mix/720p/init.mp4'; } || true)"

step "T11b-2 with the ORIGIN DOWN: playlist readable, segment not?"
origin_mode 404
curl -sS "$GW/ipfs/$ROOT/mix/master.m3u8" -o "$OUT/t11-pl.bin" -w '   playlist: http=%{http_code} size=%{size_download}\n'
cmp -s "$PL" "$OUT/t11-pl.bin" && echo "   PLAYLIST SERVED FROM LOCAL BLOCK: bytes match" || echo "   playlist bytes differ/empty"
curl -sS "$GW/ipfs/$ROOT/mix/720p/seg-1.m4s" -o "$OUT/t11-seg.bin" -w '   segment:  http=%{http_code} size=%{size_download}\n'
curl -sS "$GW/ipfs/$ROOT/mix/720p/init.mp4" -o "$OUT/t11-init.bin" -w '   init.mp4: http=%{http_code} size=%{size_download}\n'
origin_mode normal

step "T11b-3 does the real block survive repo/gc while the tree is pinned?"
api "repo/gc?enc=json&quiet=true" > "$OUT/t11-gc.json"; echo "   gc removed $(grep -c . "$OUT/t11-gc.json" || true) entries"
echo "   playlist block still there? $(api "block/stat?arg=$PLCID" 2>&1 | head -c 120)"
origin_mode 404
curl -sS "$GW/ipfs/$ROOT/mix/master.m3u8" -o "$OUT/t11-pl2.bin" -w '   playlist after gc (origin 404): http=%{http_code} size=%{size_download}\n'
cmp -s "$PL" "$OUT/t11-pl2.bin" && echo "   SURVIVES GC: bytes match" || echo "   LOST AFTER GC"
origin_mode normal
