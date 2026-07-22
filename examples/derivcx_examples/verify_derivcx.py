#!/usr/bin/env python3
"""verify_derivcx.py -- Enhancement-277: deriv() of a complex vector no longer reads
past its buffer, and now computes the correct derivative.

`cx_deriv` (src/maths/cmaths/cmath4.c) fits a polynomial over a sliding window. Its
COMPLEX branch had two index bugs the real branch did not:

  * the data window `c_indata[j + i + base]` was offset by `degree` from the fit's
    scale window (`scale + i - degree + base`) -- both a misalignment and a read
    `degree` points past the end of the input on the last block (AddressSanitizer
    heap-buffer-overflow READ);
  * the real-part output loop used `j <= i + degree/2` where the imag-part loop and
    the whole real branch use `j <= i - degree/2`, overrunning scale[]/c_outdata[].

Fixed by aligning both to the real branch (`i - degree + base` for the data,
`i - degree/2` for the output loop). The overflow is gone AND the complex derivative
is now numerically correct.

Passes iff a complex deriv runs cleanly and both complex and real derivatives are
right. Reported via exit code (0 = pass).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* deriv complex test\nv1 n 0 dc 0\nr1 n 0 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\ntran 1 10 0\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_dc.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def nocrash(rc):
    return rc is not None and rc >= 0 and rc != 139


def cnum(s):
    m = re.search(r"=\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)", s)
    return (float(m.group(1)), float(m.group(2))) if m else None


print("Enhancement-277: deriv() of a complex vector -> no overflow, correct result")

# [1] the fuzz-found complex deriv -- was a heap-buffer-overflow READ.
rc, out = run("let d = deriv((0.5,time))\nprint length(d)")
check("[1] `deriv((0.5,time))` -> clean, no overflow", nocrash(rc)
      and "Sanitizer" not in out, f"rc={rc}")

# [2] d/dt (t + 2t*i) = 1 + 2i (correct complex derivative, mid-vector).
rc, out = run("let z = time + 2*time*i\nlet dz = deriv(z)\nprint dz[3]")
line = next((ln for ln in out.splitlines() if "dz[3]" in ln), "")
c = cnum(line)
check("[2] `deriv(t + 2t*i)` == (1, 2i)  (correct complex derivative)",
      c is not None and abs(c[0] - 1.0) < 1e-6 and abs(c[1] - 2.0) < 1e-6,
      f"{c}")

# [3] a real deriv is unchanged: d/dt(2t) = 2.
rc, out = run("let dr = deriv(2*time)\nprint dr[3]")
m = re.search(r"dr\[3\]\s*=\s*([-\d.eE+]+)", out)
check("[3] a real `deriv(2t)` still == 2 (unchanged)", m is not None
      and abs(float(m.group(1)) - 2.0) < 1e-6, f"={m.group(1) if m else '?'}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
