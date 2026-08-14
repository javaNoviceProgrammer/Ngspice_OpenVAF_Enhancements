#!/usr/bin/env python3
"""Enhancement-455: seven ways a bad value was accepted, or crashed the compiler.

Found in a round-46 sweep of openvaf-r. They share one shape -- a check that
exists, and a neighbouring spelling of the same mistake that walks past it.

  * INDEXING A SCALAR PANICKED. `r[0]` on a real, `i[0]` on an integer, `s[0]`
    on a string, `p[0]` on a scalar parameter: inference marked the expression
    an error but pushed no diagnostic, so lowering reached
    `panic!("invalid HIR: path .. was not resolved")` -- exit 101, a crash
    banner and a request to open a GitHub issue, for an ordinary typo. All
    fifteen scalar/index combinations did it, in expression and
    assignment-target position alike.

  * THE VALUE GUARDS WERE LITERAL-ONLY. `const_num` folded a literal and a
    unary minus and nothing else, so every guard caught one spelling and missed
    the identical value written as an expression:

        white_noise(-1e-18)   -> refused
        white_noise(0-1e-18)  -> ACCEPTED, and produced exactly the output
                                 noise of the positive power, silently

    It was not even consistent inside the compiler: the array-bounds and
    integer-division checks fold first and DO catch `arr[2+3]` and `1/(1-1)`.

  * REVERSED RANGES SPELLED WITH `inf` WERE INVISIBLE. `from (5:1)` is refused;
    `from (inf:0)` -- one transposition from `from (0:inf)` -- was accepted and
    then enforced NOTHING: -5, 0 and 5 all pass a range that admits no value.
    `inf` is a literal token that the bound folder had no case for.

  * A CONSTANT OUTSIDE A FUNCTION'S DOMAIN said nothing. `sqrt(-1.0)`,
    `ln(-1.0)`, `asin(2.0)` folded to NaN with no diagnostic, and the model
    then failed at simulation with "Transient op failed, timestep too small" --
    a convergence message for a NaN written in the source. Integer `1/0` and
    `5 % 0` have always been compile errors.

  * `$rdist_uniform` WITH REVERSED BOUNDS returned what the correct ordering
    returns. LRM 9.13.2: "The start value shall be smaller than the end value."

  * AN ANALOG FUNCTION WITH NO ARGUMENTS compiled. LRM 4.7.1: a function "shall
    have at least one formal argument declared".

  * A DISCIPLINE NAMING ONE NATURE FOR BOTH `potential` AND `flow` compiled,
    and produced a device that contributed nothing where its well-formed twin
    gave the right answer -- and a node voltage of -999 when a contribution was
    forced.

A PARAMETER is deliberately still not folded into any of these checks. Its
default may be overridden on the instance or model card, so refusing a model for
a default that will never be used would be wrong -- the same reasoning that
keeps a parameter's default out of its own range check.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
WORK = tempfile.gettempdir()
H = '`include "disciplines.vams"\n'
M = "module m(a,b); inout a,b; electrical a,b;\n"
TAIL = " I(a,b) <+ V(a,b)*1e-3; end\nendmodule\n"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(text, tag):
    src = os.path.join(WORK, f"_vg_{tag}.va")
    osdi = os.path.join(WORK, f"_vg_{tag}.osdi")
    with open(src, "w") as f:
        f.write(text)
    r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr), (osdi if r.returncode == 0 else None)


def crashed(rc, out):
    """Enhancement-28: the panic hook exits 101 and prints a banner; the word
    'panicked' never appears, so rc and the banner are what identify a crash."""
    return rc == 101 or "has crashed" in out or "open an issue" in out


def expect(label, text, tag, reject):
    rc, out, _ = compile_va(text, tag)
    ok = (rc != 0) if reject else (rc == 0)
    detail = ""
    if not ok:
        first = [l for l in out.splitlines() if "error" in l.lower()]
        detail = first[0][:64] if first else f"rc={rc}"
    check(label, ok, detail)
    if reject:
        check(f"...{label} does not crash the compiler", not crashed(rc, out), f"rc={rc}")
    return rc, out


print("Enhancement-455: a guard, and the spelling next to it\n")

# ------------------------------------------------------- indexing a scalar ---
print("indexing a scalar is refused, not a crash")
for lbl, decl, ex in [
    ("a real", " real r;\n", "r[0]"),
    ("an integer", " integer i;\n", "i[0]"),
    ("a string", " string s;\n", "s[0]"),
    ("a scalar parameter", " parameter real p = 1.0;\n", "p[0]"),
    ("a real, runtime index", " real r; integer k;\n", "r[k]"),
    ("a real, two indices", " real r;\n", "r[0][0]"),
]:
    expect(f"[E-455] indexing {lbl}",
           H + M + decl + ' (* desc="d" *) real d;\n analog begin d = ' + ex + ";" + TAIL,
           "ix" + re.sub(r"\W", "", lbl)[:8], reject=True)
expect("[E-455] indexing a scalar as an assignment TARGET",
       H + M + " real r;\n analog begin r[0] = 1.0;" + TAIL, "ixasg", reject=True)

print("\n...while real arrays keep working (controls)")
expect("[E-455] a real array, constant index",
       H + M + ' real arr[0:2];\n (* desc="d" *) real d;\n analog begin arr[0]=1.0; d = arr[0];' + TAIL,
       "ok1", reject=False)
expect("[E-455] a real array, runtime index",
       H + M + ' real arr[0:2]; integer k;\n (* desc="d" *) real d;\n analog begin k=1; arr[k]=1.0; d = arr[k];' + TAIL,
       "ok2", reject=False)
expect("[E-455] a parameter array",
       H + M + ' parameter real pa[0:2] = \'{1.,2.,3.};\n (* desc="d" *) real d;\n analog begin d = pa[1];' + TAIL,
       "ok3", reject=False)

# ------------------------------------- the same bad value, spelled two ways ---
print("\na guard catches the value however it is written")
GUARDS = [
    ("white_noise power", "I(a,b) <+ white_noise(-1e-18);", "I(a,b) <+ white_noise(0-1e-18);",
     "I(a,b) <+ white_noise(1e-18*2);"),
    ("$bound_step", "$bound_step(0);", "$bound_step(1-1);", "$bound_step(2-1);"),
    ("transition rise time", "I(a,b) <+ transition(V(a,b),0,-1n,1n);",
     "I(a,b) <+ transition(V(a,b),0,0-1n,1n);", "I(a,b) <+ transition(V(a,b),0,2n-1n,1n);"),
    ("@(cross) direction", '@(cross(V(a,b)-0.5, 7)) $strobe("c");',
     '@(cross(V(a,b)-0.5, 3+4)) $strobe("c");', '@(cross(V(a,b)-0.5, 1-2)) $strobe("c");'),
    ("idtmod modulus", "I(a,b) <+ idtmod(V(a,b),0.0,0.0);",
     "I(a,b) <+ idtmod(V(a,b),0.0,2-2);", "I(a,b) <+ idtmod(V(a,b),0.0,1+1);"),
    ("slew rate", "I(a,b) <+ slew(V(a,b),-1e6,-1e6);",
     "I(a,b) <+ slew(V(a,b),0-1e6,-1e6);", "I(a,b) <+ slew(V(a,b),1e6,-1e6);"),
]
for name, lit, expr, good in GUARDS:
    t = re.sub(r"\W", "", name)[:9]
    expect(f"[E-455] {name}: the literal is refused",
           H + M + " analog begin " + lit + TAIL, "l" + t, reject=True)
    expect(f"[E-455] {name}: the same value as an EXPRESSION is refused",
           H + M + " analog begin " + expr + TAIL, "e" + t, reject=True)
    expect(f"[E-455] {name}: a valid constant expression still compiles",
           H + M + " analog begin " + good + TAIL, "g" + t, reject=False)

print("\na parameter default is deliberately NOT folded into these checks")
expect("[E-455] a negative rise time from a parameter default still compiles",
       H + M + " parameter real p = -1e-9;\n analog begin I(a,b) <+ transition(V(a,b),0,p,1n);" + TAIL,
       "pdef", reject=False)

# ----------------------------------------------------------- range bounds ---
print("\nreversed ranges are caught in every spelling, including inf")
for rng in ["(5:1)", "[5:1]", "(1:0)", "(inf:0)", "(0:-inf)", "(inf:-inf)",
            "[inf:-inf]", "(-inf:-inf)", "(inf:inf)"]:
    expect(f"[E-455] from {rng} is refused",
           H + M + f" parameter real q = 0.5 from {rng};\n analog begin" + TAIL,
           "r" + re.sub(r"\W", "", rng), reject=True)
for rng in ["(0:inf)", "[0:inf)", "(-inf:inf)", "(-inf:0)", "[-inf:inf]", "(0:1)", "[1:1]"]:
    expect(f"[E-455] from {rng} still compiles",
           H + M + f" parameter real q = 0.5 from {rng};\n analog begin" + TAIL,
           "s" + re.sub(r"\W", "", rng), reject=False)

# a range that IS accepted must still be enforced at run time
rc, out, osdi = compile_va(
    H + "module m(a,b); inout a,b; electrical a,b;\n parameter real p = 0.5 from (0:inf);\n"
    " analog I(a,b) <+ V(a,b)*p;\nendmodule\n", "enf")
if check("[E-455] a model with from (0:inf) compiles", osdi is not None):
    deck = os.path.join(WORK, "_vg_enf.cir")
    with open(deck, "w") as f:
        f.write(f"""* range enforcement
