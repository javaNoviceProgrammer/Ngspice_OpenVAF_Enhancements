#!/usr/bin/env python3
"""verify_maxordnote.py -- Enhancement-853: `maxord` says when it has no effect,
and trap stays at order 2.

F9 of the second robustness campaign of 2026-10-10.

The stock order control only toggles Gear between orders 1 and 2; dynorder
(Enhancement-128) and ordfix (Enhancement-181) are the ways above 2. maxord was
accepted up to 6 and range-checked, and `method=gear maxord=6` was the run of
maxord=2 to the last digit, without a word. A note now says so. Trap has no order
above 2: dynorder and ordfix took it to 3, where NIcomCof refuses the order and
the step ran on the last step's coefficients, and maxord also set dynorder's
order hold. Trap now stays at 2, and its maxord has no effect either way.

  [1] gear maxord=6: the note names maxord=6, dynorder and ordfix, and the run is
      the run of maxord=2
  [2] (control) no note for gear maxord=2, gear maxord=6 with dynorder, or gear
      with ordfix=5
  [3] trap maxord=3: the trap note
  [4] trap with dynorder: maxord=3 and maxord=6 give the run of maxord=2, bit for
      bit, with no rejected step
  [5] trap with ordfix=3 and ordfix=6: the run of ordfix=2, bit for bit; on
      E-852 ordfix=3 under trap ran past 300 s
  [6] (control) gear maxord=6 with dynorder still rises above order 2

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

WORK = tempfile.mkdtemp(prefix="maxordnote_")
checks = passed = 0
NET = "v1 1 0 sin(0 1 1meg)\nr1 1 2 1k\nc1 2 0 100p\nl1 2 3 10u\nr3 3 0 50"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(opts):
    """the run's output, its v(3) samples as text, and the order report"""
    name = re.sub(r"\W+", "_", opts)
    out = os.path.join(WORK, name + ".txt")
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* maxord\n%s\n.options %s\n.control\nset numdgt=17\nset ngdebug\ntran 1n 5u\n"
                "wrdata %s v(3)\n.endc\n.end\n" % (NET, opts, out))
    try:
        p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=60,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", None      # trap at order 3 on E-852
    text = p.stdout + p.stderr
    rows = open(out).read() if os.path.exists(out) else ""
    m = re.search(r"highest integration order used = (\d+) of maxord \d+; (\d+) accepted / (\d+) rejected",
                  text)
    order = (int(m.group(1)), int(m.group(3))) if m else None
    return text, rows, order


NOTE = "Note: maxord="

# [1], [2]
t6, r6, _ = run("method=gear maxord=6")
t2, r2, _ = run("method=gear maxord=2")
check("[1] gear maxord=6: the note names maxord=6, dynorder and ordfix, and the run is maxord=2's",
      "Note: maxord=6 has no effect without dynorder" in t6 and "dynorder" in t6 and "ordfix=6" in t6
      and r6 == r2 and r6 != "", "note" if NOTE in t6 else "no note")
td, _, od = run("method=gear maxord=6 dynorder")
tf, _, _ = run("method=gear maxord=5 ordfix=5")
check("[2] (control) no note for gear maxord=2, gear maxord=6 dynorder, or gear ordfix=5",
      NOTE not in t2 and NOTE not in td and NOTE not in tf)

# [3]
t3, _, _ = run("maxord=3")
check("[3] trap maxord=3: the trap note", "Note: maxord=3 has no effect with method=trap" in t3)

# [4]
_, a2, o2 = run("maxord=2 dynorder")
_, a3, o3 = run("maxord=3 dynorder")
_, a6, o6 = run("maxord=6 dynorder")
check("[4] trap with dynorder: maxord=3 and 6 give the run of maxord=2, with no rejected step "
      "(order 3 and 19 rejections on E-852)",
      a2 != "" and a3 == a2 and a6 == a2 and o3 is not None and o3[0] == 2 and o3[1] == 0,
      f"order/rejected {o2} {o3} {o6}")

# [5]
_, f2, _ = run("maxord=2 ordfix=2")
_, f3, _ = run("maxord=3 ordfix=3")
_, f6, _ = run("maxord=6 ordfix=6")
check("[5] trap with ordfix=3 and ordfix=6: the run of ordfix=2, bit for bit (hung on E-852)",
      f2 != "" and f3 == f2 and f6 == f2)

# [6]
check("[6] (control) gear maxord=6 with dynorder still rises above order 2",
      od is not None and od[0] > 2, f"highest order {od[0] if od else None}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
