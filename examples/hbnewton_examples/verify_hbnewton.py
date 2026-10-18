#!/usr/bin/env python3
"""verify_hbnewton.py -- Enhancements 902 and 903: the harmonic-balance Newton
converges on overdriven stages. F8 of the analyses correctness campaign of
2026-10-16.

The stages are Family B's overdriven common-emitter stages: a Gummel-Poon BJT
driven into saturation, where the diffusion capacitance (tr = 5 ns) swings
through orders of magnitude each period. The reference is a settled transient
run here, its harmonics fitted on whole periods.

E-902: the Jacobian.
  [1] seed 111 at K = 16 converges (E-901: source stepping stalled)
  [2] seed 111 at K = 48 converges, harmonics 0..6 within 1e-4 of the
      transient (E-901: stalled at lambda 0.87 after 13,518 iterations, 450 s;
      the Jacobian lacked Cdot*dv and Newton converged linearly, x0.84 a step)
  [3] the last level ends quadratically: its last step cuts |F| at least
      100 times (E-901: no level converged at full strength)
E-903: the spectrum of a real signal.
  [4] seed 105 at K = 48 converges (stalled at |F| = 2.1e-10 with the
      Jacobian corrected alone: the floor of an uncorrected anti-symmetric
      part of V)
  [5] every node's dc harmonic is real, exactly (E-901: seed 207's collector
      carried 5.0e-9 V of imaginary dc)
Both:
  [6] Sparse and KLU take the same iterations and continuation steps
  [7] a two-tone `qpss ... hb` of the stage converges

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="hbnewton_")
checks = passed = 0

# Family B (rc7 famB.plan), seeds 111, 105 and 207: overdriven common-emitter stages
SEEDS = {
    111: dict(f=3030481.9108925546, VCC=3.638289345528518, VB=0.7413779165401769, A=0.17347992918306743,
              RB=394.8032600550992, RC=1309.678437815117, CL=5.681252895416378e-13),
    105: dict(f=4308221.733174541, VCC=4.047355940507112, VB=0.7186085489858995, A=0.287896872688055,
              RB=293.98700852385616, RC=1854.9062218662316, CL=1.0047269260111194e-12),
}
MODEL = ".model qm npn is=1e-15 bf=100 vaf=50 cje=1e-12 cjc=5e-13 tf=1e-10 tr=5e-9"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def stage(p):
    return ("vcc vcc 0 %r\nrc vcc c %r\ncl c 0 %r\nvin in 0 dc %r sin(%r %r %r)\nrb in b %r\n"
            "q1 c b 0 qm\n%s\n" % (p["VCC"], p["RC"], p["CL"], p["VB"], p["VB"], p["A"], p["f"],
                                   p["RB"], MODEL))


def run(name, text, timeout=1200):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def hb(name, p, K, opt="", extra=""):
    """run `hb f0 K`; returns (output, {node: [c0..c6]} or None, iterations, levels)"""
    out = run(name, "* hb newton\n%s%s.control\nset numdgt=17\nset hb_verbose\nhb %r %d\n"
                    "let cc = c[0,6]\nlet bb = b[0,6]\nprint cc bb\n%s.endc\n.end\n"
              % (stage(p), opt, p["f"], K, extra))
    m = re.search(r"HB: converged in (\d+) iterations, (\d+) continuation", out)
    spec = {}
    rows = re.findall(r"^(\d+)\t\s*(-?[\d.]+e[+-]\d+),\s*(-?[\d.]+e[+-]\d+)\s+(-?[\d.]+e[+-]\d+),\s*(-?[\d.]+e[+-]\d+)",
                      out, re.M)
    if m and len(rows) >= 7:
        spec = {"c": [complex(float(r[1]), float(r[2])) for r in rows[:7]],
                "b": [complex(float(r[3]), float(r[4])) for r in rows[:7]]}
    return out, (spec or None), (int(m.group(1)) if m else None), (int(m.group(2)) if m else None)


def transient(p):
    """the settled transient's harmonics 0..6 of v(c), v(b), fitted on four whole periods"""
    T = 1.0 / p["f"]
    t1 = 48 * T
    out = run("tran", "* settled transient\n%s.option reltol=1e-9 abstol=1e-15 vntol=1e-12 chgtol=1e-20\n"
                      ".control\nset wr_singlescale\nset numdgt=15\ntran %r %r 0 %r\nwrdata %s v(c) v(b)\n"
                      ".endc\n.end\n" % (stage(p), T / 1000, t1, T / 1000, os.path.join(WORK, "tr.txt")))
    d = np.loadtxt(os.path.join(WORK, "tr.txt"), ndmin=2)
    t = d[:, 0]
    sel = (t >= t1 - 4 * T) & (t <= t1)
    tt = t[sel]
    cols = [np.ones_like(tt)]
    for k in range(1, 61):
        cols += [np.cos(2 * math.pi * k * p["f"] * tt), np.sin(2 * math.pi * k * p["f"] * tt)]
    A = np.column_stack(cols)
    res = {}
    for name, col in (("c", 1), ("b", 2)):
        x = np.linalg.lstsq(A, d[sel, col], rcond=None)[0]
        res[name] = [complex(x[0], 0.0)] + [complex(x[1 + 2 * i], -x[2 + 2 * i]) for i in range(6)]
    return res