V1 in 0 dc 1
Rs in mid 1k
N1 mid 0 mm
.model mm m p=-1
.control
pre_osdi {osdi}
op
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True,
                       timeout=300, stdin=subprocess.DEVNULL)
    check("[E-455] ...and an out-of-range value is still refused at run time",
          "out of bounds" in (r.stdout + r.stderr))

# ------------------------------------------------------------- math domain ---
print("\na constant outside a function's domain is reported")
for name, bad, good in [("sqrt", "sqrt(-1.0)", "sqrt(2.0)"), ("ln", "ln(-1.0)", "ln(1.0)"),
                        ("log", "log(-1.0)", "log(10.0)"), ("asin", "asin(2.0)", "asin(0.5)"),
                        ("acos", "acos(2.0)", "acos(0.5)"), ("acosh", "acosh(0.5)", "acosh(2.0)"),
                        ("atanh", "atanh(2.0)", "atanh(0.5)")]:
    expect(f"[E-455] {bad} is refused",
           H + M + ' (* desc="d" *) real d;\n analog begin d = ' + bad + ";" + TAIL,
           "m" + name, reject=True)
    expect(f"[E-455] {good} still compiles",
           H + M + ' (* desc="d" *) real d;\n analog begin d = ' + good + ";" + TAIL,
           "n" + name, reject=False)
