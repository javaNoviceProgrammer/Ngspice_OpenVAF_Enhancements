#!/usr/bin/env bash
# Run each absdelay example with both KLU and SPARSE solvers (version2 ngspice)
# and confirm the two solvers produce identical results.
set -e
NG=../../bin/macos/apple-silicon/ngspice
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

for sim in dc ac tran; do
  base="${sim}_sim.cir"
  for solver in klu sparse; do
    out="${DIR}/${sim}_${solver}.txt"
    work="${DIR}/.${sim}_${solver}.cir"
    # substitute result path
    sed "s|RESULTFILE|${out}|" "$base" > "$work"
    if [ "$solver" = "klu" ]; then
      # insert .options klu right after the title line
      sed -i '' '1a\
.options klu
' "$work"
    fi
    $NG --batch "$work" >/dev/null 2>&1
    rm -f "$work"
  done
  # compare the two solver outputs
  if diff -q "${sim}_klu.txt" "${sim}_sparse.txt" >/dev/null; then
    echo "[$sim]  KLU vs SPARSE: IDENTICAL"
  else
    md=$(paste "${sim}_klu.txt" "${sim}_sparse.txt" | awk '{n=NF/2; m=0; for(i=1;i<=n;i++){d=$i-$(i+n); if(d<0)d=-d; if(d>m)m=d} if(m>g)g=m} END{printf "%.3e", g}')
    echo "[$sim]  KLU vs SPARSE: max abs diff = $md"
  fi
done
