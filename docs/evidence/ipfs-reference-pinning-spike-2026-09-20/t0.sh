#!/usr/bin/env bash
# T0 baseline: Experimental.UrlstoreEnabled still false -> nocopy add with a URL Abspath.
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

step "config state before T0"
docker exec "$KUBO_NAME" ipfs config Experimental | tee "$OUT/t0-experimental.txt"

step "T0 add nocopy=true with URL Abspath, urlstore DISABLED"
origin_mark t0
curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&pin=true&progress=false" \
  -F "file=@$DATA/payload1.bin;filename=payload1.bin;headers=\"Abspath: $ORIGIN_BASE/payload1.bin\"" \
  -D "$OUT/t0-headers.txt" -o "$OUT/t0-body.txt" -w 'curl_exit_status_code=%{http_code}\n' \
  | tee "$OUT/t0-status.txt"
echo "--- response status line + trailers ---"; grep -Ei '^(HTTP/|x-stream-error|trailer)' "$OUT/t0-headers.txt" || true
echo "--- body ---"; cat "$OUT/t0-body.txt"; echo
echo "--- origin requests during T0 (expect none) ---"; origin_since t0