expect("[E-455] ln(0.0) is refused", H + M + ' (* desc="d" *) real d;\n analog begin d = ln(0.0);' + TAIL,
       "mln0", reject=True)
expect("[E-455] a RUNTIME argument is left alone",
       H + M + ' (* desc="d" *) real d;\n analog begin d = sqrt(V(a,b));' + TAIL, "mrt", reject=False)

# ----------------------------------------------------------- $rdist_uniform ---
print("\n$rdist_uniform bounds (LRM 9.13.2: start shall be smaller than end)")
expect("[E-455] reversed bounds are refused",
       H + M + ' (* desc="d" *) real d; integer sd;\n analog begin sd=7; d = $rdist_uniform(sd,5.0,1.0);' + TAIL,
       "u1", reject=True)
expect("[E-455] equal bounds are refused",
       H + M + ' (* desc="d" *) real d; integer sd;\n analog begin sd=7; d = $rdist_uniform(sd,3.0,3.0);' + TAIL,
       "u2", reject=True)
expect("[E-455] correct bounds still compile",
       H + M + ' (* desc="d" *) real d; integer sd;\n analog begin sd=7; d = $rdist_uniform(sd,1.0,5.0);' + TAIL,
       "u3", reject=False)

# ------------------------------------------------------- function arity -----
print("\nan analog function declares at least one argument (LRM 4.7.1)")
expect("[E-455] a zero-argument function is refused",
       H + M + "analog function real f;\n begin f = 7.0; end\nendfunction\n"
       ' (* desc="r" *) real r;\n analog begin r = f();' + TAIL, "f0", reject=True)
expect("[E-455] one argument still compiles",
       H + M + "analog function real f;\n input x; real x;\n begin f = x; end\nendfunction\n"
       ' (* desc="r" *) real r;\n analog begin r = f(1.0);' + TAIL, "f1", reject=False)
expect("[E-455] an ANSI-style argument still compiles",
       H + M + "analog function real f(real x);\n begin f = x; end\nendfunction\n"
       ' (* desc="r" *) real r;\n analog begin r = f(1.0);' + TAIL, "f2", reject=False)

# ---------------------------------------------------------------- discipline ---
print("\npotential and flow must be different natures")
NAT = 'nature zn; units="X"; access=Zp; abstol=1e-12; endnature\n'
NAT2 = 'nature zf; units="Y"; access=Zf; abstol=1e-15; endnature\n'
BODY = "module m(a,b); inout a,b; zd a,b;\n analog Zp(a,b) <+ 1.0;\nendmodule\n"
expect("[E-455] one nature for both is refused",
       H + NAT + "discipline zd; potential zn; flow zn; enddiscipline\n" + BODY, "d1", reject=True)
expect("[E-455] two distinct natures still compile",
       H + NAT + NAT2 + "discipline zd; potential zn; flow zf; enddiscipline\n" + BODY, "d2", reject=False)
expect("[E-455] potential alone still compiles",
       H + NAT + "discipline zd; potential zn; enddiscipline\n" + BODY, "d3", reject=False)
expect("[E-455] the built-in electrical discipline is untouched",
       H + M + " analog I(a,b) <+ V(a,b)*1e-3;\nendmodule\n".replace("endmodule\nendmodule", "endmodule"),
       "d4", reject=False)

for junk in os.listdir(WORK):
    if junk.startswith("_vg_"):
        try:
            os.remove(os.path.join(WORK, junk))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
