#!/usr/bin/env python3
"""openvaf-r autodiff audit -- hypot, atan2 & real-modulo derivative fixes
(Enhancement-185 + Enhancement-186).

The compiler builds the small-signal Jacobian (used by AC, convergence, noise,
.pz, every derivative-dependent result) with its own automatic differentiation.
An audit that compared the AC small-signal conductance g = dI/dV of many
nonlinear laws I = f(V) against the *analytic* f'(V) found three builtins whose
VALUE is correct (so DC is right) but whose DERIVATIVE was wrong -- the classic
"accidental correctness" pattern that DC-only tests miss:

  * hypot(x,y): the autodiff rule computed (x' + y')/(2*hypot) -- the sqrt
    pattern misapplied -- instead of the correct (x*x' + y*y')/hypot. At
    V=0.7, y=0.5 it gave 0.581/hypot where the answer is 0.7/hypot (28% off).
    It is only accidentally correct at x=0.5 (with y constant).            [185]

  * atan2(x,y): TWO bugs in the cached factors -- the common factor was
    (x^2+y^2) where the shared chain rule multiplies by it, so it needed the
    RECIPROCAL 1/(x^2+y^2); and the second-argument factor was +x where the
    derivative subtracts, so it needed -x. Result: wrong magnitude AND wrong
    sign for the y-argument derivative.                                    [185]

  * real modulo % (Frem): x % c = x - floor(x/c)*c is a slope-1 sawtooth in x,
    so d/dx(x % c) = 1 (away from wrap points), yet the opcode was grouped with
    floor/ceil/integer ops and forced to derivative 0 in BOTH the
    live-derivative gate (lib.rs) and the chain rule (builder.rs). A model
    using real modulo (phase wrap, periodic geometry) got a correct DC value
    but a zero AC/Jacobian contribution. Correct rule (also for a variable
    divisor): d/du(x % c) = x' - floor(x/c)*c'.                            [186]

All three are fixed in mir_autodiff (builder.rs + lib.rs). This suite
recompiles a battery of nonlinear laws, reads the AC conductance, and checks it
against the analytic derivative -- with hypot, atan2 and real-modulo (both a
resistive I and a reactive Q, both argument orders, chain-composed) as the
headline cases, plus a regression battery of the other math builtins that were
already correct.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
# autodiff correctness is a COMPILER property, identical under both linear
# solvers, so this suite runs once (cf. the front-end-only progressbar suite).

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(name, body):
    va = os.path.join(HERE, name + ".va")
    open(va, "w").write(body)
    r = subprocess.run([OPENVAF, va, "-o", os.path.join(HERE, name + ".osdi")],
                       capture_output=True, text=True, cwd=HERE)
    return r.returncode == 0, (r.stderr + r.stdout)


def ac_gac(name, expr, v0, kind="I"):
    """Bias node a to v0 (ideal source, DC v0 + AC 1). The device draws
    <kind>(a,b) = f(V(a,b)); in AC, -i(vb) = Y*v(a) with v(a)=1, so
    Y = -i(vb): the real part is the conductance dI/dV (kind=I) and the
    imag part / omega the dQ/dV (kind=Q). Returns (greal, gimag_over_w)."""
    body = (f'`include "disciplines.vams"\n'
            f'module dut(a,b); inout a,b; electrical a,b;\n'
            f'analog {kind}(a,b) <+ {expr};\n'
            f'endmodule\n')
    ok, log = compile_va(name, body)
    if not ok:
        return None, None, "COMPILE-FAIL: " + (log.strip().splitlines() or [""])[-1][:70]
    f = 1e3
    deck = (f"* {name}\nVb a 0 DC {v0} AC 1\nN1 a 0 dm\n.model dm dut\n"
            f".control\npre_osdi {name}.osdi\nac lin 1 {f} {f}\nprint i(vb)\n.endc\n.end\n")
    open(os.path.join(HERE, name + ".cir"), "w").write(deck)
    out = subprocess.run([NGSPICE, "-b", name + ".cir"], capture_output=True,
                         text=True, cwd=HERE, timeout=60)
    txt = out.stdout + out.stderr
    m = re.search(r"i\(vb\)\s*=\s*([-\d.eE+]+),\s*([-\d.eE+]+)", txt)
    if not m:
        return None, None, "NO-AC"
    gr = -float(m.group(1))
    gi_over_w = -float(m.group(2)) / (2 * math.pi * f)
    return gr, gi_over_w, None


def check_deriv(name, expr, fp, v0, label, tol=2e-3):
    gr, _, err = ac_gac(name, expr, v0)
    if err:
        check(label, False, err)
        return
    ref = fp(v0)
    d = abs(gr - ref) / (abs(ref) + 1e-30)
    check(label, d < tol, f"(g_ac={gr:.6e} analytic={ref:.6e} reldiff={d:.1e})")


K = 1e-3
print("Enhancement-185/186: openvaf-r autodiff -- hypot, atan2 & real-modulo fixes")

# ---------------- hypot (the headline fix) ----------------
check_deriv("h_a", f"{K}*hypot(V(a,b),0.5)", lambda v: K * v / math.hypot(v, 0.5), 0.7,
            "[hypot] d/dV hypot(V,0.5) == V/hypot (was 0.5/(2*hypot), 28% off)")
check_deriv("h_b", f"{K}*hypot(0.5,V(a,b))", lambda v: K * v / math.hypot(v, 0.5), 0.7,
            "[hypot] d/dV hypot(0.5,V) == V/hypot (arg-order symmetric)")
# hypot must equal the hand-expanded sqrt(x^2+y^2) derivative exactly
gh, _, _ = ac_gac("h_c", f"{K}*hypot(V(a,b),0.5)", 0.7)
gs, _, _ = ac_gac("h_d", f"{K}*sqrt(V(a,b)*V(a,b)+0.25)", 0.7)
check("[hypot] d/dV hypot(V,0.5) == d/dV sqrt(V*V+0.25) (identical laws)",
      gh is not None and gs is not None and abs(gh - gs) < 1e-6 * abs(gs),
      f"(hypot {gh} vs sqrt-form {gs})")
# accidental-correctness point: at V=0.5 the OLD (buggy) code was already right,
# so the bug is invisible there -- pin that the fix did not disturb it
check_deriv("h_e", f"{K}*hypot(V(a,b),0.5)", lambda v: K * v / math.hypot(v, 0.5), 0.5,
            "[hypot] still correct at the V=0.5 accidental-correctness point")

# ---------------- atan2 (two bugs: reciprocal + sign) ----------------
check_deriv("a2_a", f"{K}*atan2(V(a,b),0.5)", lambda v: K * 0.5 / (v * v + 0.25), 0.7,
            "[atan2] d/dV atan2(V,0.5) == x/(x^2+y^2) (was *(x^2+y^2), not /)")
check_deriv("a2_b", f"{K}*atan2(0.5,V(a,b))", lambda v: -K * 0.5 / (v * v + 0.25), 0.7,
            "[atan2] d/dV atan2(0.5,V) == -y/(x^2+y^2) (sign was wrong too)")
# atan2(V,V) = pi/4 constant -> derivative must cancel to 0
gr, _, err = ac_gac("a2_c", f"{K}*atan2(V(a,b),V(a,b))", 0.7)
check("[atan2] d/dV atan2(V,V) == 0 (constant pi/4; mixed partials cancel)",
      err is None and abs(gr) < 1e-9, f"(g_ac={gr})" if err is None else err)

# ---------------- the fix reaches reactive charge (AC susceptance) too ----------------
# I(a,b) = ddt(C0*hypot(V,0.5)) -> AC susceptance b = w*dQ/dV = w*C0*V/hypot,
# so the imag part of the small-signal current carries the fixed derivative.
_, bq, err = ac_gac("q_h", "ddt(1e-9*hypot(V(a,b),0.5))", 0.7)
bref = 1e-9 * 0.7 / math.hypot(0.7, 0.5)
check("[hypot] reactive charge dQ/dV (AC susceptance) also fixed",
      err is None and abs(bq - bref) < 2e-3 * abs(bref),
      f"(dQ/dV={bq:.6e} analytic={bref:.6e})" if err is None else err)

# ---------------- real modulo % (Enhancement-186) ----------------
# x % c is a slope-1 sawtooth in x: the VALUE tracks V (DC right) but the
# derivative was forced to 0 by grouping Frem with floor/ceil in the
# live-derivative gate AND the chain rule. Correct: d/dV (V % c) == 1.
check_deriv("m_a", f"{K}*(V(a,b) % 1.0)", lambda v: K, 0.7,
            "[frem] d/dV (V % 1.0) == 1 (was 0: modulo mis-grouped with floor)")
check_deriv("m_b", "5e-3*(V(a,b) % 1.0)", lambda v: 5e-3, 0.3,
            "[frem] d/dV (5m*(V % 1.0)) scales with the prefactor")
check_deriv("m_c", f"{K}*(V(a,b) % 0.4)", lambda v: K, 0.7,
            "[frem] d/dV (V % 0.4) == 1 (constant divisor != 1)")
# the chain rule must flow THROUGH the modulo: d/dV (V%1)^2 = 2*(V%1)
check_deriv("m_d", f"{K}*((V(a,b) % 1.0)*(V(a,b) % 1.0))",
            lambda v: K * 2 * (v % 1.0), 0.7,
            "[frem] chain rule through modulo: d/dV (V%1)^2 == 2*(V%1)")
# floor/ceil are GENUINELY piecewise-constant -- the fix must leave them at 0
gfl, _, efl = ac_gac("m_fl", f"{K}*floor(V(a,b)*10.0)", 0.72)
gcl, _, ecl = ac_gac("m_cl", f"{K}*ceil(V(a,b)*10.0)", 0.72)
check("[frem] floor/ceil derivatives untouched (genuinely 0)",
      efl is None and ecl is None and abs(gfl) < 1e-12 and abs(gcl) < 1e-12,
      f"(floor'={gfl} ceil'={gcl})")

# ---------------- regression: the other builtins were already correct ----------------
battery = [
    ("sin", f"{K}*sin(V(a,b))", lambda v: K * math.cos(v), 0.7),
    ("cos", f"{K}*cos(V(a,b))", lambda v: -K * math.sin(v), 0.7),
    ("tan", f"{K}*tan(V(a,b))", lambda v: K / math.cos(v) ** 2, 0.7),
    ("asin", f"{K}*asin(V(a,b))", lambda v: K / math.sqrt(1 - v * v), 0.5),
    ("atan", f"{K}*atan(V(a,b))", lambda v: K / (1 + v * v), 0.7),
    ("tanh", f"{K}*tanh(V(a,b))", lambda v: K * (1 - math.tanh(v) ** 2), 0.7),
    ("asinh", f"{K}*asinh(V(a,b))", lambda v: K / math.hypot(v, 1), 0.7),
    ("acosh", f"{K}*acosh(V(a,b))", lambda v: K / math.sqrt(v * v - 1), 1.5),
    ("atanh", f"{K}*atanh(V(a,b))", lambda v: K / (1 - v * v), 0.5),
    ("exp", "1e-6*exp(V(a,b)/0.026)", lambda v: 1e-6 / 0.026 * math.exp(v / 0.026), 0.3),
    ("ln", f"{K}*ln(V(a,b))", lambda v: K / v, 0.7),
    ("log", f"{K}*log(V(a,b))", lambda v: K / (v * math.log(10)), 0.7),
    ("sqrt", f"{K}*sqrt(V(a,b))", lambda v: K / (2 * math.sqrt(v)), 0.7),
    ("pow_f", f"{K}*pow(V(a,b),2.5)", lambda v: K * 2.5 * v ** 1.5, 0.7),
    ("pow_b", f"{K}*pow(3.0,V(a,b))", lambda v: K * 3 ** v * math.log(3), 0.7),
]
worst = 0.0
nbad = 0
for nm, ex, fp, v0 in battery:
    gr, _, err = ac_gac("b_" + nm, ex, v0)
    if err:
        nbad += 1
        continue
    ref = fp(v0)
    worst = max(worst, abs(gr - ref) / (abs(ref) + 1e-30))
    if abs(gr - ref) / (abs(ref) + 1e-30) >= 2e-3:
        nbad += 1
check(f"[regression] {len(battery)} other math builtins: derivatives still correct",
      nbad == 0, f"(worst reldiff {worst:.1e}, {nbad} bad)")

# tidy the generated .va/.osdi/.cir this suite produced
import glob
for pat in ("*.va", "*.osdi", "*.cir", "*.dat"):
    for g in glob.glob(os.path.join(HERE, pat)):
        if os.path.basename(g) not in ("hypot_demo.va", "hypot_demo.cir"):
            try:
                os.remove(g)
            except OSError:
                pass

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
