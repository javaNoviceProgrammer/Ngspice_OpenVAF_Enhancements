#!/usr/bin/env python3
"""Enhancement-362: analysis-card sweep parameters must not produce undefined
behaviour, a bad allocation size, or an unbounded loop.

These were found by fuzzing analysis-card parameters against an ASan+UBSan build
(`fuzz_analysis.py` in this directory, which is the campaign harness and is NOT
run by the regression -- it needs a sanitizer build to be worth anything). What
this file does is pin the specific repros so they cannot come back.

WHAT WAS WRONG. Several analyses computed a sweep point count as a double and
cast it to int, then used the result as an ALLOCATION SIZE:

    distoan.c   NoOfPoints        -> DstorAlloc(..., NoOfPoints+2)
    dctran.c    CKTtimeListSize   -> TMALLOC(double, ...), and osdiaccept.c
                                     sizes a buffer from it
    cktsens.c   n                 -> drives the sweep

The expressions go non-finite or out of int range on perfectly ordinary input --
a zero start frequency makes log() diverge, equal endpoints give 0/0, and a step
count of INT_MAX overflows a plain `DnumSteps+1`. Converting any of those to int
is undefined, so the count became whatever the hardware produced. One route
reached the allocator NEGATIVE (ASan: "requested allocation size
0xfffffffffffffff0"). Separately, `.dc` had no bound at all: it advances by a
step and compares against the stop value, so a step below the ULP of the start
never advances and the sweep runs forever.

WHY AN ORDINARY BUILD CANNOT SEE MOST OF THIS. Undefined conversions do not
trap; they yield a plausible number and the run continues. What a normal build
CAN observe is the consequence -- a nonsense request must be refused rather than
run with an invented point count, and a sweep that cannot progress must not hang.
That is what is asserted here.

A NOTE ON WHAT IS *NOT* A BUG. An enormous but finite sweep is slow, not hung,
and the two are indistinguishable from a timeout. `sens ac dec 1000000` over 300
decades measured 0.05 / 0.20 / 1.78 / 17.4 s at 1 / 10 / 100 / 1000 steps --
linear, so it is simply large. Those are deliberately not rejected: only counts
that cannot be represented, and loops that cannot advance, are.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DECK = """sweep guard
V1 in 0 dc 0.65 ac 1 distof1 1 distof2 1
Rs in d 1k
D1 d 0 dm
.model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)
Rl d 0 1meg
.control
option noacct
set numdgt=12
{ctl}
.endc
.end
"""


def run(ctl, tag, timeout=60):
    p = os.path.join(HERE, "_sg_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(DECK.format(ctl=ctl))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    return r.returncode, r.stdout + r.stderr


# Each of these was a distinct sanitizer report or an unbounded loop. None may
# hang, and none may proceed to produce output from an invented point count.
NONSENSE = [
    ("disto, count overflows int",      "disto oct 2147483647 1e6 1e30 -0.5"),
    ("disto, log diverges to -inf",     "disto dec 1000000 1e300 1e-30"),
    ("disto, log diverges to +inf",     "disto oct 2 1e-30 1e300"),
    ("disto, DnumSteps+1 overflows",    "disto lin 2147483647 1e30 1e6 -0.5"),
    ("disto, negative step count",      "disto lin -5 1 1e6 1e-30"),
    ("disto, zero steps per decade",    "disto dec 0 1e4 1e5"),
    ("disto, linear start == stop",     "disto lin 1 1e6 1e6"),
    ("tran, timepoint count overflows", "tran 1e6 1e30 1e6"),
    ("dc, step below the start's ULP",  "dc V1 1 1 1e-30"),
    ("dc, count exceeds int",           "dc V1 0 1 1e-30"),
    ("sens, count overflows int",       "sens v(d) ac dec 2147483647 1e6 -1e6"),
]

# Ordinary sweeps must be completely unaffected -- the guards are only allowed to
# reject what cannot be represented.
NORMAL = [
    ("disto dec",  "disto dec 2 1e4 1e5 0.9\nsetplot disto1\nprint d[0]", r"d\[0\] = (\S+)"),
    ("ac dec",     "ac dec 5 1e4 1e6\nprint vdb(d)[10]",                  r"vdb\(d\)\[10\] = (\S+)"),
    ("dc sweep",   "dc V1 0 1 0.001\nprint v(d)[500]",                    r"v\(d\)\[500\] = (\S+)"),
    ("dc reverse", "dc V1 1 0 -0.1\nprint v(d)[5]",                       r"v\(d\)\[5\] = (\S+)"),
    ("tran",       "tran 5n 2u\nprint v(d)[100]",                         r"v\(d\)\[100\] = (\S+)"),
    ("sens ac",    "sens v(d) ac dec 5 1e4 1e6",                          None),
]


def main():
    hung = [n for i, (n, c) in enumerate(NONSENSE) if run(c, "n%d" % i)[1] == "HANG"]
    check("no nonsense sweep spec hangs", not hung,
          "all %d terminate" % len(NONSENSE) if not hung else "HANG: %s" % hung)

    # A refused sweep must not also emit results computed from a garbage count.
    leaked = []
    for i, (name, ctl) in enumerate(NONSENSE):
        rc, out = run(ctl + "\nsetplot disto1\nprint d[0]", "p%d" % i)
        if out != "HANG" and re.search(r"^d\[0\] = ", out or "", re.M):
            leaked.append(name)
    check("no nonsense sweep spec produces output", not leaked,
          "none of %d emit results" % len(NONSENSE) if not leaked else str(leaked))

    # ...and every ordinary sweep still runs and still produces a finite value.
    bad = []
    for i, (name, ctl, pat) in enumerate(NORMAL):
        rc, out = run(ctl, "g%d" % i)
        if out == "HANG" or rc != 0:
            bad.append("%s rc=%s" % (name, rc))
            continue
        if pat:
            m = re.search(pat, out, re.M)
            # .disto prints a complex value as "re,im", so take the real part
            try:
                v = float(m.group(1).split(",")[0]) if m else None
            except ValueError:
                v = None
            if v is None or v != v or abs(v) == float("inf"):
                bad.append("%s no finite value" % name)
    check("ordinary sweeps are unaffected", not bad,
          "%d analyses run clean" % len(NORMAL) if not bad else str(bad))

    for junk in os.listdir(HERE):
        if junk.startswith("_sg_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
