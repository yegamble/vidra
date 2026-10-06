#!/usr/bin/env bash
# T3: directory add of an HLS tree, every part carrying its own URL Abspath.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

# curl -F parts: dir parts are empty bodies with type=application/x-directory;
# file parts carry filename=<nested path> and their own Abspath header.
dirpart() { printf -- '-F\nfile=@/dev/null;filename=%s;type=application/x-directory\n' "$1"; }

add_tree() { # add_tree <extra-query> <abspath:yes|no>
  local q="$1" abs="$2"
  local -a A
  A=(-F "file=@/dev/null;filename=hls;type=application/x-directory")
  if [ "$abs" = yes ]; then
    A+=(-F "file=@$DATA/hls__master.m3u8;filename=hls/master.m3u8;headers=\"Abspath: $ORIGIN_BASE/hls/master.m3u8\"")
  else
    A+=(-F "file=@$DATA/hls__master.m3u8;filename=hls/master.m3u8")
  fi
  A+=(-F "file=@/dev/null;filename=hls/720p;type=application/x-directory")
  if [ "$abs" = yes ]; then
    A+=(-F "file=@$DATA/hls__720p__init.mp4;filename=hls/720p/init.mp4;headers=\"Abspath: $ORIGIN_BASE/hls/720p/init.mp4\"")
    A+=(-F "file=@$DATA/hls__720p__seg-1.m4s;filename=hls/720p/seg-1.m4s;headers=\"Abspath: $ORIGIN_BASE/hls/720p/seg-1.m4s\"")
  else
    A+=(-F "file=@$DATA/hls__720p__init.mp4;filename=hls/720p/init.mp4")
    A+=(-F "file=@$DATA/hls__720p__seg-1.m4s;filename=hls/720p/seg-1.m4s")
  fi
  curl -sS -X POST "$API/add?$q" "${A[@]}"
}

step "T3a nocopy directory add"
BEFORE=$(reposize)
origin_mark t3
add_tree "nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false" yes \
  | tee "$OUT/t3-add-nocopy.txt"
AFTER=$(reposize)
python3 -c "print('RepoSize delta: %d bytes for a %d-byte tree' % ($AFTER-$BEFORE, $(cat "$DATA"/hls__* | wc -c)))"
ROOT=$(python3 - "$OUT/t3-add-nocopy.txt" <<'PY'
import json,sys
last=[json.loads(l) for l in open(sys.argv[1]) if l.strip()][-1]
print(last["Hash"])
PY
)
echo "$ROOT" > "$OUT/t3-root.txt"; echo "nocopy root CID: $ROOT"
echo "--- origin requests during the directory add (expect 0) ---"; origin_since t3

step "T3b copy-mode add of the identical tree"
add_tree "cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false&only-hash=true" no \
  | tee "$OUT/t3-add-copy.txt"
ROOTC=$(python3 - "$OUT/t3-add-copy.txt" <<'PY'
import json,sys
last=[json.loads(l) for l in open(sys.argv[1]) if l.strip()][-1]
print(last["Hash"])
PY
)
echo "copy-mode root CID: $ROOTC"
[ "$ROOT" = "$ROOTC" ] && echo "ROOT CIDs IDENTICAL" || echo "ROOT CIDs DIFFER"

step "T3c gateway resolution of the nested path"
curl -sS "$GW/ipfs/$ROOT/hls/720p/seg-1.m4s" -o "$OUT/t3-seg.bin" -w 'http=%{http_code} size=%{size_download}\n'
WANT=$(shasum -a 256 "$DATA/hls__720p__seg-1.m4s" | awk '{print $1}')
GOT=$(shasum -a 256 "$OUT/t3-seg.bin" | awk '{print $1}')
echo "want $WANT"; echo "got  $GOT"; [ "$WANT" = "$GOT" ] && echo "SEGMENT MATCH" || echo "SEGMENT MISMATCH"
echo "--- master.m3u8 through the gateway ---"
curl -sS "$GW/ipfs/$ROOT/hls/master.m3u8" -w '\nhttp=%{http_code} size=%{size_download}\n' | head -6

step "T3d is the 225-byte playlist a reference or an inlined/real block?"
api "filestore/ls?enc=json" > "$OUT/t3-filestore-ls.json"
echo "total filestore entries now: $(grep -c '\"Key\"' "$OUT/t3-filestore-ls.json")"
echo "--- entries whose FilePath mentions hls ---"
grep -o '{"Status":0[^}]*}[^}]*}' "$OUT/t3-filestore-ls.json" | grep hls || true
echo "--- ls of the tree (CIDs + sizes) ---"
curl -sS -X POST "$API/ls?arg=$ROOT/hls&enc=json" | python3 -m json.tool | head -40
