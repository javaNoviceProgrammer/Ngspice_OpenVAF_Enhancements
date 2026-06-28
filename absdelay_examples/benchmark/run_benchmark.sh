#!/usr/bin/env bash
# KLU vs SPARSE benchmark for version2 ngspice on absdelay mesh circuits.
# Runs every generated mesh_<L>_<analysis>.cir with both solvers, times each
# (best of 2 runs), and writes results/timings.csv.
set -e
NG=../../bin/macos/apple-silicon/ngspice
DIR="$(cd "$(dirname "$0")" && pwd)"
SIZES="${1:-20,30,40,50,60,70}"
cd "$DIR"
python3 gen_bench.py "$SIZES" >/dev/null
mkdir -p results
CSV="results/timings.csv"
echo "L,nodes,analysis,solver,seconds" > "$CSV"

timeit() { # $1 cir -> best of 2 'real' seconds
  local best=99999 t
  for _ in 1 2; do
    { /usr/bin/time -p sh -c "$NG --batch '$1' >/dev/null 2>&1"; } 2>/tmp/_bt.txt
    t=$(awk '/real/{print $2}' /tmp/_bt.txt)
    awk "BEGIN{exit !($t<$best)}" && best=$t
  done
  echo "$best"
}

IFS=',' read -ra LS <<< "$SIZES"
for L in "${LS[@]}"; do
  nodes=$((L*L))
  for a in dc ac tran; do
    src="cir/mesh_${L}_${a}.cir"
    sed '1a\
.options klu' "$src" > /tmp/k.cir
    cp "$src" /tmp/s.cir
    tk=$(timeit /tmp/k.cir); ts=$(timeit /tmp/s.cir)
    echo "$L,$nodes,$a,KLU,$tk"    >> "$CSV"
    echo "$L,$nodes,$a,SPARSE,$ts" >> "$CSV"
    printf "  mesh %2dx%-2d (%5d nodes) %-4s : KLU %6ss  SPARSE %6ss  (%.1fx)\n" \
       "$L" "$L" "$nodes" "$a" "$tk" "$ts" "$(awk "BEGIN{print $ts/$tk}")"
  done
done
echo "wrote $CSV"
