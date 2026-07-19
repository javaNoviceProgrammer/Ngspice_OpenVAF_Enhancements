#!/usr/bin/env python3
"""Enhancement-239: fix a NULL-deref crash on a one-argument min/max/pow/pwr.

The behavioral-source / .param expression evaluator (`PTeval` in
spicelib/parser/ifeval.c) evaluates the two-argument functions pow/pwr/min/max by
reading their operands as `tree->left->left` and `tree->left->right` -- i.e. it
assumes the argument is a `PT_COMMA` pair. A ONE-argument call like `min(1)`
makes the argument a scalar node whose `->left` is NULL, so PTeval dereferenced
NULL and crashed (SIGSEGV) at circuit-load time -- reachable from any B-source,
E/G source, or `.param` expression.

E-239 rejects the wrong arity at parse time (`PT_mkfnode`, inpptree.c): these
four functions now require a comma pair and otherwise emit a clean
"requires two arguments" error instead of crashing.

Checks (batch mode, -b). A crash shows up as a NEGATIVE return code (signal);
a clean run is 0 (a valid circuit) or a positive error exit for the rejected
one-argument forms.
 1. one-argument `min(1)`/`max(1)`/`pow(2)`/`pwr(2)` in a B-source no longer
    crash (were SIGSEGV);
 2. the same one-argument misuse inside a `.param` expression no longer crashes;
 3. well-formed two-argument calls still compute the correct value:
    min(3,7)=3, max(3,7)=7, pow(2,10)=1024, pwr(2,3)=8.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    cir = os.path.join(HERE, "_fa.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=40)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


def bsrc(expr, control=False):
    tail = (".control\nop\nprint v(2)\n.endc\n" if control else ".op\n")
    return (f"* func arity\nv1 1 0 dc 1\nr1 1 0 1k\n"
            f"b1 2 0 v={expr}\nr2 2 0 1k\n{tail}.end\n")


# 1: one-arg forms in a B-source must not crash
noncrash = all(run(bsrc(e))[0] >= 0 for e in ("min(1)", "max(1)", "pow(2)", "pwr(2)"))
check("one-arg min/max/pow/pwr in a B-source no longer crash (were SIGSEGV)",
      noncrash)

# 2: one-arg misuse inside a .param expression must not crash
rc, _ = run("* param arity\n.param p={min(1)}\nv1 1 0 dc 1\nr1 1 0 {p}\n"
            ".op\n.end\n")
check("one-arg min() inside a .param expression no longer crashes", rc >= 0,
      f"rc={rc}")

# 3: well-formed two-arg calls still correct
cases = {"min(3,7)": 3.0, "max(3,7)": 7.0, "pow(2,10)": 1024.0, "pwr(2,3)": 8.0}
allok = True
detail = []
for expr, want in cases.items():
    rc, out = run(bsrc(expr, control=True))
    m = re.search(r"v\(2\)\s*=\s*([-\d.eE+]+)", out)
    got = float(m.group(1)) if m else None
    ok = rc == 0 and got is not None and abs(got - want) < 1e-6
    allok = allok and ok
    detail.append(f"{expr}={got}")
check("well-formed two-arg calls still correct (min/max/pow/pwr)", allok,
      " ".join(detail))

p = os.path.join(HERE, "_fa.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
