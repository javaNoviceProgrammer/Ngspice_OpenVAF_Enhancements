#!/usr/bin/env python3
"""openvaf-r math-identity simplifier audit (Enhancement-187).

The compiler's algebraic simplifier (`mir_opt/src/simplify.rs`) cancels
function-inverse pairs symbolically -- `f(g(x)) -> x` -- to avoid redundant
work. But a cancellation `f(g(x)) = x` is only valid when f is a true LEFT
INVERSE of g over ALL of g's range. Several cancellations were applied
UNCONDITIONALLY even though the outer function only returns PRINCIPAL values,
so they produced the WRONG VALUE (not just a wrong derivative -- the DC
operating point itself) for perfectly ordinary finite inputs:

  * asin(sin(x)) -> x   is wrong for |x| > pi/2   (asin(sin 3)   = pi-3 = 0.1416)
  * acos(cos(x)) -> x   is wrong for x not in [0,pi]  (acos(cos 4) = 2pi-4 = 2.283)
  * atan(tan(x)) -> x   is wrong for |x| > pi/2   (atan(tan 2)   = 2-pi = -1.1416)
                        -- and this is a legitimate angle-WRAP idiom the
                        optimizer silently defeated
  * acosh(cosh(x)) -> x is wrong for x < 0        (cosh is even: acosh(cosh -2) = 2)
  * sqrt(x*x)  -> x  and  sqrt(x**2) -> x   are |x|, wrong for x < 0

The const-fold path evaluates each op correctly; the bug was the SYMBOLIC
cancellation on runtime (bias-dependent) values. This suite compiles each law
`I = 1e-3*f(V)`, biases the node, and reads the DC current back -- the wrong
cancellation shows up directly as a wrong current.

The cancellations that ARE valid over the whole real line
(tan(atan), ln(exp), asinh(sinh), atanh(tanh), sinh(asinh), ...) are kept and
regression-checked here so the fix did not over-reach.

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
# A COMPILER property (identical under both linear solvers), so this runs once.

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def dc_value(name, expr, v0):
    """I(a,b) = expr; bias node a to v0 with an ideal source, read the single
    DC point i(vb) = -I(a,b). Returns (value, err)."""
    body = (f'`include "disciplines.vams"\n'
            f'module dut(a,b); inout a,b; electrical a,b;\n'
            f'analog I(a,b) <+ {expr};\n'
            f'endmodule\n')
    va = os.path.join(HERE, name + ".va")
    open(va, "w").write(body)
    r = subprocess.run([OPENVAF, va, "-o", os.path.join(HERE, name + ".osdi")],
                       capture_output=True, text=True, cwd=HERE)
    if r.returncode:
        return None, "COMPILE-FAIL: " + (r.stderr.strip().splitlines() or [""])[-1][:70]
    deck = (f"* {name}\nVb a 0 DC {v0}\nN1 a 0 dm\n.model dm dut\n"
            f".control\npre_osdi {name}.osdi\ndc Vb {v0} {v0} 1\nprint i(vb)\n.endc\n.end\n")
    open(os.path.join(HERE, name + ".cir"), "w").write(deck)
    out = subprocess.run([NGSPICE, "-b", name + ".cir"], capture_output=True,
                         text=True, cwd=HERE, timeout=60)
    txt = out.stdout + out.stderr
    m = re.search(r"i\(vb\)\s*=\s*([-\d.eE+]+)", txt)
    if not m:
        return None, "NO-DC"
    return -float(m.group(1)), None      # -i(vb) = I(a,b) = expr


def check_val(name, expr, v0, ref, label, tol=1e-4):
    # tol 1e-4 absorbs last-ULP differences between ngspice's (LLVM/libm) and
    # Python's transcendentals; the bugs under test were off by 75-2000%.
    v, err = dc_value(name, expr, v0)
    if err:
        check(label, False, err)
        return
    d = abs(v - ref) / (abs(ref) + 1e-30)
    check(label, d < tol, f"(got={v:.6e} correct={ref:.6e} reldiff={d:.1e})")


K = 1e-3
print("Enhancement-187: openvaf-r math-identity simplifier audit")

# ---- the four principal-value cancellations (were returning the raw inner x) ----
check_val("asin_sin", f"{K}*asin(sin(V(a,b)))", 3.0, K * math.asin(math.sin(3.0)),
          "[bug] asin(sin(3)) == pi-3, not 3 (principal value)")
check_val("acos_cos", f"{K}*acos(cos(V(a,b)))", 4.0, K * math.acos(math.cos(4.0)),
          "[bug] acos(cos(4)) == 2pi-4, not 4")
check_val("atan_tan", f"{K}*atan(tan(V(a,b)))", 2.0, K * math.atan(math.tan(2.0)),
          "[bug] atan(tan(2)) == 2-pi, not 2 (angle wrap preserved)")
check_val("acosh_cosh", f"{K}*acosh(cosh(V(a,b)))", -2.0, K * math.acosh(math.cosh(-2.0)),
          "[bug] acosh(cosh(-2)) == 2, not -2 (cosh is even)")

# ---- sqrt(x*x) and sqrt(x**2) are |x|, not x ----
check_val("sqrt_mul", f"{K}*sqrt(V(a,b)*V(a,b))", -3.0, K * abs(-3.0),
          "[bug] sqrt((-3)*(-3)) == 3, not -3 (abs)")
check_val("sqrt_pow", f"{K}*sqrt(pow(V(a,b),2))", -3.0, K * abs(-3.0),
          "[bug] sqrt((-3)**2) == 3, not -3 (abs)")
# and still correct for a positive argument (the fix left the sqrt in place)
check_val("sqrt_pos", f"{K}*sqrt(V(a,b)*V(a,b))", 4.0, K * 4.0,
          "[ok ] sqrt(4*4) == 4 (positive branch unaffected)")

# ---- regression: the globally-valid cancellations must STILL fire correctly ----
safe = [
    ("tan_atan", f"{K}*tan(atan(V(a,b)))", 5.0, K * 5.0, "tan(atan(5)) == 5"),
    ("ln_exp", f"{K}*ln(exp(V(a,b)))", 3.0, K * 3.0, "ln(exp(3)) == 3"),
    ("asinh_sinh", f"{K}*asinh(sinh(V(a,b)))", 2.0, K * 2.0, "asinh(sinh(2)) == 2"),
    ("atanh_tanh", f"{K}*atanh(tanh(V(a,b)))", 1.0, K * 1.0, "atanh(tanh(1)) == 1"),
    ("sinh_asinh", f"{K}*sinh(asinh(V(a,b)))", 0.6, K * 0.6, "sinh(asinh(0.6)) == 0.6"),
]
for nm, ex, v0, ref, lbl in safe:
    check_val(nm, ex, v0, ref, "[safe] " + lbl)

# tidy generated files
import glob
for pat in ("*.va", "*.osdi", "*.cir"):
    for g in glob.glob(os.path.join(HERE, pat)):
        if os.path.basename(g) not in ("wrap_demo.va", "wrap_demo.cir"):
            try:
                os.remove(g)
            except OSError:
                pass

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
