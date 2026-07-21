#!/usr/bin/env python3
"""verify_vaflaplace.py -- Enhancement-265: laplace_*/zi_* coefficient argument
type check (a compiler panic -> a clean diagnostic).

The numerator/denominator (and pole/zero) argument of a laplace_*/zi_* operator
must be a real coefficient array (LRM 9.19). Its type check accepted anything the
array-literal / array-variable special cases did not catch and returned its type
without requiring it to be a real value -- so a bare NET reference
(`laplace_nd(1.0, 1.0, p)`), a branch, or a string slipped through to hir_lower,
where resolving a net reference as a value panicked ("invalid HIR: path .. was not
resolved"): a crash on malformed input, exit 101.

Every ordinary value context (and the laplace *input* argument) already rejects
these with "type mismatch: expected real value but found ...". The fix requires
the same of the coefficient argument, so the malformed calls now emit that clean
diagnostic instead of crashing -- while every valid coefficient shape (real/int
array literals, scalar coefficients, bare array-variable references, the zi_*
forms) still compiles.

Passes iff each malformed coefficient argument ERRORs cleanly (no CRASH/panic)
and each well-formed filter compiles. Exit code 0 = pass.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


OUT = os.path.join(tempfile.gettempdir(), "vaflaplace_out.osdi")
HDR = '`include "disciplines.vams"\n'


def compile_src(body):
    """Wrap `body` in a module, compile it; return OK / ERROR / CRASH / HANG."""
    src = (HDR + "module m(p, n);\n inout p, n; electrical p, n;\n" + body + "\nendmodule\n")
    path = os.path.join(tempfile.gettempdir(), "vaflaplace_in.va")
    with open(path, "w") as f:
        f.write(src)
    try:
        r = subprocess.run([OPENVAF, path, "-o", OUT],
                           capture_output=True, text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode is not None and r.returncode < 0:
        return "CRASH"
    if "panicked at" in out or "has crashed" in out or r.returncode == 101:
        return "CRASH"
    return "OK" if r.returncode == 0 else "ERROR"


print("Enhancement-265: laplace_*/zi_* coefficient argument -- panic -> clean diagnostic")

# Malformed coefficient arguments: each was a compiler PANIC (exit 101); now a
# clean type-mismatch ERROR.
malformed = [
    ("[1] net as denominator  (laplace_nd(1,1,p))",
     " analog V(p,n) <+ laplace_nd(1.0, 1.0, p);"),
    ("[2] net as numerator    (laplace_nd(1,p,1))",
     " analog V(p,n) <+ laplace_nd(1.0, p, 1.0);"),
    ("[3] branch as coeff     (laplace_nd(1,1,br))",
     " branch (p,n) br; analog V(p,n) <+ laplace_nd(1.0, 1.0, br);"),
    ("[4] string as coeff     (laplace_nd(1,\"s\",1))",
     ' analog V(p,n) <+ laplace_nd(1.0, "s", 1.0);'),
    ("[5] net in zi_zp roots  (zi_zp(V,p,1,1,1))",
     " analog V(p,n) <+ zi_zp(V(p,n), p, 1.0, 1.0, 1.0);"),
    ("[6] empty direct denom  (laplace_nd(V,1,'{}))",
     " analog V(p,n) <+ laplace_nd(V(p,n), 1.0, '{});"),
]
for label, body in malformed:
    r = compile_src(body)
    check(label + " -> clean error (was a hir_lower panic)", r == "ERROR", r)

# Well-formed coefficient shapes: must still compile.
valid = [
    ("[7] real array literals        laplace_nd(V,'{1},'{1,tau})",
     " parameter real tau=1e-6; analog V(p,n) <+ laplace_nd(V(p,n), '{1.0}, '{1.0, tau});"),
    ("[8] integer-looking literals    laplace_nd(V,'{1},'{-1,1})",
     " analog V(p,n) <+ laplace_nd(V(p,n), '{1}, '{-1, 1});"),
    ("[9] scalar coefficient          laplace_nd(V,1.0,'{1,1})",
     " analog V(p,n) <+ laplace_nd(V(p,n), 1.0, '{1.0, 1.0});"),
    ("[10] bare array-variable ref     laplace_nd(V,c,'{1,1})",
     " real c[0:1]; analog begin c[0]=1.0; c[1]=1.0; V(p,n) <+ laplace_nd(V(p,n), c, '{1.0,1.0}); end"),
    ("[11] zi_nd form                 zi_nd(V,'{1},'{1,1},tol)",
     " analog V(p,n) <+ zi_nd(V(p,n), '{1.0}, '{1.0, 1.0}, 1e-9);"),
    ("[12] empty numerator -> H=0     laplace_nd(V,'{},'{1,1})",
     " analog V(p,n) <+ laplace_nd(V(p,n), '{}, '{1.0, 1.0});"),
    ("[13] empty pole list -> den=1   laplace_np(V,'{1},'{})",
     " analog V(p,n) <+ laplace_np(V(p,n), '{1.0}, '{});"),
]
for label, body in valid:
    r = compile_src(body)
    check(label + " -> compiles cleanly", r == "OK", r)

# The shipped canonical files behave the same way.
def run_file(name):
    path = os.path.join(HERE, name)
    try:
        r = subprocess.run([OPENVAF, path, "-o", OUT],
                           capture_output=True, text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if (r.returncode is not None and r.returncode < 0) or "panicked at" in out \
            or "has crashed" in out or r.returncode == 101:
        return "CRASH"
    return "OK" if r.returncode == 0 else "ERROR"

check("[14] bad_coeff_net.va clean-errors", run_file("bad_coeff_net.va") == "ERROR")
check("[15] good_filter.va compiles",       run_file("good_filter.va") == "OK")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
