#!/usr/bin/env python3
"""Enhancement-649: a nature or discipline attribute value is a constant
expression, not only a literal (2026-09-16 hunt, F5).

LRM A.1.6: `nature_attribute_expression ::= constant_expression |
nature_identifier | nature_access_identifier`. openvaf-r folded an attribute
value with a folder that sees one literal and an optional sign, so
`abstol = 1e-3*1e-3` was refused as "not a real constant" (and the nature was
left with no abstol at all), while a user-defined attribute spelled the same
way reached the .osdi tables with no value, in silence.

Now parentheses, unary +/-, binary + - * / % ** and the integer shifts fold
with the LRM's operand rules (two integers make an integer, any real makes
the result real, a negative-exponent integer ** follows IEEE 1364-2005 Table
5-6 as the run-time path does). The folded abstol reaches ngspice's
convergence test (E-539) with the same value the model reads back from
`p.potential.abstol`; a discipline's `potential.abstol = 1e-3*1e-3` override
folds too, and a `[msb:lsb]` bound shares the folder (E-405) so it takes `**`
and `<<<`. A name, a function call or a string still does not fold, and says
so with a help line naming what does.
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
WORK = tempfile.mkdtemp(prefix="natureexpr_")
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


def run(tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* natureexpr {tag}\nv1 1 0 1\n.model m m\nna1 1 0 m\n.control\nset noinit\nset ngdebug\n"
                f"pre_osdi {tag}.osdi\nop\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def nat(val, extra="", disc="potential N1; flow F1;", read=True):
    # `read`: the model also prints its own view of the attribute (E-45's body
    # path, which always evaluated the full expression) so the two can be compared
    return (extra + f'nature N1; units = "x"; access = X1; abstol = {val}; endnature\n'
            'nature F1; units = "y"; access = Y1; abstol = 1e-12; endnature\n'
            f'discipline d1; {disc} enddiscipline\n'
            'module m(p,n); inout p,n; d1 p,n;\nanalog begin\n'
            + ('  $strobe("attr=%g", p.potential.abstol);\n' if read else '')
            + '  Y1(p,n) <+ X1(p,n);\nend\nendmodule\n')


def stamped(out):
    # E-585: "OSDI: m: convergence abstol = 1e-06 on 1 node"
    m = re.search(r"convergence abstol = (\S+) on (\d+) node", out)
    return (float(m.group(1)), int(m.group(2))) if m else (None, 0)


def read_back(out):
    m = re.search(r"attr=(\S+)", out)
    return float(m.group(1)) if m else None


def near(x, ref, tol=1e-5):
    return x is not None and abs(x - ref) <= tol * max(abs(ref), 1e-300)


def accepted(label, src, tag, want):
    """Compiles, and the solver stamps `want` on the node (E-539's path, the
    .osdi table) -- the same value the model reads back through the body."""
    ok, out = compile_src(src, tag)
    o = run(tag) if ok else ""
    v, n = stamped(o)
    return check(label, ok and n == 1 and near(v, want) and near(read_back(o), want),
                 (out.strip().splitlines() or [""])[0][:70] if not ok else f"stamped {v} on {n}, read back {read_back(o)}")


def refused(label, src, tag, *needles):
    ok, out = compile_src(src, tag)
    return check(label, not ok and all(nd in out for nd in needles) and out.count("error:") == 2,
                 (out.strip().splitlines() or [""])[0][:90])


BAD = "which is not a usable absolute tolerance"
NOTC = "declares an abstol that is not a real constant"
HELP = "help: LRM A.1.6 allows a constant expression here"

# ---------------------------------------------------------------- folds, and reaches the solver
ok, out = compile_src(nat("1e-3*1e-3"), "f1")
check("[1] abstol = 1e-3*1e-3 compiles -- the hunt's reproducer", ok, (out.strip().splitlines() or [""])[0][:70])
o = run("f1") if ok else ""
v, n = stamped(o)
check("[2] ... the solver stamps 1e-6 on the node, the value the model reads back from p.potential.abstol",
      n == 1 and near(v, 1e-6) and near(read_back(o), 1e-6), f"stamped {v} on {n}, read back {read_back(o)}")
accepted("[3] parentheses: abstol = (1e-6)", nat("(1e-6)"), "f3", 1e-6)
accepted("[4] a quotient: abstol = 1e-6/1000 is 1e-9", nat("1e-6/1000"), "f4", 1e-9)
accepted("[5] a real power: abstol = 2.0**-20", nat("2.0**-20"), "f5", 2.0 ** -20)
accepted("[6] nested signs: abstol = -(-1e-6)", nat("-(-1e-6)"), "f6", 1e-6)
accepted("[7] a `define in an expression: `MY*`MY with `define MY 1e-3", nat("`MY*`MY", extra="`define MY 1e-3\n"), "f7", 1e-6)
accepted("[8] abstol = 1e-6+0.0 -- E-422 called it 'perfectly sane' and pinned the refusal", nat("1e-6+0.0"), "f8", 1e-6)
accepted("[9] a real remainder: abstol = 7.5 % 2 is 1.5", nat("7.5 % 2"), "f9", 1.5)
accepted("[10] a discipline override folds too: potential.abstol = 1e-3*1e-3 over a nature saying 1e-12",
         nat("1e-12", disc="potential N1; flow F1; potential.abstol = 1e-3*1e-3;"), "f10", 1e-6)
accepted("[11] a literal abstol is unchanged (1e-12)", nat("1e-12"), "f11", 1e-12)

# ---------------------------------------------------------------- folds to a value that is then refused
refused("[12] integer operands make an integer (LRM 4.1): abstol = 1/1000000 is 0", nat("1/1000000"), "r12", "abstol = 0,", BAD)
refused("[13] an integer ** with a negative exponent (Table 5-6): abstol = 10**-6 is 0", nat("10**-6"), "r13", "abstol = 0,", BAD)
refused("[14] the remainder takes the dividend's sign (4.1.4): abstol = -7.5 % 2 is -1.5", nat("-7.5 % 2"), "r14", "abstol = -1.5,", BAD)
refused("[15] abstol = 1.0/0.0 is refused as inf, by value, no longer as 'not a constant'", nat("1.0/0.0"), "r15", "abstol = inf,", BAD)
refused("[16] abstol = 0.0/0.0 is refused as NaN", nat("0.0/0.0"), "r16", "abstol = NaN,", BAD)

# ---------------------------------------------------------------- still not constant, now with a help line
refused("[17] a string is still not a real constant, and the help line names what folds", nat('"abc"', read=False), "r17", NOTC, HELP)
refused("[18] a name (1e-3*x) is still not a constant here", nat("1e-3*x"), "r18", NOTC, HELP)
refused("[19] a function call (pow(10,-6)) is still not a constant here", nat("pow(10,-6)"), "r19", NOTC, HELP)

# ---------------------------------------------------------------- the shared width-bound folder (E-405)
ok, out = compile_src("module m(p,n); inout p,n; electrical p,n; real a[0:2**2-1]; integer b[0:(1<<<1)];\n"
                      "analog begin a[3] = 3.0; b[2] = 2; $strobe(\"w=%g %d\", a[3], b[2]); I(p,n) <+ V(p,n); end\nendmodule\n", "w20")
o = run("w20") if ok else ""
check("[20] a [msb:lsb] bound takes ** and <<< through the same folder: a[0:2**2-1], b[0:(1<<<1)] (w=3 2)",
      ok and "w=3 2" in o, (out.strip().splitlines() or [""])[0][:70] if not ok else "")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
