#!/usr/bin/env bash
# Is the single-chunk add-time origin read caused by pin=true, or intrinsic?
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"
mk() { python3 -c "import os,sys;open(sys.argv[1],'wb').write(os.urandom(int(sys.argv[2])))" "$DATA/$1" "$2"; }
probe() { # probe <name> <bytes> <extra-query>
  mk "$1" "$2"; origin_mark "$1"
  curl -sS -X POST "$API/add?nocopy=true&cid-version=1&raw-leaves=true&progress=false&$3" \
    -F "file=@$DATA/$1;filename=$1;headers=\"Abspath: $ORIGIN_BASE/$1\"" >/dev/null
  printf '%-28s %-18s -> %s origin read(s)\n' "$1 ($2 B)" "$3" "$(origin_since "$1" | grep -c 'Range=' || true)"
  origin_since "$1" | sed 's/^/    /'
}
probe sc_pin_true.bin   400     "pin=true"
probe sc_pin_false.bin  400     "pin=false"
probe sc_exact.bin      262144  "pin=false"     # exactly one 256 KiB chunk
probe mc_justover.bin   262145  "pin=false"     # two chunks
probe mc_pin_true.bin   1000000 "pin=true"
