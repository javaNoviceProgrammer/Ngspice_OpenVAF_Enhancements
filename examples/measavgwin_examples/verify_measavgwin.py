#!/usr/bin/env python3
"""verify_measavgwin.py -- Enhancement-316: `.meas AVG` ended one timestep short of `to`.

Found by oracle-checking `.meas` against its own contract (the E-302/303/304 family): AVG is
the same quantity as INTEG/(to-from) over the identical window. measure_minMaxAvg()'s final
window-clip guarded the whole accumulation with `!AlmostEqualUlps(svalue, to, 100)`, so when
the first out-of-window sample fell within 100 ULPs of `to`, the entire final trapezoid
[sprev, to] -- a full timestep -- was dropped. AVG's window then ended one timestep short of
`to`, so AVG != INTEG/(to-from) (~1.6% off on the signal below). measure_rms_integral() (INTEG/
RMS) always adds the final point, interpolating only when the sample overshoots `to`; the fix
makes AVG do the same -- the guard now gates only the interpolation, not the accumulation.

Check (fails on the pre-fix binary): over a window whose end coincides (to <100 ULPs) with a
sample, AVG equals INTEG/(to-from). Also confirms AVG's echoed window reaches `to`.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


FROM, TO = 9.355e-05, 0.00064624
r = subprocess.run([NGSPICE, "-b", "meas_avg.sp"], cwd=HERE, capture_output=True,
                   text=True, timeout=60, errors="replace")
out = (r.stdout or "") + (r.stderr or "")

def val(name):
    m = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None

avg1, int1 = val("avg1"), val("int1")
print("Enhancement-316: .meas AVG window reaches `to` (AVG == INTEG/(to-from))")
if avg1 is None or int1 is None:
    check("AVG and INTEG produced values", False, out[-160:])
else:
    ref = int1 / (TO - FROM)
    rel = abs(avg1 - ref) / abs(ref)
    check("AVG equals INTEG/(to-from) over the same window (fails pre-fix)",
          rel < 1e-3, f"avg1={avg1:.6e} int1/dur={ref:.6e} rel={rel:.2e}")
    aw = re.search(r"avg1\s*=.*?to=\s*([-\d.eE+]+)", out)
    to_echo = float(aw.group(1)) if aw else None
    check("AVG's window reaches `to` (was one timestep short)",
          to_echo is not None and abs(to_echo - TO) < 1e-9, f"to={to_echo}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
