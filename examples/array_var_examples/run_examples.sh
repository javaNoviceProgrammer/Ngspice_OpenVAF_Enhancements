#!/usr/bin/env bash
# Run the array_var_fir (array-variable declaration) DC example and write
# dc.txt. Works on macOS and Linux: the ngspice / openvaf-r binaries are
# picked from bin/<os>/<arch>/ for the current machine, and the model is
# recompiled for this platform (see _setup.sh).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/_setup.sh"        # sets NG, VAF, OSDI for this platform
cd "$DIR"

sim="dc"
base="${sim}_sim.cir"
out="${DIR}/${sim}.txt"
work="${DIR}/.${sim}.cir"
sed -e "s|RESULTFILE|${out}|" -e "s|OSDIFILE|${OSDI}|" "$base" > "$work"
"$NG" --batch "$work" >"${DIR}/${sim}.log" 2>&1
rm -f "$work"
echo "[$sim] wrote $out"
