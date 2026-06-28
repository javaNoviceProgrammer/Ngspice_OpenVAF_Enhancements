#!/usr/bin/env bash
# KLU vs SPARSE benchmark on absdelay mesh circuits. Runs every generated
# mesh_<L>_<analysis>.cir with both solvers, times each (best of 2 runs), and
# writes results/timings.csv. Works on macOS and Linux: binaries are selected
# from bin/<os>/<arch>/ and the model is recompiled for this platform.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/../_setup.sh"        # sets NG, VAF, OSDI for this platform
SIZES="${1:-20,30,40,50,60,70}"
cd "$DIR"

# gen_bench.py reads the model path from ABSDELAY_OSDI
export ABSDELAY_OSDI="$OSDI"
python3 gen_bench.py "$SIZES" >/dev/null
mkdir -p results
CSV="results/timings.csv"
echo "L,nodes,analysis,solver,seconds" > "$CSV"

# Portable wall-clock timer (python3 is already required by gen_bench.py); this
# avoids /usr/bin/time, whose presence/flags differ across macOS and Linux.
timeit() { # $1 = cir file -> best-of-2 seconds
  local best=99999 t
  for _ in 1 2; do
    t=$(python3 -c 'import subprocess,sys,time
s=time.time()
subprocess.run(sys.argv[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("%.3f" % (time.time()-s))' "$NG" --batch "$1")
    awk "BEGIN{exit !($t<$best)}" && best="$t"
  done
  echo "$best"
}

IFS=',' read -ra LS <<< "$SIZES"
for L in "${LS[@]}"; do
  nodes=$((L*L))
  for a in dc ac tran; do
    src="cir/mesh_${L}_${a}.cir"
    # insert ".options klu" after the title line (portable across BSD/GNU sed)
    sed '1a\
.options klu' "$src" > "$DIR/.k.cir"
    cp "$src" "$DIR/.s.cir"
    tk=$(timeit "$DIR/.k.cir"); ts=$(timeit "$DIR/.s.cir")
    echo "$L,$nodes,$a,KLU,$tk"    >> "$CSV"
    echo "$L,$nodes,$a,SPARSE,$ts" >> "$CSV"
    printf "  mesh %2dx%-2d (%5d nodes) %-4s : KLU %6ss  SPARSE %6ss  (%.1fx)\n" \
       "$L" "$L" "$nodes" "$a" "$tk" "$ts" "$(awk "BEGIN{print $ts/$tk}")"
  done
done
rm -f "$DIR/.k.cir" "$DIR/.s.cir"
echo "wrote $CSV"
