#!/usr/bin/env python3
"""Enhancement-650: eleven diagnostic slips from the 2026-09-16 hunt (F6).

Each item is a message that blamed the wrong thing, said nothing, or said
"encountered unexpected token!" for an input that deserved its own sentence:

  a contribution across two disciplines blamed on the destination's shape;
  `endif/`else with no `ifdef, a `\\` continuation followed by white space, and
  a NUL byte all reported as "encountered unexpected token!"; `line accepted
  in silence; an unknown lint name in openvaf_allow accepted in silence (the
  report existed and was never emitted); `from {1, 2.5}` on an integer
  accepted in silence; `.5` refused as "unexpected token '.'" while `5.` had
  the LRM sentence; "\\777" printing U+01FF and `\\q` passing without a word;
  `%m` inside a child instance printing the top instance's name; a bad -D
  argument reported inside /std/__openvaf_defines__.va, a file the user never
  wrote; a file including itself blamed on `disciplines.vams` 64 levels down;
  `define G() reported as "expected an identifier"; and "attriubte".
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
WORK = tempfile.mkdtemp(prefix="diagslips_")
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag, args=(), binary=False):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "wb" if binary else "w") as f:
        f.write(src)
    r = subprocess.run([VAF, *args, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True, errors="replace")
    return r.returncode == 0, r.stdout + r.stderr


def run(tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* diagslips {tag}\nv1 1 0 1\n.model m m\nna1 1 0 m\n.control\nset noinit\npre_osdi {tag}.osdi\nop\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL, errors="replace")
    return p.stdout + p.stderr


def first(out):
    return (out.strip().splitlines() or [""])[0][:90]


MOD = lambda body: HDR + "module m(p,n); inout p,n; electrical p,n;\n" + body + "\nendmodule\n"
UNEXPECTED = "encountered unexpected token"

# ---------------------------------------------------------------- [1] a contribution across two disciplines
ok, out = compile_src(HDR + "discipline thermal2; potential Temperature; flow Power; enddiscipline\n"
                      "module m(p,n); inout p,n; electrical p; thermal2 n;\nanalog Pwr(p,n) <+ 1.0;\nendmodule\n", "a1")
check("[1] Pwr(p,n) <+ 1.0 across electrical/thermal2 names the incompatible disciplines, not the destination's shape",
      not ok and "have incompatible disciplines" in out and "invalid destination" not in out, first(out))

# ---------------------------------------------------------------- [2-5] the "encountered unexpected token!" trio
ok, out = compile_src(MOD("`endif\nanalog I(p,n) <+ V(p,n);"), "b1")
check("[2] `endif with no `ifdef", not ok and "'`endif' without a matching '`ifdef' or '`ifndef'" in out and UNEXPECTED not in out, first(out))
ok, out = compile_src(MOD("`else\nanalog I(p,n) <+ V(p,n);"), "b2")
check("[3] `else with no `ifdef", not ok and "'`else' without a matching" in out and UNEXPECTED not in out, first(out))
ok, out = compile_src(MOD("`define K \\  \n8.0\nanalog I(p,n) <+ `K*V(p,n);"), "b3")
check("[4] a `\\` continuation followed by two spaces: counted and explained",
      not ok and "must be the last character on its line, but 2 white-space character(s) follow it" in out and UNEXPECTED not in out, first(out))
ok, out = compile_src(MOD("analog I(p,n) <+ V(p,n);").encode().replace(b"analog", b"ana\x00log"), "b4", binary=True)
check("[5] a NUL byte in the source", not ok and "the source contains a NUL byte" in out and UNEXPECTED not in out, first(out))

# ---------------------------------------------------------------- [6] `line
ok, out = compile_src(MOD('`line 100 "other.va" 0\nanalog begin $strobe("L=%d", `__LINE__); I(p,n) <+ V(p,n); end'), "c1")
o = run("c1") if ok else ""
check("[6] `line is warned about (diagnostics keep the physical position) and still moves `__LINE__ (L=100)",
      ok and "'`line' changes '`__FILE__' and '`__LINE__' only" in out and "L=100" in o, first(out))
ok, out = compile_src(MOD('`line 100 "other.va" 0\nanalog I(p,n) <+ V(p,n) + x;'), "c2")
check("[7] ... and an error after it is reported at the physical line 4, as the warning says",
      not ok and re.search(r"c2\.va:4:\d+", out) is not None and "other.va" not in out.split("warning")[0], first(out))

# ---------------------------------------------------------------- [8-11] openvaf_allow with an unknown name
ok, out = compile_src(MOD('(* openvaf_allow="no_such_lint" *) parameter real r = 1;\nanalog I(p,n) <+ V(p,n)/r;'), "d1")
check("[8] an unknown lint name on a parameter is refused (lint_not_found is deny by default)",
      not ok and "unknown lint 'no_such_lint'" in out and "L008" in out, first(out))
ok, out = compile_src(MOD('analog begin (* openvaf_allow="no_such_lint" *) I(p,n) <+ V(p,n); end'), "d2")
check("[9] ... and on a statement", not ok and "unknown lint 'no_such_lint'" in out, first(out))
ok, out = compile_src(MOD('analog begin (* openvaf_allow="discarded_contributions" *) V(p,n) <+ 1; I(p,n) <+ V(p,n); end'), "d3")
check("[10] a near miss gets its correction: did you mean 'discarded_contribution'?",
      not ok and "did you mean 'discarded_contribution'" in out, first(out))
ok, out = compile_src(MOD('(* openvaf_allow="param_default_out_of_range" *) parameter real r = 5 from [0:1];\nanalog I(p,n) <+ V(p,n)/r;'), "d4")
check("[11] a known name still silences its lint", ok and "violates its own range" not in out, first(out))

# ---------------------------------------------------------------- [12-15] from {..} on an integer
ok, out = compile_src(MOD("parameter integer k = 1 from {1, 2.5};\nanalog I(p,n) <+ k*V(p,n);"), "e1")
check("[12] parameter integer k from {1, 2.5}: the member no integer equals is warned about (dead_range_member) and the model compiles",
      ok and "names the non-integer 2.5" in out and "can never be chosen" in out and "L034" in out, first(out))
ok, out = compile_src(MOD("parameter integer k = 1 exclude {2.5};\nanalog I(p,n) <+ k*V(p,n);"), "e2")
check("[13] exclude {2.5} on an integer is left alone: a vacuous exclusion is not a claim (the intrange suite pins `exclude 2.5`)", ok and "non-integer" not in out, first(out))
ok, out = compile_src(MOD("parameter integer k = 1 from {1, 2};\nanalog I(p,n) <+ k*V(p,n);"), "e3")
check("[14] from {1, 2} on an integer is clean", ok and "non-integer" not in out, first(out))
ok, out = compile_src(MOD("parameter real k = 1 from {1, 2.5};\nanalog I(p,n) <+ k*V(p,n);"), "e4")
check("[15] from {1, 2.5} on a real is clean", ok and "non-integer" not in out, first(out))

# ---------------------------------------------------------------- [16-18] .5
SENT = "a real constant needs a digit on each side of the decimal point"
ok, out = compile_src(MOD("analog I(p,n) <+ .5*V(p,n);"), "f1")
check("[16] .5 gets the LRM 2.6.2 sentence, not \"unexpected token '.'\"", not ok and SENT in out and "unexpected token '.'" not in out, first(out))
ok, out = compile_src(MOD("analog I(p,n) <+ 5.*V(p,n);"), "f2")
check("[17] 5. keeps it", not ok and SENT in out, first(out))
ok, out = compile_src(HDR + "module m(p,n); inout p,n; electrical p,n;\nanalog begin $strobe(\"a=%g\", p.potential.abstol); I(p,n) <+ 0.5*V(p,n) + 1.5e-3 + 2.5u; end\nendmodule\n", "f3")
check("[18] 0.5, 1.5e-3, 2.5u and a dotted name p.potential.abstol are untouched", ok, first(out))

# ---------------------------------------------------------------- [19-21] string escapes
ok, out = compile_src(MOD('analog begin $strobe("[\\777]"); I(p,n) <+ V(p,n); end'), "g1")
check("[19] \"\\777\" is refused: an octal escape names one 8-bit character", not ok and "exceeds \\377" in out, first(out))
ok, out = compile_src(MOD('analog begin $strobe("out=[\\q][\\x41]"); I(p,n) <+ V(p,n); end'), "g2")
o = run("g2") if ok else ""
check("[20] \\q and \\x41 are warned about (L032) and still kept verbatim, as E-48 decided",
      ok and out.count("unknown escape sequence") == 2 and "L032" in out and "out=[\\q][\\x41]" in o, first(out))
ok, out = compile_src(MOD('analog begin $strobe("[\\101\\n\\t\\\\\\"]"); I(p,n) <+ V(p,n); end'), "g3")
check("[21] the LRM's own escapes raise nothing", ok and "warning" not in out, first(out))

# ---------------------------------------------------------------- [22] %m in a child instance
ok, out = compile_src(HDR + 'module leaf(a,b); inout a,b; electrical a,b;\nanalog begin $strobe("m=%m %%m"); I(a,b) <+ V(a,b); end\nendmodule\n'
                      'module mid(a,b); inout a,b; electrical a,b;\nleaf l2(a,b);\nleaf arr[0:1](a,b);\nendmodule\n'
                      'module m(p,n); inout p,n; electrical p,n;\nmid l1(p,n);\nanalog $strobe("top=%m");\nendmodule\n', "h1")
o = run("h1") if ok else ""
names = sorted(set(re.findall(r"m=(\S+) %m", o)))
check("[22] %m in inlined children is the hierarchical instance name: na1.l1.l2, na1.l1.arr[0], na1.l1.arr[1]; %%m stays; the top is na1",
      ok and names == ["na1.l1.arr[0]", "na1.l1.arr[1]", "na1.l1.l2"] and "top=na1" in o, first(out) if not ok else str(names))

# ---------------------------------------------------------------- [23-27] -D
src = MOD('analog begin $strobe("G=%g", `G); I(p,n) <+ V(p,n); end')
ok, out = compile_src(src, "i1", args=("-D", "G==2.0"))
check("[23] -D G==2.0 is refused by name, on the command line", not ok and "the value '=2.0' starts with a second '='" in out and "'-D G=2.0' defines G as 2.0" in out, first(out))
ok, out = compile_src(src, "i2", args=("-D", "`G=2.0"))
check("[24] -D `G=2.0: the name is written without its backtick", not ok and "written without its backtick -- '-D G=2.0'" in out, first(out))
ok, out = compile_src(src, "i3", args=("-D", "1G=2.0"))
check("[25] -D 1G=2.0 is not a macro name", not ok and "'1G' is not a macro name" in out, first(out))
ok, out = compile_src(src, "i4", args=("-D", "G=)"))
check("[26] a value that fails to parse names the -D argument it came from", not ok and "synthesized from the command-line argument `-D G=)`" in out, first(out))
ok, out = compile_src(src, "i5", args=("-D", "G=2.0"))
check("[27] -D G=2.0 works (G=2)", ok and "G=2" in run("i5"), first(out))

# ---------------------------------------------------------------- [28-29] a file including itself
ok, out = compile_src(MOD("analog I(p,n) <+ V(p,n);") + '`include "j1.va"\n', "j1")
check("[28] a file that includes itself after its module: the cycle is named at the include, disciplines.vams is not blamed",
      not ok and "includes a file that is already being included" in out and "disciplines.vams" not in out and "nests too deeply" not in out, first(out))
with open(os.path.join(WORK, "ja.va"), "w") as f:
    f.write('`include "jb.va"\n')
with open(os.path.join(WORK, "jb.va"), "w") as f:
    f.write('`include "ja.va"\n')
ok, out = compile_src(MOD("analog I(p,n) <+ V(p,n);") + '`include "ja.va"\n', "j2")
check("[29] two files including each other: the cycle is named once, at jb.va's include of ja.va",
      not ok and out.count("includes a file that is already being included") == 1 and re.search(r"jb\.va:1:1", out) is not None, first(out))

# ---------------------------------------------------------------- [30-31] `define G()
ok, out = compile_src(MOD("`define G() 6.0\nanalog I(p,n) <+ `G*V(p,n);"), "k1")
check("[30] `define G() 6.0: an empty formal list gets its sentence", not ok and "needs at least one formal argument" in out and "expected 'an identifier'" not in out, first(out))
ok, out = compile_src(MOD("`define G(a) (a)*2\nanalog begin $strobe(\"G=%g\", `G(3)); I(p,n) <+ V(p,n); end"), "k2")
check("[31] `define G(a) is unchanged (G=6)", ok and "G=6" in run("k2"), first(out))

# ---------------------------------------------------------------- [32] attriubte
ok, out = compile_src(HDR + 'nature N1; units = "x"; access = X1; abstol = 1e-6; endnature\nnature F1; units = "y"; access = Y1; abstol = 1e-12; endnature\n'
                      'discipline d1; potential N1; flow F1; enddiscipline\nmodule m(p,n); inout p,n; d1 p,n;\n'
                      'analog begin $strobe("%s", p.potential.abstol); Y1(p,n) <+ X1(p,n); end\nendmodule\n', "l1")
check("[32] 'nature attribute reference' is spelt right", not ok and "nature attribute reference" in out and "attriubte" not in out, first(out))

# ---------------------------------------------------------------- Enhancement-708 (robustness campaign F10 of 2026-09-23)
ok, out = compile_src(MOD("integer i; analog begin i = 'hFFFFFFFFFF; I(p,n) <+ V(p,n)*i; end"), "m1")
check("[33] 'hFFFFFFFFFF (40 bits) draws L030: truncated to 32 bits, it reads as -1",
      ok and "warning[L030]" in out and "40 significant bits, more than the 32 of an `integer`" in out and "reads as -1" in out, first(out))
ok, out = compile_src(MOD("integer i; analog begin i = 'hFFFFFFFF; I(p,n) <+ V(p,n)*i; end"), "m2")
check("[34] 'hFFFFFFFF (32 bits) is silent", ok and "L030" not in out, first(out))
ok, out = compile_src(MOD("integer i; analog begin i = 'h0FFFFFFFF; I(p,n) <+ V(p,n)*i; end"), "m3")
check("[35] a leading 0 digit adds no bits: 'h0FFFFFFFF is silent", ok and "L030" not in out, first(out))
ok, out = compile_src(MOD("integer i; analog begin i = 8'hFFF; I(p,n) <+ V(p,n)*i; end"), "m4")
check("[36] 8'hFFF: 12 bits into a declared size of 8, reads as 255",
      ok and "12 significant bits, more than its declared size of 8" in out and "reads as 255" in out, first(out))
ok, out = compile_src(MOD("integer i; analog begin i = 'd4294967296; I(p,n) <+ V(p,n)*i; end"), "m5")
check("[37] 'd4294967296 (33 bits) is judged like the hex form", ok and "33 significant bits" in out, first(out))
ok, out = compile_src(MOD("integer i; analog begin i = 'h" + "F" * 100000 + "; I(p,n) <+ V(p,n)*i; end"), "m6")
l030 = next((l for l in out.splitlines() if "L030" in l), "")
check("[38] a 100 000-digit literal is measured (400000 bits) and abbreviated in the message",
      ok and "400000 significant bits" in l030 and "(100002 characters)" in l030 and "F" * 100 not in l030, first(out))
ok, out = compile_src(MOD("integer i; analog begin i = 'hFFFFFFFFFF; I(p,n) <+ V(p,n)*i; end"), "m7", args=("-A", "L030"))
check("[39] -A L030 silences it", ok and "significant bits" not in out, first(out))
ok, out = compile_src(HDR + '`include ""\n' + MOD("analog I(p,n) <+ V(p,n);"), "m8")
check("[40] `include \"\" names the empty name, not the directory it resolved to",
      not ok and "'`include \"\"' names no file" in out and "is a directory" not in out, first(out))
ok, out = compile_src(MOD('string s; analog begin $sformat(s, "%999999999d", 1); I(p,n) <+ V(p,n); end'), "m9")
check("[41] $sformat %999999999d (a 1 GB string at run time) is refused: above the limit of 4096",
      not ok and "the field width 999999999 is above the limit of 4096" in out, first(out))
ok, out = compile_src(MOD('string s; analog begin $sformat(s, "%.99999999999999999999f", 1.0); I(p,n) <+ V(p,n); end'), "m10")
check("[42] a 20-digit precision is refused with its digits, not a wrapped number",
      not ok and "the field precision 99999999999999999999 is above the limit of 4096" in out, first(out))
ok, out = compile_src(MOD('string s; analog begin $sformat(s, "%4096d|%08.3f", 1, 2.0); I(p,n) <+ V(p,n); end'), "m11")
check("[43] %4096d and %08.3f compile", ok, first(out))
ok, out = compile_src(MOD('integer w; analog begin w = 100000; $strobe("[%*d]", w, 7); I(p,n) <+ V(p,n); end'), "m12")
line = next((l for l in run("m12").splitlines() if "[" in l and "7]" in l), "")
seg = line[line.index("["):line.index("]") + 1] if "[" in line and "]" in line else ""
check("[44] a `*` width of 100 000 is clamped to 4096 at run time (the field is 4096 wide)",
      ok and len(seg) == 4098 and seg.endswith("7]"), f"field of {max(len(seg) - 2, 0)}")
ok, out = compile_src(MOD("parameter real a = 0.0, b = 0.0; analog I(p,n) <+ laplace_nd(V(p,n), '{1}, '{1, a/b});"), "m13")
out2 = run("m13")
check("[45] laplace_nd with a deck-fixed NaN highest-order coefficient: 'must be a finite non-zero number, but is nan', not 'must not be zero'",
      ok and "must be a finite non-zero number" in out2 and "nan" in out2.lower() and "must not be zero" not in out2, first(out2))
ok, out = compile_src(MOD("parameter real a = 1.0, b = 0.0; analog I(p,n) <+ laplace_nd(V(p,n), '{1}, '{1, a/b});"), "m14")
out2 = run("m14")
check("[46] ...and an infinite one, which used to normalise the filter to a silent 0",
      ok and "must be a finite non-zero number" in out2 and "inf" in out2.lower(), first(out2))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
