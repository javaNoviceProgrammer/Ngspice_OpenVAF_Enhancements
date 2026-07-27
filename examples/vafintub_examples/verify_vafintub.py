#!/usr/bin/env python3
"""Enhancement-334: the two integer-UB shapes Enhancement-333 left behind.

E-286's comment named THREE compile-time-constant integer operations that LLVM
defines as poison -- a zero divisor, `i32::MIN / -1`, and a shift distance outside
0..32 -- and declined to fold each one. Declining is what leaves the poison in the
IR, where it becomes `unreachable` -> `brk`. E-333 fixed only the divisor; the other
two still compiled with exit 0 and killed ngspice with SIGTRAP:

    (-2147483647 - 1) / (-1)   inside `&&`   -> SIGTRAP
    1 << 40                    inside `&&`   -> SIGTRAP

Both are now clean compile errors.

  [1] `i32::MIN / -1` is a clean compile error naming the overflow
  [2] an out-of-range shift distance is a clean compile error naming the distance
  [3] neither leaves a model that can be simulated (nothing to trap)
  [4] legal shifts, runtime distances and parameter/localparam operands STILL
      compile and simulate -- the guard is constant-operand-only on purpose

Note `-2147483648` written directly exceeds i32::MAX and promotes to REAL, so the
integer overflow is only reachable as `(-2147483647 - 1)`.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    osdi = os.path.join(HERE, name.replace(".va", ".osdi"))
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi],
                           capture_output=True, text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", ""
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    # [1]+[2] both UB shapes are clean errors, and the messages are specific
    rc, out = compile_va("intub.va")
    check("the integer-UB shapes are a clean compile error, not a crash",
          rc == 65, f"rc={rc}")
    check("`i32::MIN / -1` is reported as an overflow",
          "overflow" in out, (out.strip().splitlines() or ["no output"])[0][:60])
    check("the out-of-range shift is reported with its distance",
          "shift distance out of range" in out and "40" in out,
          next((l for l in out.splitlines() if "shift" in l), "")[:60])

    # [3] nothing compiled, so nothing can trap
    check("no .osdi is produced for them (nothing left to trap)",
          not os.path.exists(os.path.join(HERE, "intub.osdi")))

    # [4] the legal forms still compile AND simulate
    rc_ok, out_ok = compile_va("intub_ok.va")
    check("legal shifts, runtime distances and localparam operands still compile",
          rc_ok == 0, f"rc={rc_ok}")
    if rc_ok == 0:
        deck = os.path.join(HERE, "_iu.cir")
        with open(deck, "w") as f:
            f.write("intub ok\nV1 a 0 dc 1\nN1 a 0 m\n.model m intub_ok\n"
                    ".control\npre_osdi intub_ok.osdi\nop\nprint i(v1)\n.endc\n.end\n")
        try:
            r = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                               capture_output=True, text=True, timeout=120)
            o = r.stdout + r.stderr
            sig = r.returncode
        finally:
            for p in (deck, os.path.join(HERE, "intub_ok.osdi")):
                if os.path.exists(p):
                    os.remove(p)
        m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", o)
        got = float(m.group(1)) if m else None
        check("and they SIMULATE without trapping (I = V/1k, no signal)",
              sig >= 0 and got is not None and abs(got - (-1e-3)) < 1e-9,
              f"rc={sig} i(v1)={got}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
