#!/usr/bin/env bash
# T11c: if the Abspath-less part comes LAST, are the earlier parts already
# committed as references (partial write) or is the whole add atomic?
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
origin_mode normal; clean_slate
python3 - "$DATA" <<'PY'
import os,sys
d=sys.argv[1]
open(os.path.join(d,"mix2__720p__seg-1.m4s"),"wb").write(os.urandom(2*1024*1024))
open(os.path.join(d,"mix2__720p__bad.m3u8"),"wb").write(os.urandom(50).hex().encode())
PY
step "directory add: good part (with Abspath) FIRST, bad part (no Abspath) LAST"
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&recursive=true&wrap-with-directory=true&progress=false" \
  -F "file=@/dev/null;filename=mix2;type=application/x-directory" \
  -F "file=@/dev/null;filename=mix2/720p;type=application/x-directory" \
  -F "file=@$DATA/mix2__720p__seg-1.m4s;filename=mix2/720p/seg-1.m4s;headers=\"Abspath: $ORIGIN_BASE/mix2/720p/seg-1.m4s\"" \
  -F "file=@$DATA/mix2__720p__bad.m3u8;filename=mix2/720p/bad.m3u8" \
  -w '\nhttp=%{http_code}\n'
echo "--- refs written for the GOOD part despite the failed request ---"
echo "   seg-1 refs now: $( { api 'filestore/ls?enc=json' | grep -cF 'mix2/720p/seg-1.m4s'; } || true)"
echo "   total filestore entries: $(api 'filestore/ls?enc=json' | grep -c . || true)"
echo "   pins: $(api 'pin/ls?type=recursive&enc=json' | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("Keys",{})))')"
