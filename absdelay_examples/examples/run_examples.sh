#!/usr/bin/env bash
# Run each absdelay example with both KLU and SPARSE solvers and confirm the two
# solvers produce identical results. Works on macOS and Linux: the ngspice /
# openvaf-r binaries are picked from bin/<os>/<arch>/ for the current machine,
# and the model is recompiled for this platform (see ../_setup.sh).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/../_setup.sh"        # sets NG, VAF, OSDI for this platform
cd "$DIR"

for sim in dc ac tran; do
  base="${sim}_sim.cir"
  for solver in klu sparse; do
    out="${DIR}/${sim}_${solver}.txt"
    work="${DIR}/.${sim}_${solver}.cir"
    # substitute the result-file and osdi-model placeholders
    sed -e "s|RESULTFILE|${out}|" -e "s|OSDIFILE|${OSDI}|" "$base" > "$work"
    if [ "$solver" = "klu" ]; then
      # insert ".options klu" after the title line (portable across BSD/GNU sed)
      sed '1a\
.options klu' "$work" > "$work.tmp" && mv "$work.tmp" "$work"
    fi
    "$NG" --batch "$work" >/dev/null 2>&1
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
