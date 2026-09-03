#!/bin/zsh
# usage: ./run_all.sh [openvaf-r-path] [ngspice-path]   (defaults: the committed bin/macos/apple-silicon pair)
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
OV=${1:-$ROOT/bin/macos/apple-silicon/openvaf-r}
NG=${2:-$ROOT/bin/macos/apple-silicon/ngspice}
cd "$(dirname "$0")"
for va in *.va; do
  n=${va%.va}
  out=$($OV $va -o $n.osdi 2>&1)
  if echo "$out" | grep -q '^error'; then echo "[$n] compile: $(echo "$out" | grep -m1 '^error' | cut -c1-110)"; else echo "[$n] compile: ok $(echo "$out" | grep -m1 '^warning' | cut -c1-90)"; fi
  if [ -f $n.cir ]; then echo "$($NG -b $n.cir 2>&1 | grep -E '^OSDI|^v\(|^i\(|^[0-9]\s|singular' | head -6 | sed 's/^/    /')"; fi
done
