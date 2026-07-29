#!/usr/bin/env python3
"""Fuzz ngspice analysis-card parameters against a sanitizer build.

Motivation: Enhancement-361 found `(int)NaN` undefined behaviour in `.disto`'s
sweep-point count, reachable from ordinary input (`disto lin 1 1e6 1e6`, or a
zero-step decade sweep). That whole family -- a cast to int over an expression
that can go 0/0 or 0*inf -- is invisible to a normal build, which happily
converts the NaN to whatever the hardware produces and carries on.

So: drive every sweep-taking analysis with degenerate and extreme parameters,
under ASan+UBSan, and classify what comes back. A clean rejection is a PASS; the
interesting outcomes are a sanitizer report, a crash, or a hang.

What counts as a finding, in order of severity:
  SANITIZER  undefined behaviour or a memory error -- a real defect
  CRASH      signal / abort rather than a diagnosed error
  HANG       no termination inside the timeout -- a CANDIDATE, not a finding.
             An enormous-but-finite sweep is slow, not hung, and the two look
             identical to a timeout. Confirm by scaling the step count: if
             runtime scales with it the run is progressing (a `sens ac dec 1e6`
             over 300 decades measured 0.05/0.20/1.78/17.4s at 1/10/100/1000
             steps -- linear, so simply large). Only a non-advancing or
             unbounded loop is a defect.
  (ok / error are both fine: rejecting bad input IS correct behaviour)

Usage:  python3 fuzz_analysis.py [--iters N] [--seed S]
        NGSPICE_BIN must point at a sanitizer build for this to be worth running.
"""
import argparse
import os
import random
import re
import subprocess
import sys

NG = os.environ.get("NGSPICE_BIN")
OSDI = os.environ.get("FUZZ_OSDI", "")          # optional .osdi to include
HERE = os.path.dirname(os.path.abspath(__file__))

# Values chosen to break arithmetic rather than to be realistic: zero and
# negative step counts divide, equal endpoints give 0/0, a zero start frequency
# gives log(inf), and the extremes probe overflow on the way to the int cast.
COUNTS = ["0", "1", "2", "-1", "-5", "1000000", "2147483647"]
FREQS = ["0", "1e-30", "1", "1e6", "1e30", "-1e6", "1e300"]
RATIOS = ["0.9", "0", "1", "-0.5", "1e30", "1e-30"]
STEPTYPE = ["dec", "oct", "lin"]

DECK_HEAD = """fuzz
V1 in 0 dc 0.65 ac 1 distof1 1 distof2 1
Rs in d 1k
D1 d 0 dm
.model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)
Rl d 0 1meg
"""


def cards(rng):
    """One fuzzed analysis card. Sweep-taking analyses are weighted heavily --
    that is where the E-361 family lives."""
    st = rng.choice(STEPTYPE)
    n = rng.choice(COUNTS)
    f1 = rng.choice(FREQS)
    f2 = rng.choice(FREQS)
    r = rng.choice(RATIOS)
    return rng.choice([
        f"disto {st} {n} {f1} {f2}",
        f"disto {st} {n} {f1} {f2} {r}",
        f"ac {st} {n} {f1} {f2}",
        f"noise v(d) V1 {st} {n} {f1} {f2}",
        f"noise v(d) V1 {st} {n} {f1} {f2} {rng.choice(COUNTS)}",
        f"sens v(d) ac {st} {n} {f1} {f2}",
        f"pz 1 0 1 0 cur pol",
        f"tf v(d) V1",
        f"sp {st} {n} {f1} {f2}",
        f"dc V1 {f1} {f2} {rng.choice(['0','1e-30','-1','1e30'])}",
        f"tran {f1} {f2}",
        f"tran {f1} {f2} {f1}",
        f"four {f1} v(d)",
        f"fft v(d)",
    ])


SAN = re.compile(r"AddressSanitizer|runtime error:|UndefinedBehaviorSanitizer|"
                 r"LeakSanitizer", re.I)
CRASH = re.compile(r"Segmentation fault|Bus error|Abort trap|signal \d+|"
                   r"stack smashing|assertion failed", re.I)


def run_one(body, tag, timeout=25):
    path = os.path.join(HERE, "_fz_%s.cir" % tag)
    pre = ("pre_osdi %s\n" % OSDI) if OSDI else ""
    with open(path, "w") as f:
        f.write(DECK_HEAD + ".control\n" + pre + "option noacct\n" + body +
                "\n.endc\n.end\n")
    try:
        r = subprocess.run([NG, "-b", os.path.basename(path)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", ""
    out = r.stdout + r.stderr
    if SAN.search(out):
        m = re.search(r"([A-Za-z_0-9./]+\.c:\d+:\d+: runtime error: [^\n]*)", out)
        if not m:
            m = re.search(r"(ERROR: AddressSanitizer[^\n]*)", out)
        return "SANITIZER", (m.group(1) if m else out[:200])
    if r.returncode < 0 or CRASH.search(out):
        return "CRASH", "rc=%s" % r.returncode
    return "ok", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260728)
    a = ap.parse_args()
    if not NG or not os.path.exists(NG):
        print("set NGSPICE_BIN to a sanitizer build")
        return 2

    rng = random.Random(a.seed)
    seen, tally = {}, {"ok": 0, "SANITIZER": 0, "CRASH": 0, "HANG": 0}
    for i in range(a.iters):
        body = cards(rng)
        verdict, detail = run_one(body, str(i % 8))
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict != "ok":
            key = (verdict, detail)
            if key not in seen:              # one repro per distinct signature
                seen[key] = body
                print("  %-10s %-52s %s" % (verdict, body[:52], detail[:90]),
                      flush=True)
    print("\n  %d runs: " % a.iters +
          ", ".join("%s=%d" % (k, v) for k, v in sorted(tally.items())))
    print("  distinct findings: %d" % len(seen))
    for (verdict, detail), body in seen.items():
        print("    %-10s repro: %s" % (verdict, body))
    for junk in os.listdir(HERE):
        if junk.startswith("_fz_"):
            os.remove(os.path.join(HERE, junk))
    return 1 if seen else 0


sys.exit(main())
