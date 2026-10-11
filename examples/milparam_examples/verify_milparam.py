#!/usr/bin/env python3
"""verify_milparam.py -- Enhancement-858: a `.param` reads a suffixed number as
the netlist does, and passes its value on with every digit.

F3 of the third robustness campaign of 2026-10-10.

numparam's suffix table had no `mil`: it read `m` and let "il" go, so `{1mil}`
was 1e-3 where `r1 1 0 1mil`, a B-source and `let` give 25.4e-6, the manual's
value -- the same text 39 times apart in one netlist. The dig found two more
ways a `.param` drifted from the netlist's reading of the same text. A mantissa
with its own exponent was multiplied by the suffix, a second rounding:
`{66.5e4u}` was 0.6649999999999999 where the netlist reads 0.665, 37 of 300
such spellings an ulp off. And the value went back into the deck with 16
significant digits, which a double does not always survive: `{0.1+0.2}` reached
the element as 0.3.

  [1] {1mil} is 1mil to the bit (1e-3 on E-857)
  [2] mil's spellings: 2.5mil, 1MIL, 10mils, 3.3e2mil, 1e-3mil
  [3] mil in an expression, and through a subcircuit parameter
  [4] 300 spellings with an exponent and a suffix: each .param is the element
      value to the bit (37 an ulp off on E-857)
  [5] 17 digits reach the element: {0.1+0.2}, {sin(45f/7.1f)} as the B-source
  [6] (control) plain suffixes, and m still milli

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

WORK = tempfile.mkdtemp(prefix="milparam_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, lines, prints):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\nop\n%s\n.endc\n.end\n"
                % (name, "\n".join(lines), "\n".join("print " + p for p in prints)))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    return p.stdout + p.stderr


def val(out, node):
    m = re.search(r"^v\(%s\) = (\S+)" % re.escape(node), out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def pairs(name, texts, param_text=None):
    """each text as an element value and as {text} in a .param; both read back"""
    lines = []
    for i, t in enumerate(texts):
        pt = param_text(t) if param_text else t
        lines += ["ve%d e%d 0 dc %s" % (i, i, t), "re%d e%d 0 1" % (i, i),
                  ".param q%d = {%s}" % (i, pt), "vp%d p%d 0 dc {q%d}" % (i, i, i), "rp%d p%d 0 1" % (i, i)]
    out = run(name, lines, ["v(e%d) v(p%d)" % (i, i) for i in range(len(texts))])
    return [(t, val(out, "e%d" % i), val(out, "p%d" % i)) for i, t in enumerate(texts)]


def bad(rows):
    return [(t, e, p) for t, e, p in rows if e is None or p is None or e != p]


# [1]
rows = pairs("mil1", ["1mil"])
check("[1] {1mil} is 1mil to the bit, 2.5399999999999997e-05", not bad(rows) and rows[0][1] == 25.4 * 1e-6,
      "element %r, .param %r" % rows[0][1:])

# [2]
rows = pairs("mils", ["2.5mil", "1MIL", "10mils", "3.3e2mil", "1e-3mil"])
check("[2] mil's spellings: 2.5mil, 1MIL, 10mils, 3.3e2mil, 1e-3mil", not bad(rows),
      "; ".join("%s: %r vs %r" % r for r in bad(rows)))

# [3]
out = run("milexpr", [".param w = 2mil", ".param q = {2*w + 1mil}", "v1 a 0 dc {q}", "r1 a 0 1",
                      ".subckt wire n wid=1",
                      "vw n 0 dc {wid}",
                      ".ends",
                      "x1 b wire wid=4mil", "r2 b 0 1"],
          ["v(a)", "v(b)"])
got = (val(out, "a"), val(out, "b"))
check("[3] {2*w + 1mil} with w = 2mil is 5 mil, and a subcircuit's wid=4mil is 4 mil",
      got[0] is not None and abs(got[0] - 5 * 25.4e-6) < 1e-18 and got[1] is not None and
      abs(got[1] - 4 * 25.4e-6) < 1e-18, "%r %r" % got)

# [4]
rng = random.Random(7)
S = ["t", "g", "k", "m", "u", "n", "p", "f", "a", "meg", "mil"]
texts = []
for _ in range(300):
    m = rng.choice(["%d" % rng.randint(1, 999), "%.*f" % (rng.randint(1, 5), rng.uniform(0, 100))])
    texts.append("%se%d%s" % (m, rng.randint(-12, 12), rng.choice(S)))
rows = pairs("random", texts)
b = bad(rows)
check("[4] 300 spellings with an exponent and a suffix: the .param is the element value to the bit",
      not b and len(rows) == 300, "%d differ, first %s" % (len(b), b[0]) if b else "")

# [5]
out = run("digits", [".param a = {0.1+0.2}", "v1 a 0 dc {a}", "r1 a 0 1",
                     ".param s = {sin(45f/7.1f)}", "v2 s 0 dc {s}", "r2 s 0 1",
                     "b3 bs 0 v = sin(45f/7.1f)", "r3 bs 0 1"],
          ["v(a)", "v(s)", "v(bs)"])
got = (val(out, "a"), val(out, "s"), val(out, "bs"))
check("[5] 17 digits reach the element: {0.1+0.2} is 0.30000000000000004, {sin(45f/7.1f)} the B-source's",
      got[0] == 0.1 + 0.2 and got[1] is not None and got[1] == got[2], "%r %r %r" % got)

# [6]
rows = pairs("plain", ["1.1u", "33k", "1meg", "7m", "2.2e-1", "4.7p", "1m"])
check("[6] (control) plain suffixes, and m still milli: the .param is the element value",
      not bad(rows) and rows[-1][2] == 1e-3, "; ".join("%s: %r vs %r" % r for r in bad(rows)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
