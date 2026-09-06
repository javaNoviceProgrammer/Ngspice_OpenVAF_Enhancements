#!/bin/sh
# Compile every probe here with openvaf-r and print rc + the first diagnostic.
# ./run_all.sh [openvaf-r] [ngspice]
VAF=${1:-../../../OpenVAF-master-20260610/target/opt/openvaf-r}
NG=${2:-../../../ngspice-46/build/src/ngspice}
cd "$(dirname "$0")"
for f in t*.va u*.va w*.va; do
  b=${f%.va}
  "$VAF" "$f" -o "$b.osdi" > "$b.log" 2>&1; rc=$?
  first=$(grep -m1 -E "^(error|warning|OpenVAF encountered)" "$b.log" | cut -c1-110)
  printf "%-26s rc=%-3s %s\n" "$b" "$rc" "$first"
  rm -f "$b".o "$b".o[0-9a-f]   # fragments a compiler crash leaves behind
done
if [ -f t21_retention.osdi ]; then
  "$NG" -b ret.cir 2>&1 | grep -E "v\(a\)" | sed 's/^/value retention: /'
fi
