#!/usr/bin/env bash
# Run the laplace_lpf DC/AC/transient examples, plus the four-forms
# cross-check (laplace_variants) and the isolated laplace_zd fixture, and
# write dc.txt, ac.txt, tran.txt, dc_variants.txt, dc_zd_only.txt. Works on
# macOS and Linux: the ngspice / openvaf-r binaries are picked from
# bin/<os>/<arch>/ for the current machine, and the models are recompiled
# for this platform (see _setup.sh).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/_setup.sh"        # sets NG, VAF, OSDI, OSDI_VARIANTS, OSDI_ZD for this platform
cd "$DIR"

for sim in dc ac tran; do
  base="${sim}_sim.cir"
  out="${DIR}/${sim}.txt"
  work="${DIR}/.${sim}.cir"
  sed -e "s|RESULTFILE|${out}|" -e "s|OSDIFILE|${OSDI}|" "$base" > "$work"
  "$NG" --batch "$work" >"${DIR}/${sim}.log" 2>&1
  rm -f "$work"
  echo "[$sim] wrote $out"
done

base="dc_variants.cir"
out="${DIR}/dc_variants.txt"
work="${DIR}/.dc_variants.cir"
sed -e "s|RESULTFILE|${out}|" -e "s|OSDIFILE_VARIANTS|${OSDI_VARIANTS}|" "$base" > "$work"
"$NG" --batch "$work" >"${DIR}/dc_variants.log" 2>&1
rm -f "$work"
echo "[dc_variants] wrote $out"

base="dc_zd_only.cir"
out="${DIR}/dc_zd_only.txt"
work="${DIR}/.dc_zd_only.cir"
sed -e "s|RESULTFILE|${out}|" -e "s|OSDIFILE_ZD|${OSDI_ZD}|" "$base" > "$work"
"$NG" --batch "$work" >"${DIR}/dc_zd_only.log" 2>&1
rm -f "$work"
echo "[dc_zd_only] wrote $out"
