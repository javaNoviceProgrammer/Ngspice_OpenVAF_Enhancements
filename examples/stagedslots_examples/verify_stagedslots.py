#!/usr/bin/env python3
"""verify_stagedslots.py -- Enhancement-874: trbdf2 and sdirk keep their
accepted history, so their step control is that of their order.

F2 of the transient stress campaign of 2026-10-12.

A staged step rotates the state history once per stage and splices its
interior stages back out. They were parked in CKTstates[maxord+1] (and
CKTstates[maxord] for sdirk), which the truncation estimate reads as the
oldest accepted point at the default maxord. The estimate compared a stage
value with the old points' spacing and scaled as a first-order method's: an RC
took 580 045 points under trbdf2 and 265 117 under sdirk at reltol=1e-6, where
trap took 512. The stages now sit above the history, and maxord is pinned to
the method's order (2 and 3).

  [1] trbdf2 on a sine into an RC, reltol 1e-3 to 1e-6: the points grow by
      less than 3x per decade, and end below trap's (E-872: 130, 5 626,
      57 898, 580 045)
  [2] sdirk on the same: less than 2.5x per decade, below trap's
      (E-872: 69, 1 308, 26 268, 265 117)
  [3] (control) both are within 1.5x of trap's error against the exact
      solution at every reltol (E-872 passed it by over-resolving)
  [4] maxord has no effect: trbdf2 at maxord=6 and sdirk at maxord=2 and 6
      run point for point as at the default, and a Note says so for 6
  [5] (control) a method changed by `option` between two runs gets its stage
      slots: trap, then sdirk, then trbdf2 in one session match fresh runs
  [6] a trbdf2 checkpoint (savestate) loads in a fresh process and ends where
      the uninterrupted run ends (E-875: "checkpoint state layout does not
      match circuit" -- the stage slot is allocated at the first step)

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

WORK = tempfile.mkdtemp(prefix="stagedslots_")
checks = passed = 0
RELTOLS = (1e-3, 1e-4, 1e-5, 1e-6)


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def rc(opts, tag):
    """points and max error of v(out) against the exact response"""
    out_file = os.path.join(WORK, tag + ".txt")
    out = run(tag, "* sine into an RC\nv1 in 0 sin(0 1 100k)\nr1 in out 1k\nc1 out 0 1n\n.option %s\n"
                   ".control\nset numdgt=17\nset wr_singlescale\ntran 1u 50u 0 50u\nwrdata %s v(out)\n.endc\n.end\n"
              % (opts, out_file))
    rows = []
    with open(out_file) as f:
        for line in f:
            p = line.split()
            try:
                rows.append((float(p[0]), float(p[1])))
            except (ValueError, IndexError):
                pass
    w, tau = 2 * math.pi * 1e5, 1e-6
    a, ph = 1 / math.sqrt(1 + (w * tau) ** 2), math.atan(w * tau)
    err = max(abs(v - (a * math.sin(w * t - ph) + a * math.sin(ph) * math.exp(-t / tau))) for t, v in rows)
    return len(rows), err, out


res = {m: [rc("%s reltol=%g" % (m, r), "%s_%g" % (m.replace("=", ""), r)) for r in RELTOLS]
       for m in ("", "method=trbdf2", "method=sdirk")}


def growth(m):
    n = [x[0] for x in res[m]]
    return max(n[i + 1] / n[i] for i in range(len(n) - 1)), n


g, n = growth("method=trbdf2")
check("[1] trbdf2: points grow < 3x per decade of reltol and end below trap's",
      g < 3.0 and n[-1] < res[""][-1][0], "points %s (trap %s), worst growth %.2fx" % (n, [x[0] for x in res[""]], g))
g, n = growth("method=sdirk")
check("[2] sdirk: points grow < 2.5x per decade and end below trap's",
      g < 2.5 and n[-1] < res[""][-1][0], "points %s, worst growth %.2fx" % (n, g))
ratios = ["%s %.2f" % (m.split("=")[1], res[m][i][1] / res[""][i][1]) for m in ("method=trbdf2", "method=sdirk") for i in range(4)]
check("[3] (control) trbdf2 and sdirk are within 1.5x of trap's error at every reltol",
      all(res[m][i][1] <= 1.5 * res[""][i][1] for m in ("method=trbdf2", "method=sdirk") for i in range(4)),
      "error / trap's: " + ", ".join(ratios))

# [4] maxord pinned
same = []
for m, mo in (("method=trbdf2", 6), ("method=sdirk", 2), ("method=sdirk", 6)):
    n0, e0, _ = res[m][1]
    n1, e1, out = rc("%s maxord=%d reltol=1e-4" % (m, mo), "%s_mo%d" % (m.replace("=", ""), mo))
    note = ("has no effect with %s" % m) in out
    same.append((n0 == n1 and e0 == e1 and (note or mo == 2), "%s maxord=%d: %d pts (default %d), note %s" % (m, mo, n1, n0, note)))
check("[4] maxord has no effect on trbdf2 or sdirk, and maxord=6 draws a Note",
      all(x[0] for x in same), "; ".join(x[1] for x in same))

# [5] method changed between runs in one session
sess = run("session", "* method changes between runs\nv1 in 0 sin(0 1 100k)\nr1 in out 1k\nc1 out 0 1n\n"
                      ".control\nset numdgt=17\ntran 1u 50u 0 50u\noption method=sdirk\ntran 1u 50u 0 50u\n"
                      "let a = v(out)[length(v(out))-1]\nprint a\noption method=trbdf2\ntran 1u 50u 0 50u\n"
                      "let b = v(out)[length(v(out))-1]\nprint b\n.endc\n.end\n")


def last(m):
    out = run("fresh_" + m, "* fresh\nv1 in 0 sin(0 1 100k)\nr1 in out 1k\nc1 out 0 1n\n.option method=%s\n"
                          ".control\nset numdgt=17\ntran 1u 50u 0 50u\nlet z = v(out)[length(v(out))-1]\nprint z\n.endc\n.end\n" % m)
    mm = re.search(r"^z\s*=\s*(\S+)", out, re.M)
    return float(mm.group(1)) if mm else None


ma = re.search(r"^a\s*=\s*(\S+)", sess, re.M)
mb = re.search(r"^b\s*=\s*(\S+)", sess, re.M)
fa, fb = last("sdirk"), last("trbdf2")
check("[5] (control) trap, then sdirk, then trbdf2 in one session match fresh runs",
      ma and mb and float(ma.group(1)) == fa and float(mb.group(1)) == fb,
      "session %s / %s, fresh %s / %s" % (ma.group(1) if ma else None, mb.group(1) if mb else None, fa, fb))

# [6] a trbdf2 checkpoint across processes (checkpoints need Sparse: E-131)
CK = """* trbdf2 checkpoint
v1 in 0 pulse(0 1 0 1n 1n 1u 2u)
r1 in out 1k
c1 out 0 1n
.option sparse method=trbdf2
.tran 10n 4u
.control
set numdgt=17
%s
.endc
.end
"""
ckfile = os.path.join(WORK, "ck.bin")
run("ck1", CK % ("stop when time > 1.5u\nrun\nsavestate %s" % ckfile))
out2 = run("ck2", CK % ("loadstate %s\nlet z = v(out)[length(v(out))-1]\nprint z" % ckfile))
out3 = run("ck3", CK % "run\nlet z = v(out)[length(v(out))-1]\nprint z")
m2 = re.search(r"^z\s*=\s*(\S+)", out2, re.M)
m3 = re.search(r"^z\s*=\s*(\S+)", out3, re.M)
ok6 = m2 is not None and m3 is not None and abs(float(m2.group(1)) - float(m3.group(1))) < 1e-3 * abs(float(m3.group(1)))
check("[6] a trbdf2 checkpoint loads in a fresh process and ends where the uninterrupted run ends", ok6,
      "loaded %s, uninterrupted %s%s" % (m2.group(1) if m2 else None, m3.group(1) if m3 else None,
                                         "" if m2 else "; " + " ".join(l for l in out2.splitlines() if "loadstate" in l)[:120]))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
