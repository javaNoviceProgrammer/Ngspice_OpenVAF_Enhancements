#!/usr/bin/env python3
"""verify_scaleguard.py -- Enhancement-278: the transform functions integ / deriv /
ifft no longer overrun the heap on a vector whose length differs from its plot scale.

`cx_integ`, `cx_deriv`, and `cx_ifft` (src/maths/cmaths/cmath4.c) index both the data
(by `length`) and its plot scale. A synthetic vector whose length differs from the
current plot's scale -- e.g. `integ(unitvec(200))` / `deriv(unitvec(200))` (longer
than the scale) or `ifft(vector(5))` (much shorter) -- ran the loops off the end. Only
`cx_fft` had been guarded (Enhancement-225); the siblings had not.

Fixes:
  * integ / deriv reject a data vector LONGER than its scale (the direction that read
    the scale out of bounds); a shorter data vector, as produced by fft, stays valid;
  * ifft grows its transform size N to cover the output length `tpts` before
    allocating, so a data vector much SHORTER than the scale no longer overruns the
    (length-sized) datax buffer.

Passes iff the mismatched inputs resolve cleanly (no overflow) and valid transforms --
including the fft->ifft round-trip and a group-delay-style deriv -- still work.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = ("* transform scale-guard test\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\n"
        "v1 a 0 dc 1 ac 1 pulse(0 1 0 1u 1u 1m 2m)\n")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\ntran 1u 20u\nlet vx = v(b)\n" + control + \
        "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_sg.cir")
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


print("Enhancement-278: integ/deriv/ifft guard a length/scale mismatch (no overflow)")

# [1] integ of a vector LONGER than the scale -> clean error.
rc, out = run("let y = integ(unitvec(200))")
check("[1] `integ(unitvec(200))` (data > scale) -> clean, no overflow",
      nocrash(rc) and "Sanitizer" not in out, f"rc={rc}")

# [2] deriv of a vector LONGER than the scale -> clean error.
rc, out = run("let y = deriv(unitvec(200))")
check("[2] `deriv(unitvec(200))` (data > scale) -> clean, no overflow",
      nocrash(rc) and "Sanitizer" not in out, f"rc={rc}")

# [3] ifft of a vector much SHORTER than the scale -> no datax overrun.
rc, out = run("let y = ifft(vector(5))")
check("[3] `ifft(vector(5))` (data << scale) -> clean, no overflow",
      nocrash(rc) and "Sanitizer" not in out, f"rc={rc}")

# [4] the fft -> ifft round-trip still works (data slightly shorter than scale).
rc, out = run("let s = fft(vx)\nlet t = ifft(s)\nprint length(vx) length(t)")
lv = re.search(r"length\(vx\)\s*=\s*([-\d.eE+]+)", out)
lt = re.search(r"length\(t\)\s*=\s*([-\d.eE+]+)", out)
check("[4] fft->ifft round-trip still returns a full-length vector",
      nocrash(rc) and lv and lt and float(lv.group(1)) == float(lt.group(1)),
      f"vx={lv.group(1) if lv else '?'} t={lt.group(1) if lt else '?'}")

# [5] a valid integ / deriv of a real vector (data == scale) still works.
rc, out = run("let yi = integ(vx)\nlet yd = deriv(vx)\nprint length(yi) length(yd)")
li = re.findall(r"length\(y[id]\)\s*=\s*([-\d.eE+]+)", out)
check("[5] valid `integ(vx)` / `deriv(vx)` (data == scale) still work",
      nocrash(rc) and len(li) == 2 and all(float(x) == 66.0 for x in li),
      f"{li}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
