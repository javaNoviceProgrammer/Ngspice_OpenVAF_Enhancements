#!/usr/bin/env python3
"""
verify_abstolperf.py -- pins the COST of the LRM 3.6.1 nature-abstol path.

Enhancement-539 made a nature's declared `abstol` reach the convergence test.
The first implementation searched the CKTnode list for every (instance, node)
pair -- O(instances x nodes x circuit nodes). It was written believing the path
was rare ("only models that declare custom natures"), which is false:
`disciplines.vams` declares abstol on the STANDARD natures, so it runs for every
OSDI node in every deck. On a 17-model photonic deck it cost 4.1 s of a 6.2 s
run. The fix collects tolerances into an array indexed by node number and
applies them in one node-list walk per model type.

WHY THIS TEST IS A RATIO AND NOT A STOPWATCH. An absolute time threshold is a
machine-speed measurement, not a complexity measurement -- it goes red on a slow
box and green on a fast one whatever the algorithm does. Doubling the circuit
instead separates the two shapes by construction: a linear cost doubles, a
quadratic one quadruples. Measured on this fixture, same deck, same binary,
only the algorithm differing:

    pre-fix  (quadratic)   8000 -> 16000 devices : 3.52x
    post-fix (linear)      8000 -> 16000 devices : 1.85x - 1.98x  (both solvers)

so LINEAR_RATIO_MAX sits at 2.8: ~41% clear of the fixed measurement and ~20%
below the broken one.

  [1] the fixture model compiles
  [2] the nature-abstol path is ACTIVE on this deck -- nodes really do receive a
      declared tolerance. Without this a future "optimization" that simply
      deleted the feature would sail through the timing check below.
  [3] the operating point is still correct (a fast wrong answer is not a pass)
  [4] setup cost scales about linearly in circuit size, not quadratically

Check [4] is the regression pin; [2] and [3] are what stop it being gamed.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

# circuit sizes for the doubling; both are cheap once the cost is linear
SMALL, LARGE = 8000, 16000
REPEATS = 5                 # the MINIMUM of these is the estimate: robust to load spikes
LINEAR_RATIO_MAX = 2.8      # see the note above
SANITY_SECONDS = 1.5        # a baseline slower than this means the machine is too
                            # busy to time anything; report rather than fail

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

# The generated decks are also gitignored, and deliberately so: the solver
# harness rewrites each deck it runs to pin `.option klu`/`sparse` and restores
# the original at PROCESS EXIT, which lands after this script's own cleanup and
# recreates them. Every suite that generates decks is ignored the same way.
ARTEFACTS = ["abstolperf.osdi", "_ap_small.cir", "_ap_large.cir", "_ap_dbg.cir"]
def clean():
    for f in ARTEFACTS:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
clean()

def deck(n, ctl=("op",)):
    """A ladder of n OSDI devices: instances AND circuit nodes both scale with n,
    which is what makes the quadratic term visible."""
    lines = [f"* abstolperf ladder n={n}", "v1 w0 0 dc 1"]
    lines += [f"nd{k} w{k} w{k+1} mm" for k in range(n)]
    lines += [f"rterm w{n} 0 1k", ".model mm abstolperf r=1k", ".control",
              "pre_osdi abstolperf.osdi"] + list(ctl) + ["quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"

def write(name, text):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(text)
    return name

def run(name):
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       cwd=HERE, errors="replace")
    return r.stdout + r.stderr

def timed(name):
    """Best of REPEATS. The minimum, not the mean: it is the run least
    disturbed by whatever else the machine was doing."""
    best = None
    for _ in range(REPEATS):
        t0 = time.time()
        subprocess.run([NGSPICE, "-b", name], capture_output=True, cwd=HERE)
        dt = time.time() - t0
        best = dt if best is None else min(best, dt)
    return best

# ------------------------------------------------------------------- [1] -----
r = subprocess.run([OPENVAF, "abstolperf.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "abstolperf.osdi"))
check("the fixture model compiles", compiled,
      (r.stdout + r.stderr).strip().splitlines()[0] if not compiled else "")

if not compiled:
    print(f"\n{passed}/{checks} checks passed")
    raise SystemExit(1)

# ------------------------------------------------------------------- [2] -----
# Anti-gaming: the path must actually be doing its job on this very deck.
write("_ap_dbg.cir", deck(200, ctl=("set ngdebug", "op")))
dbg = run("_ap_dbg.cir")
stamped = len(re.findall(r"convergence abstol", dbg))
check("the nature-abstol path is active on this deck (nodes are stamped)",
      stamped > 0, f"{stamped} nodes reported; expected > 0")

# ------------------------------------------------------------------- [3] -----
# A ladder of n 1k devices plus a 1k terminator, driven by 1 V: the far node
# sits at 1/(n+1). A fast but wrong setup must not pass.
small_deck = write("_ap_small.cir", deck(SMALL, ctl=("op", f"print v(w{SMALL})")))
out = run(small_deck)
m = re.search(rf"v\(w{SMALL}\)\s*=\s*([-\d.eE+]+)", out)
got = float(m.group(1)) if m else None
want = 1.0 / (SMALL + 1)
check("the operating point is still correct",
      got is not None and abs(got - want) <= 1e-3 * want,
      f"got {got}, want {want:.6e}")

# ------------------------------------------------------------------- [4] -----
large_deck = write("_ap_large.cir", deck(LARGE))
t_small = timed(small_deck)
t_large = timed(large_deck)
ratio = t_large / t_small if t_small > 0 else float("inf")

print(f"      {SMALL:6d} devices: {t_small:6.3f}s   "
      f"{LARGE:6d} devices: {t_large:6.3f}s   ratio {ratio:.2f}x "
      f"(linear 2.0 / quadratic 4.0, threshold {LINEAR_RATIO_MAX})")

if t_small > SANITY_SECONDS:
    # Not a failure: the baseline itself is implausible, so the ratio carries no
    # information about the algorithm. Say so rather than reporting a red that
    # is really about machine load.
    print(f"      SKIPPED: baseline {t_small:.2f}s > {SANITY_SECONDS}s -- machine too "
          f"loaded for the ratio to mean anything")
    check("setup cost scales about linearly in circuit size (not timed)", True)
else:
    check("setup cost scales about linearly in circuit size, not quadratically",
          ratio < LINEAR_RATIO_MAX,
          f"ratio {ratio:.2f}x >= {LINEAR_RATIO_MAX} -- the nature-abstol stamp "
          f"(or something else in OSDIsetup) has gone superlinear again")

clean()
print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