print("Enhancements 902-903: the harmonic-balance Newton on overdriven stages")
P111 = SEEDS[111]

out, spec, it, lev = hb("s111k16", P111, 16)
check("[1] seed 111 at K = 16 converges", spec is not None,
      "%s iterations, %s steps" % (it, lev) if it else (re.search(r"HB: source stepping stalled[^\n]*", out) or [out[-120:]])[0])

out, spec, it, lev = hb("s111k48", P111, 48)
err = None
if spec:
    ref = transient(P111)
    scale = max(abs(ref["c"][1]), abs(ref["b"][1]))
    err = max(abs(spec[n][k] - ref[n][k]) / scale for n in ("c", "b") for k in range(7))
check("[2] seed 111 at K = 48 converges, within 1e-4 of the settled transient",
      err is not None and err < 1e-4,
      ("%s iterations, %s steps, error %.1e" % (it, lev, err)) if err is not None else
      (re.search(r"HB: source stepping stalled[^\n]*", out) or [out[-120:]])[0])

# [3] the final level: the trace lines of the last lambda
lv = re.findall(r"HB  lambda=([\d.]+)\s+iter\s+\d+: \|F\| = ([\d.e+-]+)", out)
last = [float(f) for l, f in lv if l == "1.0000"]
tail = last[-3:] if spec else []
red = (tail[-2] / tail[-1]) if len(tail) >= 2 and tail[-1] > 0 else None
check("[3] the last level ends quadratically: its last step cuts |F| at least 100 times",
      red is not None and red >= 100.0,
      "last residuals %s" % ", ".join("%.2e" % x for x in tail) if tail else "no converged full-strength level")

out, spec105, it105, lev105 = hb("s105k48", SEEDS[105], 48)
check("[4] seed 105 at K = 48 converges", spec105 is not None,
      "%s iterations, %s steps" % (it105, lev105) if it105 else
      (re.search(r"HB: source stepping stalled[^\n]*", out) or [out[-120:]])[0])

dc = ([spec[n][0].imag for n in ("c", "b")] + [spec105[n][0].imag for n in ("c", "b")]) if (spec and spec105) else None
check("[5] every node's dc harmonic is real, exactly", dc is not None and len(dc) == 4 and all(x == 0.0 for x in dc),
      "imaginary dc %s" % (", ".join("%.1e" % x for x in dc) if dc else "no spectrum"))

res = {}
for s in ("sparse", "klu"):
    o, sp_, i_, l_ = hb("s111k16_" + s, P111, 16, opt=".option %s\n" % s)
    res[s] = (i_, l_)
check("[6] Sparse and KLU take the same iterations and continuation steps",
      res["sparse"][0] is not None and res["sparse"] == res["klu"],
      "Sparse %s, KLU %s (iterations, steps)" % (res["sparse"], res["klu"]))

TT = ("* two-tone stage\nvcc vcc 0 %r\nrc vcc c %r\ncl c 0 %r\nvin1 in x dc %r sin(0 0.08 3.0e6)\n"
      "vin2 x 0 dc 0 sin(0 0.08 3.3e6)\nrb in b %r\nq1 c b 0 qm\n%s\n.control\nqpss v(c) 3.0e6 3.3e6 hb 4 4\n"
      ".endc\n.end\n" % (P111["VCC"], P111["RC"], P111["CL"], P111["VB"], P111["RB"], MODEL))
out = run("qp", TT)
m = re.search(r"QPSS-HB: converged in (\d+) iterations, (\d+) continuation", out)
check("[7] a two-tone qpss ... hb of the stage converges", m is not None,
      "%s iterations, %s steps" % (m.group(1), m.group(2)) if m else
      (re.search(r"QPSS-HB: source stepping stalled[^\n]*", out) or ["no result"])[0])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
