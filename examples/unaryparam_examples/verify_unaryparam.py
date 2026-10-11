#!/usr/bin/env python3
"""verify_unaryparam.py -- Enhancement-857: a sign after an operator in a
`.param` is unary, as in the B-source.

F2 of the third robustness campaign of 2026-10-10.

numparam read a minus after a binary operator by setting a flag that only a
NUMBER consumed. Before a name, a parenthesis or a function the flag was left
over and the formula refused, which stops the netlist (`{2*-p}`, `{1/-(2)}`,
`{2*-sin(1)}`). A second minus set the flag again instead of clearing it, so a
sign was lost without a word (`{2*--2}` was -4, `{2---2}` 4). The flag
negated the number before `^` saw it (`{2*-3^2}` was 18, the B-source -18).
A plus there was a misplaced operator (`{2*+3}`). A sign after an operator now
takes the power chain after it as its operand, as the B-source's grammar and
`let`'s do, and `let` takes a unary plus.

  [1] before a name: {2*-p}, {2 * - p} (refused on E-855)
  [2] before a parenthesis and a function: {1/-(2)}, {2^-(1)}, {2*-sin(1)}
  [3] two or three signs: {2*--2} 4, {0+--2} 2, {1/--2} 0.5, {2^--1} 2,
      {2---2} 0, {---2} -2 (one sign lost on E-855)
  [4] a sign before a power takes the chain: {2*-3^2} -18, {3*-2^2*2} -24,
      {1--2^2} 5, {2^-3^2} 2^-9 (18, 24, -3, 2^-6 on E-855)
  [5] a unary plus after an operator: {2*+3} 6, {2-+2} 0, {2*-+-3} 6
  [6] a sign with nothing after it is refused, naming it
  [7] the same through a subcircuit parameter and an element value
  [8] `let` takes a unary plus: 2*+3, +2 (a syntax error on E-855)
  [9] (control) the forms that already worked: {2*-3}, {-p*2}, {2*(-p)},
      {-3^2}, {2^-1}, {1e-3*-2}, {3*-2k}, {1>-3}
  [10] a table of 34 expressions: the .param and the B-source agree on each

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="unaryparam_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, control):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\n%s\n.endc\n.end\n" % (name, body, control))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=60,
                       errors="replace")
    return p.stdout + p.stderr


def params(name, exprs):
    """each expression as a .param, read back as the voltage of a source"""
    body = [".param p = 3"]
    for i, e in enumerate(exprs):
        body += [".param q%d = {%s}" % (i, e), "v%d n%d 0 dc {q%d}" % (i, i, i), "r%d n%d 0 1" % (i, i)]
    out = run(name, "\n".join(body), "op\n" + "\n".join("print v(n%d)" % i for i in range(len(exprs))))
    return [num(out, r"^v\(n%d\) = (\S+)" % i) for i in range(len(exprs))], out


def bsrc(name, exprs):
    body = [".param p = 3"]
    for i, e in enumerate(exprs):
        body += ["b%d n%d 0 v = %s" % (i, i, e), "r%d n%d 0 1" % (i, i)]
    out = run(name, "\n".join(body), "op\n" + "\n".join("print v(n%d)" % i for i in range(len(exprs))))
    return [num(out, r"^v\(n%d\) = (\S+)" % i) for i in range(len(exprs))], out


def num(out, pat):
    m = re.search(pat, out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def same(got, want):
    return all(g is not None and abs(g - w) <= 1e-12 * max(1.0, abs(w)) for g, w in zip(got, want))


def first_error(out):
    for line in out.splitlines():
        if re.search(r"rror|Nothing follows", line) and "incomplete or empty netlist" not in line:
            return line.strip()
    return ""


# [1]
got, out = params("name", ["2*-p", "2 * - p"])
check("[1] before a name: {2*-p} and {2 * - p} are -6", same(got, [-6, -6]), "%s %s" % (got, first_error(out)))

# [2]
got, out = params("paren", ["1/-(2)", "2^-(1)", "2*-sin(1)"])
check("[2] before a parenthesis and a function: {1/-(2)} {2^-(1)} {2*-sin(1)}",
      same(got, [-0.5, 0.5, -2 * 0.8414709848078965]), "%s %s" % (got, first_error(out)))

# [3]
got, out = params("twice", ["2*--2", "0+--2", "1/--2", "2^--1", "2---2", "---2"])
check("[3] two or three signs: 4, 2, 0.5, 2, 0, -2", same(got, [4, 2, 0.5, 2, 0, -2]),
      "%s %s" % (got, first_error(out)))

# [4]
got, out = params("power", ["2*-3^2", "3*-2^2*2", "1--2^2", "2^-3^2", "2*-(1+2)^2"])
check("[4] a sign before a power takes the chain: -18, -24, 5, 2^-9, -18",
      same(got, [-18, -24, 5, 2.0 ** -9, -18]), "%s %s" % (got, first_error(out)))

# [5]
got, out = params("plus", ["2*+3", "2-+2", "2*-+-3"])
check("[5] a unary plus after an operator: {2*+3} 6, {2-+2} 0, {2*-+-3} 6", same(got, [6, 0, 6]),
      "%s %s" % (got, first_error(out)))

# [6]
out = run("dangling", ".param p = 3\n.param q = {2*-}\nv1 n 0 dc {q}\nr1 n 0 1", "op\nprint v(n)")
check("[6] a sign with nothing after it is refused, naming it",
      'Nothing follows the "-" in 2*-' in out and num(out, r"^v\(n\) = (\S+)") is None, first_error(out))

# [7]
out = run("sub", "\n".join([
    ".param p = 3",
    ".subckt half a k=1",
    "va a 0 dc {0-k}",
    ".ends",
    "x1 n1 half k={2*-p}",
    "r1 n1 0 1",
    "v2 n2 0 dc {1-2*-p^2}",
    "r2 n2 0 1"]), "op\nprint v(n1)\nprint v(n2)")
got = [num(out, r"^v\(n1\) = (\S+)"), num(out, r"^v\(n2\) = (\S+)")]
check("[7] a subcircuit parameter k={2*-p} gives 6, an element value {1-2*-p^2} 19",
      same(got, [6, 19]), "%s %s" % (got, first_error(out)))

# [8]
out = run("let", "v1 1 0 1\nr1 1 0 1", "let x = 2*+3\nprint x\nlet y = +2\nprint y\nlet z = 2*-3^2\nprint z")
got = [num(out, r"^x = (\S+)"), num(out, r"^y = (\S+)"), num(out, r"^z = (\S+)")]
check("[8] `let` takes a unary plus: 2*+3 is 6, +2 is 2 (and 2*-3^2 is -18)", same(got, [6, 2, -18]),
      "%s %s" % (got, first_error(out)))

# [9]
got, out = params("control", ["2*-3", "-p*2", "2*(-p)", "-3^2", "2^-1", "1e-3*-2", "3*-2k", "1>-3", "p-1"])
check("[9] (control) the forms that already worked",
      same(got, [-6, -6, -6, -9, 0.5, -2e-3, -6000, 1, 2]), "%s %s" % (got, first_error(out)))

# [10]
TABLE = ["2*-p", "2 * - p", "1/-(2)", "2^-(1)", "2*-sin(1)", "2*--2", "0+--2", "1/--2", "2^--1",
         "2---2", "---2", "-+2", "+-2", "2*-3^2", "3*-2^2*2", "1--2^2", "2^-3^2", "2^-3^2*4",
         "2*-(1+2)^2", "2*+3", "2-+2", "2*-+-3", "3*-2k", "2*-1e-3", "2*-1.5e2u", "1>-p",
         "max(-p,-2*-p)", "2^-2*3", "-2*-3", "2/-2*3", "2+-3*2", "1-2^-1", "2*(-3)^2", "-(2)^2"]
a, oa = params("table_param", TABLE)
b, ob = bsrc("table_bsrc", TABLE)
bad = [(e, x, y) for e, x, y in zip(TABLE, a, b)
       if x is None or y is None or abs(x - y) > 1e-12 * max(1.0, abs(y))]
check("[10] %d expressions: the .param and the B-source agree on each" % len(TABLE), not bad,
      "%d differ, first %s" % (len(bad), bad[0]) if bad else "")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
