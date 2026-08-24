#!/usr/bin/env python3
"""Enhancement-473: the Monte Carlo fast path armed on a draw it could not push.

`montecarlo`'s fast path (Enhancement-346) re-draws the random values and pushes
them into the live circuit instead of re-sourcing the deck per sample. It is
only sound if EVERY use of a random value is actually pushed, and the arming
check had a hole.

Only a BRACED expression is captured. numparam decides the braces, and it does
not always write them: a quoted reference `rd='rv'` arrives as
`rd={(agauss(...))}` and is captured, but a BARE one -- a B-source's `v=rv` --
arrives as `v= ( agauss(...) )` with no braces at all. `sw_fp_scan_valueline()`
walked past it, found no swept token, and reported the line ELIGIBLE. The fast
path then armed while that value was never pushed, and a B-source's value is
substituted textually at parse time, so nothing short of a re-source moves it:
every sample after the first saw the FIRST draw.

WHAT THAT COST. A 40-sample Monte Carlo whose spec depended only on the frozen
value reported a yield of 100% or 0% -- and DIFFERED BETWEEN RUNS of the same
deck and the same seed, because what the frozen value happened to be depended on
surviving state. The correct answer, which the reset path gives, is ~45%.

That is a silently wrong AND unstable yield, in the same family as
Enhancement-438 (a Monte Carlo counting failed samples as passes). It needed the
deck to arm at all, which needs at least one CAPTURABLE random value alongside
the uncapturable one -- so `.model rd='rv'` plus `B1 bs 0 v=rv` is the shape.

A random draw sitting outside any braces is now ineligible, so such a deck
disarms and takes the reset path: slower, and right.

That fix is also what unblocked giving `montecarlo` the setup reuse of
Enhancements 471/472, which is the second half of this suite. Arming now means
every varying value really is pushed -- the same guarantee `sweep` relies on --
so the circuit can be kept standing between samples.

THAT REUSE IS OFFERED ONLY UNDER `-warm`. Not tearing the circuit down also
leaves the previous sample's SOLUTION in place, which warm-starts the next one,
and Enhancement-188 made that opt-in deliberately -- it keeps its guess in a
buffer OUTSIDE the CKTcircuit precisely because a reset destroys the solution.
Measured on E-188's own suite, an unconditional reuse cut the COLD path from
20606 to 1416 iterations per sample: the homotopy it exists to avoid, avoided
without being asked. The yields matched, but a starting point decides which
operating point a sample finds on a circuit that has more than one, and Monte
Carlo samples are meant to be independent. Under `-warm` the user has already
asked for state to carry between samples, so the reuse is pure speed on top of
what was requested; without it nothing changes at all. Checks [9] and [10] are
what hold that line.
"""
import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)


def _cleanup():
    # `set ngdebug` makes ngspice write debug-out*.txt beside the deck
    for junk in os.listdir(HERE):
        if junk.startswith("_mca_") or junk.startswith("debug-out") \
                or junk.endswith(".osdi"):
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


