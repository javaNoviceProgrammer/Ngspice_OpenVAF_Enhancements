#!/usr/bin/env python3
"""verify_ifftreal.py -- Enhancement-275: ifft() on a real input vector no longer
reads past its buffer.

`cx_ifft` (src/maths/cmaths/cmath4.c) unconditionally did
`ngcomplex_t *indata = (ngcomplex_t *) data;`. For a VF_REAL input, `data` is a
plain `double[length]` (length*8 bytes), so reading `indata[i]` for `i < length`
walked `length` complex elements (length*16 bytes) -- twice past the buffer, an
AddressSanitizer heap-buffer-overflow READ. cx_fft (Enhancement-225) already
distinguishes real and complex input; cx_ifft did not. Fixed by building a proper
complex array (imag = 0) for the real case (and freeing it), plus a length>=2 guard.

The test passes iff ifft on a real vector runs cleanly (no overflow) and the
fft->ifft round-trip and complex ifft still work. Reported via exit code (0 = pass).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = ("* ifft-real test\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\n"
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
    path = os.path.join(HERE, "_if.cir")
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


print("Enhancement-275: ifft() on a real vector -> no heap overflow (cmath4.c)")

# [1] ifft of a REAL vector -- was a heap-buffer-overflow READ (2x past buffer).
rc, out = run("let y = ifft(vx)\nprint length(y)")
check("[1] `ifft(vx)` (real input) -> clean, no overflow", nocrash(rc)
      and "Sanitizer" not in out, f"rc={rc}")

# [2] the fft -> ifft round-trip returns a vector of the same length.
rc, out = run("let s = fft(vx)\nlet t = ifft(s)\nprint length(vx) length(t)")
lv = re.search(r"length\(vx\)\s*=\s*([-\d.eE+]+)", out)
lt = re.search(r"length\(t\)\s*=\s*([-\d.eE+]+)", out)
ok2 = nocrash(rc) and lv and lt and float(lv.group(1)) == float(lt.group(1))
check("[2] fft->ifft round-trip keeps the length", ok2,
      f"vx={lv.group(1) if lv else '?'} t={lt.group(1) if lt else '?'}")

# [3] ifft of a genuinely complex vector still works.
rc, out = run("let s = fft(vx)\nlet z = ifft(s)\nprint length(z)")
check("[3] `ifft(complex)` still works", nocrash(rc) and "Sanitizer" not in out,
      f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
