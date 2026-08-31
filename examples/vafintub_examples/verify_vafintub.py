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
  [2] an out-of-range shift distance is reported with the distance -- since the
      E-518 expressions audit as a WARNING, because LRM 4.2.11 gives it a
      defined value (distance is unsigned; every bit shifts out -> 0)
  [3] neither leaves anything for codegen to trap on (the div errors out; the
      shift folds to its defined value)
  [4] legal shifts, runtime distances and parameter/localparam operands STILL
      compile and simulate -- the guard is constant-operand-only on purpose

Enhancement-392 UPDATE: `-2147483648` written directly used to exceed i32::MAX and
promote to REAL, so the integer overflow was only reachable as `(-2147483647 - 1)`.
That promotion was itself a defect -- the same value arriving at runtime stayed an
integer, so one expression had two meanings -- and E-392 folds the sign into the
literal. The direct spelling therefore reaches this same guard now, which check [5]
below pins: it is the one operation that genuinely traps, so making the literal
work correctly must not make it compile.
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
    # E-518 (expressions audit) UPDATE: LRM 4.2.11 treats the shift distance as
    # unsigned over a 32-bit integer, so an out-of-range distance has a DEFINED
    # value (every bit shifted out -> 0; `>>>` -> the sign fill) rather than
    # being UB. The old hard error became a warning that still names the
    # distance -- and the folded 0 leaves no poison for codegen to trap on.
    check("the out-of-range shift is reported with its distance",
          "shift distance outside 0..=31" in out and "shift distance is 40" in out,
          next((l for l in out.splitlines() if "shift" in l), "")[:60])

    # [5] E-392: the INT_MIN LITERAL spelling reaches the same guard. Before E-392
    # `-2147483648` promoted to real, so this line compiled clean and quietly
    # computed 2147483648.0 instead of overflowing.
    check("the `-2147483648` literal spelling is caught too, not silently made real",
          out.count("overflow") >= 2 and "intub_minlit" not in out.replace("overflow", ""),
          f"overflow diagnostics={out.count('overflow')}")

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
