#!/usr/bin/env python3
"""Enhancement-479: a check that only ever saw a literal.

Bug-hunt round 48. Every value guard in openvaf-r asked "is this argument a
number?" by looking at the SYNTAX of the argument, so it saw a literal and
nothing else. A `localparam` is a compile-time constant the LRM forbids from
being overridden -- the compiler knows its value exactly -- yet naming one made
every guard skip. The same bad value, three ways:

    white_noise(-1e-12)                          -> rejected
    white_noise(-1e-12*1.0)                      -> rejected (folding IS applied)
    localparam real q = -1e-12; white_noise(q)   -> ACCEPTED, silently

That gap reached nine operator guards, the `$rdist_*`/`analysis`/`$simparam`
name checks and the parameter-range emptiness check. It is not academic: models
name their constants, and a negative `transition` time supplied that way drove a
0->1 signal to -2.5 V and responded BEFORE the input edge, with rc=0 and no
diagnostic anywhere.

The same literal-only assumption sat in the compile-time table builder, where
the caller turned "cannot fold" into 0.0. One table, one value written two ways:

    $table_model(1.5, '{1.0,10.0, 2.0,20.0, 3.0,30.0}, "1L")  ->  15
    localparam real v2 = 20.0;
    $table_model(1.5, '{1.0,10.0, 2.0,v2  , 3.0,30.0}, "1L")  ->   5

-- a smooth, plausible, wrong curve. `noise_table` lost its noise entirely the
same way.

THE UNIT UNDER TEST IS THE AGREEMENT: [1]-[9] check that a literal and a named
constant holding the SAME value are treated the same, and [10]-[13] that a table
entry means the same thing however it is spelled.

WHAT IS DELIBERATELY NOT CHANGED, pinned here so a later round does not "fix" it:
  * A `parameter` is still not folded and its DEFAULT is still not policed. The
    model card may override it, so the declared value is not what the model runs
    with. [30]
  * `@(timer)` still accepts a period <= 0 and fires ONCE. LRM 5.10.3.3 says it
    "shall trigger only once at the specified start_time"; that is the spelling
    of a computed one-shot. [26]
  * `noise_table_log` still refuses a NEGATIVE power. It takes the same LINEAR
    (Hz, power) input as `noise_table` (LRM 4.6.4.4) and interpolates log-log,
    so a negative power has no logarithm. Only the diagnostic changed: it used
    to name "noise_table" for a `noise_table_log` call. [27][28]
  * `0.0 * NaN` still folds to 0 (Enhancement-337 keeps that fold deliberately:
    removing it moved HiSIM2's DC drain current by 10x). [29]
  * A real literal that UNDERFLOWS is still accepted silently. [31]
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.gettempdir()
H = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(text, tag):
    src = os.path.join(WORK, f"_cg_{tag}.va")
    osdi = os.path.join(WORK, f"_cg_{tag}.osdi")
    with open(src, "w") as f:
        f.write(text)
    r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr), (osdi if r.returncode == 0 else None)


def crashed(rc, out):
    """Enhancement-28: the panic hook exits 101 and prints a banner; the word
    'panicked' never appears, so rc and the banner are what identify a crash."""
    return rc == 101 or "has crashed" in out or "open an issue" in out


def sim(osdi, deck, ctl, tag, timeout=300):
    path = os.path.join(WORK, f"_cg_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* constguard {tag}\n{deck}\n.control\npre_osdi {osdi}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=timeout, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr)


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def rows(out):
    return [l.split() for l in out.splitlines() if re.match(r"^\d+\s", l.strip())]


print("Enhancement-479: a check that only ever saw a literal\n")

# ------------------------------------- [1]-[9] the guard layer sees a name ---
print("a guard treats a localparam like the literal holding the same value")
GUARDS = [
    ("$bound_step",   "$bound_step({V});",                             "real",    "-1e-9"),
    ("@(timer) start", "@(timer({V}, 2n)) z = 1.0;",                   "real",    "-1e-9"),
    ("@(cross) dir",  "@(cross(V(a,b)-1, {V})) z = 1.0;",              "integer", "7"),
    ("transition",    "I(a,b) <+ 1e-6*transition(V(a,b),0,{V},{V});",  "real",    "-1e-9"),
    ("absdelay",      "I(a,b) <+ 1e-6*absdelay(V(a,b),{V});",          "real",    "-1e-9"),
    ("zi_nd period",  "I(a,b) <+ 1e-6*zi_nd(V(a,b),'{{1.0}},'{{1.0}},{V},0.0);", "real", "-1e-5"),
    ("last_crossing", "I(a,b) <+ 1e-6*last_crossing(V(a,b)-1,{V});",   "integer", "7"),
    ("white_noise",   "I(a,b) <+ white_noise({V});",                   "real",    "-1e-12"),
    ("flicker_noise", "I(a,b) <+ flicker_noise({V},1.0);",             "real",    "-1e-12"),
]
for i, (label, body, ty, bad) in enumerate(GUARDS, start=1):
    lit = H + ("module m(a,b); inout a,b; electrical a,b; real z;\n analog begin\n  "
               + body.format(V=bad) + "\n  I(a,b) <+ 1e-3*V(a,b)*(1.0+1e-12*z);\n end\nendmodule\n")
    nm = "k"
    lp = H + (f"module m(a,b); inout a,b; electrical a,b; localparam {ty} {nm} = {bad}; real z;\n"
              " analog begin\n  " + body.format(V=nm)
              + "\n  I(a,b) <+ 1e-3*V(a,b)*(1.0+1e-12*z);\n end\nendmodule\n")
    rc_l, out_l, _ = compile_va(lit, f"lit{i}")
    rc_p, out_p, _ = compile_va(lp, f"lp{i}")
    check(f"[{i}] {label}: literal and localparam agree",
          rc_l != 0 and rc_p != 0, f"literal rc={rc_l}, localparam rc={rc_p}")
    check(f"...[{i}] and neither crashes the compiler",
          not crashed(rc_l, out_l) and not crashed(rc_p, out_p), "")

# ------------------------------- [10]-[13] a compile-time table entry ---------
print("\na table entry means the same thing however it is spelled")
TBL = H + """
module m(a,b); inout a,b; electrical a,b;
 parameter real xin = 1.5;
 localparam real v2 = 20.0;
 real y_named, y_literal, y_folded;
 analog begin
  y_named   = $table_model(xin, '{1.0,10.0,2.0,v2       ,3.0,30.0}, "1L");
  y_literal = $table_model(xin, '{1.0,10.0,2.0,20.0     ,3.0,30.0}, "1L");
  y_folded  = $table_model(xin, '{1.0,10.0,2.0,10.0*2.0 ,3.0,30.0}, "1L");
  $strobe("YN=%g YL=%g YF=%g", y_named, y_literal, y_folded);
  I(a,b) <+ 1e-3*V(a,b);
 end
endmodule
"""
rc, out, osdi = compile_va(TBL, "tbl")
if check("[10] the table module compiles", rc == 0, out.splitlines()[0][:60] if rc else ""):
    _, o = sim(osdi, "V1 q 0 dc 1\nN1 q 0 mm\n.model mm m(xin=1.5)", "op", "tbl")
    m = re.findall(r"YN=(\S+) YL=(\S+) YF=(\S+)", o)
    got = m[-1] if m else ("?", "?", "?")
    check("[11] $table_model: a NAMED entry reads as the literal does",
          got[0] == got[1] == "15", f"named={got[0]} literal={got[1]}")
    check("[12] ...and so does a folded expression entry",
          got[2] == "15", f"folded={got[2]}")

NT = H + """
module m(a,b); inout a,b; electrical a,b;
 localparam real q = 1e-12;
 analog I(a,b) <+ 1e-3*V(a,b) + noise_table('{1.0, q, 1e6, q});
endmodule
"""
rc, out, osdi = compile_va(NT, "nt")
NT_LIT = H + ("module m(a,b); inout a,b; electrical a,b;\n"
              " analog I(a,b) <+ 1e-3*V(a,b) + noise_table('{1.0, 1e-12, 1e6, 1e-12});\nendmodule\n")
rc2, _, osdi2 = compile_va(NT_LIT, "ntl")
if rc == 0 and rc2 == 0:
    deck = "V1 in 0 dc 0 ac 1\nR1 in q 1k\nN1 q 0 mm\n.model mm m()"
    ctl = "noise v(q) v1 dec 5 1 1k\nprint onoise_total"
    _, a = sim(osdi, deck, ctl, "nt")
    _, b = sim(osdi2, deck, ctl, "ntl")
    va, vb = val(a, "onoise_total"), val(b, "onoise_total")
    check("[13] noise_table: a NAMED entry gives the literal table's noise",
          va is not None and vb is not None and abs(va - vb) < 1e-12 and va > 1e-3,
          f"named={va} literal={vb}")

# ------------------------------------------------------- [14] abs(-0.0) ------
print("\nabs() agrees with the compiler's own constant folding")
ABS = H + """
module m(a,b); inout a,b; electrical a,b;
 parameter real x = -0.0;
 localparam real folded = 1.0/abs(-0.0);
 real generated;
 analog begin
  generated = 1.0/abs(x);
  $strobe("F=%g G=%g", folded, generated);
  I(a,b) <+ 1e-3*V(a,b);
 end
endmodule
"""
rc, out, osdi = compile_va(ABS, "abs")
if rc == 0:
    _, o = sim(osdi, "V1 q 0 dc 1\nN1 q 0 mm\n.model mm m(x=-0.0)", "op", "abs")
    m = re.findall(r"F=(\S+) G=(\S+)", o)
    got = m[-1] if m else ("?", "?")
    check("[14] 1/abs(-0.0) is +inf in BOTH the folded and generated paths",
          got == ("inf", "inf"), f"folded={got[0]} generated={got[1]}")

# ----------------------------------------- [15]-[23] guards that were absent --
print("\nguards that did not exist at all")
ABSENT = [
    ("[15] $rdist_normal negative sd",     "$rdist_normal(s,0.0,-1.0)"),
    ("[16] $rdist_exponential neg mean",   "$rdist_exponential(s,-1.0)"),
    ("[17] $rdist_poisson negative mean",  "$rdist_poisson(s,-1)"),
    ("[18] $rdist_chi_square neg dof",     "$rdist_chi_square(s,-3)"),
    ("[19] $rdist_t negative dof",         "$rdist_t(s,-3)"),
    ("[20] $rdist_erlang negative k",      "$rdist_erlang(s,-2,1.0)"),
]
for label, expr in ABSENT:
    src = H + ("module m(a,b); inout a,b; electrical a,b; integer s;\n analog begin s=1;\n"
               f"  I(a,b) <+ 1e-3*V(a,b)*(1.0+1e-12*{expr});\n end\nendmodule\n")
    rc, out, _ = compile_va(src, re.sub(r"\W", "", label)[:12])
    check(label + " is refused", rc != 0, f"rc={rc}")

for label, expr in [("[21] $vt(-300) (no negative absolute temperature)", "$vt(-300.0)"),
                    ("[21b] $vt(0) (absolute zero put a NaN in the solution)", "$vt(0.0)")]:
    src = H + f"module m(a,b); inout a,b; electrical a,b;\n analog I(a,b) <+ V(a,b)/{expr};\nendmodule\n"
    rc, _, _ = compile_va(src, re.sub(r"\W", "", label)[:12])
    check(label + " is refused", rc != 0, f"rc={rc}")

for label, expr in [("[22] ddt negative abstol", "ddt(V(a,b), -1e-9)"),
                    ("[22b] idt negative abstol", "idt(V(a,b),0.0,0,-1e-9)")]:
    src = H + f"module m(a,b); inout a,b; electrical a,b;\n analog I(a,b) <+ 1e-6*{expr} + 1e-3*V(a,b);\nendmodule\n"
    rc, _, _ = compile_va(src, re.sub(r"\W", "", label)[:12])
    check(label + " is refused", rc != 0, f"rc={rc}")

# a denominator whose HIGHEST-order coefficient is zero
for label, den, reject in [
        ("[23] laplace_nd padded denominator", "'{1.0}, '{1.0, 0.0}", True),
        ("[23b] laplace_zd padded denominator", "'{}, '{1.0, 0.0}", True),
        ("[23c] ...but an unpadded one still compiles", "'{1.0}, '{1.0}", False)]:
    src = H + (f"module m(pin,pout); inout pin,pout; electrical pin,pout;\n"
               f" analog V(pout) <+ laplace_nd(V(pin), {den});\nendmodule\n")
    rc, out, _ = compile_va(src, re.sub(r"\W", "", label)[:12])
    check(label + (" is refused" if reject else ""), (rc != 0) == reject, f"rc={rc}")

# zi_* handles the same padding correctly and must NOT be refused
for label, expr in [("[23d] zi_nd padded denominator still compiles",
                     "zi_nd(V(pin),'{1.0},'{1.0, 0.0},1e-5,0.0)")]:
    src = H + f"module m(pin,pout); inout pin,pout; electrical pin,pout;\n analog V(pout) <+ {expr};\nendmodule\n"
    rc, out, osdi = compile_va(src, "zipad")
    if check(label, rc == 0, f"rc={rc}"):
        _, o = sim(osdi, "V1 in 0 dc 0 ac 1\nN1 in out mm\nRl out 0 1meg\n.model mm m()",
                   "ac dec 1 10 100\nprint mag(v(out))", "zipad")
        g = [float(r[2]) for r in rows(o)]
        check("...[23d] and its gain is 1, as the unpadded spelling gives",
              bool(g) and all(abs(x - 1.0) < 1e-6 for x in g), f"gains={g}")

# --------------------------------------- [24]-[25] a build that defines none --
print("\na build that defines no module is not a success")
rc, out, _ = compile_va(H + "/* unterminated\nmodule m(a,b); inout a,b; electrical a,b;"
                        " analog I(a,b) <+ 1e-3*V(a,b); endmodule\n", "unterm")
check("[24] an unterminated /* comment is diagnosed", rc != 0, f"rc={rc}")
check("...[24] and the message says what is missing",
      "defines no module" in out, out.splitlines()[0][:60] if out else "")
rc, out, _ = compile_va(H, "nomod")
check("[25] a file with no module at all is diagnosed", rc != 0, f"rc={rc}")

# --------------------------- [26]-[31] pinned decisions, NOT to be "fixed" ----
print("\ndeliberately unchanged (pinned so a later round does not 'fix' them)")
TIMER = H + """
module m(a,b); inout a,b; electrical a,b;
 integer n;
 analog begin
  @(initial_step) n = 0;
  @(timer(1n, 0)) n = n + 1;
  I(a,b) <+ 1e-3*V(a,b) + 1e-6*n;
 end
endmodule
"""
rc, out, osdi = compile_va(TIMER, "timer")
if check("[26] @(timer) with a period of 0 still COMPILES (LRM 5.10.3.3)", rc == 0, f"rc={rc}"):
    _, o = sim(osdi, "V1 p 0 dc 1\nN1 p 0 mm\n.model mm m()", "tran 1n 100n\nprint i(v1)", "timer")
    r = rows(o)
    fires = round((abs(float(r[-1][2])) - 1e-3) / 1e-6) if r else -1
    check("...[26] and fires exactly ONCE, which is what the LRM specifies",
          fires == 1, f"fires={fires}")

rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\n"
                        " analog I(a,b) <+ 1e-3*V(a,b) + noise_table_log('{1.0, -120.0, 1e6, -120.0});\nendmodule\n",
                        "ntlneg")
check("[27] noise_table_log still refuses a negative power (its input is LINEAR)",
      rc != 0, f"rc={rc}")
check("[28] ...and the diagnostic names noise_table_log, not noise_table",
      "noise_table_log:" in out,
      (re.search(r"error: (.*)", out).group(1)[:52] if re.search(r"error: (.*)", out) else ""))

ZM = H + """
module m(a,b); inout a,b; electrical a,b;
 parameter real z = 0.0;
 real n, p;
 analog begin
  n = z/z;
  p = 0.0*n;
  $strobe("N=%g P=%g", n, p);
  I(a,b) <+ 1e-3*V(a,b);
 end
endmodule
"""
rc, out, osdi = compile_va(ZM, "zmul")
if rc == 0:
    _, o = sim(osdi, "V1 q 0 dc 1\nN1 q 0 mm\n.model mm m(z=0.0)", "op", "zmul")
    m = re.findall(r"N=(\S+) P=(\S+)", o)
    got = m[-1] if m else ("?", "?")
    check("[29] 0.0*NaN still folds to 0 (Enhancement-337 keeps that deliberately)",
          got == ("nan", "0"), f"nan={got[0]} product={got[1]}")

rc, out, osdi = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\n"
                           " localparam real k = 1e-324;\n"
                           ' analog begin $strobe("K=%g", k); I(a,b) <+ 1e-3*V(a,b); end\nendmodule\n',
                           "uflow")
if check("[31] a real literal that underflows still compiles", rc == 0, f"rc={rc}"):
    _, o = sim(osdi, "V1 q 0 dc 1\nN1 q 0 mm\n.model mm m()", "op", "uflow")
    k = re.findall(r"K=(\S+)", o)
    check("...[31] and is 0, which IEEE 754 defines", k and k[-1] == "0", f"k={k[-1] if k else '?'}")

rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\n"
                        " parameter real p = -1e-12;\n"
                        " analog I(a,b) <+ 1e-3*V(a,b) + white_noise(p);\nendmodule\n", "pdflt")
check("[30] a PARAMETER default is still not policed (the model card may replace it)",
      rc == 0, f"rc={rc}")
rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\n"
                        " parameter real p0 = 1e-12;\n localparam real q = -p0;\n"
                        " analog I(a,b) <+ 1e-3*V(a,b) + white_noise(q);\nendmodule\n", "lpofp")
check("...[30] nor a localparam DERIVED from one, whose value is not known here",
      rc == 0, f"rc={rc}")

# ------------------------------------------- [32]-[38] valid values still ok --
print("\nvalid values are still accepted")
OK = [
    ("[32] white_noise(1e-12)",        "I(a,b) <+ 1e-3*V(a,b) + white_noise(1e-12);"),
    ("[33] transition(...,1n,1n)",     "I(a,b) <+ 1e-6*transition(V(a,b),0,1n,1n) + 1e-3*V(a,b);"),
    ("[34] slew(...,1e6,-1e6)",        "I(a,b) <+ 1e-6*slew(V(a,b),1e6,-1e6) + 1e-3*V(a,b);"),
    ("[35] absdelay(...,1n,5n)",       "I(a,b) <+ 1e-6*absdelay(V(a,b),1n,5n) + 1e-3*V(a,b);"),
    ("[36] $vt(300.0)",                "I(a,b) <+ V(a,b)/$vt(300.0);"),
    ("[37] ddt(V,1e-9)",               "I(a,b) <+ 1e-6*ddt(V(a,b),1e-9) + 1e-3*V(a,b);"),
    ("[38] $rdist_normal(s,0.0,1.0)",  "I(a,b) <+ 1e-3*V(a,b)*(1.0+1e-12*$rdist_normal(s,0.0,1.0));"),
]
for label, body in OK:
    src = H + ("module m(a,b); inout a,b; electrical a,b; integer s;\n analog begin s=1;\n  "
               + body + "\n end\nendmodule\n")
    rc, out, _ = compile_va(src, re.sub(r"\W", "", label)[:12])
    check(label + " still compiles", rc == 0,
          (re.search(r"error: (.*)", out).group(1)[:52] if rc and re.search(r"error: (.*)", out) else ""))

# ---------------------------------------------------------------------------
# Enhancement-545 (compiler hunt F1): simulation state in a constant
#
# `parameter real t0 = $temperature;` crashed the compiler outright: a
# parameter default or range is validated in the constant context, where
# `analysis()` was already refused but the simulation-state functions and the
# random draws were not, so they reached LLVM codegen of the setup functions
# with no value to read (mir_llvm builder.rs: "attempted to read undefined
# value"). `$mfactor` -- a hierarchical parameter, not a builtin -- folded to a
# placeholder 1 instead, and `$random` to one fixed number for every instance.
# Each is now refused where analysis() is, with the rule named; the same
# functions stay legal in the analog block.
# ---------------------------------------------------------------------------
print("\nEnhancement-545: simulation state and random draws in a constant are refused, not crashed")

def const_case(label, decl, want):
    src = H + "module m(a,b); inout a,b; electrical a,b;\n" + decl + "\nanalog I(a,b) <+ V(a,b)/1e3;\nendmodule\n"
    rc, out, _ = compile_va(src, "e545_" + re.sub(r"\W", "", label)[:14])
    msg = re.search(r"error: (.*)", out)
    check(label, not crashed(rc, out) and rc != 0 and want in out,
          f"{'CRASH' if crashed(rc, out) else (msg.group(1)[:70] if msg else 'accepted')}")

for label, decl, want in (
    ("$temperature as a default", "parameter real t0 = $temperature;", "system function '$temperature' is not allowed in constants"),
    ("$vt as a default", "parameter real v0 = $vt;", "system function '$vt' is not allowed in constants"),
    ("$abstime as a default", "parameter real a0 = $abstime;", "system function '$abstime' is not allowed in constants"),
    ("$port_connected as a default", "parameter integer k0 = $port_connected(a);", "system function '$port_connected' is not allowed in constants"),
    ("$mfactor as a default (a hierarchical parameter, not a builtin)", "parameter real m0 = $mfactor;", "system function '$mfactor' is not allowed in constants"),
    ("$temperature in a range bound", "parameter real r0 = 1.0 from [0:$temperature];", "'$temperature' is not allowed in constants"),
    ("$temperature in an array default", "parameter real c0[0:1] = '{$temperature, 1.0};", "'$temperature' is not allowed in constants"),
    ("$temperature in an instance-typed default", "(* type=\"instance\" *) parameter real i0 = $temperature;", "'$temperature' is not allowed in constants"),
    ("$temperature inside an expression default", "parameter real e0 = 2.0 * $temperature + 1.0;", "'$temperature' is not allowed in constants"),
    ("$random as a default", "parameter real x0 = $random;", "random draw '$random' is not allowed in constants"),
    ("$rdist_normal as a default", "parameter integer sd = 1; parameter real d0 = $rdist_normal(sd, 0.0, 1.0);", "random draw '$rdist_normal' is not allowed in constants"),
    ("$mfactor in a range bound", "parameter real g0 = 1.0 from [0:$mfactor];", "'$mfactor' is not allowed in constants"),
):
    const_case(label, decl, want)

rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\nparameter real t0 = $temperature;\nanalog I(a,b) <+ V(a,b)/1e3;\nendmodule\n", "e545_notes")
check("the refusal names the rule and the way out",
      "constant expression (LRM 3.4)" in out and "analog initial" in out, out.count("help:"))
rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\nparameter real x0 = $random;\nanalog I(a,b) <+ V(a,b)/1e3;\nendmodule\n", "e545_rndnotes")
check("a draw's refusal points at (* std *) and .option osdimc", "std=<sigma>" in out and "osdimc" in out, out.count("help:"))

# controls: what must keep working
rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\nparameter real r = 1.0; parameter real g = $param_given(r) ? 2.0 : 1.0;\nparameter real gm = $simparam(\"gmin\", 1e-12);\nanalog I(a,b) <+ (g + gm)*V(a,b)/1e3;\nendmodule\n", "e545_ok")
check("$param_given and $simparam in a default stay legal ($simparam keeps its L015 warning)",
      rc == 0 and "L015" in out and "not allowed in constants" not in out,
      f"rc={rc} L015={'L015' in out}")
rc, out, osdi = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\n(* desc=\"t\" *) real t; (* desc=\"mf\" *) real mf; (* desc=\"rn\" *) real rn;\nanalog begin t = $temperature + $vt + $abstime + $port_connected(a); mf = $mfactor; rn = $random*0.0; I(a,b) <+ (t*0.0 + mf*0.0 + rn) + V(a,b)/1e3; end\nendmodule\n", "e545_analog")
check("the same functions in the analog block still compile", rc == 0 and "not allowed" not in out, f"rc={rc}")
if osdi:
    rc2, out2 = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm m=3\n.model mm m", "op\nprint @n1[t]\nprint @n1[mf]", "e545_run")
    check("... and read the live values there (temperature 300.15, $mfactor 3)",
          val(out2, "@n1[t]") is not None and abs(val(out2, "@n1[t]") - (300.15 + 0.025852 + 0 + 1)) < 1e-3 and val(out2, "@n1[mf]") == 3.0,
          f"t={val(out2, '@n1[t]')} mf={val(out2, '@n1[mf]')}")
else:
    check("... and read the live values there (temperature 300.15, $mfactor 3)", False, "no .osdi")
rc, out, _ = compile_va(H + "module m(a,b); inout a,b; electrical a,b;\nparameter integer a0 = analysis(\"dc\");\nanalog I(a,b) <+ a0*V(a,b)/1e3;\nendmodule\n", "e545_analysis")
check("analysis() in a default keeps its own message", rc != 0 and "analysis function 'analysis' is not allowed in constants" in out)

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