def run(body, ctl, tag, osdi=(), dbg=False, off=False):
    pre = "".join(f"pre_osdi {o}\n" for o in osdi)
    deck = (f"mcarming {tag}\n{body}.control\n{pre}option noacct\n"
            f"{'set ngdebug' if dbg else ''}\n{'set reusesetup=0' if off else ''}\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_mca_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def yields(out):
    m = re.search(r"yield\s*:\s*([\d.]+)%", out)
    return m.group(1) if m else None


def armed(out):
    return "fast path armed" in out


def decision(out):
    m = re.search(r"montecarlo: setup reused at (\d+) of \d+ samples, (\d+) rebuilt",
                  out)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


print("Enhancement-473: the Monte Carlo fast path armed on an unpushable draw\n")

r = subprocess.run([OPENVAF, "cs_thresh.va", "-o", "cs_thresh.osdi"], cwd=HERE,
                   capture_output=True, text=True)
check("[0] the model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "cs_thresh.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# ------------------------------------------------------------- the arming ----
# `rd='rv'` is capturable (numparam writes braces) and gives the deck something
# to arm on; `B1 ... v=rv` is the SAME random param used where numparam writes
# no braces, so it cannot be pushed. Before the fix, both were accepted.
print("a draw the fast path cannot push must stop it arming")

BAD = ("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n"
       "B1 bs 0 v=rv\nRb bs 0 1meg\n"
       ".param rv=agauss(100,60,3)\n.model cgm cs_thresh rd='rv' rth=1e9\n")
MC_BAD = "montecarlo 40 -seed 11 -analysis op -spec v(bs) -min 0 -max 100"

a = run(BAD, MC_BAD, "bad", osdi=("cs_thresh.osdi",), dbg=True)
check("[1] a deck with an unpushable draw no longer arms", not armed(a), "")

# THE HEADLINE. This deck used to answer 100% on one run and 0% on the next,
# from the same seed, because the frozen value depended on surviving state.
runs = [yields(run(BAD, MC_BAD, f"bad{i}", osdi=("cs_thresh.osdi",)))
        for i in range(5)]
check("[2] ...so its yield is the same on every run of the same deck and seed",
      len(set(runs)) == 1 and runs[0] is not None, f"{runs}")

# rv ~ N(100,60) against a 0 <= v <= 100 spec is P = 0.452, so 40 samples must
# land near that -- NOT at the 0% or 100% a frozen value produced.
y = float(runs[0]) if runs[0] else -1
check("[3] ...and it is a sampled ~45%, not the 0%/100% of a frozen value",
      25.0 < y < 70.0, f"{y}%")

print("\nthe decks that were always fine must still arm")
OK_BODY = ("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n"
           ".param rv=agauss(100,60,3)\n.model cgm cs_thresh rd='rv' rth=1e9\n")
MC_OK = "montecarlo 20 -seed 7 -analysis op -spec v(out) -min 0 -max 1"
a = run(OK_BODY, MC_OK, "ok", osdi=("cs_thresh.osdi",), dbg=True)
check("[4] a quoted random .model value still arms", armed(a), "")

BR = "V1 in 0 dc 1\nR1 in out {agauss(1k,100,3)}\nRl out 0 1k\n"
a = run(BR, MC_OK, "braced", dbg=True)
check("[5] a braced random device value still arms", armed(a), "")

# the three spellings are the same circuit and must give the same answer
sp = {}
for tag, spell in (("bare", "rv"), ("quoted", "'rv'"), ("braced", "{rv}")):
    body = (f"V1 in 0 dc 1\nB1 bs 0 v={spell}\nRb bs 0 1meg\n"
            ".param rv=agauss(100,60,3)\n")
    sp[tag] = yields(run(body, "montecarlo 40 -seed 5 -analysis op "
                               "-spec v(bs) -min 0 -max 100", "sp" + tag))
check("[6] the three ways of spelling the same B-source value agree",
      len(set(sp.values())) == 1 and None not in sp.values(), f"{sp}")

# --------------------------------------------------------------- the reuse ---
# With arming honest, montecarlo can keep the circuit standing between samples
# (Enhancements 471/472). Every guard is theirs, unchanged.
print("\nand montecarlo can now keep the circuit standing")

MC_WARM = MC_OK + " -warm"
a = run(OK_BODY, MC_WARM, "r1", osdi=("cs_thresh.osdi",), dbg=True)
b = run(OK_BODY, MC_WARM, "r1o", osdi=("cs_thresh.osdi",), dbg=True, off=True)
check("[7] under -warm, every sample after the first is kept",
      decision(a) == (19, 0), f"{decision(a)}")
check("[8] ...with the yield identical to rebuilding every sample",
      yields(a) is not None and yields(a) == yields(b), f"{yields(a)} vs {yields(b)}")

# THE LINE THAT MUST NOT MOVE: without -warm the circuit is still rebuilt per
# sample, so a user who never asked for state to carry between samples does not
# silently get it. An unconditional reuse cut E-188's COLD path from 20606 to
# 1416 iterations per sample -- its opt-in, turned on without being asked.
c = run(OK_BODY, MC_OK, "r1c", osdi=("cs_thresh.osdi",), dbg=True)
check("[9] WITHOUT -warm nothing is kept -- the opt-in is not overridden",
      decision(c) == (0, 0), f"{decision(c)}")
check("[10] ...and the answer is the same either way",
      yields(c) is not None and yields(c) == yields(a), f"{yields(c)} vs {yields(a)}")
check("[11] with the reuse option off nothing is kept", decision(b) == (0, 0),
      f"{decision(b)}")

# THE DECISIVE ONE: draws that straddle the collapse threshold. The spec passes
# only a COLLAPSED sample (collapsed v(out) is exactly 0.5; uncollapsed is
# 1000/(2000+rd) < 0.476 for rd > 100), so the yield measures the topology
# directly -- frozen, it would be 0% or 100% instead of tracking the draws.
CB = ("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n"
      ".param rv=agauss(100,60,3)\n.model cgm cs_thresh rd='rv' rth=100\n")
MC_C = "montecarlo 20 -seed 7 -analysis op -spec v(out) -min 0.49 -warm"
a = run(CB, MC_C, "c1", osdi=("cs_thresh.osdi",), dbg=True)
b = run(CB, MC_C, "c1o", osdi=("cs_thresh.osdi",), dbg=True, off=True)
kept, rebuilt = decision(a)
check("[12] draws that move the node collapse force real rebuilds",
      rebuilt is not None and rebuilt > 0 and kept + rebuilt == 19,
      f"kept {kept}, rebuilt {rebuilt}")
check("[13] ...and the yield still tracks the topology draw for draw",
      yields(a) is not None and yields(a) == yields(b) and yields(a) == "50.000",
      f"{yields(a)} vs {yields(b)}")

# a deck that cannot arm re-sources per sample, so there is nothing to keep
a = run(BAD, MC_BAD + " -warm", "nr", osdi=("cs_thresh.osdi",), dbg=True)
check("[14] a deck that does not arm keeps nothing",
      decision(a) == (0, 0), f"{decision(a)}")

print("\nevery spelling that means off means off")
for i, spell in enumerate(("reusesetup=0", "reusesetup=false", "reusesetup=no",
                           "reusesetup=off", "noreusesetup")):
    a = run(OK_BODY, f"set {spell}\n{MC_WARM}", f"sp{i}",
            osdi=("cs_thresh.osdi",), dbg=True)
    check(f"[{15+i}] `set {spell}` really turns it off",
          decision(a) == (0, 0), f"{decision(a)}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
