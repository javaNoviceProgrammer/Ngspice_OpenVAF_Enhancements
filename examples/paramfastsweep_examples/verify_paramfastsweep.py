#!/usr/bin/env python3
"""Enhancement-320 / -321: verify the `.param` fast-sweep path.

Four forward guards:
  1. A top-level `.param` feeding a device value ARMS the fast path (the
     "fast .param path armed" banner appears) and skips the per-point reset.
  2. Its swept operating points match the closed-form voltage divider
     out(rval) = R2 / (rval + R2), with R2 = 1k, to machine precision.
  3. (E-321) The same param feeding a device INSIDE a subcircuit also ARMS --
     the flattened instance's expression is recovered from the numparam table --
     and matches the same closed form.
  4. (E-321) A subcircuit that LOCALLY shadows the swept param DISARMS (the
     arm-time self-check catches that the value does not track the global) and
     falls back to reset -- yet still produces the correct (constant) values.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG  # noqa: E402

R2 = 1000.0
RVALS = [100.0 + 100.0 * i for i in range(9)]   # lin 9 100 900


def run(deck):
    r = subprocess.run([NG, "-b", deck], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def load(path):
    with open(os.path.join(HERE, path)) as f:
        return [[float(x) for x in line.split()] for line in f if line.strip()]


def main():
    fails = []

    # --- Check 1 + 2: top-level param arms, matches closed form ---
    out = run("divider.cir")
    if "fast .param path armed" not in out:
        fails.append("Check 1: top-level device-value param did NOT arm")
    else:
        print("  [1] top-level param armed (no per-point reset)  OK")
    rows = load("divider_out.dat")
    worst = max(abs(v - R2 / (rv + R2)) / (R2 / (rv + R2))
                for (rv, v, _rv2, _iv1) in rows)
    if len(rows) != len(RVALS) or worst > 1e-6:
        fails.append("Check 2: divider mismatch vs closed form (worst %.2e)" % worst)
    else:
        print("  [2] out(rval) == R2/(rval+R2) to %.1e  OK" % worst)

    # --- Check 3 (E-321): subckt-internal param arms + correct ---
    out_s = run("divider_subckt.cir")
    if "fast .param path armed" not in out_s:
        fails.append("Check 3: subckt-internal device-value param did NOT arm")
    rows_s = load("divider_sub_out.dat")
    worst_s = max(abs(v - R2 / (rv + R2)) / (R2 / (rv + R2))
                  for (rv, v, _rv2, _iv1) in rows_s)
    if len(rows_s) != len(RVALS) or worst_s > 1e-6:
        fails.append("Check 3: subckt divider mismatch (worst %.2e)" % worst_s)
    elif "fast .param path armed" in out_s:
        print("  [3] subckt-internal param armed + exact (%.1e)  OK" % worst_s)

    # --- Check 4 (E-321): subckt local shadow disarms, still correct ---
    out_sh = run("divider_shadow.cir")
    armed_sh = "fast .param path armed" in out_sh
    rows_sh = load("divider_shadow_out.dat")
    # local rval=500 (constant): out is constant R2/(500+R2) regardless of sweep
    const = R2 / (500.0 + R2)
    worst_sh = max(abs(v - const) / const for (_rv, v) in rows_sh)
    if armed_sh:
        fails.append("Check 4: shadowing subckt armed (should fall back to reset)")
    elif worst_sh > 1e-6:
        fails.append("Check 4: shadow-fallback values wrong (worst %.2e)" % worst_sh)
    else:
        print("  [4] local-shadow subckt -> reset fallback, constant out exact "
              "(%.1e)  OK" % worst_sh)

    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("\nAll 4 checks passed.")


if __name__ == "__main__":
    main()
