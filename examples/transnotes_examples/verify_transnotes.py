#!/usr/bin/env python3
"""verify_transnotes.py -- Enhancement-885, Enhancement-886, Enhancement-887
and Enhancement-888: N2, N4, N5 and N6 of the transient stress campaign of
2026-10-12.

  [1] E-885: xmu=0 takes backward Euler's steps -- the points and the value of
      method=gear maxord=1 (E-883: trap's step control, a quarter of the
      points)
  [2] E-885: xmu=0.2 takes more points than trap, and its error against a
      tight reference is below 1 % of the range (E-883: fewer points than
      trap, 1.7 %)
  [3] E-885 (control): xmu=0.5 is the default run
  [4] E-886: newtrunc says it is ignored and what runs instead; ltereltol,
      lteabstol and ltetrtol each say they have no effect; a deck without
      them prints neither (E-883: the three said nothing)
  [5] E-887: a run started by `run`, given maxord=3, the other solver and
      method=gear maxord=4 dynorder during a pause, resumes without a crash,
      names each with the value it keeps, and ends where the uninterrupted run
      ends (E-883: segmentation fault)
  [6] E-887: a run started by `tran` names and keeps them the same way
      (E-883: kept without a word)
  [7] E-887: reltol and trtol given during the pause are taken on both
      routes, which say so and end at the same value (E-883: taken by the
      `run` route only, without a word)
  [8] E-887: the options held for the resumed run take effect at the next
      analysis, on both routes
  [9] E-888: an ordfix run says every converged step is accepted with no
      truncation-error estimate; at adams ordfix=3 also that the order is not
      A-stable, at gear ordfix=2 not (E-883: no word)
  [10] E-888: a stiff network at adams ordfix=3 stops when a node passes
      1e15 V (E-883: it ran to 3e201 V and exited 0)
  [11] E-888 (control): at gear ordfix=2 the same network runs to the end

Exit code 0 = pass.
"""
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

