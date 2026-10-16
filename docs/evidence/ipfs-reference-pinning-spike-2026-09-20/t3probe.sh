#!/usr/bin/env bash
# T3 probe: attribute the origin burst seen around T3 to a precise sub-step,
# using a FRESH tree (re-adding identical bytes writes no new refs).
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

python3 - "$DATA" <<'PY'
import os, sys
d = sys.argv[1]
open(os.path.join(d, "hls2__master.m3u8"), "wb").write(os.urandom(120))
open(os.path.join(d, "hls2__720p__init.mp4"), "wb").write(os.urandom(700))
open(os.path.join(d, "hls2__720p__seg-1.m4s"), "wb").write(os.urandom(3 * 1024 * 1024))
PY

count_since() { origin_since "$1" | grep -c 'Range=' || true; }

step "P1: nocopy add of a SINGLE small file (225B-class), nothing else"
python3 -c "import os;open('$DATA/tiny1.bin','wb').write(os.urandom(300))"
origin_mark p1
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/tiny1.bin;filename=tiny1.bin;headers=\"Abspath: $ORIGIN_BASE/tiny1.bin\""
echo "origin requests caused by single-small-file nocopy add: $(count_since p1)"; origin_since p1

step "P2: nocopy add of a single MULTI-chunk file (3 MiB)"
python3 -c "import os;open('$DATA/mid1.bin','wb').write(os.urandom(3*1024*1024))"
origin_mark p2
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/mid1.bin;filename=mid1.bin;headers=\"Abspath: $ORIGIN_BASE/mid1.bin\""
echo "origin requests caused by single-multichunk nocopy add: $(count_since p2)"; origin_since p2

step "P3: nocopy DIRECTORY add (fresh tree), nothing read afterwards"
origin_mark p3
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false" \
  -F "file=@/dev/null;filename=hls2;type=application/x-directory" \
  -F "file=@$DATA/hls2__master.m3u8;filename=hls2/master.m3u8;headers=\"Abspath: $ORIGIN_BASE/hls2/master.m3u8\"" \
  -F "file=@/dev/null;filename=hls2/720p;type=application/x-directory" \
  -F "file=@$DATA/hls2__720p__init.mp4;filename=hls2/720p/init.mp4;headers=\"Abspath: $ORIGIN_BASE/hls2/720p/init.mp4\"" \
  -F "file=@$DATA/hls2__720p__seg-1.m4s;filename=hls2/720p/seg-1.m4s;headers=\"Abspath: $ORIGIN_BASE/hls2/720p/seg-1.m4s\""
echo "origin requests caused by the directory nocopy add: $(count_since p3)"; origin_since p3
