#!/usr/bin/env python3
"""Enhancement-472: `optimize` keeps the circuit standing between evaluations.

Enhancement-471 stopped `sweep` tearing the circuit down and rebuilding it for
every point, but asked for that in exactly one place. `optimize` never
re-sources the deck for `-param` / `-mparam` knobs -- and with Enhancement-322's
fast path armed, not for `-dparam` either -- yet it still paid for a full
teardown and rebuild on every evaluation, and a fit runs hundreds of them.

WHAT MAKES IT SAFE is Enhancement-471's machinery, unchanged: CKTdoJob still
runs CKTtemp on a reused analysis, so an OSDI device's node collapse is
re-decided against the snapshot the matrix was built from, and any change forces
a genuine rebuild. This suite's job is to show that holds when the thing moving
the collapse is a SEARCH STEP rather than a sweep point.

That needs a different model from Enhancement-417's `cs_gate`, which collapses
at exactly `rd == 0` -- a value a sweep can step onto deliberately but a search
step will never land on. `cs_thresh` collapses below a THRESHOLD, so a search
range straddling it moves the topology on its own.

The decisive checks are the ones where the report says a rebuild fired WHILE the
answer is unchanged -- proving the guard did work, rather than that the test
never exercised it.

WHY `montecarlo` IS NOT HERE. Its fast path (Enhancement-346) also leaves the
circuit standing between samples and would gain as much. It is deliberately
excluded, because that fast path can arm while a random `.param` still has a use
it cannot push -- a B-source's value is substituted textually at parse time, so
nothing short of a re-source moves it. That is already a live defect without any
reuse: such a deck reports a 100%/0% yield, flipping between runs of the SAME
deck and seed, where re-sourcing every sample reports the correct 45%. The
arming check has to be fixed before there is anything safe to build on, so
`montecarlo` is left exactly as it was -- which checks [15] and [16] assert.
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
    # `set ngdebug` makes ngspice write debug-out*.txt beside the deck, so the
    # suite has to sweep those up too or it litters the repo with untracked
    # files that no `_` prefix convention can catch -- ngspice chooses the name.
    for junk in os.listdir(HERE):
        if junk.startswith("_rl_") or junk.startswith("debug-out") \
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


def run(body, ctl, tag, osdi=("cs_thresh.osdi",), off=False):
    pre = "".join(f"pre_osdi {o}\n" for o in osdi)
    deck = (f"reuseloops {tag}\n{body}.control\n{pre}option noacct\nset numdgt=10\n"
            f"set ngdebug\n{'set reusesetup=0' if off else ''}\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_rl_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def decision(out):
    """(analyses whose setup was kept, analyses rebuilt) -- ngspice's own report.

    Without this the suite could only show the answer is the same, which a build
    where the reuse never engaged would satisfy just as well."""
    m = re.search(r"optimize: setup reused at (\d+) of \d+ analyses, (\d+) rebuilt",
                  out)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def result(out):
    m = re.search(r"optimize: converged, (?:sum-sq residual|objective) = (\S+).*?"
                  r"after (\d+) evaluations", out)
    knob = re.search(r"@cgm\[rd\]\s*=\s*(-?[\d.]+e?[-+]?\d*)", out, re.I)
    return (m.group(1), m.group(2), knob.group(1) if knob else None) if m else None


print("Enhancement-472: optimize keeps the circuit standing\n")

r = subprocess.run([OPENVAF, "cs_thresh.va", "-o", "cs_thresh.osdi"], cwd=HERE,
                   capture_output=True, text=True)
check("[0] the model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "cs_thresh.osdi")),
      (r.stdout + r.stderr).strip()[:60])

BODY = ("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n"
        ".model cgm cs_thresh rd=600 rth=100\n")
# the optimum (rd = 500) is on the SAME side of the collapse as the start
FIT = ("optimize -mparam @cgm[rd] 600 0 1k -analysis op -target v(out) 0.4 "
       "-maxiter 30\nprint @cgm[rd]")
# the optimum (rd -> 0) is on the FAR side, so the search must cross it
FITX = ("optimize -mparam @cgm[rd] 600 0 1k -analysis op -target v(out) 0.5 "
        "-maxiter 30\nprint @cgm[rd]")

print("an in-place fit reuses the setup")
a, b = run(BODY, FIT, "op1"), run(BODY, FIT, "op1o", off=True)
kept, rebuilt = decision(a)
check("[1] every analysis after the first is kept",
      kept is not None and kept >= 1 and rebuilt == 0, f"{decision(a)}")
check("[2] with the reuse off nothing is kept", decision(b) == (0, 0), f"{decision(b)}")
check("[3] the fit finds the identical parameter in the identical evaluations",
      result(a) is not None and result(a) == result(b), f"{result(a)} vs {result(b)}")

print("\na search that crosses a node collapse rebuilds, and still answers the same")
a, b = run(BODY, FITX, "op2"), run(BODY, FITX, "op2o", off=True)
check("[4] the crossing forces a real rebuild",
      decision(a)[1] is not None and decision(a)[1] > 0, f"{decision(a)}")
check("[5] ...and some analyses were still reused around it",
      decision(a)[0] is not None and decision(a)[0] > 0, f"{decision(a)}")
check("[6] ...and the answer and evaluation count are identical",
      result(a) is not None and result(a) == result(b), f"{result(a)} vs {result(b)}")

print("\nthe cases that must decline it")
a = run(BODY + ".param rv=600\nB1 x 0 v=v(out)*rv\n",
        "optimize -dparam rv 600 0 1k -analysis op -target v(out) 0.4 -maxiter 20",
        "op3")
check("[7] a -dparam fit that re-sources each evaluation keeps nothing",
      decision(a) == (0, 0), f"{decision(a)}")

# a built-in device decides its collapse in DEVsetup and cannot be re-checked,
# so CKTdoJob declines for the whole circuit even though the optimizer asked --
# nothing but the report can show this, since the answer is the same either way
a = run(BODY + "Q1 in out 0 qmod\n.model qmod npn bf=100\n", FIT, "op4")
check("[8] a built-in device declines the reuse for the whole circuit",
      decision(a) == (0, 0), f"{decision(a)}")

a = run("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n.param rv=agauss(0,20,3)\n"
        ".model cgm cs_thresh rd='600+rv' rth=100\n",
        "optimize -mparam @cgm[g] 1m 0.5m 2m -analysis op -center "
        "-spec v(out) -min 0.3 -max 0.6 -nsamples 6 -maxiter 4", "op5")
check("[9] -center, whose inner Monte Carlo resets per sample, keeps nothing",
      decision(a) == (0, 0), f"{decision(a)}")

print("\nevery spelling that means off means off")
for i, spell in enumerate(("reusesetup=0", "reusesetup=false", "reusesetup=no",
                           "reusesetup=off", "noreusesetup")):
    a = run(BODY, f"set {spell.replace('=', ' ') if False else spell}\n{FIT}",
            f"sp{i}")
    check(f"[{10+i}] `set {spell}` really turns it off",
          decision(a) == (0, 0), f"{decision(a)}")

# ------------------------------------------------------------- montecarlo ----
# Deliberately untouched -- see the module docstring. These two checks are what
# stop it being switched on by accident.
print("\nmontecarlo is deliberately left alone")
MC_BODY = ("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n"
           ".param rv=agauss(100,60,3)\n.model cgm cs_thresh rd='rv' rth=1e9\n")
MC = "montecarlo 20 -seed 7 -analysis op -spec v(out) -min 0 -max 1"
a, b = run(MC_BODY, MC, "mc1"), run(MC_BODY, MC, "mc1o", off=True)


def yields(out):
    m = re.search(r"yield\s*:\s*([\d.]+)%\s*\((\d+) / (\d+) pass\)", out)
    return m.group(0) if m else None


check("[15] montecarlo never asks for the reuse",
      "setup reused" not in a and "fast path armed" in a, "")
check("[16] ...and answers identically whichever way the option is set",
      yields(a) is not None and yields(a) == yields(b),
      f"{yields(a)} vs {yields(b)}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