WORK = tempfile.mkdtemp(prefix="transnotes_")
SOLVER = os.environ.get("_NG_SOLVER") or os.environ.get("NGSPICE_SOLVER") or "sparse"
OTHER = "sparse" if SOLVER == "klu" else "klu"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(tag, text):
    path = os.path.join(WORK, tag + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def num(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


# ---- E-885: xmu below 0.5 ----------------------------------------------------
XMU = """* xmu step control
v1 a 0 pulse(0 1 0 10n 10n 1u 2u)
r1 a b 1k
c1 b 0 1n
l1 b c 1u
r2 c 0 100
c2 c 0 100p
.option %s
.control
set wr_singlescale
tran 100n 6u
wrdata %s v(b) v(c)
let z = v(b)[length(v(b))-1]
let n = length(time)
print z
print n
.endc
.end
"""


def xmu_run(tag, opts):
    _, out = run(tag, XMU % (opts, tag + ".txt"))
    d = np.loadtxt(os.path.join(WORK, tag + ".txt"), skiprows=1, ndmin=2)
    return num(out, "z"), num(out, "n"), d


ref = xmu_run("ref", "reltol=1e-8 abstol=1e-15 chgtol=1e-18 trtol=1")[2]


def err(d):
    T = np.linspace(0, 6e-6, 60001)
    return max(np.sqrt(np.mean((np.interp(T, d[:, 0], d[:, j]) - np.interp(T, ref[:, 0], ref[:, j])) ** 2))
               / np.ptp(ref[:, j]) for j in (1, 2))


z0, n0, d0 = xmu_run("xmu0", "xmu=0")
zb, nb, db = xmu_run("be", "method=gear maxord=1")
check("[1] E-885: xmu=0 takes backward Euler's steps",
      n0 is not None and n0 == nb and z0 == zb, "xmu=0: %s points, %s; gear maxord=1: %s, %s" % (n0, z0, nb, zb))
zt, nt, dt = xmu_run("trap", "reltol=1e-3")
z2, n2, d2 = xmu_run("xmu02", "xmu=0.2")
e2 = err(d2)
check("[2] E-885: xmu=0.2 takes more points than trap, error below 1 % of the range",
      n2 is not None and nt is not None and n2 > nt and e2 < 1e-2, "%s points against trap's %s, error %.2e" % (n2, nt, e2))
z5, n5, _ = xmu_run("xmu05", "xmu=0.5")
check("[3] E-885 (control): xmu=0.5 is the default run", n5 == nt and z5 == zt, "%s, %s" % (n5, z5))

# ---- E-886: newtrunc's tolerances --------------------------------------------
LTE = """* lte options
v1 a 0 pulse(0 1 0 10n 10n 1u 2u)
r1 a b 1k
c1 b 0 1n
%s
.tran 10n 2u
.control
run
.endc
.end
"""
_, a = run("lte", LTE % ".option newtrunc ltereltol=1e-4 lteabstol=1e-8 ltetrtol=2")
_, b = run("nolte", LTE % "")
ok = ("Option newtrunc is ignored" in a and "estimate from the charges" in a and
      all(("Option %s has no effect" % o) in a for o in ("ltereltol", "lteabstol", "ltetrtol")) and
      "newtrunc" not in b and "has no effect" not in b)
check("[4] E-886: newtrunc and its three tolerances say they have no effect and what is used",
      ok, "newtrunc %s, lte* %d of 3" % ("Option newtrunc is ignored" in a,
                                         sum(("Option %s has no effect" % o) in a for o in ("ltereltol", "lteabstol", "ltetrtol"))))

# ---- E-887: options given during a pause -------------------------------------
PAUSE = """* pause and change
v1 a 0 pulse(0 1 0 10n 10n 1u 2u)
r1 a b 1k
c1 b 0 1n
l1 b c 1u
r2 c 0 100
%s
.control
stop when time > 1u
%s
delete all
%s
resume
let z = v(b)[length(v(b))-1]
print z
%s
.endc
.end
"""


def pause(tag, route, opt, after=""):
    if route == "run":
        text = PAUSE % (".tran 10n 4u", "run", opt, after)
    else:
        text = PAUSE % ("", "tran 10n 4u", opt, after)
    return run(tag, text)


_, base = pause("p_base", "run", "echo")
zbase = num(base, "z")
HELD = (("option maxord=3", ["maxord = 3", "keeps maxord = 2"]),
        ("option " + OTHER, [OTHER, "keeps " + SOLVER]),
        ("option method=gear maxord=4 dynorder",
         ["method = gear", "maxord = 4", "dynorder on", "keeps method = trap"]))


def held(route):
    ok, det = True, []
    for i, (opt, words) in enumerate(HELD):
        rc, out = pause("p_%s_%d" % (route, i), route, opt)
        z = num(out, "z")
        ok = ok and rc == 0 and z == zbase and all(w in out for w in words)
        det.append("%s: rc %d, %s" % (opt.split()[1], rc, z))
    return ok, "; ".join(det)


ok, det = held("run")
check("[5] E-887: `run` route -- maxord, the solver, method+dynorder during a pause: no crash, named, kept", ok, det)
ok, det = held("tran")
check("[6] E-887: `tran` route -- the same options are named and kept", ok, det)

rr, outr = pause("p_tol_run", "run", "option reltol=1e-6 trtol=0.1")
rt, outt = pause("p_tol_tran", "tran", "option reltol=1e-6 trtol=0.1")
zr, zt2 = num(outr, "z"), num(outt, "z")
said = "the resumed run takes reltol = 1e-06 and trtol = 0.1"
check("[7] E-887: reltol and trtol given during the pause are taken on both routes, which say so",
      zr is not None and zr == zt2 and zr != zbase and said in outr and said in outt,
      "run %s, tran %s, default %s" % (zr, zt2, zbase))

FRESH = """* fresh run with the options
v1 a 0 pulse(0 1 0 10n 10n 1u 2u)
r1 a b 1k
c1 b 0 1n
l1 b c 1u
r2 c 0 100
.option method=gear maxord=3
.control
tran 10n 4u
let z = v(b)[length(v(b))-1]
print z
.endc
.end
"""
_, f = run("fresh", FRESH)
zf = num(f, "z")
nxt = "tran 10n 4u\nlet z2 = v(b)[length(v(b))-1]\nprint z2"
_, nr = pause("p_next_run", "run", "option method=gear maxord=3", nxt)
_, nt2 = pause("p_next_tran", "tran", "option method=gear maxord=3", nxt)
check("[8] E-887: the held options take effect at the next analysis, on both routes",
      zf is not None and num(nr, "z2") == zf and num(nt2, "z2") == zf,
      "fresh gear maxord=3 %s; next analysis: run %s, tran %s" % (zf, num(nr, "z2"), num(nt2, "z2")))

# ---- E-888: ordfix -------------------------------------------------------------
STIFF = """* stiff linear network (Family A seed 1017)
c0 1 0 3.570642051047291e-10
c1 3 0 3.719889133835243e-11
c2 5 0 1.9757071567848896e-11
c3 8 0 2.750225318262255e-11
r4 3 0 3545.3500123542094
r5 2 3 626.825236697454
r6 1 2 43945.521124352636
r7 4 0 42.15150572170037
r8 7 3 131.52282379858423
r9 9 4 38.59232002135949
r10 8 1 340.4711396378661
r11 5 4 26.834391198875217
r12 6 8 173.837095905585
v0 2 0 sin(-0.45690191849130446 -0.6013457478544217 3550.1606982636454)
v1 4 0 pwl(0.0 0.026423837021960717 4.114728540860615e-06 -0.009780345015122371 9.815649306825742e-06 0.0386778484980701 2.248483845067009e-05 0.9646366770286849 3.35614809382112e-05 -0.9336787776003228 4.0024495701089315e-05 -0.9168042434797046)
.option %s reltol=1e-2
.control
tran 4.2251608518274613e-07 8.450321703654923e-05 0 8.450321703654923e-08
let z = v(5)[length(v(5))-1]
print z
.endc
.end
"""
_, a3 = run("of_adams3", STIFF % "method=adams maxord=3 ordfix=3")
_, g2 = run("of_gear2", STIFF % "method=gear maxord=2 ordfix=2")
none_ = "no truncation-error estimate checks it"
check("[9] E-888: ordfix says there is no truncation control; adams 3 is named not A-stable, gear 2 not",
      none_ in a3 and none_ in g2 and "order 3 of adams is not A-stable" in a3 and "not A-stable" not in g2,
      "adams3 %s/%s, gear2 %s/%s" % (none_ in a3, "not A-stable" in a3, none_ in g2, "not A-stable" in g2))
check("[10] E-888: the stiff network at adams ordfix=3 stops when a node passes 1e15 V",
      "the solution is diverging" in a3 and num(a3, "z") is not None and abs(num(a3, "z")) < 1e16,
      "diverging %s, last value %s" % ("the solution is diverging" in a3, num(a3, "z")))
zg = num(g2, "z")
check("[11] E-888 (control): at gear ordfix=2 the same network runs to the end",
      zg is not None and abs(zg + 0.9168) < 1e-3 and "diverging" not in g2, str(zg))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
