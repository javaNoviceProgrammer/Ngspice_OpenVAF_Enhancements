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

# ---------------- cross-derivatives: BOTH arguments live ----------------
# Every check above pins a two-argument builtin with the *other* argument a
# CONSTANT (`hypot(V,0.5)` / `hypot(0.5,V)`). That cannot see the second
# argument's chain rule as a circuit derivative: it only ever produces the
# self-conductance dI/dV(a,b). E-185's hypot bug lived in exactly that rule, so
# this section makes both arguments genuine circuit unknowns:
#
#     dut(a,b,c,d):  I(a,b) <+ f(V(a,b), V(c,d))
#
# and reads the current in the a-b branch while the AC stimulus sits on the
# *other* pair. That off-diagonal Jacobian entry (the transconductance) exists
# only if d/d(arg2) is right, and it is what AC/noise/pz consume for any model
# whose law couples two node pairs.
def ac_cross(name, expr, x0, y0):
    """(df/dx, df/dy, err) with x=V(a,b), y=V(c,d) both live unknowns."""
    body = ('`include "disciplines.vams"\n'
            'module dutx(a,b,c,d); inout a,b,c,d; electrical a,b,c,d;\n'
            f'analog I(a,b) <+ {expr};\n'
            'endmodule\n')
    ok, log = compile_va(name, body)
    if not ok:
        return None, None, "COMPILE-FAIL: " + (log.strip().splitlines() or [""])[-1][:70]
    out = []
    for drive in (1, 2):                       # which pair carries the AC stimulus
        a1, a2 = ("1", "0") if drive == 1 else ("0", "1")
        deck = (f"* {name} cross\nVb1 a 0 DC {x0} AC {a1}\nVb2 c 0 DC {y0} AC {a2}\n"
                f"N1 a 0 c 0 dmx\n.model dmx dutx\n.control\npre_osdi {name}.osdi\n"
                f"ac lin 1 1e3 1e3\nprint i(vb1)\n.endc\n.end\n")
        open(os.path.join(HERE, name + f"_{drive}.cir"), "w").write(deck)
        r = subprocess.run([NGSPICE, "-b", name + f"_{drive}.cir"], capture_output=True,
                           text=True, cwd=HERE, timeout=60)
        m = re.search(r"i\(vb1\)\s*=\s*([-\d.eE+]+),\s*([-\d.eE+]+)", r.stdout + r.stderr)
        if not m:
            return None, None, "NO-AC"
        out.append(-float(m.group(1)))
    return out[0], out[1], None


XV, YV = "V(a,b)", "V(c,d)"
# Points are deliberately ASYMMETRIC: E-185 records that the old hypot rule was
# *accidentally* correct at x == y, so a symmetric point proves nothing.
cross = [
    ("hypot(x,y)", f"{K}*hypot({XV},{YV})",
     lambda x, y: K * x / math.hypot(x, y), lambda x, y: K * y / math.hypot(x, y),
     [(0.7, 0.3), (0.4, 1.1)]),
    ("atan2(x,y)", f"{K}*atan2({XV},{YV})",
     lambda x, y: K * y / (x * x + y * y), lambda x, y: -K * x / (x * x + y * y),
     [(0.7, 0.3), (0.4, 1.1)]),
    ("pow(x,y)", f"{K}*pow({XV},{YV})",
     lambda x, y: K * y * x ** (y - 1), lambda x, y: K * x ** y * math.log(x),
     [(0.7, 0.3), (1.3, 2.2)]),
    ("x*y", f"{K}*{XV}*{YV}", lambda x, y: K * y, lambda x, y: K * x, [(0.7, 0.3)]),
    ("x/y", f"{K}*{XV}/{YV}", lambda x, y: K / y, lambda x, y: -K * x / (y * y),
     [(0.7, 0.3)]),
    ("x*sin(y)", f"{K}*{XV}*sin({YV})",
     lambda x, y: K * math.sin(y), lambda x, y: K * x * math.cos(y), [(0.7, 0.3)]),
    # E-186: the modulo slope is 1 in x and -floor(x/y) in a VARIABLE divisor
    ("x%y", f"{K}*({XV} % {YV})",
     lambda x, y: K, lambda x, y: -K * math.floor(x / y), [(0.7, 0.3)]),
]
nbadx = worstx = 0
worstx = 0.0
for nm, ex, dfdx, dfdy, pts in cross:
    for (x0, y0) in pts:
        gx, gy, err = ac_cross("x_" + re.sub(r"\W", "", nm) + f"{x0}_{y0}".replace(".", ""),
                               ex, x0, y0)
        if err:
            nbadx += 1
            continue
        for got, ref in ((gx, dfdx(x0, y0)), (gy, dfdy(x0, y0))):
            d = abs(got - ref) / (abs(ref) + 1e-30)
            worstx = max(worstx, d)
            if d >= 2e-3:
                nbadx += 1
