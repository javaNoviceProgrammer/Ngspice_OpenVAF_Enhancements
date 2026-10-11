#!/usr/bin/env python3
"""verify_cplxmod.py -- Enhancement-864: complex `%` takes a real divisor.

F9 of the third robustness campaign of 2026-10-10.

Complex `%` takes the real and imaginary parts modulo the divisor's real and
imaginary parts (E-480), and checked that both of the divisor's were nonzero. A
real divisor, promoted to complex, has an imaginary part of 0, so `v(1) % 2`
after an ac failed "argument out of range for mod" while `v(1) % (2+j(1))`
evaluated. A divisor with no imaginary part now takes both parts modulo itself.

  [1] after an ac, v(1) % 2 evaluates, each part modulo 2 (refused on E-863)
  [2] a complex scalar: (5.5 + 7.25j) % 2 is 1.5 + 1.25j, % 0.3 part by part
  [3] (control) a divisor of 0 is still refused
  [4] (control) a complex divisor: part by part, as E-480 made it
  [5] (control) real % real: 5.5 % 3 is 2.5, -5 % 3 is -2

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

WORK = tempfile.mkdtemp(prefix="cplxmod_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, control, body="v1 1 0 dc 0 ac 5.5 52.8\nr1 1 0 1"):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\n%s\n.endc\n.end\n" % (name, body, control))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=60,
                       errors="replace")
    return p.stdout + p.stderr


def cval(out, name):
    m = re.search(r"^%s = (\S+?),(\S+)$" % re.escape(name), out, re.M)
    return complex(float(m.group(1)), float(m.group(2))) if m else None


def rval(out, name):
    m = re.search(r"^%s = (\S+)$" % re.escape(name), out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def err(out):
    m = re.search(r"Error: argument.*", out)
    return m.group(0) if m else ""


# [1]
out = run("ac", "ac lin 1 1k 1k\nlet z = v(1)\nlet a = v(1) % 2\nprint z a")
z, a = cval(out, "z"), cval(out, "a")
ok = z is not None and a is not None and a == complex(math.fmod(z.real, 2), math.fmod(z.imag, 2))
check("[1] after an ac, v(1) % 2 evaluates, each part modulo 2", ok, err(out) or "%r -> %r" % (z, a))

# [2]
out = run("scalar", "let z = 5.5 + j(7.25)\nlet a = z % 2\nlet b = z % 0.3\nprint a b")
a, b = cval(out, "a"), cval(out, "b")
check("[2] (5.5 + 7.25j) % 2 is 1.5 + 1.25j, and % 0.3 part by part",
      a == complex(1.5, 1.25) and b == complex(math.fmod(5.5, 0.3), math.fmod(7.25, 0.3)),
      err(out) or "%r %r" % (a, b))

# [3]
out = run("zero", "let z = 5.5 + j(7.25)\nlet a = z % 0\nprint a")
check("[3] (control) a divisor of 0 is still refused", "argument out of range for mod" in out and cval(out, "a") is None,
      err(out))

# [4]
out = run("cplx", "let z = 5.5 + j(7.25)\nlet a = z % (2 + j(3))\nprint a")
a = cval(out, "a")
check("[4] (control) a complex divisor: part by part", a == complex(math.fmod(5.5, 2), math.fmod(7.25, 3)),
      err(out) or "%r" % a)

# [5]
out = run("real", "let a = 5.5 % 3\nlet b = -5 % 3\nprint a b")
check("[5] (control) real % real: 5.5 % 3 is 2.5, -5 % 3 is -2", rval(out, "a") == 2.5 and rval(out, "b") == -2.0,
      "%r %r" % (rval(out, "a"), rval(out, "b")))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
