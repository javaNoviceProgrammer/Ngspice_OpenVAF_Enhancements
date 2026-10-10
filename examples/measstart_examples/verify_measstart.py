#!/usr/bin/env python3
"""verify_measstart.py -- Enhancements 848 and 849: a measurement window's start.

F4 and F5 of the second robustness campaign of 2026-10-10.

F4, Enhancement-848: AVG, INTEG and RMS with `from=` interpolated the value at
`from` by OVERWRITING the first sample inside the window, so that sample never
entered the sum: the trapezoid ran from `from` straight to the second sample.
On a triangle whose corner is that sample, AVG and INTEG were off by 3e-4.

F5, Enhancement-849: WHEN with `td=` spent the window's first sample on
remembering a value and its second on classifying the side, so a crossing
between them was lost, and with several crossings the next one was reported.
FIND..WHEN and TRIG with TD, WHEN with FROM, and dc and ac sweeps entered
through FROM or TO did the same.

The window now starts at the boundary: its value there is interpolated as a
point of its own. The checks pick `td` and `from` from the samples of a first
run, so they do not depend on where the timestep control puts them.

  [1] AVG and INTEG over a window opening just before a corner sample: exact
  [2] RMS over a ramp-then-flat window opening just before the corner: the
      trapezoid on the first piece, exact on the rest
  [3] (control) AVG and INTEG with `from` on a sample, and without a window
  [4] WHEN td= with the crossing between the first two samples after TD
  [5] WHEN td= with the crossing between the last sample before TD and the
      first after it, past TD; and (control) one before TD is not counted
  [6] FIND..WHEN, TRIG/TARG and a two-vector WHEN with that TD, and WHEN from=
  [7] several crossings: fall=1 td= reports the first after TD, not the next
  [8] ac: WHEN with from= on a low-pass
  [9] dc: WHEN with from= on a rising sweep, through to= on a falling one, and
      with from= on nested sweeps
  [10] (control) nested dc sweeps: rise=2 without a window entry is unchanged
  [11] (control) WHEN without td, and with a td well before the crossing

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

WORK = tempfile.mkdtemp(prefix="measstart_")
US = 1e-6
checks = passed = 0


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


def measure(name, netlist, analysis, meas):
    """run `analysis` with the .meas cards in `meas` = [(name, card)], and return
    {name: value}, NaN for a measurement that failed"""
    lines = ["* " + name, netlist.strip()] + [".meas %s %s %s" % (analysis.split()[0], n, c) for n, c in meas]
    lines += ["." + analysis, ".control", "set numdgt=17", "run"] + ["print " + n for n, _ in meas]
    lines += [".endc", ".end", ""]
    rc, out = run(name, "\n".join(lines))
    got = {}
    for n, _ in meas:
        m = re.search(r"^%s = (\S+)" % n, out, re.M)
        got[n] = float(m.group(1)) if m else float("nan")
    return got


def samples(name, netlist, analysis, vec="time"):
    """the scale of a run of `analysis`"""
    out = os.path.join(WORK, name + ".txt")
    run(name + "_s", "* %s\n%s\n.%s\n.control\nset numdgt=17\nset wr_singlescale\nset wr_vecnames\nrun\n"
        "wrdata %s %s\n.endc\n.end\n" % (name, netlist.strip(), analysis, out, vec))
    with open(out) as f:
        next(f)
        return [float(line.split()[0]) for line in f if line.strip()]


def near(got, want, tol=1e-9):
    return got == got and abs(got - want) <= tol * max(abs(want), 1e-30)


def fmt(got, want):
    return f"got {got!r}, want {want!r}"


# [1]..[3] F4: AVG, INTEG, RMS with from= ------------------------------------------
TRI = "v1 1 0 pwl(0 0 1u 1 2u 0)\nv2 2 0 pwl(0 0 1u 1 3u 1)\nr1 1 0 1k\nr2 2 0 1k"
s = samples("tri", TRI, "tran 0.1u 2u")
k = min(range(len(s)), key=lambda j: abs(s[j] - US))        # the corner is a breakpoint, so a sample
lo = s[k - 1] + 0.7 * (s[k] - s[k - 1])                      # opens the window just before it
hi = 1.5 * US
got = measure("f4", TRI, "tran 0.1u 2u",
              [("a1", "avg v(1) from=%r to=%r" % (lo, hi)), ("i1", "integ v(1) from=%r to=%r" % (lo, hi)),
               ("q2", "rms v(2) from=%r to=%r" % (lo, hi)),
               ("a0", "avg v(1) from=%r to=%r" % (s[k], hi)), ("i0", "integ v(1) from=%r to=%r" % (s[k], hi)),
               ("aw", "avg v(1)")])
# v(1) is t/1us up to the corner, 2 - t/1us after it; the integrals are exact for a pwl
integ = (US - lo) * (lo / US + 1) / 2 + (hi - US) * (1 + (2 - hi / US)) / 2
check("[1] AVG over a window opening just before a corner sample: exact (1.1e-4 low on E-844)",
      near(got["a1"], integ / (hi - lo)), fmt(got["a1"], integ / (hi - lo)))
check("[1] INTEG over the same window: exact", near(got["i1"], integ), fmt(got["i1"], integ))
# v(2)^2: a trapezoid on the first piece, where its widths differ; exact on the flat part
q2 = math.sqrt(((US - lo) * ((lo / US) ** 2 + 1) / 2 + (hi - US)) / (hi - lo))
check("[2] RMS of a ramp-then-flat over the same window: the trapezoid on the ramp, exact after",
      near(got["q2"], q2), fmt(got["q2"], q2))
i0 = (hi - US) * (1 + (2 - hi / US)) / 2
check("[3] (control) AVG and INTEG with `from` on the corner sample, and AVG without a window",
      near(got["a0"], i0 / (hi - US)) and near(got["i0"], i0) and near(got["aw"], 0.5),
      f"a0 {got['a0']!r}, i0 {got['i0']!r}, aw {got['aw']!r}")

# [4]..[6] F5: WHEN with td= on a ramp -------------------------------------------
RAMP = ("v1 1 0 pwl(0 0 1u 1)\nv4 4 0 pwl(0 0 1u 2)\nv5 5 0 dc %r\n"
        "r1 1 0 1k\nr4 4 0 1k\nr5 5 0 1k")
TR = "tran 0.1u 1u 0 0.1u"
s = samples("ramp", RAMP % 0.55, TR)
# v(1) = t/1us. Pick the interval [s[j], s[j+1]] holding 0.55 us, at least two samples in
j = max(2, max(i for i in range(len(s) - 1) if s[i] < 0.55 * US))
tc = 0.5 * (s[j] + s[j + 1])                          # a crossing mid-interval
td_a = 0.5 * (s[j - 1] + s[j])                        # TD before s[j]: [s[j], s[j+1]] is the first interval
td_b = s[j] + 0.4 * (s[j + 1] - s[j])                 # TD inside it
tb = s[j] + 0.7 * (s[j + 1] - s[j])                   # a crossing past TD, before the first sample after it
tx = s[j] + 0.2 * (s[j + 1] - s[j])                   # a crossing before TD
va, vb, vx = tc / US, tb / US, tx / US
got = measure("f5", RAMP % va, TR,
              [("w1", "when v(1)=%r rise=1 td=%r" % (va, td_a)),
               ("w3", "when v(1)=%r rise=1 td=%r" % (vb, td_b)),
               ("w4", "when v(1)=%r rise=1 td=%r" % (vx, td_b)),
               ("f1", "find v(4) when v(1)=%r rise=1 td=%r" % (va, td_a)),
               ("t1", "trig v(1) val=%r rise=1 td=%r targ v(1) val=0.9 rise=1" % (va, td_a)),
               ("w7", "when v(1)=v(5) rise=1 td=%r" % td_a),
               ("w6", "when v(1)=%r rise=1 from=%r" % (va, td_a)),
               ("w0", "when v(1)=%r rise=1" % va),
               ("w2", "when v(1)=%r rise=1 td=%r" % (va, 0.3 * tc))])
check("[4] WHEN td= with the crossing between the first two samples after TD: found (failed before)",
      near(got["w1"], tc), fmt(got["w1"], tc))
check("[5] WHEN td= with the crossing past TD, before the first sample after it: found",
      near(got["w3"], tb), fmt(got["w3"], tb))
check("[5] (control) a crossing before TD is not counted",
      got["w4"] != got["w4"], f"got {got['w4']!r}")
check("[6] FIND..WHEN with that TD", near(got["f1"], 2 * va), fmt(got["f1"], 2 * va))
check("[6] TRIG with that TD", near(got["t1"], 0.9 * US - tc), fmt(got["t1"], 0.9 * US - tc))
check("[6] a two-vector WHEN with that TD", near(got["w7"], tc), fmt(got["w7"], tc))
check("[6] WHEN from= at the same place", near(got["w6"], tc), fmt(got["w6"], tc))
check("[11] (control) WHEN without td, and with a td well before the crossing",
      near(got["w0"], tc) and near(got["w2"], tc), f"w0 {got['w0']!r}, w2 {got['w2']!r}")

# [7] several crossings --------------------------------------------------------
TRIW = "v3 3 0 pwl(0 0 0.2u 1 0.4u 0 0.6u 1 0.8u 0 1u 1)\nr3 3 0 1k"
s = samples("triw", TRIW, "tran 0.1u 1u")
# falls on (0.2, 0.4) us and (0.6, 0.8) us; take an interval of the first, past 0.25 us
j = min(i for i in range(2, len(s) - 1) if s[i] > 0.25 * US and s[i + 1] < 0.4 * US)
tc = 0.5 * (s[j] + s[j + 1])
val = 1 - (tc - 0.2 * US) / (0.2 * US)
td = 0.5 * (s[j - 1] + s[j])
got = measure("f5b", TRIW, "tran 0.1u 1u", [("w5", "when v(3)=%r fall=1 td=%r" % (val, td))])
check("[7] fall=1 td= with the first fall after TD in the first interval: that fall, not the next",
      near(got["w5"], tc), fmt(got["w5"], tc))

# [8] ac -----------------------------------------------------------------------
FC = 4.5e3
RC = "v1 in 0 dc 0 ac 1\nr1 in out 1k\nc1 out 0 %r" % (1 / (2 * math.pi * 1e3 * FC))
vm = lambda f: 1 / math.sqrt(1 + (f / FC) ** 2)  # noqa: E731
val = vm(4.5e3)
fx = 4e3 + (vm(4e3) - val) / (vm(4e3) - vm(5e3)) * 1e3    # linear between the samples at 4k and 5k
got = measure("ac", RC, "ac lin 10 1k 10k", [("f3", "when vm(out)=%r fall=1 from=3.5k" % val)])
check("[8] ac: WHEN from= with the crossing between the first two samples after FROM",
      near(got["f3"], fx), fmt(got["f3"], fx))

# [9]..[10] dc -------------------------------------------------------------------
DC = "v1 1 0 0\nr1 1 0 1k"
got = measure("dcup", DC, "dc v1 0 1 0.1",
              [("d1", "when v(1)=0.55 rise=1 from=0.45"), ("d2", "when v(1)=0.47 rise=1 from=0.45")])
check("[9] dc: WHEN from= on a rising sweep, the crossing in the first interval after FROM, or just before",
      near(got["d1"], 0.55) and near(got["d2"], 0.47), f"d1 {got['d1']!r}, d2 {got['d2']!r}")
got = measure("dcdn", DC, "dc v1 1 0 -0.1", [("d3", "when v(1)=0.55 fall=1 from=0.2 to=0.65")])
check("[9] dc: WHEN on a falling sweep entering its window through to=", near(got["d3"], 0.55),
      fmt(got["d3"], 0.55))
NEST = "v1 1 0 0\nv3 3 0 0\nr1 1 0 1k\nr3 3 0 1k\nb2 2 0 v=v(1)+0.3*v(3)"
got = measure("dcnest", NEST, "dc v1 0 1 0.1 v3 0 1 1",
              [("n0", "when v(2)=0.55 rise=2"), ("n1", "when v(2)=0.55 rise=2 to=0.8"),
               ("n4", "when v(2)=0.55 rise=1 from=0.45")])
check("[9] dc: WHEN from= on nested sweeps finds the first sweep's crossing", near(got["n4"], 0.55),
      fmt(got["n4"], 0.55))
check("[10] (control) nested dc sweeps: rise=2 is the second sweep's 0.25, with and without to=",
      near(got["n0"], 0.25) and near(got["n1"], 0.25), f"n0 {got['n0']!r}, n1 {got['n1']!r}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
