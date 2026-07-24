#!/usr/bin/env python3
"""verify_qpssleak.py -- Enhancement-319: the transient-form QPSS Fourier projection leaked the
fundamental into every mixing bin.

`qpss <expr> <f1> <f2> [periods] [maxorder]` (the transient-form, as opposed to `... hb K1 K2`)
computed each 2-D harmonic by a trapezoidal integral of v(t)exp(-j2pi f t) over the "last period"
[tt[i0], tt[end]] of the raw transient grid. That window was not exactly the beat period T, its
steps were non-uniform, and its endpoints were non-periodic, so the large DC/fundamental leaked
~tstep/T into EVERY mixing bin. On a LINEAR two-tone RC (where every product k1*f1+k2*f2 with
|k1|+|k2|>=2 is exactly 0) every bin read ~5.8e-4 * |dominant line| (~-45 dB) -- confirmed against
the HB-form (~1e-16) and a plain .tran + uniform DFT.

The fix resamples the last beat period onto a uniform grid over EXACTLY [wend-T, wend) and uses a
rectangular-rule DFT; for commensurate tones every harmonic completes an integer number of cycles
in T, so it is exact. The spurious floor drops ~4 decades (to ~-122 dB); real products (e.g. the
strong IM3 in qpss_examples) are unchanged.

Check (fails on the pre-fix binary): the linear circuit's mixing bins are < 1e-5 of the
fundamental (pre-fix ~7e-3), while the two fundamentals are present.
"""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

passed = failed = 0
def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    passed += ok; failed += (not ok)

deck = open(os.path.join(HERE, "qpss_linear.cir")).read().rstrip() + \
    "\n.control\nqpss v(a) 100meg 110meg 8 3\n.endc\n.end\n"
# strip the trailing .end from the base file, append the control block
deck = deck.replace(".end\n.control", ".control")
with open(os.path.join(HERE, "_run.cir"), "w") as fh:
    fh.write(deck)
r = subprocess.run([NGSPICE, "-b", "_run.cir"], cwd=HERE, capture_output=True, text=True, timeout=120)
out = (r.stdout or "") + (r.stderr or "")

# parse (k1,k2) |value| rows
rows = {}
for m in re.finditer(r"\(\s*(-?\d+),\s*(-?\d+)\)\s+[-\d.eE+]+\s+([-\d.eE+]+)", out):
    rows[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))

print("Enhancement-319: transient-form QPSS mixing-bin leakage on a linear circuit")
fund = max(rows.get((1, 0), 0.0), rows.get((0, 1), 0.0))
check("both fundamentals present (~0.08)", fund > 0.05, f"max fund={fund:.4e}")
mixing = {k: v for k, v in rows.items() if abs(k[0]) + abs(k[1]) >= 2}
worst = max(mixing.values()) if mixing else 0.0
check("all mixing products < 1e-5 of the fundamental (fails pre-fix, was ~7e-3)",
      len(mixing) > 0 and worst < 1e-5 * fund, f"worst mixing={worst:.3e}, fund={fund:.3e}, rel={worst/fund:.1e}")

for f in os.listdir(HERE):
    if f.startswith("_"):
        os.remove(os.path.join(HERE, f))
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
