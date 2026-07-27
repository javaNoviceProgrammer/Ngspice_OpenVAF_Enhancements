#!/usr/bin/env python3
"""Enhancement-333: integer division by a literal zero SIGTRAPped the simulator.

`if ((5 / 0) > 0 && ione > 0) ...` compiled with exit 0 and no diagnostic, then
killed ngspice with signal 5 (SIGTRAP) and no output whatsoever.

Enhancement-286 had deliberately let this through, reasoning that "a runtime zero
divisor has always been accepted, so a literal one must be too". Both halves are
wrong. The literal case is NOT the runtime case -- only the literal one leaves an
`sdiv x, 0` in the IR, which LLVM treats as immediate undefined behaviour and
lowers to poison -> `unreachable` -> `brk`. And runtime acceptance is itself
target-specific: AArch64 returns a value where x86 raises SIGFPE, and this project
ships x86 builds for macOS, Linux and Windows. There is no portable value to fold
to, so a literal zero divisor is now rejected.

  [1] the trapping shape is a clean compile error (exit 65), not a crash
  [2] the diagnostic names the defect, points at the zero, and says what is still allowed
  [3] `%` by a literal zero is rejected the same way
  [4] a zero divisor via parameter / localparam / derived constant is STILL accepted
      and simulates -- the check is literal-only on purpose
  [5] ordinary integer division and IEEE float division by zero are untouched
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


def source(text, name):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def main():
    # [1]+[2] the trapping shape is now a clean error
    rc, out = compile_va("divzero_bad.va")
    check("literal zero divisor is a clean compile error, not a crash",
          rc == 65, f"rc={rc}")
    check("the diagnostic names the defect and what is still allowed",
          "integer division by zero" in out and "divisor is zero" in out
          and "parameter or localparam" in out,
          (out.strip().splitlines() or ["no output"])[0][:70])

    # [3] remainder too
    name = "_rem.va"
    source('`include "disciplines.vams"\n'
           "module _rem(o); output o; electrical o;\n"
           "  parameter integer ione = 1;\n"
           "  analog begin if ((5 % 0) > 0 && ione > 0) V(o) <+ 1.0; else V(o) <+ 2.0; end\n"
           "endmodule\n", name)
    rc_r, out_r = compile_va(name)
    check("`%` by a literal zero is rejected the same way",
          rc_r == 65 and "remainder by zero" in out_r, f"rc={rc_r}")
    for p in (os.path.join(HERE, name), os.path.join(HERE, "_rem.osdi")):
        if os.path.exists(p):
            os.remove(p)

    # [4]+[5] non-literal zeros still accepted, and they simulate
    rc_ok, out_ok = compile_va("divzero_ok.va")
    check("parameter / localparam / derived zero divisors are STILL accepted",
          rc_ok == 0, f"rc={rc_ok}")
    if rc_ok == 0:
        deck = os.path.join(HERE, "_dz.cir")
        with open(deck, "w") as f:
            f.write("divzero ok\nV1 a 0 dc 1\nN1 a 0 m\n.model m divzero_ok\n"
                    ".control\npre_osdi divzero_ok.osdi\nop\nprint i(v1)\n.endc\n.end\n")
        try:
            r = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                               capture_output=True, text=True, timeout=120)
            o = r.stdout + r.stderr
            sig = r.returncode
        finally:
            for p in (deck, os.path.join(HERE, "divzero_ok.osdi")):
                if os.path.exists(p):
                    os.remove(p)
        m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", o)
        got = float(m.group(1)) if m else None
        # 1 kOhm resistor; every other term is multiplied by 0.0
        check("and they SIMULATE without trapping (I = V/1k, no signal)",
              sig >= 0 and got is not None and abs(got - (-1e-3)) < 1e-9,
              f"rc={sig} i(v1)={got}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