check(f"[cross] {len(cross)} two-arg builtins: BOTH partials correct with both "
      f"arguments live (off-diagonal Jacobian, asymmetric points)",
      nbadx == 0, f"(worst reldiff {worstx:.1e}, {nbadx} bad)")

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

# A single bias point per builtin is how hypot hid: its old rule was exactly
# right at one point (V=0.5) and 28% off elsewhere. Re-run the battery over a
# spread of points so an "accidentally correct at the tested point" rule cannot
# pass -- scaling each builtin's point into its own valid domain.
def spread(v0):
    return [v0 * s for s in (0.55, 1.0, 1.7)]

worst_m = 0.0
nbad_m = 0
npts = 0
for nm, ex, fp, v0 in battery:
    for i, v in enumerate(spread(v0)):
        if nm in ("asin", "atanh") and abs(v) >= 0.98:      # domain |x| < 1
            continue
        if nm == "acosh" and v <= 1.02:                     # domain x > 1
            continue
        if nm == "tan" and abs(math.cos(v)) < 1e-2:         # near the pole
            continue
        gr, _, err = ac_gac(f"s_{nm}{i}", ex, v)
        npts += 1
        if err:
            nbad_m += 1
            continue
        ref = fp(v)
        d = abs(gr - ref) / (abs(ref) + 1e-30)
        worst_m = max(worst_m, d)
        if d >= 2e-3:
            nbad_m += 1
check(f"[multipoint] the same battery over {npts} bias points (no builtin may be "
      f"merely accidentally correct at one point)",
      nbad_m == 0, f"(worst reldiff {worst_m:.1e}, {nbad_m} bad)")

