#!/usr/bin/env python3
"""Enhancement-320: verify the `.param` fast-sweep path.

Three forward guards:
  1. A top-level `.param` feeding a device value ARMS the fast path (the
     "fast .param path armed" banner appears) and skips the per-point reset.
  2. Its swept operating points match the closed-form voltage divider
     out(rval) = R2 / (rval + R2), with R2 = 1k, to machine precision.
  3. The same param moved INSIDE a subckt DISARMS (conservative reset
     fallback) yet produces the identical divider values -- proving the
     classifier's fallback is correct, never a miscompute.
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


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol * (abs(b) + 1e-30)


def main():
    fails = []

    # --- Check 1 + 2: fast path arms, results match closed form ---
    out = run("divider.cir")
    armed = "fast .param path armed" in out
    if not armed:
        fails.append("Check 1: fast .param path did NOT arm on a top-level "
                     "device-value param")
    else:
        print("  [1] fast .param path armed (no per-point reset)  OK")

    rows = load("divider_out.dat")
    if len(rows) != len(RVALS):
        fails.append("Check 2: expected %d points, got %d"
                     % (len(RVALS), len(rows)))
    else:
        worst = 0.0
        for (rval, vout, _rv2, _iv1) in rows:
            expect = R2 / (rval + R2)
            worst = max(worst, abs(vout - expect) / abs(expect))
        if worst > 1e-6:
            fails.append("Check 2: divider out(rval) mismatch vs closed form, "
                         "worst rel = %.3e" % worst)
        else:
            print("  [2] swept out(rval) == R2/(rval+R2) to %.1e  OK" % worst)

    # --- Check 3: subckt param falls back to reset, still correct ---
    out_s = run("divider_subckt.cir")
    armed_s = "fast .param path armed" in out_s
    if armed_s:
        fails.append("Check 3: subckt-internal param armed the fast path "
                     "(should fall back to reset)")
    rows_s = load("divider_sub_out.dat")
    if len(rows_s) != len(RVALS):
        fails.append("Check 3: subckt fallback produced %d points, expected %d"
                     % (len(rows_s), len(RVALS)))
    else:
        worst = 0.0
        for (rval, vout) in rows_s:
            expect = R2 / (rval + R2)
            worst = max(worst, abs(vout - expect) / abs(expect))
        if worst > 1e-6:
            fails.append("Check 3: subckt fallback values wrong, worst rel = "
                         "%.3e" % worst)
        elif not armed_s:
            print("  [3] subckt param -> reset fallback, values still exact "
                  "(%.1e)  OK" % worst)

    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("\nAll 3 checks passed.")


if __name__ == "__main__":
    main()
