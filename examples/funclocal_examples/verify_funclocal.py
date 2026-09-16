#!/usr/bin/env python3
"""Enhancement-646: an analog function's local variables start every call afresh
(2026-09-16 hunt, F2).

A function body is inlined at its call site, so its locals were module
variables: a read before the call's own write reached the hidden-state value
left by the previous call or the previous Newton iteration. `integer n;
n = n + 1; cnt = n;` counted every evaluation (1074 at one operating point,
reached through gmin stepping), an `integer n = 5;` initializer applied once,
and a named block's local the same. The return variable (LRM 4.7.2.1) and the
output arguments (4.7.2.2) were already fresh per call.

Now every variable the function declares -- its locals, a named block's
locals, a local array, a string, the return array's elements -- takes its
declared initializer (zero, "" for a string) at every call; a local written
before it is read, and accumulation within one call, are unchanged.
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
WORK = tempfile.mkdtemp(prefix="funclocal_")
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
        f.write(f"* funclocal {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\npre_osdi {osdi}.osdi\n{ctl}\nquit\n.endc\n.end\n")
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

# [1]-[2] the hunt's reproducer: a counter local
ok, out = compile_src(MOD("fa", "analog function real cnt; input x; real x; integer n; begin n = n + 1; cnt = n; end endfunction\n"
                       "real a; analog begin a = cnt(1.0); $strobe(\"cnt=%g\", a); I(p,n) <+ a + V(p,n)*0; end"), "fa")
o = run(DECK("fa"), "op\nprint i(v1)", "fa", "fa") if ok else ""
check("[1] a local read before its write is zero on every call (cnt=1 at the operating point, I = -1 A)",
      ok and re.search(r"cnt=1\b", o) is not None and near(iv1(o), -1.0))
check("[2] ... and the operating point needs no gmin stepping", ok and "gmin stepping" not in o)

# [3] two calls in one evaluation
ok, out = compile_src(MOD("fb", "analog function real acc; input x; real x; real s; begin s = s + x; acc = s; end endfunction\n"
                       "real a, b; analog begin a = acc(1.0); b = acc(1.0); $strobe(\"a=%g b=%g\", a, b); I(p,n) <+ V(p,n); end"), "fb")
o = run(DECK("fb"), "op", "fb", "fb") if ok else ""
check("[3] a real local starts at zero in each of two calls of one evaluation (a=1 b=1)", ok and "a=1 b=1" in o)

# [4] a declared initializer applies per call
ok, out = compile_src(MOD("fc", "analog function real cnt; input x; real x; integer n = 5; begin n = n + 1; cnt = n; end endfunction\n"
                       "real a, b; analog begin a = cnt(1.0); b = cnt(1.0); $strobe(\"a=%g b=%g\", a, b); I(p,n) <+ V(p,n); end"), "fc")
o = run(DECK("fc"), "op", "fc", "fc") if ok else ""
check("[4] a local's declared initializer applies at every call (integer n = 5: a=6 b=6)", ok and "a=6 b=6" in o)

# [5] a string local
ok, out = compile_src(MOD("fd", "analog function real f; input x; real x; string s; begin $strobe(\"s=[%s]\", s); s = \"set\"; f = x; end endfunction\n"
                       "real a, b; analog begin a = f(1.0); b = f(1.0); I(p,n) <+ V(p,n); end"), "fd")
o = run(DECK("fd"), "op", "fd", "fd") if ok else ""
check("[5] a string local is the empty string at every call", ok and "s=[set]" not in o and "s=[]" in o)

# [6] a named block's local
ok, out = compile_src(MOD("fe", "analog function real f; input x; real x; begin : blk integer k; $strobe(\"k=%d\", k); k = k + 7; f = x + k; end endfunction\n"
                       "real a, b; analog begin a = f(1.0); b = f(1.0); $strobe(\"a=%g b=%g\", a, b); I(p,n) <+ V(p,n); end"), "fe")
o = run(DECK("fe"), "op", "fe", "fe") if ok else ""
check("[6] a named block's local inside the function is zero at every call (k=0, a=8 b=8)",
      ok and re.search(r"k=0\b", o) is not None and re.search(r"k=[1-9]", o) is None and "a=8 b=8" in o)

# [7] a local array accumulated within one call
ok, out = compile_src(MOD("ff", "analog function real f; input x; real x; real t[0:2]; integer i; begin for (i = 0; i < 3; i = i + 1) t[i] = t[i] + x * i; f = t[0] + t[1] + t[2]; end endfunction\n"
                       "analog I(p,n) <+ f(V(p,n));"), "ff")
check("[7] a local array starts at zeros and accumulates within the call (I = -3 A)",
      ok and near(iv1(run(DECK("ff"), "op\nprint i(v1)", "ff", "ff")), -3.0))

# [8] the return array's elements
ok, out = compile_src(MOD("fg", "analog function real [0:1] two; input x; input which; real x; integer which; begin if (which == 0) two[0] = 5.0; else two[1] = x; end endfunction\n"
                       "real a[0:1], b[0:1]; analog begin a = two(3.0, 0); b = two(3.0, 1); $strobe(\"a=%g,%g b=%g,%g\", a[0], a[1], b[0], b[1]); I(p,n) <+ V(p,n); end"), "fg")
o = run(DECK("fg"), "op", "fg", "fg") if ok else ""
check("[8] a return array's unwritten elements are zero on the next call (a=5,0 b=0,3; LRM 4.7.2.1)", ok and "a=5,0 b=0,3" in o)

# [9] the $limit path
ok, out = compile_src(MOD("fh", "analog function real mylim; input v, vold; real v, vold; real d; begin d = v - vold; mylim = (d > 0.1) ? vold + 0.1 : ((d < -0.1) ? vold - 0.1 : v); end endfunction\n"
                       "analog I(p,n) <+ 1e-3*exp($limit(V(p,n), mylim) * 10);"), "fh")
check("[9] a local in a $limit limiting function (I = -1e-3 e^10)",
      ok and near(iv1(run(DECK("fh"), "op\nprint i(v1)", "fh", "fh")), -1e-3 * 2.718281828459045 ** 10, 1e-6))

# [10] two instances
ok, out = compile_src(MOD("fi", "analog function real cnt; input x; real x; integer n; begin n = n + 1; cnt = n; end endfunction\n"
                       "real a; analog begin a = cnt(1.0); $strobe(\"%m cnt=%g\", a); I(p,n) <+ V(p,n); end"), "fi")
o = run("v1 1 0 1\n.model fi fi\nna1 1 0 fi\nna2 1 0 fi", "op\nprint i(v1)", "fi", "fi") if ok else ""
check("[10] two instances each see cnt=1 (I = -2 A)", ok and "na1 cnt=1" in o and "na2 cnt=1" in o and near(iv1(o), -2.0))

# [11] unchanged: a local written before it is read
ok, out = compile_src(MOD("fj", "analog function real sq2; input x; real x; real t; begin t = x*x; sq2 = t + t; end endfunction\n"
                       "analog I(p,n) <+ sq2(V(p,n)) * 2;"), "fj")
check("[11] a local written before it is read is unchanged (I = -4 A)", ok and near(iv1(run(DECK("fj"), "op\nprint i(v1)", "fj", "fj")), -4.0))

# [12] a transient: the count stays 1 at every time point
ok, out = compile_src(MOD("fk", "analog function real cnt; input x; real x; integer n; begin n = n + 1; cnt = n; end endfunction\n"
                       "real a; analog begin a = cnt(1.0); I(p,n) <+ a * V(p,n); end"), "fk")
o = run(DECK("fk"), "tran 1u 10u\nmeas tran imax max i(v1)\nmeas tran imin min i(v1)", "fk", "fk") if ok else ""
mx = re.search(r"imax\s*=\s*([-+0-9.eE]+)", o); mn = re.search(r"imin\s*=\s*([-+0-9.eE]+)", o)
check("[12] in a transient the local is zero at every evaluation (I = -1 A at every point)",
      ok and mx and mn and near(float(mx.group(1)), -1.0) and near(float(mn.group(1)), -1.0))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
