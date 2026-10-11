#!/usr/bin/env python3
"""verify_lettan.py -- Enhancement-863: `let` takes tan(0).

F8 of the third robustness campaign of 2026-10-10.

d_tan, the front end's real tangent, checked rcheck(tan(x) != 0), which refused
a valid result: `let x = tan(0)` failed "argument out of range for tan" while
tan(0.5) was fine, and tan(0) is 0 in a .param and a B-source. The pole it
meant to guard is never exactly met by a double; the check is now that the
result is finite.

  [1] let a = tan(0) is 0 (refused on E-861)
  [2] a vector with a 0 in it: tan of each element
  [3] with units=degrees: tan(0) is 0, tan(45) is 1 to rounding
  [4] (control) tan(0.5), tan(-0.5), and a complex tan(0)
  [5] (control) the .param and the B-source give 0 for tan(0)

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="lettan_")
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


def val(out, name):
    m = re.search(r"^%s = (\S+?)(,\S+)?$" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


PLAIN = "v1 1 0 1\nr1 1 0 1"

# [1]
out = run("zero", PLAIN, "let a = tan(0)\nprint a")
check("[1] let a = tan(0) is 0", val(out, "a") == 0.0 and "out of range" not in out,
      (re.search(r"Error: argument.*", out) or [""])[0] or "a = %r" % val(out, "a"))

# [2]
out = run("vec", PLAIN, "let v = vector(4) - 1\nlet t = tan(v)\nprint t")
rows = [float(x) for x in re.findall(r"^\d+\s+(\S+)\s*$", out, re.M)]
want = [math.tan(x) for x in (-1, 0, 1, 2)]
check("[2] tan of a vector with a 0 in it: tan(-1), 0, tan(1), tan(2)",
      len(rows) == 4 and all(abs(a - b) <= 1e-15 * max(1, abs(b)) for a, b in zip(rows, want)), "%r" % rows)

# [3]
out = run("deg", PLAIN, "set units=degrees\nlet a = tan(0)\nlet b = tan(45)\nprint a b")
check("[3] units=degrees: tan(0) is 0 and tan(45) is 1 to rounding",
      val(out, "a") == 0.0 and val(out, "b") is not None and abs(val(out, "b") - 1) < 1e-15,
      "%r %r" % (val(out, "a"), val(out, "b")))

# [4]
out = run("ctl", PLAIN, "let a = tan(0.5)\nlet b = tan(-0.5)\nlet c = tan(0 + j(0))\nprint a b c")
check("[4] (control) tan(0.5), tan(-0.5) and a complex tan(0)",
      val(out, "a") == math.tan(0.5) and val(out, "b") == math.tan(-0.5) and val(out, "c") == 0.0,
      "%r %r %r" % (val(out, "a"), val(out, "b"), val(out, "c")))

# [5]
out = run("netlist", ".param p = {tan(0)}\nv1 a 0 dc {p}\nr1 a 0 1\nb1 b 0 v = tan(0)\nr2 b 0 1",
          "op\nprint v(a) v(b)")
check("[5] (control) the .param and the B-source give 0 for tan(0)",
      val(out, "v(a)") == 0.0 and val(out, "v(b)") == 0.0, "%r %r" % (val(out, "v(a)"), val(out, "v(b)")))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
