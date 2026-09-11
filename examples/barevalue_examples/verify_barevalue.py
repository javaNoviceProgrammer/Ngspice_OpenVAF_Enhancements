#!/usr/bin/env python3
"""Enhancement-597: a parameter name without a value is refused, not zeroed.

`n1 a 0 im w=2 m` -- the `=3` lost from `m` -- read the bare `m`, asked for
its value at the end of the line, got 0 from the evaluator's error path and
applied it: m = 0, the device gone from every analysis, nothing said (F2 of
the 2026-09-10 integration hunt). `temp` alone was 0 C, a second bare `w` was
w = 0 refused deep in setup with no value in the message, a `.model` card's
instance-parameter default (`.model im istr width`) put 0 into every instance,
and an integer that does not fit was applied as 0 on an instance line. A bare
word straight after the model name (`n1 a 0 im k`) was taken as the model,
reported as "Unable to find definition of model k", and the card it hid was
commented out as unused.

Checks (built-in devices too; the parser is shared):
  [1] a bare name after a value: refused, named, with the fix spelled out
  [2] a bare name followed by a token that is not a number
  [3] the .model card's instance default: bare name, bad integer
  [4] string: bare name refused, "" legal on the line and on the card
  [5] integer: 1e300 refused on the line and on the card
  [6] a bare word or number straight after the model: the model kept, the
      word named; an unknown model still reported as such
  [7] built-in: `r1 a 0 1k tc1` refused; the diode's `off` flag still legal
  [8] legal lines unchanged: name=value pairs, m=0 (the disable idiom)
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
WORK = tempfile.mkdtemp(prefix="barevalue_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


r = subprocess.run([VAF, os.path.join(HERE, "istr.va"), "-o", os.path.join(WORK, "istr.osdi")], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(inst, model=".model im istr", tag="t"):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* barevalue\n.control\npre_osdi istr.osdi\n.endc\nv1 a 0 1\n{inst}\n{model}\n.control\nop\nprint i(v1)\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def current(out):
    m = re.search(r"(?m)^i\(v1\) = (\S+)", out)
    return float(m.group(1)) if m else None


def refused(out):
    return "Simulation interrupted" in out and current(out) is None


print("Enhancement-597: a parameter without a value\n")

# ------------------------------------------------------------- [1] ---
out = run("n1 a 0 im w=2 m")
check("[1] `w=2 m`: refused, 'm' named, the fix spelled out",
      refused(out) and "parameter 'm' has no value -- write m=<value>" in out, out[-160:])
out = run("n1 a 0 im w=2 temp")
check("[1] `w=2 temp`: refused (was 0 C)", refused(out) and "parameter 'temp' has no value" in out)
out = run("n1 a 0 im w=2 w")
check("[1] `w=2 w`: the duplicate warning, then the refusal with the value named as missing",
      refused(out) and "set more than once" in out and "parameter 'w' has no value" in out)

# ------------------------------------------------------------- [2] ---
out = run("n1 a 0 im w=2 m x=1")
check("[2] `m x=1`: 'x=1' is not a number", refused(out) and "parameter 'm': 'x=1' is not a number" in out, out[-160:])

# ------------------------------------------------------------- [3] ---
out = run("n1 a 0 im", ".model im istr w")
check("[3] `.model im istr w`: refused, and the message says which card",
      refused(out) and "parameter 'w' has no value on the .model im card -- write w=<value>" in out, out[-160:])
out = run("n1 a 0 im", ".model im istr k=1e300")
check("[3] `.model im istr k=1e300`: does not fit an integer, on the card",
      refused(out) and "parameter 'k' on the .model im card: the value does not fit an integer" in out, out[-160:])
out = run("n1 a 0 im", ".model im istr w=2 k=3")
check("[3] ...a proper card default still applies (w=2: 2 mA)", current(out) is not None and abs(current(out) + 2e-3) < 1e-9, f"{current(out)}")

# ------------------------------------------------------------- [4] ---
out = run("n1 a 0 im w=2 tag")
check("[4] a bare string parameter is refused", refused(out) and "parameter 'tag' has no value" in out)
out = run('n1 a 0 im tag="" w=2')
check("[4] `tag=\"\"` is an empty value, legal (2 mA)", current(out) is not None and abs(current(out) + 2e-3) < 1e-9, f"{current(out)}")
out = run("n1 a 0 im", '.model im istr tag=""')
check("[4] ...and on the card too", current(out) is not None and abs(current(out) + 1e-3) < 1e-9, f"{current(out)}")
out = run("n1 a 0 im", ".model im istr tag")
check("[4] a bare string name on the card is refused", refused(out) and "parameter 'tag' has no value on the .model im card" in out)

# ------------------------------------------------------------- [5] ---
out = run("n1 a 0 im k=1e300")
check("[5] `k=1e300` on the line: does not fit an integer (was applied as 0)",
      refused(out) and "parameter 'k': the value does not fit an integer" in out, out[-160:])
out = run("n1 a 0 im w=1 k")
check("[5] a bare integer name after a value is refused", refused(out) and "parameter 'k' has no value" in out)

# ------------------------------------------------------------- [6] ---
out = run("n1 a 0 im k")
check("[6] `im k`: the word named, the model named, no 'Unable to find definition of model k'",
      refused(out) and "'k' is not a model and not a name=value parameter; the model is 'im'" in out
      and "Unable to find definition" not in out and "can't find model" not in out, out[-220:])
out = run("n1 a 0 im 3")
check("[6] `im 3`: a value without a parameter name", refused(out) and "'3' is a value without a parameter name; the model is 'im' -- write <name>=3" in out, out[-160:])
out = run("n1 a 0 nosuch")
check("[6] an unknown model is still 'Unable to find definition of model nosuch'",
      refused(out) and "Unable to find definition of model nosuch" in out)

# ------------------------------------------------------------- [7] ---
out = run("r1 a 0 1k tc1", "")
check("[7] built-in `r1 a 0 1k tc1`: refused (tc1 was silently 0)", refused(out) and "parameter 'tc1' has no value -- write tc1=<value>" in out, out[-160:])
out = run("d1 a 0 dm off", ".model dm d")
check("[7] the diode's `off` flag takes no value and stays legal", current(out) is not None and "no value" not in out, out[-120:])
out = run("d1 a 0 dm off area", ".model dm d")
check("[7] ...but a bare `area` after it is refused", refused(out) and "parameter 'area' has no value" in out)

# ------------------------------------------------------------- [8] ---
out = run("n1 a 0 im w=2 m=3")
check("[8] `w=2 m=3`: 6 mA", current(out) is not None and abs(current(out) + 6e-3) < 1e-9, f"{current(out)}")
out = run("n1 a 0 im m=0")
check("[8] `m=0` is the disable idiom (E-426): silent, 0 A", current(out) == 0.0 and "no value" not in out and "Warning" not in out, out[-120:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
