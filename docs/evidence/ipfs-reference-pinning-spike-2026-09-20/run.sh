#!/usr/bin/env bash
# Reference-pinning spike: end-to-end reproduction.
#
#   bash run.sh            # setup + every test, transcripts under out/
#   bash run.sh teardown   # remove every refpin-spike-* docker resource
#
# The node NEVER joins the public IPFS network: Routing.Type=none, an empty
# bootstrap list, no swarm addresses, and `daemon --offline`. RPC/gateway are
# published on 127.0.0.1 only, on non-default ports (15001/18080).
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = teardown ]; then
  [ -f out/origin.pid ] && kill "$(cat out/origin.pid)" 2>/dev/null || true
  docker rm -f refpin-spike-kubo >/dev/null 2>&1 || true
  docker volume rm refpin-spike-repo >/dev/null 2>&1 || true
  echo "--- remaining refpin-spike-* resources (expect none) ---"
  docker ps -a    --filter name=refpin-spike --format '{{.Names}}'
  docker volume ls --filter name=refpin-spike --format '{{.Name}}'
  docker network ls --filter name=refpin-spike --format '{{.Name}}'
  exit 0
fi

mkdir -p out
bash setup.sh   2>&1 | tee out/setup.txt      # payloads, origin, offline Kubo
bash t0.sh      2>&1 | tee out/t0.txt         # urlstore disabled -> error text
bash t1.sh      2>&1 | tee out/t1.txt         # enable urlstore; 64 MiB nocopy add
bash t2.sh      2>&1 | tee out/t2.txt         # read back, count ranged GETs
bash t3.sh      2>&1 | tee out/t3.txt         # HLS directory tree
bash t3probe.sh 2>&1 | tee out/t3probe.txt    # which add shape touches the origin
bash t3probe2.sh 2>&1 | tee out/t3probe2.txt  # the single-chunk boundary
bash t4.sh      2>&1 | tee out/t4.txt         # origin down / corrupt / 404 / 307
bash t4d.sh     2>&1 | tee out/t4d.txt        # redirect via gateway + self-heal
bash t5.sh      2>&1 | tee out/t5.txt         # migrating a copied pin to references
bash t6.sh      2>&1 | tee out/t6.txt         # gc safety
bash t10.sh     2>&1 | tee out/t10.txt        # first-writer-wins + heal
bash t11.sh     2>&1 | tee out/t11.txt        # mixed copy/reference tree
bash t11c.sh    2>&1 | tee out/t11c.txt       # partial write on a late bad part
bash t12.sh     2>&1 | tee out/t12.txt        # which maintenance ops read the origin
bash t12b.sh    2>&1 | tee out/t12b.txt       # confirm refs -r and read amplification
bash t789.sh    2>&1 | tee out/t789.txt       # chunk size, throughput, concurrency
echo
echo "Done. Evidence transcripts in out/. Run 'bash run.sh teardown' to clean up."
