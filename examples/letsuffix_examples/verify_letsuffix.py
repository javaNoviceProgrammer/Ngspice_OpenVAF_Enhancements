#!/usr/bin/env python3
"""verify_letsuffix.py -- Enhancement-859: the front end reads a scale factor
after an exponent, as the netlist does.

F4 of the third robustness campaign of 2026-10-10.

ft_numparse, the front end's number reader, took a scale factor or an exponent
and never both: `let x = 1.5e2u` was 150 where an element value 1.5e2u is
1.5e-4, `1e3meg` was 1000 and `1e-3k` 0.001, without a word. It now reads the
exponent, then the scale factor, into one exact decimal, so the value is the
netlist's to the bit.

  [1] let x = 1.5e2u is 1.5e-4 (150 on E-857)
  [2] 1e3meg, 1e-3k, 4.7e3p, 2.2e-1u, 3.3e2mil
  [3] 300 spellings with an exponent and a suffix: let is the element value to
      the bit
  [4] inside an expression: a vector times 1e-3k
  [5] (control) an `e` that is not an exponent is trailing text: 1em, 2ex are 1, 2
  [6] (control) plain numbers and suffixes: 1.5e2, 33k, 1mil, 1.1u

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

WORK = tempfile.mkdtemp(prefix="letsuffix_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def pairs(name, texts):
    """each text as an element value and through `let`; both read back"""
    lines = []
    for i, t in enumerate(texts):
        lines += ["ve%d e%d 0 dc %s" % (i, i, t), "re%d e%d 0 1" % (i, i)]
    ctl = ["set numdgt=17", "op"] + ["print v(e%d)" % i for i in range(len(texts))]
    ctl += ["let x%d = %s" % (i, t) for i, t in enumerate(texts)] + ["print x%d" % i for i in range(len(texts))]
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\n%s\n.endc\n.end\n" % (name, "\n".join(lines), "\n".join(ctl)))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    out = p.stdout + p.stderr
    rows = []
    for i, t in enumerate(texts):
        e = re.search(r"^v\(e%d\) = (\S+)" % i, out, re.M)
        x = re.search(r"^x%d = (\S+)" % i, out, re.M)
        rows.append((t, float(e.group(1)) if e else None, float(x.group(1)) if x else None))
    return rows


def bad(rows):
    return [(t, e, x) for t, e, x in rows if e is None or x is None or e != x]


def let_values(name, cmds, names):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\nv1 1 0 dc 2\nr1 1 0 1\n.control\nset numdgt=17\nop\n%s\n%s\n.endc\n.end\n"
                % (name, "\n".join(cmds), "\n".join("print " + n for n in names)))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    out = p.stdout + p.stderr
    got = []
    for n in names:
        m = re.search(r"^%s = (\S+)" % re.escape(n), out, re.M)
        got.append(float(m.group(1)) if m else None)
    return got


# [1]
rows = pairs("one", ["1.5e2u"])
check("[1] let x = 1.5e2u is 1.5e-4, the element value", not bad(rows) and rows[0][2] == 1.5e-4,
      "element %r, let %r" % rows[0][1:])

# [2]
rows = pairs("table", ["1e3meg", "1e-3k", "4.7e3p", "2.2e-1u", "3.3e2mil"])
check("[2] 1e3meg, 1e-3k, 4.7e3p, 2.2e-1u, 3.3e2mil: let is the element value", not bad(rows),
      "; ".join("%s: %r vs %r" % r for r in bad(rows)))

# [3]
rng = random.Random(11)
S = ["t", "g", "k", "m", "u", "n", "p", "f", "a", "meg", "mil"]
texts = []
for _ in range(300):
    m = rng.choice(["%d" % rng.randint(1, 999), "%.*f" % (rng.randint(1, 5), rng.uniform(0, 100))])
    texts.append("%se%d%s" % (m, rng.randint(-12, 12), rng.choice(S)))
rows = pairs("random", texts)
b = bad(rows)
check("[3] 300 spellings with an exponent and a suffix: let is the element value to the bit",
      not b and len(rows) == 300, "%d differ, first %s" % (len(b), b[0]) if b else "")

# [4]
got = let_values("expr", ["let y = v(1) * 1e-3k", "let z = 2e1u + 0"], ["y", "z"])
check("[4] in an expression: v(1) * 1e-3k is 2, 2e1u + 0 is 2e-5", got == [2.0, 2e-5], "%r" % got)

# [5]
got = let_values("trail", ["let a = 1em", "let b = 2ex"], ["a", "b"])
check("[5] (control) an e that is not an exponent is trailing text: 1em is 1, 2ex is 2", got == [1.0, 2.0], "%r" % got)

# [6]
rows = pairs("plain", ["1.5e2", "33k", "1mil", "1.1u", "7m", "2meg"])
check("[6] (control) plain numbers and suffixes: let is the element value", not bad(rows),
      "; ".join("%s: %r vs %r" % r for r in bad(rows)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
