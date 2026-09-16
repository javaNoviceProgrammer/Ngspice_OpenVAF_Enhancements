#!/usr/bin/env python3
"""Enhancement-645: a parameter array is an array argument, and a paramset
binds an array parameter (2026-09-16 hunt, F1).

An array PARAMETER fed to an analog function's array formal -- LRM 4.7.1
Example 3's `input [0:1] b; real b[0:1];` with `parameter real c[0:1]` -- was
refused as "'c' requires a bit-select [i]" (a variable array passed), a size
mismatch got the same wrong message, and a paramset's `.c = '{...}` was
"a parameter the module does not declare". Now:

  * a parameter array binds an `input` array formal (1-D, N-D, integer), the
    Jacobian flows through it, and a card value for an element reaches the call;
  * a size mismatch says so ("array argument has 4 elements but the function's
    formal declares 3"); an `output`/`inout` formal fed a parameter array is
    refused by name (a parameter cannot receive the copy-back, LRM 4.7.2.2);
  * a paramset assigns an array parameter whole, `.c = '{10.0, 20.0, 30.0};`,
    each element taking the leaf at its own position; a literal of the wrong
    length, or a scalar, is refused; an element outside the declared range is
    refused by its element name; the paramset's own parameters may appear in
    the leaves (card and instance-line routes); the E-563 fold and a 2-D array
    work; a bound element can no longer be set from the card.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="paramarrayarg_")
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run(deck, ctl, tag, osdi):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* paramarrayarg {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\npre_osdi {osdi}.osdi\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def iv1(out):
    m = re.search(r"i\(v1\)\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


def near(x, ref, tol=1e-9):
    return x is not None and abs(x - ref) <= tol * max(1.0, abs(ref))


MOD = lambda name, body: f"module {name}(p,n); inout p,n; electrical p,n;\n{body}\nendmodule\n"
DECK = lambda model, extra="": f"v1 1 0 1\n.model {model} {model} {extra}\nna1 1 0 {model}"

# ---------------------------------------------------------------- functions
SUM3 = "analog function real sum3; input [0:2] a; real a[0:2]; sum3 = a[0]+a[1]+a[2]; endfunction\n"

ok, out = compile_src(MOD("fa", "parameter real c[0:2] = '{1.0, 2.0, 3.0};\n" + SUM3 + "analog I(p,n) <+ sum3(c) * V(p,n);"), "fa")
check("[1] a parameter array binds an input array formal", ok, out.strip().splitlines()[-1][:80] if not ok else "")
if ok:
    check("[2] the call sums the array (I = -6 A)", near(iv1(run(DECK("fa"), "op\nprint i(v1)", "fa", "fa")), -6.0))
    check("[3] a card value for one element reaches the call (c[1]=20, I = -24 A)",
          near(iv1(run(DECK("fa", "c[1]=20"), "op\nprint i(v1)", "fa2", "fa")), -24.0))

ok, out = compile_src(MOD("fb", "parameter real m[0:1][0:1] = '{'{1.0, 2.0}, '{3.0, 4.0}};\n"
                       "analog function real sum4; input [0:1][0:1] a; real a[0:1][0:1]; sum4 = a[0][0]+a[0][1]+a[1][0]+a[1][1]; endfunction\n"
                       "analog I(p,n) <+ sum4(m) * V(p,n);"), "fb")
check("[4] a 2-D parameter array binds a 2-D formal (I = -10 A)", ok and near(iv1(run(DECK("fb"), "op\nprint i(v1)", "fb", "fb")), -10.0))

ok, out = compile_src(MOD("fc", "parameter integer c[0:2] = '{1, 2, 3};\n"
                       "analog function integer isum; input [0:2] a; integer a[0:2]; isum = a[0]+a[1]+a[2]; endfunction\n"
                       "analog I(p,n) <+ isum(c) * V(p,n);"), "fc")
check("[5] an integer parameter array binds an integer formal (I = -6 A)", ok and near(iv1(run(DECK("fc"), "op\nprint i(v1)", "fc", "fc")), -6.0))

ok, out = compile_src(MOD("fd", "parameter real c[0:1] = '{1.0, 2.0};\n"
                       "analog function real poly; input [0:1] a; input x; real a[0:1], x; poly = a[0]*x + a[1]*x*x; endfunction\n"
                       "real g; analog begin g = ddx(poly(c, V(p,n)), V(p)); $strobe(\"dIdV=%g\", g); I(p,n) <+ poly(c, V(p,n)); end"), "fd")
o = run(DECK("fd"), "op\nprint i(v1)", "fd", "fd") if ok else ""
m = re.search(r"dIdV=([-+0-9.eE]+)", o)
check("[6] the derivative flows through the parameter-array argument (dI/dV = c0 + 2 c1 V = 5, I = -3 A)",
      ok and m is not None and near(float(m.group(1)), 5.0) and near(iv1(o), -3.0))

ok, out = compile_src(MOD("fe", SUM3 + "real c[0:3]; analog begin c[0]=1; c[1]=2; c[2]=3; c[3]=4; I(p,n) <+ sum3(c) * V(p,n); end"), "fe")
check("[7] a variable array of the wrong size is refused by size, not as a missing bit-select",
      not ok and "array argument has 4 elements but the function's formal declares 3" in out and "bit-select" not in out)

ok, out = compile_src(MOD("ff", "parameter real c[0:1] = '{1.0, 2.0};\n" + SUM3 + "analog I(p,n) <+ sum3(c) * V(p,n);"), "ff")
check("[8] a parameter array of the wrong size is refused by size",
      not ok and "array argument has 2 elements but the function's formal declares 3" in out)

ok, out = compile_src(MOD("fg", "parameter real c[0:1] = '{1.0, 2.0};\n"
                       "analog function real fill; output [0:1] y; input x; real y[0:1], x; begin y[0] = x; y[1] = x; fill = 0; end endfunction\n"
                       "real r; analog begin r = fill(c, 2.0); I(p,n) <+ V(p,n); end"), "fg")
check("[9] an output formal fed a parameter array is refused by name, once",
      not ok and "output argument bound to parameter array 'c', which cannot be written" in out and out.count("error:") == 2)

ok, out = compile_src(MOD("fh", "parameter real c[0:1] = '{1.0, 2.0};\n"
                       "analog function real add; inout [0:1] y; input x; real y[0:1], x; begin y[0] = y[0] + x; add = 0; end endfunction\n"
                       "real r; analog begin r = add(c, 2.0); I(p,n) <+ V(p,n); end"), "fh")
check("[10] an inout formal fed a parameter array is refused the same way",
      not ok and "output argument bound to parameter array 'c'" in out)

# ---------------------------------------------------------------- paramsets
BASE = lambda name, rng="": (f"module {name}(p,n); inout p,n; electrical p,n; parameter real c[0:2] = '{{1.0, 2.0, 3.0}} {rng}; parameter real r = 1;\n"
                             f"analog begin $strobe(\"c = %g %g %g r=%g\", c[0], c[1], c[2], r); I(p,n) <+ (c[0]+c[1]+c[2])*V(p,n)/r; end\nendmodule\n")

ok, out = compile_src(BASE("pa") + "paramset paps pa; .c = '{10.0, 20.0, 30.0}; endparamset\n", "pa")
check("[11] a paramset binds an array parameter whole", ok, out.strip().splitlines()[-1][:80] if not ok else "")
if ok:
    o = run(DECK("paps"), "op\nprint i(v1)", "pa", "pa")
    check("[12] every element takes its leaf (c = 10 20 30, I = -60 A)", "c = 10 20 30 r=1" in o and near(iv1(o), -60.0))
    o = run(DECK("paps", "c[1]=5"), "op\nprint i(v1)", "pa2", "pa")
    check("[13] a bound element is no longer settable from the card (warned, value kept)",
          "fixed (localparam)" in o and near(iv1(o), -60.0))

ok, out = compile_src(BASE("pb") + "paramset pbps pb; .c = '{10.0, 20.0}; endparamset\n", "pb")
check("[14] a literal of the wrong length is refused",
      not ok and "paramset assigns array parameter 'c' a value with 2 elements but the array has 3" in out)

ok, out = compile_src(BASE("pc") + "paramset pcps pc; .c = 5.0; endparamset\n", "pc")
check("[15] a scalar for an array is refused", not ok and "a value with 1 element but the array has 3" in out)

ok, out = compile_src(BASE("pd", "from [0:10]") + "paramset pdps pd; .c = '{1.0, 50.0, 3.0}; endparamset\n", "pd")
check("[16] an element outside the declared range is refused by its element name",
      not ok and "paramset assigns 'c[1]' the value 50, which its declared range [0:10] forbids" in out)

ok, out = compile_src(BASE("pe") + "paramset peps pe; parameter real k = 1; .c = '{k, 2*k, 3.0}; endparamset\n", "pe")
if check("[17] the paramset's own parameter may appear in the leaves", ok):
    o = run(DECK("peps", "k=2"), "op\nprint i(v1)", "pe", "pe")
    check("[18] ... from the card (k=2: c = 2 4 3, I = -9 A)", "c = 2 4 3" in o and near(iv1(o), -9.0))
    o = run(DECK("peps"), "op\nprint i(v1)\nalter @na1[k]=3\nop\nprint i(v1)", "pe2", "pe")
    vals = [float(x) for x in re.findall(r"i\(v1\)\s*=\s*([-+0-9.eE]+)", o)]
    check("[19] ... and from the instance line (E-644 route; alter k=3: I = -12 A)",
          len(vals) == 2 and near(vals[0], -6.0) and near(vals[1], -12.0) and "c = 3 6 3" in o)

ok, out = compile_src("module pf(p,n); inout p,n; electrical p,n; parameter real m[0:1][0:1] = '{'{1.0, 2.0}, '{3.0, 4.0}}; analog I(p,n) <+ (m[0][0]+m[0][1]+m[1][0]+m[1][1])*V(p,n); endmodule\n"
                      "paramset pfps pf; .m = '{'{10.0, 20.0}, '{30.0, 40.0}}; endparamset\n", "pf")
check("[20] a 2-D array is bound row-major (I = -100 A)", ok and near(iv1(run(DECK("pfps"), "op\nprint i(v1)", "pf", "pf")), -100.0))

ok, out = compile_src("module corner_x; localparam real rr = 7.0; endmodule\n" + BASE("pg")
                      + "paramset pgps pg; .c = '{10.0, 20.0, 30.0}; .r = corner_x.rr; endparamset\n", "pg")
o = run(DECK("pgps"), "op\nprint i(v1)", "pg", "pg") if ok else ""
check("[21] the E-563 fold (an out-of-module reference beside the array) keeps the binding (I = -60/7 A)",
      ok and "c = 10 20 30 r=7" in o and near(iv1(o), -60.0 / 7.0, 1e-6))

ok, out = compile_src("module ph(p,n); inout p,n; electrical p,n; localparam real c[0:1] = '{1.0, 2.0}; analog I(p,n) <+ (c[0]+c[1])*V(p,n); endmodule\n"
                      "paramset phps ph; .c = '{10.0, 20.0}; endparamset\n", "ph")
check("[22] a localparam array is refused as not a parameter, once",
      not ok and "paramset assigns 'c', which is not a parameter of 'ph'" in out and out.count("error:") == 2)

ok, out = compile_src(BASE("pi") + "paramset pips pi; .c = '{10.0, 20.0, 30.0}; .zz = 1; endparamset\n", "pi")
check("[23] an unknown name beside a bound array is still reported", not ok and "paramset assigns 'zz', which module 'pi' does not declare" in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
