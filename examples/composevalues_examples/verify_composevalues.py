#!/usr/bin/env python3
"""verify_composevalues.py -- Enhancement-900: `compose name values ...` reads a
signed word after a complete value as a new value. F6 of the analyses
correctness campaign of 2026-10-16.

The values were flattened into one string and parsed as an expression list, so
`1 -2 3` was the list [1-2, 3]: a negative value was subtracted from the one
before it, without a word. The shell's lexer turns a comma after a word into a
word break, so `1, -2, 3` was the same. A word that starts with a sign, follows
a word ending an operand, and sits outside parentheses and brackets now starts
a new value, as in a MATLAB row.

  [1] `1 -2 3` is [1, -2, 3] (E-899: [-1, 3])
  [2] `1, -2, 3` is [1, -2, 3] (E-899: [-1, 3])
  [3] `1 +2 3` is [1, 2, 3] (E-899: [3, 3])
  [4] signed expressions: `1 -2*3 4`, `x -x`, `sin(0) -cos(0)`,
      `1 -(2+3) 4`, `3 -2 +1` (E-899: [-5, 4], [0], [-1], [-4, 4], [2])
  [5] eleven random values in [-5, 5], written as a program writes them: the
      same eleven values (E-899: 3, each a run of them summed)
  [6] the binary forms are unchanged: `1 - 2 3`, `1-2 3`, `(1 -2) 3`,
      `2 * -3 4`, `2 ^ -1 4`, `x gt -1 7`
  [7] bracketed negatives and complex values are unchanged: `1 (-2) 3`,
      `(1, -2) (3,4)`
  [8] errors are still reported: `1 -` is a syntax error, `1 -foo` names the
      missing vector, an empty list warns; none makes a vector

Exit code 0 = pass.
"""
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="composevalues_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, ctl):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* compose values\n.control\n" + ctl + "\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def compose(cases, pre=""):
    """{label: list of floats or None} for each `compose` value list"""
    ctl = [pre]
    for k, (vals, _) in enumerate(cases):
        ctl += ["compose c%d values %s" % (k, vals), "echo VEC%d $&c%d" % (k, k)]
    out = run("c%d" % len(cases), "\n".join(ctl))
    got = []
    for k in range(len(cases)):
        m = re.search(r"^VEC%d (.*)$" % k, out, re.M)
        try:
            got.append([float(x) for x in m.group(1).split()] if m else None)
        except ValueError:
            got.append(None)
    return got, out


def same(a, b, tol=1e-12):
    return a is not None and len(a) == len(b) and all(abs(x - y) <= tol * max(1.0, abs(y)) for x, y in zip(a, b))


def group(label, cases, pre=""):
    got, out = compose(cases, pre)
    bad = ["`%s` -> %s" % (v, g) for (v, want), g in zip(cases, got) if not same(g, want)]
    check(label, not bad, "; ".join(bad) if bad else ", ".join("`%s`" % v for v, _ in cases))


print("Enhancement-900: compose values reads a signed word as a new value")
group("[1] `1 -2 3` is [1, -2, 3]", [("1 -2 3", [1, -2, 3])])
group("[2] `1, -2, 3` is [1, -2, 3]", [("1, -2, 3", [1, -2, 3]), ("1,-2,3", [1, -2, 3])])
group("[3] `1 +2 3` is [1, 2, 3]", [("1 +2 3", [1, 2, 3])])
group("[4] signed expressions start new values",
      [("1 -2*3 4", [1, -6, 4]), ("x -x", [5, -5]), ("sin(0) -cos(0)", [0, -1]),
       ("1 -(2+3) 4", [1, -5, 4]), ("3 -2 +1", [3, -2, 1]), ("-1 -2 -3", [-1, -2, -3]),
       ("1e-3 -1e-3", [1e-3, -1e-3])], pre="let x = 5")

rng = random.Random(16)
txt = " ".join("%g" % rng.uniform(-5, 5) for _ in range(11))
vals = [float(x) for x in txt.split()]
got, out = compose([(txt, vals)])
check("[5] eleven random values in [-5, 5]: the same eleven values", same(got[0], vals, 1e-9),
      "%d values from `%s`" % (len(got[0]) if got[0] else 0, txt))

group("[6] the binary forms are unchanged",
      [("1 - 2 3", [-1, 3]), ("1-2 3", [-1, 3]), ("(1 -2) 3", [-1, 3]), ("2 * -3 4", [-6, 4]),
       ("2 ^ -1 4", [0.5, 4]), ("x gt -1 7", [1, 7])], pre="let x = 5")

out = run("cplx", "compose b values 1 (-2) 3\necho VB $&b\n"
          "compose z values (1, -2) (3,4)\nlet zr = real(z)\nlet zi = imag(z)\necho VR $&zr\necho VI $&zi")
m = [re.search(r"^%s (.*)$" % t, out, re.M) for t in ("VB", "VR", "VI")]
v = [[float(x) for x in g.group(1).split()] if g else None for g in m]
check("[7] bracketed negatives and complex values are unchanged",
      same(v[0], [1, -2, 3]) and same(v[1], [1, 3]) and same(v[2], [-2, 4]),
      "1 (-2) 3 -> %s; (1, -2) (3,4) -> re %s im %s" % tuple(v))

out1 = run("err1", "compose e1 values 1 -\ndisplay")
out2 = run("err2", "compose e2 values 1 -foo\ndisplay")
out3 = run("err3", "compose e3 values\ndisplay")
check("[8] errors are still reported, and no vector is made",
      "syntax error" in out1.lower() and "foo" in out2 and "NULL arithmetic expression" in out3
      and not re.search(r"^\s+e[123]\s+:", out1 + out2 + out3, re.M),
      "`1 -`: %s; `1 -foo`: %s; empty: %s" % (
          "syntax error" if "syntax error" in out1.lower() else "no error",
          "names foo" if "foo" in out2 else "no message",
          "warns" if "NULL arithmetic expression" in out3 else "silent"))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