# ---------------------------------------------------------------------------
# [matrix] the FULL multi-terminal Jacobian, both resistive and reactive.
#
# Everything above biases a 2-terminal device, and [cross] reads a single
# off-diagonal entry. Neither exercises the entries openvaf does NOT obtain by
# differentiating a contribution: on a 4-terminal device the source row follows
# from KCL over the other contributions, and an untouched terminal must produce
# an identically zero row/column. A sign or index slip there is invisible to a
# 2-terminal test but wrong in every real compact model.
#
# Both contributions are polynomials in THREE distinct branch voltages, at a bias
# where every branch voltage differs, so all 16 entries are distinct numbers and
# no accidental symmetry can mask a wrong one.
# ---------------------------------------------------------------------------
def terminal_matrix(kind, coeffs, bias, freq=1e3):
    """Measure the 4x4 terminal matrix of the quad dut. kind 'I' -> conductance
    (real part), kind 'Q' -> capacitance (imag part / omega)."""
    a1, a2, a3, c1, c2 = coeffs
    inner_d = f"{a1}*V(d,s) + {a2}*V(g,s)*V(g,s) + {a3}*V(d,s)*V(b,s)"
    inner_g = f"{c1}*V(g,s) + {c2}*V(d,s)*V(g,s)"
    if kind == "Q":
        inner_d, inner_g = f"ddt({inner_d})", f"ddt({inner_g})"
    body = ('`include "disciplines.vams"\n'
            'module quaddut(d,g,s,b); inout d,g,s,b; electrical d,g,s,b;\n'
            'analog begin\n'
            f'    I(d,s) <+ {inner_d};\n'
            f'    I(g,s) <+ {inner_g};\n'
            'end\nendmodule\n')
    ok, log = compile_va("quaddut", body)
    if not ok:
        return None, log
    w = 2.0 * math.pi * freq
    meas = {}
    for col in "dgsb":
        src = "\n".join(f"v{t} {t} 0 dc {bias[t]} ac {1 if t == col else 0}"
                         for t in "dgsb")
        deck = (f"* autodiff terminal matrix, column {col}\n{src}\n"
                "n1 d g s b qm\n.model qm quaddut()\n.control\n"
                "pre_osdi quaddut.osdi\n"
                f"ac lin 1 {freq:g} {freq:g}\n"
                "print real(i(vd)) real(i(vg)) real(i(vs)) real(i(vb)) "
                "imag(i(vd)) imag(i(vg)) imag(i(vs)) imag(i(vb))\n"
                ".endc\n.end\n")
        cir = os.path.join(HERE, "_qm.cir")
        open(cir, "w").write(deck)
        out = subprocess.run([NGSPICE, "-b", cir], capture_output=True,
                             text=True, cwd=HERE).stdout
        part = "real" if kind == "I" else "imag"
        for row in "dgsb":
            m = re.search(rf"{part}\(i\(v{row}\)\)\s*=\s*([-\d.eE+]+)", out)
            if m is None:
                return None, out
            meas[(row, col)] = -float(m.group(1)) / (1.0 if kind == "I" else w)
    return meas, ""


def matrix_reference(kind, coeffs, bias):
    """Analytic 4x4 terminal matrix: chain the branch partials through KCL."""
    a1, a2, a3, c1, c2 = coeffs
    vds, vgs, vbs = bias["d"] - bias["s"], bias["g"] - bias["s"], bias["b"] - bias["s"]
    fd = {"ds": a1 + a3 * vbs, "gs": 2 * a2 * vgs, "bs": a3 * vds}
    fg = {"ds": c2 * vgs, "gs": c1 + c2 * vds, "bs": 0.0}
    dbr = {"ds": {"d": 1, "s": -1, "g": 0, "b": 0},
           "gs": {"g": 1, "s": -1, "d": 0, "b": 0},
           "bs": {"b": 1, "s": -1, "d": 0, "g": 0}}
    ref = {}
    for row in "dgsb":
        if row == "b":
            f = {k: 0.0 for k in fd}
        elif row == "d":
            f = fd
        elif row == "g":
            f = fg
        else:
            f = {k: -(fd[k] + fg[k]) for k in fd}
        for col in "dgsb":
            ref[(row, col)] = sum(f[br] * dbr[br][col] for br in f)
    return ref


COEFF_I = (0.11, 0.23, 0.37, 0.13, 0.29)
COEFF_Q = (0.19e-12, 0.31e-12, 0.43e-12, 0.53e-12, 0.67e-12)
BIAS = {"d": 1.7, "g": 1.1, "s": 0.4, "b": 0.9}

for kind, coeffs, label, scale in (
        ("I", COEFF_I, "conductance dI/dV", 1.0),
        ("Q", COEFF_Q, "capacitance dQ/dV", 1e-12)):
    meas, log = terminal_matrix(kind, coeffs, BIAS)
    if meas is None:
        check(f"[matrix] 4x4 {label}", False, "(no result) " + log[:200])
        continue
    ref = matrix_reference(kind, coeffs, BIAS)
    worst, worst_at = 0.0, None
    for key in ref:
        e, g = ref[key], meas[key]
        d = abs(g - e) / max(abs(e), scale)   # absolute floor for the zero entries
        if d > worst:
            worst, worst_at = d, key
    check(f"[matrix] all 16 entries of the 4-terminal {label} "
          f"(incl. the KCL-derived source row and the zero body row)",
          worst < 1e-5,
          f"(worst reldiff {worst:.1e} at dI_{worst_at[0]}/dV_{worst_at[1]})")


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
