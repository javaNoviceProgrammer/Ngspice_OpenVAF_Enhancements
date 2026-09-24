#!/usr/bin/env python3
"""Enhancement-489: `pow` and `**` join the constant-domain guard `sqrt` already had.

Enhancement-455 refuses a CONSTANT argument outside a function's domain --
`sqrt(-1.0)`, `ln(0.0)`, `asin(2.0)` and four more -- because the fold produces a
NaN that reaches the user not as a compiler message but as

    Error: Transient op failed, timestep too small

a convergence complaint for a NaN written literally in the source. `pow` was left
out of that list, and `pow(-2.0, 0.5)` IS `sqrt(-2.0)`: same operation, same NaN,
same misleading run-time failure. Measured before the fix, it compiled clean and
produced exactly that message.

TWO SPELLINGS, TWO CODE PATHS. `pow(x,y)` resolves to `BuiltIn::pow` and is judged
in the call handler; `x ** y` is `BinaryOp::Power` and never goes near it. The
first version of this fix guarded only the call form and `(-2.0)**0.5` still
compiled. Judging one spelling of an operation and not the other is precisely how
two siblings drift apart, so both are judged here, on one rule. Checks [1]-[6].

THE INTEGER OPERATION IS A DIFFERENT OPERATION, AND THIS IS THE TRAP. `**` on two
integers is IEEE 1364-2005 Table 5-6, implemented by Enhancement-420, where a
negative exponent is fully defined: `2 ** -1` is 0, `-1 ** -3` is -1, `1 ** -5` is
1, and a base of 0 is `'x`, which is 0 in an integer context. Those are correct
answers, not NaNs. The first version of this arm judged them by the REAL domain
rule and rejected valid models -- vafdegen_examples went from 91/91 to failing ten
checks, which is how the mistake was found. Checks [7]-[11] hold that line from the
other side, and they FAIL against a guard that forgets to test the operand type.

WHAT IS DELIBERATELY NOT GUARDED, so a later pass does not "extend" this:
  * a RUN-TIME base or exponent -- E-455's stated convention, unchanged here.
  * an overridable `parameter` -- same convention: it may be overridden, so its
    default is not judged. A `localparam` IS judged, because Enhancement-479
    taught `const_num` to see one; this guard inherits that for free.
  * `pow(-2.0, 3.0)` and `pow(-2.0, -3.0)` -- a negative base with an INTEGER
    exponent has a real root and is ordinary arithmetic.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_pg_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    shutil.rmtree(d, ignore_errors=True)
    return r.returncode, out


def model(expr, decl="", vtype="real"):
    return (HDR + "module pg(a,b);\n  inout a,b; electrical a,b;\n" + decl +
            "  analog begin : blk\n    " + vtype + " t;\n    t = " + expr + ";\n"
            "    I(a,b) <+ t*V(a,b);\n  end\nendmodule\n")


def rejected(label, expr, tag, needle, decl="", vtype="real"):
    rc, out = build(model(expr, decl, vtype), tag)
    check(label, rc != 0 and needle in out and "panicked" not in out,
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:70])


def accepted(label, expr, tag, decl="", vtype="real"):
    rc, out = build(model(expr, decl, vtype), tag)
    check(label, rc == 0 and "error" not in out,
          f"rc={rc} " + (out.strip().splitlines() or [""])[0][:66])


print("Enhancement-489: the constant-domain guard reaches pow and **\n")

print("both spellings of the same operation are judged")
rejected("[1] pow(-2.0, 0.5) -- a negative base with a fractional exponent is sqrt(-2)",
         "pow(-2.0,0.5)", "p1", "outside the domain of pow")
rejected("[2] (-2.0) ** 0.5 -- the OPERATOR spelling, a different code path",
         "(-2.0)**0.5", "p2", "outside the domain of **")
rejected("[3] pow(0.0, -1.0) -- a zero base with a negative exponent is 1/0",
         "pow(0.0,-1.0)", "p3", "the result would be infinite")
rejected("[4] 0.0 ** (-1.0) -- likewise, as an operator",
         "0.0**(-1.0)", "p4", "the result would be infinite")

print("\n...and a localparam is seen, inherited from Enhancement-479")
rejected("[5] a localparam BASE", "nb**0.5", "p5",
         "outside the domain of **", decl="  localparam real nb = -2.0;\n")
rejected("[6] a localparam EXPONENT", "(-2.0)**ex", "p6",
         "outside the domain of **", decl="  localparam real ex = 0.5;\n")

print("\nthe INTEGER operation is Table 5-6 and must be left alone")
print("  (these FAIL against a guard that forgets to test the operand type)")
accepted("[7] integer 2 ** -1   -- Table 5-6 says 0, not NaN", "2**(-1)", "i1", vtype="integer")
accepted("[8] integer 0 ** -1   -- 'x, which is 0 in an integer context",
         "0**(-1)", "i2", vtype="integer")
accepted("[9] integer -1 ** -3  -- Table 5-6 says -1", "(-1)**(-3)", "i3", vtype="integer")
accepted("[10] integer 1 ** -5  -- Table 5-6 says 1", "1**(-5)", "i4", vtype="integer")
accepted("[11] integer 7 ** -2  -- Table 5-6 says 0", "7**(-2)", "i5", vtype="integer")

print("\nordinary real arithmetic must still compile")
accepted("[12] pow(-2.0, 3.0)  -- integer exponent, a real root exists", "pow(-2.0,3.0)", "o1")
accepted("[13] pow(-2.0, -3.0) -- likewise negative", "pow(-2.0,-3.0)", "o2")
accepted("[14] pow(2.0, 0.5)   -- positive base", "pow(2.0,0.5)", "o3")
accepted("[15] 0.0 ** 2.0      -- zero base, positive exponent", "0.0**2.0", "o4")
accepted("[16] 2.0 ** 3.0      -- ordinary", "2.0**3.0", "o5")

print("\na value the compiler cannot pin down stays the model's own business")
accepted("[17] a RUN-TIME base", "pow(V(a,b),0.5)", "r1")
accepted("[18] an overridable parameter base -- it may be overridden",
         "p**0.5", "r2", decl="  parameter real p = -2.0;\n")

print("\nEnhancement-706: constant arithmetic that is not a number (robustness campaign F6 of 2026-09-23)")
print("  the undefined quotient and the overflowing call are refused where they are born")
rejected("[19] 0.0/0.0 -- folded to NaN in silence, and the NaN then passed every constant-argument check",
         "V(a,b)*(0.0/0.0)", "n1", "the quotient is undefined; the result would be NaN")
rejected("[20] exp(1000.0) -- inside the domain, past the largest double",
         "exp(1000.0)", "n2", "exp exceeds the largest double")
accepted("[21] exp(700.0) is finite", "exp(700.0)*1e-300", "n3")
rejected("[22] cosh(1000.0)", "cosh(1000.0)", "n4", "cosh exceeds the largest double")
rejected("[23] pow(10.0, 400.0)", "pow(10.0,400.0)", "n5", "pow exceeds the largest double")
rejected("[24] 10.0 ** 400.0 -- the operator spelling", "10.0**400.0", "n6", "** exceeds the largest double")
accepted("[25] pow(10.0, 300.0) is finite", "pow(10.0,300.0)*1e-300", "n7")

print("\n  an infinity is a value (Enhancement-333 left IEEE's 1.0/0.0 to the model); its consumer judges it")
accepted("[26] 1.0/0.0 in an expression stays legal", "(1.0/0.0 > 1e300) ? 1.0 : 0.0", "n8")
accepted("[27] V(a,b)/0.0 -- a run-time dividend over a literal zero is IEEE arithmetic", "V(a,b)/0.0", "n9")
rejected("[28] absdelay(V, 1.0/0.0) -- the infinity now folds, and the delay must be finite",
         "absdelay(V(a,b), 1.0/0.0)", "n10", "the delay must be a finite number, but is inf")
rejected("[29] absdelay(V, 1.0/z) with a localparam zero is the same infinity",
         "absdelay(V(a,b), 1.0/z)", "n11", "the delay must be a finite number, but is inf",
         decl="  localparam real z = 0.0;\n")
accepted("[30] absdelay(V, 1.0/z) with an overridable parameter is the deck's business",
         "absdelay(V(a,b), 1.0/z)", "n12", decl="  parameter real z = 0.0;\n")
rejected("[31] parameter real q = 1.0/0.0 -- Enhancement-640's rule, reached at last",
         "V(a,b)*q", "n13", "overflows to infinity", decl="  parameter real q = 1.0/0.0;\n")
rejected("[32] absdelay(V, 1e308*10) -- was 'must not be negative, but is inf'",
         "absdelay(V(a,b), 1e308*10)", "n14", "the delay must be a finite number, but is inf")

print("\n  ...and the NaN no longer reaches the argument checks")
rejected("[33] absdelay(V, 0.0/0.0) -- a NaN delay was a zero delay at run time",
         "absdelay(V(a,b), 0.0/0.0)", "n15", "the quotient is undefined")
rejected("[34] a NaN parameter range bound, from [0.0/0.0:1]", "V(a,b)*q", "n16",
         "the quotient is undefined", decl="  parameter real q = 1 from [0.0/0.0:1];\n")
rejected("[35] laplace_nd(V, '{1}, '{1, 0.0/0.0}) -- refused before the run time could call it zero",
         "laplace_nd(V(a,b), '{1}, '{1, 0.0/0.0})", "n17", "the quotient is undefined")

print("\n  the two siblings keep their own sentences")
rejected("[36] integer 1/0 is Enhancement-333's", "1/0", "n18", "integer division by zero", vtype="integer")
rejected("[37] 1.0 % 0.0 is Enhancement-578's", "1.0 % 0.0", "n19", "LRM 4.2.4 makes an error")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
