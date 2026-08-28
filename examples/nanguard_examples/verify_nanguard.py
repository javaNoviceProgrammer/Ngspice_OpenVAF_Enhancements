#!/usr/bin/env python3
"""Enhancement-502: the guard that refuses the wrong value and admits NaN.

Round 60 swept the commands that produce a REPORT -- `emir`, `eye`, `reduce`,
`envelope`, `qpss`, `hbosc` -- and found one guard written the same way in every
one of them:

    if (x <= 0.0) { refuse; }

Every comparison with NaN is false, so that test refuses 0 and refuses a negative
number and lets NaN straight through. It is one `!` away from correct.

What walked through it was not harmless. `emir jmax nan` reported **0 segments
over Jmax**, every segment `ok`, on a power grid with two genuine violations --
the same shape Enhancement-501 fixed for the statistical spec bounds, one command
over. `reduce nan` reported **"26 nodes -> 26 nodes (1.0x)"** and wrote a file
called `reduced.sp` that reduced nothing. `qpss ... maxorder nan` silently became
`order <= 1`, dropping every intermodulation product -- the entire reason that
command exists. `eye -ui nan` reported an **eye height of 0**, a fully closed
serial link. And `envelope <node> nan <tstop>` built an internal
`tran nan nan 0 nan`, which ngspice refuses, leaving the matrix unbuilt for a
**SIGSEGV** one call later in `SMPmatSize`.

`eye -tstart nan` is the one worth staring at, because it did not blank the
result: the "skip samples before tstart" test is also a comparison, so NaN never
skipped, the startup transient the flag exists to exclude was folded into the
eye, and RMS jitter came back **660x larger** -- a different, entirely plausible
number, with no diagnostic anywhere.

Two things are fixed besides the guards.

`envelope` no longer trusts its own internal transient. The NaN is refused at the
front now, but any refused transient -- a step the circuit cannot take, a bias
point that will not converge -- leaves `CKTmatrix` NULL, and the command walked
straight into it. A command must never use the result of an internal analysis
without asking whether it happened; that is Enhancement-438's shape.

And `emir` can now tell a width the user GAVE from the resistor's default. It
reads `@r[w]`, which answers 1e-5 for an undimensioned wire, so the segment most
likely to be the oversight was analysed as a comfortable 10 um conductor and
reported `ok` -- while the header of `com_emir.c` says such segments are skipped.
Meanwhile `w=0` and `w=-0.5u` WERE skipped and reported as *"no width given"*,
which is the one thing they were not.

The right idiom was already in the tree: `hbosc` refuses `K nan` because its test
is `K >= 1`, and `compose` refuses NaN on every parameter it takes. The guards
now go through three shared helpers in `frontend/parser/numparse.c`.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ng_") or junk == "reduced.sp":
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, timeout=900):
    p = os.path.join(HERE, f"_ng_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"nanguard\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


REFUSED = re.compile(r"must be a number, not|must be a positive finite|must be finite|"
                     r"must be a whole number|more points than a vector|"
                     r"expected four S-parameter|factor is the time-constant")


def refused(out):
    return bool(REFUSED.search(out))


GRID = ("Vdd vdd 0 dc 1.0\nRw1 vdd n1 0.5 w=2u\nRw2 n1 n2 0.5 w=1u\n"
        "Rw3 n2 n3 0.5 w=0.5u\nIload1 n1 0 dc 0.1\nIload2 n2 0 dc 0.1\n"
        "Iload3 n3 0 dc 0.1\n")
EYE = "Vtx tx 0 PULSE(0 1 0 10p 10p 0.49n 1n)\nR1 tx rx 300\nC1 rx 0 0.6p\n.tran 1p 60n\n"
QP = ("V1 a 0 dc 0 sin(0 0.1 1e6)\nV2 b 0 dc 0 sin(0 0.1 1.1e6)\n"
      "B1 o 0 v = v(a)+v(b) + 0.5*(v(a)+v(b))*(v(a)+v(b))\nR1 o 0 1k\n")
LAD = ("".join(f"R{i} {'in' if i == 1 else f'n{i-1}'} n{i} 15\nC{i} n{i} 0 50f\n"
               for i in range(1, 25)) + "Rout n24 out 15\nV1 in 0 dc 1 ac 1\n")
ENV = "v1 s 0 sin(0 1 5.032921e6)\nl1 s a 1u\nc1 a 0 1n\nr1 a 0 100k\n"
OSC = ("L1 a 0 1e-06\nC1 a 0 1e-09\nR1 a 0 100k\n"
       "B1 a 0 i = -(5e-4*v(a)) + 5e-4*v(a)*v(a)*v(a)\n.ic v(a)=0.1\n")
DIV = "V1 a 0 dc 1\nR1 a 0 1k\n"
TP = ("V1 in 0 dc 0 ac 1 portnum 1 z0 50\nR1 in mid 25\nR2 mid 0 100\nR3 mid out 25\n"
      "V2 out 0 dc 0 ac 0 portnum 2 z0 50\n.sp lin 2 1meg 2meg 1\n")

print("Enhancement-502: a NaN argument is refused, not reported on")

# ---------------------------------------------------------------------------
# [1]-[3]  envelope: the crash
# ---------------------------------------------------------------------------
print("\n  envelope -- the SIGSEGV")

for i, arg in enumerate(("nan", "inf")):
    rc, out = run(ENV, f"envelope a {arg} 600u", f"ev{i}")
    check(f"[{1+i}] `envelope a {arg} 600u` is refused, not a SIGSEGV",
          rc is not None and rc >= 0 and refused(out),
          "SIGSEGV" if (rc is not None and rc < 0) else "refused")

rc, out = run(ENV, "envelope a 5.032921e6 600u", "ev2")
check("[3] a good envelope run is unchanged", "26 envelope samples" in out,
      (re.findall(r"envelope: .*samples[^\n]*", out) or ["(none)"])[0][:52])

# ---------------------------------------------------------------------------
# [4]-[11]  emir
# ---------------------------------------------------------------------------
print("\n  emir -- a current-density limit that was never exceeded")

for i, (opt, arg) in enumerate([("jmax", "nan"), ("thick", "nan"), ("rail", "nan"),
                                ("n", "nan"), ("tref", "nan"), ("top", "nan")]):
    rc, out = run(GRID, f"emir thick 0.5u jmax 3.5e11 {opt} {arg}", f"em{i}")
    ran = "segments over Jmax" in out
    check(f"[{4+i}] `emir {opt} {arg}` is refused", refused(out) and not ran,
          "refused" if refused(out) else "ACCEPTED")

rc, out = run(GRID, "emir thick 0.5u jmax 3.5e11 tref 3.15e8", "emg")
check("[10] a good emir run still finds both violations",
      "2 segments over Jmax" in out,
      (re.findall(r"\d+ segments? over Jmax", out) or ["(none)"])[0])
rc, out = run(GRID, "emir thick 0.5u jmax 3.5e11 rail -1", "emn")
check("[11] a NEGATIVE rail is still legal (a negative supply is a supply)",
      "worst drop" in out and not refused(out))

# ---------------------------------------------------------------------------
# [12]-[14]  emir: a width that was given vs one that was defaulted
# ---------------------------------------------------------------------------
print("\n  emir -- a width the user gave, and one the resistor defaulted")


def grid_w3(w):
    return ("Vdd vdd 0 dc 1.0\nRw1 vdd n1 0.5 w=2u\nRw2 n1 n2 0.5 w=1u\n"
            f"Rw3 n2 n3 0.5 {w}\nIload1 n1 0 dc 0.1\nIload2 n2 0 dc 0.1\n"
            "Iload3 n3 0 dc 0.1\n")


rc, out = run(grid_w3(""), "emir thick 0.5u jmax 3.5e11", "ew0")
check("[12] an UNDIMENSIONED segment is skipped, not analysed at the 10um default",
      "no width given" in out and not re.search(r"^\s*rw3\s", out, re.M),
      "skipped" if "no width given" in out else "analysed as 10um and reported ok")
rc, out = run(grid_w3("w=-0.5u"), "emir thick 0.5u jmax 3.5e11", "ew1")
check("[13] a NEGATIVE width is not reported as 'no width given'",
      "not a positive finite number" in out and "no width given" not in out,
      (re.findall(r"\(1 resistor[^\n]*", out) or ["(none)"])[0][:58])
rc, out = run(grid_w3("w=0.5u"), "emir thick 0.5u jmax 3.5e11", "ew2")
check("[14] a segment WITH a width is still analysed",
      bool(re.search(r"^\s*rw3\s", out, re.M)))

# ---------------------------------------------------------------------------
# [15]-[19]  eye
# ---------------------------------------------------------------------------
print("\n  eye -- a closed eye, and a jitter number 660x out")

rc, out = run(EYE, "run\neye v(rx) -ui nan -tstart 3n", "ey0")
check("[15] `-ui nan` is refused, not reported as a closed eye",
      refused(out) and "eye height" not in out,
      "refused" if refused(out) else "reported height 0")
rc, out = run(EYE, "run\neye v(rx) -ui 0.5n -tstart nan", "ey1")
check("[16] `-tstart nan` is refused, not silently ignored",
      refused(out) and "eye height" not in out)
rc, out = run(EYE, "run\neye v(rx) -ui 0.5n -tstart 3n -window 5", "ey2")
check("[17] `-window 5` is named rather than silently replaced by the default",
      "must be in (0, 0.5)" in out, "named" if "(0, 0.5)" in out else "SILENT")

rc, out = run(EYE, "run\neye v(rx) -ui 0.5n -tstart 3n\nprint eye_jitter_rms", "ey3")
j = re.findall(r"eye_jitter_rms\s*=\s*(\S+)", out)
check("[18] a good eye run is unchanged", bool(j) and abs(float(j[-1]) - 1.4965e-15) < 1e-17,
      f"jitter_rms = {j[-1] if j else None}")
rc, out = run(EYE, "run\neye v(rx) -ui 0.5n -tstart 0", "ey4")
check("[19] `-tstart 0` is still legal", "eye height" in out)

# ---------------------------------------------------------------------------
# [20]-[24]  qpss
# ---------------------------------------------------------------------------
print("\n  qpss -- an all-NaN spectrum, and a silently dropped order")

for i, c in enumerate(["qpss v(o) nan 1.1e6 4 3", "qpss v(o) 1e6 nan 4 3",
                       "qpss v(o) 1e6 1.1e6 nan 3", "qpss v(o) 1e6 1.1e6 4 nan"]):
    rc, out = run(QP, c, f"qp{i}", timeout=300)
    lbl = c.split()[-4:]
    check(f"[{20+i}] `{c[5:]}` is refused",
          refused(out) and "(k1,k2)" not in out,
          "refused" if refused(out) else "printed a table")

rc, out = run(QP, "qpss v(o) 1meg 1.1meg 4 3", "qpg", timeout=300)
check("[24] a good qpss run (SPICE suffixes) still resolves order 3",
      "order <= 3" in out and "( 1, 1)" in out)

# ---------------------------------------------------------------------------
# [25]-[28]  reduce
# ---------------------------------------------------------------------------
print("\n  reduce -- a reduction that reduced nothing")

for i, (c, why) in enumerate([("reduce nan keep out", "NaN band"),
                              ("reduce inf keep out", "infinite band"),
                              ("reduce 3g factor nan keep out", "NaN factor")]):
    rc, out = run(LAD, c, f"rd{i}")
    noop = "26 nodes -> 26 nodes" in out
    check(f"[{25+i}] `{c}` is refused ({why})", refused(out) and not noop,
          "refused" if refused(out) else "wrote a 1.0x 'reduction'")

rc, out = run(LAD, "reduce 3g keep out", "rdg")
check("[28] a good reduce run still collapses 26 nodes to 3",
      "26 nodes -> 3 nodes" in out,
      (re.findall(r"\d+ nodes -> \d+ nodes \([\d.]+x\)", out) or ["(none)"])[0])

# ---------------------------------------------------------------------------
# [29]-[31]  hbosc, compose, rfstab
# ---------------------------------------------------------------------------
print("\n  hbosc / compose / rfstab")

rc, out = run(OSC, "hbosc a 5 nan 100u", "hb0", timeout=300)
check("[29] `hbosc <fguess> nan` names fguess, not an internal TSTEP",
      refused(out) and "TSTEP is invalid" not in out,
      "refused" if refused(out) else "leaked 'TSTEP is invalid'")
rc, out = run(OSC, "hbosc a 5 5e6 100u", "hb1", timeout=300)
check("[30] a good hbosc run still converges", "f0" in out or "oscillation" in out)

rc, out = run(DIV, "compose v lin=1e12 start=0 stop=1", "co0")
check("[31] `compose lin=1e12` is refused, not clamped to a 17 GB vector",
      "more points than a vector" in out)
rc, out = run(DIV, "compose v lin=5 start=0 stop=1\nprint length(v)", "co1")
check("[32] `compose lin=5` still builds five points", "length(v) = 5" in out)

rc, out = run(TP, "run\nrfstab S_1_1 S_1_2 S_2_1 S_2_2 S_1_1", "rs0")
check("[33] rfstab refuses a FIFTH vector name (two or three already did)",
      "expected four S-parameter" in out)
rc, out = run(TP, "run\nrfstab", "rs1")
check("[34] a good rfstab run still reports a verdict",
      "unconditionally stable" in out or "potentially UNSTABLE" in out)

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
