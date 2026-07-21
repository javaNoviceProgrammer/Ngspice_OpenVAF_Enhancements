#!/usr/bin/env python3
"""verify_vafsqrtguard.py -- Enhancement-261: openvaf-r no longer emits an
UNGUARDED singular derivative for sqrt().

A Verilog-A conductor I = K*sqrt(V) has an infinite small-signal conductance
dI/dV = K/(2*sqrt(V)) at ngspice's default V=0 initial guess. openvaf-r used to
emit that raw +inf, which NaN-poisoned the Jacobian and made the DC operating
point fail outright -- dynamic/true gmin, source, and pseudo-transient stepping
all died and the node came back `nan`. (Meanwhile the mathematically identical
pow(V,0.5) converged, because Pow had a base==0 derivative guard that sqrt did
not -- a plain internal inconsistency.)

E-261 regularizes the emitted sqrt derivative to K/(2*sqrt(V + a)) with a = 1e-18
-- the exact derivative of the smoothly regularized sqrt(V+a). It is FINITE at
V=0 (a large but bounded conductance -> small controlled Newton steps that creep
out of the singularity, exactly like ngspice's own B-source sqrt), and because
the nudge is INSIDE the root the perturbation for V>0 is ~a/(2V) < 1 ULP, so
every finite-bias derivative is unchanged. Being a plain value it also composes
through downstream operators (e.g. K*sqrt or 1/(1+sqrt)), which the alternative
block-split guard could not.

Checks (both linear solvers):
 [1] I=sqrt(V): DC op == the true KCL root (v0=0.178045), KCL satisfied, NOT nan;
 [2] I=K*sqrt(V), K=2 and K=5 (strongly scaled): the op is the true root and
     MATCHES ngspice's own B-source I=K*sqrt(v(n)) in the identical topology;
 [3] the guarded derivative is EXACT for V>0: the AC conductance G = K/(2*sqrt(V))
     at several biases matches the analytic value to ~1e-6;
 [4] composition: I = G0/(1+sqrt(V)) (sqrt feeding a reciprocal) also converges
     to its true root -- the guard propagates through the downstream operator;
 [5] pow(V,0.5) (== sqrt) still agrees with sqrt(V): the internal inconsistency
     is gone.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    passed += 1 if ok else 0
    failed += 0 if ok else 1


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run(deck, extra_ctrl):
    """Write a deck (V-source 0.6 through 1 ohm into node n), return v(n) or None."""
    open(os.path.join(HERE, "_sg.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_sg.cir"], capture_output=True, text=True,
                       cwd=HERE, timeout=60)
    out = r.stdout
    if "could not be simulated" in out:
        return None
    m = re.search(r"v\(n\)\s*=\s*([-\d.eE+na]+)", out)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    return val if math.isfinite(val) else None


# ---- compile the demo models ----
log, ok = compile_va("sqrtguard_demo.va")
check("compile sqrtguard_demo.va with openvaf-r", ok, "" if ok else log[-300:])
if not ok:
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1)

OSDI = "sqrtguard_demo.osdi"


def osdi_op(model_card, inst="N1 n 0 m"):
    deck = (f"* sqrt guard op\nV1 in 0 DC 0.6\nR1 in n 1\n{inst}\n{model_card}\n"
            f".control\npre_osdi {OSDI}\nop\nprint v(n)\n.endc\n.end\n")
    return run(deck, "")


def bsrc_op(law):
    deck = (f"* bsrc sqrt op\nV1 in 0 DC 0.6\nR1 in n 1\nB1 n 0 I={law}\n"
            f".control\nop\nprint v(n)\n.endc\n.end\n")
    return run(deck, "")


# KCL at node n: (0.6 - v)/1 = K*sqrt(v)  ->  K*sqrt(v) + v - 0.6 = 0.
def kcl_root(K):
    lo, hi = 0.0, 0.6
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f = K * math.sqrt(mid) + mid - 0.6
        if f > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# [1] bare sqrt: true root, KCL satisfied, not nan
v1 = osdi_op(".model m sqrtdev K=1")
root1 = kcl_root(1.0)
check("[1] I=sqrt(V): DC op is the true KCL root, not nan",
      v1 is not None and abs(v1 - root1) < 2e-3,
      f"(v(n)={v1} vs {root1:.6f}; pre-E-261 this was nan / op failed)")

# [2] strongly-scaled sqrt: true root AND B-source parity
for K in (2.0, 5.0):
    vo = osdi_op(f".model m sqrtdev K={K}")
    vb = bsrc_op(f"{K}*sqrt(v(n))")
    root = kcl_root(K)
    ok2 = (vo is not None and vb is not None
           and abs(vo - root) < 2e-3 and abs(vo - vb) < 2e-3)
    check(f"[2] I={K:g}*sqrt(V): op is true root AND matches B-source",
          ok2, f"(osdi={vo} bsrc={vb} exact={root:.6f})")

# [3] guarded derivative is EXACT for V>0: AC conductance G = K/(2 sqrt(V))
def osdi_G(K, vb):
    deck = (f"* sqrt ac cond\nV1 p 0 DC {vb} AC 1\nN1 p 0 m\n.model m sqrtdev K={K}\n"
            f".control\npre_osdi {OSDI}\nac lin 1 1k 1k\nprint real(i(v1))\n.endc\n.end\n")
    open(os.path.join(HERE, "_sg.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_sg.cir"], capture_output=True, text=True,
                       cwd=HERE, timeout=60)
    m = re.search(r"real\(i\(v1\)\)\s*=\s*([-\d.eE+]+)", r.stdout)
    return -float(m.group(1)) if m else None

worst = 0.0
for K in (1.0, 2.0):
    for vb in (0.05, 0.2, 0.7, 1.3):
        g = osdi_G(K, vb)
        ga = K / (2.0 * math.sqrt(vb))
        if g is None:
            worst = 1.0
            break
        worst = max(worst, abs(g - ga) / ga)
check("[3] guarded derivative is EXACT for V>0 (AC G = K/(2 sqrt V))",
      worst < 1e-4, f"(worst rel err = {worst:.2e})")

# [4] composition: I = G0/(1+sqrt(V)) converges (guard propagates through 1/(.))
def compose_op():
    deck = (f"* sqrt compose op\nV1 in 0 DC 0.6\nR1 in n 1\nN1 n 0 m\n"
            f".model m sqrtcompose G0=0.5\n"
            f".control\npre_osdi {OSDI}\nop\nprint v(n)\n.endc\n.end\n")
    return run(deck, "")
vc = compose_op()
# KCL: (0.6-v)/1 = 0.5/(1+sqrt(v)); solve
def compose_root():
    lo, hi = 0.0, 0.6
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f = 0.5 / (1.0 + math.sqrt(mid)) + mid - 0.6
        if f > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
rc = compose_root()
check("[4] I=G0/(1+sqrt(V)): composed sqrt converges to its true root",
      vc is not None and abs(vc - rc) < 2e-3,
      f"(v(n)={vc} vs {rc:.6f}; guard propagates through the reciprocal)")

# [5] pow(V,0.5) == sqrt(V): internal inconsistency gone
open(os.path.join(HERE, "_sgp.va"), "w").write(
    '`include "disciplines.vams"\nmodule powhalf(p,n);\n inout p,n; electrical p,n;\n'
    ' analog I(p,n) <+ pow(V(p,n),0.5);\nendmodule\n')
_, okp = compile_va("_sgp.va")
vp = None
if okp:
    deck = ("* powhalf op\nV1 in 0 DC 0.6\nR1 in n 1\nN1 n 0 m\n.model m powhalf\n"
            f".control\npre_osdi _sgp.osdi\nop\nprint v(n)\n.endc\n.end\n")
    vp = run(deck, "")
check("[5] pow(V,0.5) agrees with sqrt(V) (inconsistency gone)",
      vp is not None and v1 is not None and abs(vp - v1) < 2e-3,
      f"(pow={vp} sqrt={v1})")

# cleanup generated scratch (underscore temps are gitignored; _sgp.va is not)
for f in ("_sg.cir", "_sgp.va", "_sgp.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
