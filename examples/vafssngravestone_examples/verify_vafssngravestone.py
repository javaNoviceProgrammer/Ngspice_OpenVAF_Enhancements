#!/usr/bin/env python3
"""Enhancement-329: a GRAVESTONE phi operand reaching the small-signal network.

GRAVESTONE is the compiler's placeholder for "an unused value that must remain
(in phis)" -- the SSA re-builder puts it in a phi for an edge with no reaching
definition. `small_signal_network.rs` asserted such a value could never reach it
(`ValueDef::Invalid => unreachable!()`, in both `analyze_value` and
`analyze_dependency`) and crashed the SHIPPED compiler.

A value on a dead edge cannot be used at run time, so it contributes nothing:
the arms now return `FlatSet::Zero` / `Dependency::Independent`, mirroring their
neighbouring "contributes nothing" arms.

An `unreachable!()` that fires usually means something upstream is malformed, so
a guard is only legitimate if what it lets through is CORRECT. Check [3] is that
proof: the crash shape and a reference with the ingredients removed must agree
exactly.

  [1] the crash shape compiles                 (pre-fix: compiler panic)
  [2] it simulates to a finite operating point
  [3] and matches the reference model EXACTLY  (r0*r1 contributes precisely 0)
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


def main():
    osdi = os.path.join(HERE, "ssngravestone.osdi")
    if os.path.exists(osdi):
        os.remove(osdi)
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, "ssngravestone.va"), "-o", osdi],
                           capture_output=True, text=True, timeout=120)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = "HANG", ""
    sig = next((l for l in out.splitlines() if "panicked at" in l), "")
    check("the GRAVESTONE crash shape compiles", rc == 0 and os.path.exists(osdi),
          f"rc={rc} {sig[:60]}")
    if rc != 0:
        print(f"\nFAILURES: {passed}/{checks} passed")
        sys.exit(1)

    deck = os.path.join(HERE, "_ssn.cir")
    with open(deck, "w") as f:
        f.write("ssn gravestone\n"
                "V1 n1 0 dc 1\nNs n1 n2 0 smod\n"
                "V2 n3 0 dc 1\nNr n3 n4 0 rmod\n"
                ".model smod ssn s0=2\n.model rmod ssn_ref\n"
                ".control\npre_osdi ssngravestone.osdi\nop\n"
                "print i(v1) i(v2) v(n2) v(n4)\n.endc\n.end\n")
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                            capture_output=True, text=True, timeout=120)
        out = rr.stdout + rr.stderr
    finally:
        if os.path.exists(deck):
            os.remove(deck)

    def val(n):
        m = re.search(rf"{re.escape(n)}\s*=\s*([-\d.eE+]+)", out)
        return float(m.group(1)) if m else None

    i_ssn, i_ref = val("i(v1)"), val("i(v2)")
    v_ssn, v_ref = val("v(n2)"), val("v(n4)")

    finite = (i_ssn is not None and v_ssn is not None
              and abs(i_ssn) < 1e30 and i_ssn == i_ssn and v_ssn == v_ssn)
    check("it simulates to a finite operating point", finite, f"i={i_ssn} v={v_ssn}")

    agree = (finite and i_ref is not None and v_ref is not None
             and abs(i_ssn - i_ref) < 1e-15 and abs(v_ssn - v_ref) < 1e-15)
    check("and matches the reference exactly (r0*r1 contributes 0)", agree,
          f"ssn=({i_ssn},{v_ssn}) ref=({i_ref},{v_ref})")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
