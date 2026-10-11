#!/usr/bin/env python3
"""verify_powassoc.py -- Enhancement-865: `^` associates left to right in
`let`, as in the .param, the B-source, the manual and Verilog-A.

F10 of the third robustness campaign of 2026-10-10.

The manual (2.11.5) says equal-precedence binary operators evaluate left to
right, and the .param and the B-source take 2^3^2 as (2^3)^2 = 64; so does
Verilog-A's LRM for `**`. `let`'s grammar had '^' %right and gave 512. Unary
minus sits below '^' in all three ngspice parsers (-2^2 is -4), where the
manual's precedence table lists it above.

  [1] let 2^3^2 is 64 (512 on E-863)
  [2] let 2^0.5^2 and 2^2^3: the .param's and the B-source's values, to the bit
  [3] (control) a sign inside a chain: 2^-3^2 is 2^-9 in all three
  [4] (control) -2^2 is -4 in all three
  [5] (control) the .param's ** and ^ chains

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

WORK = tempfile.mkdtemp(prefix="powassoc_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def three(name, exprs):
    """each expression through a .param, a B-source and let"""
    body = []
    for i, e in enumerate(exprs):
        body += [".param q%d = {%s}" % (i, e), "vp%d p%d 0 dc {q%d}" % (i, i, i), "rp%d p%d 0 1" % (i, i),
                 "bb%d b%d 0 v = %s" % (i, i, e), "rb%d b%d 0 1" % (i, i)]
    ctl = ["set numdgt=17", "op"] + ["print v(p%d) v(b%d)" % (i, i) for i in range(len(exprs))]
    ctl += ["let l%d = %s" % (i, e) for i, e in enumerate(exprs)] + ["print l%d" % i for i in range(len(exprs))]
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\n%s\n.endc\n.end\n" % (name, "\n".join(body), "\n".join(ctl)))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=60,
                       errors="replace")
    out = p.stdout + p.stderr

    def num(pat):
        m = re.search(pat, out, re.M)
        return float(m.group(1)) if m else None
    return [(e, num(r"^v\(p%d\) = (\S+)" % i), num(r"^v\(b%d\) = (\S+)" % i), num(r"^l%d = (\S+)" % i))
            for i, e in enumerate(exprs)]


def same(rows, want=None):
    return all(p is not None and p == b == l and (want is None or p == w)
               for (e, p, b, l), w in zip(rows, want or [None] * len(rows)))


fmt = lambda rows: "; ".join("%s: %r %r %r" % r for r in rows)

# [1]
rows = three("chain", ["2^3^2"])
check("[1] let 2^3^2 is 64, as the .param and the B-source", same(rows, [64.0]), fmt(rows))

# [2]
rows = three("chains", ["2^0.5^2", "2^2^3", "3^2^0.5"])
check("[2] 2^0.5^2, 2^2^3, 3^2^0.5: the three parsers agree to the bit", same(rows),
      fmt(rows))

# [3]
rows = three("sign", ["2^-3^2"])
check("[3] (control) 2^-3^2 is 2^-9 in all three", same(rows, [2.0 ** -9]), fmt(rows))

# [4]
rows = three("neg", ["-2^2", "-(2)^2", "(-2)^2"])
check("[4] (control) -2^2 and -(2)^2 are -4, (-2)^2 is 4, in all three", same(rows, [-4.0, -4.0, 4.0]), fmt(rows))

# [5]
rows = three("pstar", ["2**3**2", "2**3^2"])
check("[5] (control) the .param's ** and ^ chains are 64", [r[1] for r in rows] == [64.0, 64.0],
      fmt(rows))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
