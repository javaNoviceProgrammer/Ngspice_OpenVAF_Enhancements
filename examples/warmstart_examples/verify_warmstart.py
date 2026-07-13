#!/usr/bin/env python3
"""Enhancement-188: Monte Carlo warm-start (`montecarlo ... -warm`).

The `montecarlo` command re-sources the deck for each sample and, by default,
COLD-solves the DC bias point -- running the full gmin/source-stepping homotopy
(~50 Newton iterations here) every time, even though consecutive samples move
the operating point only slightly. `-warm` reuses the previous sample's
converged solution as the initial guess, so a direct Newton converges in a
handful of iterations; a poor guess simply fails the first Newton and falls
back to the cold homotopy, so the converged point -- and the yield -- is the
same to within the solver's convergence tolerance.

This suite checks, on a ladder of Verilog-A diodes with random saturation
currents:

  * the warm yield equals the cold yield EXACTLY at a tight tolerance
    (reltol=1e-6), proving warm-start converges to the same operating point;
  * at the default tolerance they agree to within a few boundary samples (the
    metric here sits at ~3.8 V, where the default reltol window ~= the narrow
    spec band, so a couple of samples right at the edge can flip -- a
    tolerance effect, not a warm-start error);
  * warm-start cuts the per-sample Newton iteration count dramatically
    (~50 -> a handful);
  * `-warm` composes with `-lhs`.

It is a solver-side property; it runs once (Sparse), and also confirms the KLU
path, since warm-start lives in the shared DC operating-point code.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

OSDI = os.path.join(HERE, "warmstart_diode.osdi")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def build_osdi():
    r = subprocess.run([OPENVAF, "warmstart_diode.va", "-o", OSDI],
                       capture_output=True, text=True, cwd=HERE)
    return r.returncode == 0, (r.stderr + r.stdout)


LADDER = "".join(
    f"N{i} {i} {i+1} dm is={{agauss(1e-14, 3e-15, 3)}}\n" for i in range(1, 7)
) + "".join(f"R{i} {i+1} 0 100k\n" for i in range(1, 7))


def run(warm, reltol=None, lhs=False, solver="sparse"):
    """Run one montecarlo; return (npass, last_sample_iterations)."""
    opts = (f".options reltol={reltol}\n" if reltol else "") + \
           (".options klu\n" if solver == "klu" else "")
    flags = ("-warm " if warm else "") + ("-lhs " if lhs else "")
    deck = (
        "* warmstart verify\n"
        f"{opts}"
        "Vs 1 0 DC 5\n"
        f"{LADDER}"
        ".model dm wdiode\n"
        ".control\n"
        f"pre_osdi {os.path.basename(OSDI)}\n"
        "option noacct\n"
        f"montecarlo 400 {flags}-seed 1 -analysis op -spec v(3) -max 3.791 -min 3.785\n"
        "rusage totiter\n"
        ".endc\n.end\n"
    )
    open(os.path.join(HERE, "_wv.cir"), "w").write(deck)
    out = subprocess.run([NGSPICE, "-b", "_wv.cir"], capture_output=True,
                         text=True, cwd=HERE, timeout=600).stdout
    err = ""  # ngspice prints to stdout in -b
    txt = out
    mp = re.search(r"\(\s*(\d+)\s*/\s*\d+\s*pass\)", txt)
    mi = re.search(r"Total iterations\s*=\s*(\d+)", txt)
    return (int(mp.group(1)) if mp else None,
            int(mi.group(1)) if mi else None)


ok, log = build_osdi()
if not ok:
    print("  FAIL  compile warmstart_diode.va\n" + log[-400:])
    raise SystemExit(1)

print("Enhancement-188: Monte Carlo warm-start")

# 1. EXACT match at a tight tolerance -> warm converges to the same OP as cold.
cold_t, cold_it = run(warm=False, reltol="1e-6")
warm_t, warm_it = run(warm=True, reltol="1e-6")
check("[exact] warm yield == cold yield at reltol=1e-6",
      cold_t is not None and cold_t == warm_t,
      f"(cold {cold_t}/400, warm {warm_t}/400)")

# 2. Default tolerance: agree to within a few boundary samples.
cold_d, cold_id = run(warm=False)
warm_d, warm_id = run(warm=True)
check("[default] warm yield ~= cold yield (agree to convergence tolerance)",
      cold_d is not None and abs(cold_d - warm_d) <= 6,
      f"(cold {cold_d}/400, warm {warm_d}/400, delta {abs(cold_d - warm_d)})")

# 3. The optimization: warm cuts the per-sample Newton iteration count a lot.
check("[speed] warm cuts iterations >=3x (cold homotopy avoided)",
      cold_id is not None and warm_id is not None and warm_id * 3 <= cold_id,
      f"(cold {cold_id} iters/sample, warm {warm_id})")

# 4. Composes with LHS (exact at tight tolerance).
cold_l, _ = run(warm=False, reltol="1e-6", lhs=True)
warm_l, _ = run(warm=True, reltol="1e-6", lhs=True)
check("[lhs] -warm composes with -lhs (same yield)",
      cold_l is not None and cold_l == warm_l,
      f"(lhs {cold_l}/400, lhs+warm {warm_l}/400)")

# 5. KLU path: warm-start lives in the shared DC op code, so it works there too.
cold_k, _ = run(warm=False, reltol="1e-6", solver="klu")
warm_k, _ = run(warm=True, reltol="1e-6", solver="klu")
check("[klu] warm yield == cold yield under KLU",
      cold_k is not None and cold_k == warm_k,
      f"(cold {cold_k}/400, warm {warm_k}/400)")

# tidy
for f in ("_wv.cir", os.path.basename(OSDI)):
    try:
        os.remove(os.path.join(HERE, f))
    except OSError:
        pass

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
