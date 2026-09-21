#!/usr/bin/env python3
"""Enhancement-651: a deck-fixed argument that is projected onto its domain is
named (2026-09-16 hunt, F7).

Enhancement-504/505/506 project an unusable argument onto its domain at run
time -- a negative or NaN noise power to 0 (the source contributes nothing),
a negative standard deviation to the mean, a reversed uniform range to its
start, a NaN flicker exponent to an inert source -- and the LRM mandates no
error for these, so the projection stays. But the compiler refuses the same
value written out as a literal, and a value the MODEL CARD fixed can only be
the same mistake one step removed: `white_noise(pw)` with `pw = -1e-18` and
`$rdist_normal(s, 0, sg)` with `sg = -1` ran, drew nothing, and reported
nothing, while `$rdist_exponential` with a bad deck mean was already a
`$fatal` (E-527, where LRM 9.13.2 does mandate the error).

Now a deck-fixed value that is projected is named through a deferred
`$warning`-style message: the builtin, the domain, the number and the
substitute. A run-time quantity (a variable, a node voltage) is projected in
silence exactly as before; a zero noise power or standard deviation is legal
and passes without a word; the exponential family keeps its fatal.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="domainwarn_")
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run(tag, deck, ctl):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* domainwarn {tag}\n{deck}\n.control\nset noinit\npre_osdi {tag}.osdi\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL, errors="replace")
    return p.stdout + p.stderr


MOD = lambda body: "module m(p,n); inout p,n; electrical p,n;\n" + body + "\nendmodule\n"
NOISE_DECK = "vin 1 0 dc 1 ac 1\nr1 1 2 1k\n.model m m\nna1 2 0 m"
NOISE_CTL = "noise v(2) vin lin 1 1000 1000\nsetplot noise1\nprint onoise_spectrum"
OP_DECK = "v1 1 0 1\n.model m m\nna1 1 0 m"
FLOOR = 2.035686e-09  # the series resistor's thermal floor at the output, 1 kHz


def onoise(o):
    m = re.search(r"onoise_spectrum\s*=\s*([-+0-9.eE]+)", o)
    return float(m.group(1)) if m else None


def xval(o):
    m = re.search(r"x=(\S+)", o)
    return float(m.group(1)) if m else None


def warned(o, *needles):
    lines = [l for l in o.splitlines() if "OSDI(warn)" in l and "outside the domain" in l]
    return bool(lines) and all(any(nd in l for l in lines) for nd in needles), (lines or [""])[0][:120]


def noise_case(label, body, tag, want_floor, *needles):
    ok, out = compile_src(MOD(body), tag)
    o = run(tag, NOISE_DECK, NOISE_CTL) if ok else ""
    v = onoise(o)
    w, line = warned(o, *needles)
    at_floor = v is not None and abs(v - FLOOR) / FLOOR < 1e-3
    return check(label, ok and (at_floor == want_floor) and (w if needles else not w),
                 (out.strip().splitlines() or [""])[0][:70] if not ok else f"onoise={v} {line}")


def op_case(label, body, tag, want_x, *needles):
    ok, out = compile_src(MOD(body), tag)
    o = run(tag, OP_DECK, "op") if ok else ""
    x = xval(o)
    w, line = warned(o, *needles)
    return check(label, ok and x is not None and abs(x - want_x) < 1e-9 and (w if needles else not w),
                 (out.strip().splitlines() or [""])[0][:70] if not ok else f"x={x} {line}")


# ---------------------------------------------------------------- noise power
noise_case("[1] white_noise(pw) with a deck pw = -1e-18: the source stays inert (the floor) and says so",
           "parameter real pw = -1e-18;\nanalog I(p,n) <+ V(p,n)/1k + white_noise(pw, \"w\");", "n1", True,
           "white_noise", "noise power not negative", "-1e-18", "the source contributes nothing")
noise_case("[2] white_noise(z/z) with a deck z = 0 (NaN): inert, and named as nan",
           "parameter real z = 0;\nanalog I(p,n) <+ V(p,n)/1k + white_noise(z/z, \"w\");", "n2", True,
           "white_noise", "nan")
noise_case("[3] a zero power is a power (a source switched off): inert, no word",
           "parameter real pw = 0;\nanalog I(p,n) <+ V(p,n)/1k + white_noise(pw, \"w\");", "n3", True)
noise_case("[4] a usable power is untouched: above the floor, no word",
           "parameter real pw = 1e-18;\nanalog I(p,n) <+ V(p,n)/1k + white_noise(pw, \"w\");", "n4", False)
noise_case("[5] flicker_noise(pw, 1.0) with a deck pw = -1e-18 names flicker_noise",
           "parameter real pw = -1e-18;\nanalog I(p,n) <+ V(p,n)/1k + flicker_noise(pw, 1.0, \"f\");", "n5", True,
           "flicker_noise", "noise power not negative", "-1e-18")
noise_case("[6] flicker_noise(1e-18, p/q) with a deck 0/0 exponent: inert, and the exponent is named",
           "parameter real ea = 0, eb = 0;\nanalog I(p,n) <+ V(p,n)/1k + flicker_noise(1e-18, ea/eb, \"f\");", "n6", True,
           "flicker_noise", "exponent a number", "nan")
noise_case("[7] flicker_noise with a zero exponent (white) is untouched, no word",
           "parameter real af = 0;\nanalog I(p,n) <+ V(p,n)/1k + flicker_noise(1e-18, af, \"f\");", "n7", False)

# ---------------------------------------------------------------- distributions
RN = lambda decl, sg: decl + "integer s; real x; analog begin s = 1; x = $rdist_normal(s, 0, " + sg + "); $strobe(\"x=%g\", x); I(p,n) <+ V(p,n); end"
op_case("[8] $rdist_normal(s, 0, sg) with a deck sg = -1: the mean (0) with certainty, and named",
        RN("parameter real sg = -1;\n", "sg"), "d8", 0.0, "$rdist_normal", "standard deviation not negative", "-1", "the mean is returned")
op_case("[9] a zero standard deviation is legal (the mean with certainty), no word",
        RN("parameter real sg = 0;\n", "sg"), "d9", 0.0)
ok, out = compile_src(MOD(RN("parameter real sg = 1;\n", "sg")), "d10")
o = run("d10", OP_DECK, "op") if ok else ""
check("[10] a usable standard deviation draws (x != 0), no word",
      ok and xval(o) is not None and xval(o) != 0.0 and not warned(o)[0], f"x={xval(o)}")
op_case("[11] $dist_normal, the integer sibling, names $dist_normal",
        "parameter integer sg = -1;\ninteger s, x; analog begin s = 1; x = $dist_normal(s, 0, sg); $strobe(\"x=%d\", x); I(p,n) <+ V(p,n); end",
        "d11", 0.0, "$dist_normal", "standard deviation not negative")
RU = lambda decl, lo, hi: decl + "integer s; real x; analog begin s = 1; x = $rdist_uniform(s, " + lo + ", " + hi + "); $strobe(\"x=%g\", x); I(p,n) <+ V(p,n); end"
op_case("[12] $rdist_uniform(s, lo, hi) with deck lo = 1, hi = 0: the start (1) with certainty, both numbers named",
        RU("parameter real lo = 1, hi = 0;\n", "lo", "hi"), "d12", 1.0, "$rdist_uniform", "start below end", "the start is 1 and the end is 0", "the start is returned")
op_case("[13] equal bounds are a reversed range too (start shall be smaller than end): named",
        RU("parameter real lo = 1, hi = 1;\n", "lo", "hi"), "d13", 1.0, "$rdist_uniform", "the start is 1 and the end is 1")
ok, out = compile_src(MOD(RU("parameter real lo = 0, hi = 1;\n", "lo", "hi")), "d14")
o = run("d14", OP_DECK, "op") if ok else ""
check("[14] ordered bounds draw inside them, no word",
      ok and xval(o) is not None and 0.0 <= xval(o) <= 1.0 and not warned(o)[0], f"x={xval(o)}")
op_case("[15] one deck bound beside a literal counts as deck-fixed: $rdist_uniform(s, 1, hi) with hi = 0",
        RU("parameter real hi = 0;\n", "1", "hi"), "d15", 1.0, "$rdist_uniform", "the start is 1 and the end is 0")
op_case("[16] $dist_uniform, the integer sibling, names $dist_uniform",
        "parameter integer lo = 10, hi = 0;\ninteger s, x; analog begin s = 1; x = $dist_uniform(s, lo, hi); $strobe(\"x=%d\", x); I(p,n) <+ V(p,n); end",
        "d16", 10.0, "$dist_uniform", "the start is 10 and the end is 0")

# ---------------------------------------------------------------- left alone
op_case("[17] a RUN-TIME standard deviation (V(p,n) - 2 = -1) is projected in silence, as before",
        "integer s; real x, sg; analog begin s = 1; sg = V(p,n) - 2; x = $rdist_normal(s, 0, sg); $strobe(\"x=%g\", x); I(p,n) <+ V(p,n); end",
        "d17", 0.0)
ok, out = compile_src(MOD("parameter real mn = 0;\ninteger s; real x; analog begin s = 1; x = $rdist_exponential(s, mn); $strobe(\"x=%g\", x); I(p,n) <+ V(p,n); end"), "d18")
o = run("d18", OP_DECK, "op") if ok else ""
check("[18] $rdist_exponential with a deck mean of 0 keeps E-527's mandated $fatal (LRM 9.13.2)",
      ok and "fatal" in o and "9.13.2" in o and "raised $fatal" in o, (out.strip().splitlines() or [""])[0][:70] if not ok else "")
ok, out = compile_src(MOD("integer s; real x; analog begin s = 1; x = $rdist_normal(s, 0, -1); I(p,n) <+ V(p,n); end"), "d19")
check("[19] a literal negative standard deviation is still refused at compile time", not ok and "must not be negative" in out)
ok, out = compile_src(MOD("parameter real sg = -1;\ninteger s; real x; analog begin s = 1; x = $rdist_normal(s, 0, sg); $strobe(\"x=%g\", x); I(p,n) <+ V(p,n); end"), "d20")
o = run("d20", OP_DECK, "tran 1u 5u") if ok else ""
n = sum(1 for l in o.splitlines() if "outside the domain" in l)
check("[20] the warning is deferred and repeat-suppressed: a 5-point transient prints it a handful of times, not per iteration",
      ok and 1 <= n <= 8, f"{n} lines")

# ---------------------------------------------------------------- slew / transition (E-696)
# Enhancement-696 (hunt F6 of 2026-09-21): a `slew` rate or a `transition` time
# the deck fixed outside its domain was projected in silence -- a wrong sign to
# its magnitude, a negative time to 0 -- and a ZERO rate was a zero clamp: the
# output could not move, so `rate=0` on a card froze a slew output at its initial
# value for the whole run without a line in the log. The projections say so now
# (E-651's rule, once per accepted point), and a zero rate drops the limit in
# that direction. A run-time quantity is projected in silence, as before.
A = "@"
SL2 = ("parameter real pos = 1e5, neg = -1e5;\n(*desc=\"y\"*) real y;\n"
       "analog begin y = slew(V(p,n) > 0.5 ? 1.0 : 0.0, pos, neg); I(p,n) <+ V(p,n)/1k; end")
SL1 = ("parameter real rate = 1e5;\n(*desc=\"y\"*) real y;\n"
       "analog begin y = slew(V(p,n) > 0.5 ? 1.0 : 0.0, rate); I(p,n) <+ V(p,n)/1k; end")
TR = ("parameter real td = 0, tr = 10u;\n(*desc=\"y\"*) real y;\n"
      "analog begin y = transition(V(p,n) > 0.5 ? 1.0 : 0.0, td, tr, tr); I(p,n) <+ V(p,n)/1k; end")
RT = ("(*desc=\"y\"*) real y;\n"
      "analog begin y = slew(V(p,n) > 0.5 ? 1.0 : 0.0, 1e5 * (V(p,n) - 2.0)); I(p,n) <+ V(p,n)/1k; end")
PULSE = "v1 1 0 pulse(0 1 1m 1n 1n 2m 10m) dc 0\nna1 1 0 m\n"
SLCTL = f"save all {A}na1[y]\ntran 10u 4m\nmeas tran y25 FIND {A}na1[y] AT=2.5m\nmeas tran y35 FIND {A}na1[y] AT=3.5m"


def slew_case(label, body, tag, card, want25, want35, *needles):
    ok, out = compile_src(MOD(body), tag)
    o = run(tag, PULSE + ".model m m " + card, SLCTL) if ok else ""
    got = {}
    for k in ("y25", "y35"):
        m = re.search(k + r"\s*=\s*([-+0-9.eE]+)", o)
        got[k] = float(m.group(1)) if m else None
    lines = [l for l in o.splitlines() if "OSDI(warn)" in l]
    w = bool(lines) and all(any(nd in l for l in lines) for nd in needles) if needles else not lines
    vals_ok = all(got[k] is not None and abs(got[k] - want) < 1e-3 for k, want in (("y25", want25), ("y35", want35)))
    return check(label, ok and vals_ok and w,
                 (out.strip().splitlines() or [""])[0][:70] if not ok else f"y25={got['y25']} y35={got['y35']} {(lines or [''])[0][-90:]}")


slew_case("[21] slew(x, pos, neg) with a deck pos = 0: the output follows the input (1 at 2.5 ms, 0 at 3.5 ms; it stood at 0 for the whole run) and says the positive limit is dropped",
          SL2, "s21", "pos=0", 1.0, 0.0, "slew: the maximum positive rate is 0", "requires it positive", "no positive slew limit")
slew_case("[22] a deck pos = -1e5: the magnitude is used, and named",
          SL2, "s22", "pos=-1e5", 1.0, 0.0, "the maximum positive rate is -100000", "its magnitude is used")
slew_case("[23] a deck neg = +1e5 (LRM 4.5.9 wants it negative): the magnitude is the negative limit, and named",
          SL2, "s23", "neg=1e5", 1.0, 0.0, "the maximum negative rate is 100000", "requires it negative", "its magnitude is used as the negative limit")
slew_case("[24] a deck neg = 0: the fall happens (the output was held at 1) and the negative limit is dropped, named",
          SL2, "s24", "neg=0", 1.0, 0.0, "the maximum negative rate is 0", "no negative slew limit")
slew_case("[25] the one-rate form with a deck rate = 0: 'the rate is 0', no slew limit, one line",
          SL1, "s25", "rate=0", 1.0, 0.0, "slew: the rate is 0", "there is no slew limit")
slew_case("[26] transition with a deck tr = -1u and td = -1m: instantaneous from 1 ms, both named with LRM 4.5.8 and '0 is used'",
          TR, "s26", "tr=-1u td=-1m", 1.0, 0.0, "transition: the rise time is -1e-06, negative", "the fall time is -1e-06", "the delay is -0.001, negative", "LRM 4.5.8", "0 is used")
slew_case("[27] usable rates and times, and a RUN-TIME rate that goes negative, pass without a word",
          RT, "s27", "", 1.0, 0.0)
ok, out = compile_src(MOD(SL2), "s28")
o = run("s28", PULSE + ".model m m", SLCTL) if ok else ""
check("[28] the defaults (1e5, -1e5) ramp in 10 us and print nothing",
      ok and not any("OSDI(warn)" in l for l in o.splitlines()) and "y25" in o, "")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
