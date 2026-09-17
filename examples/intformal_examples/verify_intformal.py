#!/usr/bin/env python3
"""Enhancement-647: a real converts into an integer function input and a real
`case` item matches an integer selector (2026-09-16 hunt, F3).

LRM 4.7.3 assigns a call's actual to the formal and 4.2.1.1 rounds a real
assigned to an integer -- `k = 2.7` is `k = 3`, and openvaf-r did that for
assignments, `repeat` counts, integer returns and array elements -- yet an
integer INPUT formal given a real (literal or variable) was a type error, and
LRM 5.8.3's `case` refused a real item under an integer selector while it
accepted an integer item under a real one.

Now a scalar integer input formal takes anything assignable to an integer
(rounded, LRM 4.2.1.1), and an integer or boolean selector with a real item is
compared as real. Unchanged and still refused: a real seed for `$random`/
`$dist_*`, a real shift distance, an integer output formal bound to a real
variable, a string into an integer formal, a string selector with a real item.
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
WORK = tempfile.mkdtemp(prefix="intformal_")
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
        f.write(f"* intformal {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\npre_osdi {osdi}.osdi\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def iv1(out):
    m = re.search(r"i\(v1\)\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


def near(x, ref, tol=1e-9):
    return x is not None and abs(x - ref) <= tol * max(1.0, abs(ref))


MOD = lambda name, body: f"module {name}(p,n); inout p,n; electrical p,n;\n{body}\nendmodule\n"
DECK = lambda model: f"v1 1 0 1\n.model {model} {model}\nna1 1 0 {model}"
IDENT = "analog function integer f; input y; integer y; f = y; endfunction\n"

# ---------------------------------------------------------------- function inputs
ok, out = compile_src(MOD("fa", IDENT + "analog begin $strobe(\"r=%d %d %d %d\", f(2.7), f(-2.5), f(0.5), f(1.5)); I(p,n) <+ V(p,n); end"), "fa")
o = run(DECK("fa"), "op", "fa", "fa") if ok else ""
check("[1] a real literal into an integer input formal compiles", ok, out.strip().splitlines()[-1][:80] if not ok else "")
check("[2] ... and rounds as LRM 4.2.1.1 says (2.7, -2.5, 0.5, 1.5 -> 3 -3 1 2)", "r=3 -3 1 2" in o)

ok, out = compile_src(MOD("fb", IDENT + "real r; integer k; analog begin r = 2.7; k = f(r); $strobe(\"f(r)=%d f(3V)=%d\", k, f(V(p,n)*3)); I(p,n) <+ k * V(p,n); end"), "fb")
o = run(DECK("fb"), "op\nprint i(v1)", "fb", "fb") if ok else ""
check("[3] a real variable and a node expression into an integer input formal (f(r)=3, f(3V)=3, I = -3 A)",
      ok and "f(r)=3 f(3V)=3" in o and near(iv1(o), -3.0))

ok, out = compile_src(MOD("fc", "analog function real g; input x; real x; g = 2*x; endfunction\nanalog I(p,n) <+ g(3) * V(p,n);"), "fc")
check("[4] an integer into a real input formal is unchanged (I = -6 A)", ok and near(iv1(run(DECK("fc"), "op\nprint i(v1)", "fc", "fc")), -6.0))

ok, out = compile_src(MOD("fd", "analog function integer f; input y, z; integer y; real z; f = y + z; endfunction\n"
                       "analog begin $strobe(\"m=%d\", f(1.6, 1)); I(p,n) <+ V(p,n); end"), "fd")
o = run(DECK("fd"), "op", "fd", "fd") if ok else ""
check("[5] mixed formals: a real into the integer one rounds, an integer into the real one converts (f(1.6, 1) = 3)", ok and "m=3" in o)

# ---------------------------------------------------------------- case
CASE = lambda decl, sel, items: MOD("cs", f"{decl} real g; analog begin case ({sel}) {items} default: g = 99; endcase I(p,n) <+ g*V(p,n); end")
ok, out = compile_src(CASE("parameter integer sel = 2;", "sel", "2.0: g = 20;"), "ca")
check("[6] an integer selector with a real item 2.0 compiles", ok, out.strip().splitlines()[-1][:80] if not ok else "")
check("[7] ... and matches (I = -20 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "ca", "ca")), -20.0))

ok, out = compile_src(CASE("parameter integer sel = 2; parameter real lab = 2.0;", "sel", "lab: g = 20;"), "cb")
check("[8] a real parameter item matches an integer selector (I = -20 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "cb", "cb")), -20.0))

ok, out = compile_src(CASE("parameter integer sel = 3;", "sel", "2.5: g = 25; 3: g = 30;"), "cc")
check("[9] a real item 2.5 does not match 3 and the integer item 3 still does (I = -30 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "cc", "cc")), -30.0))

ok, out = compile_src(CASE("parameter integer sel = 2;", "sel", "2.5: g = 25;"), "cd")
check("[10] a real item 2.5 under an integer selector 2 falls to default, not to a rounded match (I = -99 A)",
      ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "cd", "cd")), -99.0))

ok, out = compile_src(CASE("parameter real sel = 2;", "sel", "2: g = 20;"), "ce")
check("[11] a real selector with an integer item is unchanged (I = -20 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "ce", "ce")), -20.0))

ok, out = compile_src(CASE("", "V(p,n) > 0.5", "1.0: g = 5;"), "cf")
check("[12] a boolean selector with a real item 1.0 (I = -5 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "cf", "cf")), -5.0))

ok, out = compile_src(MOD("cs", "parameter integer sel = 5; real g; analog begin casez (sel) 4'b01?1: g = 7; default: g = 9; endcase I(p,n) <+ g*V(p,n); end"), "cg")
check("[13] casez with integer items keeps its don't-care masks (I = -7 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "cg", "cg")), -7.0))

ok, out = compile_src(MOD("cs", "real a[0:1]; real g; analog begin a[0] = 1; a[1] = 2; case (a) '{1.0, 2.0}: g = 1; default: g = 9; endcase I(p,n) <+ g*V(p,n); end"), "ch")
check("[14] an array case is unchanged (I = -1 A)", ok and near(iv1(run(DECK("cs"), "op\nprint i(v1)", "ch", "ch")), -1.0))

# ---------------------------------------------------------------- still refused
ok, out = compile_src(MOD("ra", "real s, x; analog begin s = 3; x = $rdist_normal(s, 0, 1); I(p,n) <+ V(p,n); end"), "ra")
check("[15] a real seed for $rdist_normal is still refused", not ok and "expected integer value but found real variable reference" in out)
ok, out = compile_src(MOD("rb", "integer k; analog begin k = 1 << 2.0; I(p,n) <+ V(p,n); end"), "rb")
check("[16] a real shift distance is still refused", not ok and "expected integer value but found real literal" in out)
ok, out = compile_src(MOD("rc", "analog function real f; output y; integer y; begin y = 7; f = 1; end endfunction\nreal a, r; analog begin r = f(a); I(p,n) <+ V(p,n); end"), "rc")
check("[17] an integer output formal bound to a real variable is still refused", not ok and "expected integer variable reference but found real variable reference" in out)
ok, out = compile_src(MOD("rd", IDENT + "string s; analog begin s = \"x\"; I(p,n) <+ f(s) * V(p,n); end"), "rd")
check("[18] a string into an integer formal is still refused", not ok and "expected integer value but found string variable reference" in out)
ok, out = compile_src(CASE("parameter string s = \"a\";", "s", "2.0: g = 1;"), "re")
check("[19] a string selector with a real item is still refused", not ok and "expected string value but found real literal" in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
