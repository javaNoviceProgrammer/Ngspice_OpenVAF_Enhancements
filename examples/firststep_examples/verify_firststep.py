#!/usr/bin/env python3
"""verify_firststep.py -- Enhancement-846: the first transient step is checked
against the truncation error; Enhancement-847: an inductor's tolerance floor is
a voltage.

F2 and F3 of the second robustness campaign of 2026-10-10.

F2: the first step was accepted unchecked ("no check on first time point"): its
size is min(tstop/100, tstep)/100 whatever the circuit's time constants and the
tolerances. A sine into a 1 ns RC took a 1 ns backward-Euler step -- 32 % off at
reltol = 1e-7 -- and a `uic` charge 21 %. After an operating point the circuit
was at rest before t = 0, which is the history the check needs; it is now made,
down to a floor of a thousandth of that first step.

F3: the bad first point stayed in every later estimate's divided differences: a
7-element linear L-C network failed "Timestep too small" right after it at
reltol <= 1e-6. And CKTterr's absolute floor for an inductor -- whose state
derivative is a VOLTAGE -- was `abstol`, a current: at reltol = 1e-7 with a
small `chgtol` the network still collapsed under KLU. It is now `vntol`.

  [1] a sine into a 1 ns RC from the op, reltol = 1e-7: the first sample, and the
      whole run, against the exact solution
  [2] a 1 ns RC charged from `.ic v(1)=0` with `uic`: the first step's sample
  [3] the reduced L-C network at reltol 1e-6, 1e-7, and 1e-7 with chgtol 1e-20,
      and at the defaults (control): each runs to tstop
  [4] (control) an inconsistent `.ic` -- a source across a capacitor holding
      another value -- still runs: the check stops at its floor
  [5] (control) an RC step response at the default tolerances, against exact

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

WORK = tempfile.mkdtemp(prefix="firststep_")
checks = passed = 0

LC = """r9 5 0 2285.405580218766
r10 1 8 757.4759645133245
l17 3 1 5.58612830132151e-07
c18 5 1 2.914119347771001e-12
c19 6 3 2.4794844806727606e-12
l20 0 6 2.3225052696110058e-05
l23 8 6 1.7832400428838883e-06
i0 0 1 sin(0.0002786245656298781 -0.00037963181379056766 929399.7948612613)
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300,
                       errors="replace")
    return p.returncode, p.stdout + p.stderr


def table(path):
    rows = []
    with open(path) as f:
        next(f)
        for line in f:
            p = line.split()
            if len(p) >= 2:
                rows.append((float(p[0]), float(p[1])))
    return rows


# [1] a sine into a 1 ns RC, from the op
A, R, TAU, W = 1e-3, 1e3, 1e-9, 2 * math.pi * 1e8


def v_sine(t):
    return A * R / (1 + (W * TAU) ** 2) * (math.sin(W * t) - W * TAU * math.cos(W * t)
                                           + W * TAU * math.exp(-t / TAU))


out1 = os.path.join(WORK, "w1.txt")
rc, out = run("sine", "* sine into a 1 ns RC\ni1 0 1 sin(0 1m 100meg)\nr1 1 0 1k\nc1 1 0 1p\n"
              ".option reltol=1e-7\n.control\nset numdgt=17\nset wr_singlescale\nset wr_vecnames\n"
              "tran 1u 10u 0 1n\nwrdata %s v(1)\n.endc\n.end\n" % out1)
rows = table(out1) if rc == 0 and os.path.exists(out1) else []
scale = A * R / math.sqrt(1 + (W * TAU) ** 2)
if len(rows) > 2:
    t1, v1 = rows[1]
    e1 = abs(v1 - v_sine(t1)) / scale
    emax = max(abs(v - v_sine(t)) for t, v in rows) / scale
else:
    t1 = e1 = emax = float("nan")
check("[1] sine into a 1 ns RC, reltol 1e-7: the first sample within 1e-5 of the swing (3.2e-3 on E-844)",
      e1 < 1e-5, f"first step {t1:.3g} s, error {e1:.2e}")
check("[1] ...and the whole run within 1e-4 of the swing", emax < 1e-4, f"max error {emax:.2e}")

# [2] a uic charge. Enhancement-852 gave a uic run its t = 0 point: the first
#     step is index 1
rc, out = run("uic", "* uic RC\ni1 0 1 1m\nr1 1 0 1k\nc1 1 0 1p\n.ic v(1)=0\n.option reltol=1e-7\n"
              ".control\nset numdgt=17\ntran 1u 10u uic\nprint time[1] v(1)[1]\n.endc\n.end\n")
m_t = re.search(r"^time\[1\] = (\S+)", out, re.M)
m_v = re.search(r"^v\(1\)\[1\] = (\S+)", out, re.M)
if m_t and m_v:
    t0, v0 = float(m_t.group(1)), float(m_v.group(1))
    e0 = abs(v0 - (1 - math.exp(-t0 / TAU)))
else:
    t0 = e0 = float("nan")
check("[2] a 1 ns RC charged from .ic v(1)=0 under uic: the first step's sample within 1e-3 V of exact (0.13 V on E-844)",
      e0 < 1e-3, f"first step {t0:.3g} s, error {e0:.2e} V")

# [3] the reduced L-C network
for opts in ("reltol=1e-6", "reltol=1e-7", "reltol=1e-7 chgtol=1e-20", ""):
    deck = "* L-C network\n" + LC + (".option %s\n" % opts if opts else "") + \
        ".control\ntran 5.3798161218083645e-08 1.0759632243616729e-05\nprint length(time)\n.endc\n.end\n"
    rc, out = run("lc", deck)
    small = "Timestep too small" in out
    n = re.search(r"^length\(time\) = (\S+)", out, re.M)
    check("[3] the L-C network at %s runs to tstop%s" % (opts or "the defaults", "" if opts else " (control)"),
          rc == 0 and not small and n is not None, "Timestep too small" if small else f"rc={rc}")

# [4] an inconsistent .ic
rc, out = run("jump", "* inconsistent ic\nv1 1 0 1\nr1 1 2 1k\nc1 1 0 1n\nc2 2 0 1n\n.ic v(1)=0 v(2)=0\n"
              ".option reltol=1e-6\n.control\ntran 1u 10u uic\nprint v(2)[length(time)-1]\n.endc\n.end\n")
m = re.search(r"^v\(2\)\[length\(time\)-1\] = (\S+)", out, re.M)
check("[4] (control) an .ic a source contradicts still runs under uic, and v(2) settles to 1 V",
      rc == 0 and m is not None and abs(float(m.group(1)) - 1) < 1e-3, f"rc={rc}")

# [5] default tolerances
rc, out = run("step", "* RC step\nv1 1 0 pwl(0 0 1n 1)\nr1 1 2 1k\nc1 2 0 1n\n.control\nset numdgt=12\n"
              "tran 10n 5u\nmeas tran v2 find v(2) at=2u\nprint v2\n.endc\n.end\n")
m = re.search(r"^v2 = (\S+)", out, re.M)
# exact: a 1 ns ramp into a 1 us RC, at 2 us
ex = 1 - (math.exp(-(2e-6 - 1e-9) / 1e-6) - math.exp(-2e-6 / 1e-6)) * 1e-6 / 1e-9
check("[5] (control) an RC step response at the default tolerances: v(2) at 2 us within 1e-3 of exact",
      m is not None and abs(float(m.group(1)) - ex) < 1e-3, f"got {m.group(1) if m else None}, exact {ex:.6f}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
