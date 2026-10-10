#!/usr/bin/env python3
"""verify_noisegain.py -- Enhancement-850: the input-referred noise divides by
the gain the circuit has.

F6 of the second robustness campaign of 2026-10-10.

The noise analysis refers each device's noise to the input by dividing by the
gain squared from the input source to the output, and floored that at 1e-20, a
gain of 1e-10, without a word. A real circuit reaches it: 1 fF into 1 kOhm has a
gain of 6.3e-12 at 1 Hz, and inoise_spectrum came out 40.7 V/sqrt(Hz) where
onoise/|gain| is 648. The floor now stands only for a zero, 1e-100, and a
frequency that reaches it is reported once per analysis.

  [1] 1 fF into 1 kOhm: inoise/onoise = 1/|H| at 1, 50.5 and 100 Hz
  [2] ...with no note about the gain
  [3] an output the input does not reach: a note names the source and counts
      the frequencies
  [4] (control) an RC low-pass: inoise/onoise = 1/|H| at every point, no note

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="noisegain_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def noise(name, netlist, sweep):
    """run `noise v(out) v1 <sweep>` and return (rows of (f, inoise, onoise), output)"""
    out = os.path.join(WORK, name + ".txt")
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\nset wr_singlescale\nnoise v(out) v1 %s\n"
                "setplot noise1\nwrdata %s inoise_spectrum onoise_spectrum\n.endc\n.end\n"
                % (name, netlist, sweep, out))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300,
                       errors="replace")
    rows = []
    if os.path.exists(out):
        for line in open(out):
            v = line.split()
            if len(v) >= 3:
                rows.append(tuple(float(x) for x in v[:3]))
    return rows, p.stdout + p.stderr


def ratio_err(rows, gain):
    """the largest relative error of inoise/onoise against 1/|gain(f)|"""
    if not rows:
        return float("inf")
    return max(abs((i / o) * gain(f) - 1) for f, i, o in rows)


# [1], [2] a gain of 6.3e-12 at 1 Hz
R, C = 1e3, 1e-15
hp = lambda f: 2 * math.pi * f * R * C / math.hypot(1, 2 * math.pi * f * R * C)  # noqa: E731
rows, out = noise("hp", "v1 in 0 dc 0 ac 1\nc1 in out %r\nr1 out 0 %r" % (C, R), "lin 3 1 100")
e = ratio_err(rows, hp)
check("[1] 1 fF into 1 kOhm: inoise/onoise = 1/|H| at 1, 50.5 and 100 Hz (16x low at 1 Hz on E-844)",
      len(rows) == 3 and e < 1e-6, f"{len(rows)} points, worst {e:.2e}")
check("[2] ...and no note about the gain, which is real", "gain from" not in out)

# [3] a zero gain
rows, out = noise("zero", "v1 in 0 dc 0 ac 1\nr1 in 0 1k\nr2 out 0 1k", "dec 2 1 100")
m = re.search(r"gain from (\S+) to the output is zero at (\d+) of (\d+) frequencies, the first (\S+) Hz", out)
check("[3] an output the input does not reach: a note names v1 and counts 5 of 5 frequencies from 1 Hz",
      m is not None and m.group(1) == "v1" and m.group(2) == "5" and m.group(3) == "5"
      and float(m.group(4)) == 1.0, m.group(0) if m else "no note")

# [4] control
R, C = 1e3, 1e-9
lp = lambda f: 1 / math.hypot(1, 2 * math.pi * f * R * C)  # noqa: E731
rows, out = noise("lp", "v1 in 0 dc 0 ac 1\nr1 in out %r\nc1 out 0 %r" % (R, C), "dec 5 1k 10meg")
e = ratio_err(rows, lp)
check("[4] (control) an RC low-pass: inoise/onoise = 1/|H| at every point, and no note",
      len(rows) == 21 and e < 1e-6 and "gain from" not in out, f"{len(rows)} points, worst {e:.2e}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
