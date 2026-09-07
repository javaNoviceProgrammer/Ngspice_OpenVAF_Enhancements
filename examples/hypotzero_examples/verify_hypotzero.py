#!/usr/bin/env python3
"""
verify_hypotzero.py -- the 2026-09-07 bug hunt's F1
(docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md), fixed by Enhancement-580.

`hypot(x, y)` had the derivative rule (x*x' + y*y') / hypot(x, y), which is 0/0 = NaN
when both arguments are zero -- and V = 0 is ngspice's DC initial guess, so a model
that takes hypot of node quantities failed every operating-point method (gmin stepping,
source stepping, the transient op) on its very first Newton iteration, while abs, sqrt
and pow at zero were guarded already. atan2 had the same singularity one step further:
1/(x^2+y^2) = +inf multiplied by (x'*y - y'*x) = 0. Both caches are regularised the way
sqrt's was (Enhancement-261): hypot(hypot(x,y), 1e-18) and 1/(x^2+y^2+1e-36), finite at
the origin and below the ULP everywhere else.

  [1] operating point at the origin: hypot(V,0), hypot(Va,Vb), atan2(Vb,Va), and their
      sum, each as a contribution, solve at V = 0 (the shipped compiler fails all four
      with "The operating point could not be simulated successfully")
  [2] the derivatives away from the origin are the analytic ones, unchanged: at
      (0.3, 0.4), d hypot/dx = x/h = 0.6, d atan2(y,x)/dx = -y/(x^2+y^2) = -1.6, and the
      Jacobian of the sum is their sum; at (0.5, 0) hypot(V,0) has slope 1
  [3] the neighbours still behave: abs(V) at 0 has slope 1, sqrt(V*V) at 0 slope 0,
      sqrt(V) at 0 a large finite slope, and a transient through the origin runs
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

ok_all = True
n_pass = 0
n_total = 0


def check(label, cond, detail=""):
    global ok_all, n_pass, n_total
    n_total += 1
    n_pass += bool(cond)
    ok_all = ok_all and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")


def compile_va(name, text):
    with open(os.path.join(HERE, name + ".va"), "w") as fh:
        fh.write(text)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TERM="dumb")
    r = subprocess.run([OPENVAF, name + ".va", "-o", name + ".osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, r.stdout + r.stderr


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=300)
    return r.stdout + r.stderr


def lets(out):
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"^(\w+) = (\S+)", out, re.M)}


MOD = '''`include "disciplines.vams"
module two(a,b,n); inout a,b,n; electrical a,b,n;
(* type="instance" *) parameter integer sel=1;
real x, y, f;
analog begin
  x = V(a,n); y = V(b,n);
  case (sel)
    1: f = hypot(x, 0.0);
    2: f = hypot(x, y);
    3: f = atan2(y, x);
    4: f = hypot(x, y) + atan2(y, x);
    5: f = abs(x);
    6: f = sqrt(x*x);
    7: f = sqrt(x);
    default: f = x + y;
  endcase
  I(a,n) <+ f * 1e-3;
end
endmodule
'''
rc, log = compile_va("two", MOD)
check("two.va compiles", rc == 0, log.strip().splitlines()[0] if rc else "")


def run(sel, x, y, tran=False):
    ctl = ("tran 10n 2u\nlet np = length(time)\nprint np\n" if tran else
           "op\nac lin 1 1k 1k\nlet ga = mag(i(va))\nlet pa = 180/pi*ph(i(va))\nprint ga pa\n")
    src = "pulse(-0.5 0.5 0.5u 10n 10n 1u 2u)" if tran else f"dc {x} ac 1"
    out = ngspice(f"* hypotzero\n.model m two\nVa a 0 {src}\nVb b 0 dc {y}\nN1 a b 0 m sel={sel}\n"
                  f".control\nset numdgt=10\npre_osdi two.osdi\n{ctl}quit\n.endc\n.end\n")
    return ("could not be simulated" in out or "timestep too small" in out), lets(out)


print("[1] operating point at the origin")
for sel, why in [(1, "hypot(V, 0)"), (2, "hypot(Va, Vb)"), (3, "atan2(Vb, Va)"), (4, "hypot + atan2")]:
    failed, v = run(sel, 0, 0)
    check(f"{why} solves at (0, 0) with a finite, zero small-signal conductance",
          not failed and v.get("ga") == 0.0, "op failed" if failed else v)

print("[2] derivatives away from the origin are the analytic ones")
tol = 1e-9
failed, v = run(2, 0.3, 0.4)
check("d hypot(x,y)/dx at (0.3,0.4) = x/h = 0.6", not failed and abs(v.get("ga", 0) - 6e-4) < tol and abs(v.get("pa", 0) - 180) < 1e-6, v)
failed, v = run(3, 0.3, 0.4)
check("d atan2(y,x)/dx at (0.3,0.4) = -y/(x^2+y^2) = -1.6", not failed and abs(v.get("ga", 0) - 1.6e-3) < tol and abs(v.get("pa", 0)) < 1e-6, v)
failed, v = run(4, 0.3, 0.4)
check("the sum's Jacobian is the sum: 0.6 - 1.6 = -1.0", not failed and abs(v.get("ga", 0) - 1e-3) < tol and abs(v.get("pa", 0)) < 1e-6, v)
failed, v = run(1, 0.5, 0)
check("d hypot(x,0)/dx at 0.5 = 1", not failed and abs(v.get("ga", 0) - 1e-3) < tol, v)
failed, v = run(2, 1e-6, 2e-6)
check("d hypot/dx at a 1e-6 radius is x/h = 0.4472 (the regularisation is below the ULP there)",
      not failed and abs(v.get("ga", 0) - 1e-3 * (1e-6 / (5e-12 ** 0.5))) < 1e-12, v)

print("[3] the neighbours")
failed, v = run(5, 0, 0)
check("abs(V) at 0: slope 1 (unchanged)", not failed and abs(v.get("ga", 0) - 1e-3) < tol, v)
failed, v = run(6, 0, 0)
check("sqrt(V*V) at 0: slope 0 (unchanged)", not failed and v.get("ga") == 0.0, v)
failed, v = run(7, 0, 0)
check("sqrt(V) at 0: a large finite slope (the E-261 guard, unchanged)", not failed and 1e4 < v.get("ga", 0) < 1e9, v)
failed, v = run(2, 0, 0, tran=True)
check("a transient of hypot(Va, Vb) sweeping Va through the origin runs", not failed and v.get("np", 0) > 100, v)
failed, v = run(4, 0, 0, tran=True)
check("...and one of hypot + atan2", not failed and v.get("np", 0) > 100, v)

for f in ("two.va", "two.osdi", "_o.cir"):
    try:
        os.remove(os.path.join(HERE, f))
    except OSError:
        pass
print(f"\n{'ALL PASS' if ok_all else 'SOME FAILED'}: {n_pass}/{n_total} checks passed")
sys.exit(0 if ok_all else 1)
