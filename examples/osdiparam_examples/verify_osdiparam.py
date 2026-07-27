#!/usr/bin/env python3
"""Enhancement-336: OSDI descriptor and parameter-binding integrity.

Three defects, none of which crashed anything:

  * A Verilog-A instance parameter named `M` was shadowed by the `m` alias
    ngspice synthesizes for $mfactor. The decision to synthesize used a
    case-SENSITIVE compare against "m", so a model declaring `M` did not
    suppress it, while its own `M` was lowercased to `m` on registration. Both
    became `m`, the alias won, and `M=7` was silently applied as the device
    MULTIPLIER while the model's own M kept its default.
  * Two parameters differing only in case are distinct in Verilog-A but not in
    SPICE, and one silently lost its value. That cannot be resolved in the
    loader (a netlist is lowercased when parsed) but it must not be silent.
  * `num_resistive_jacobian_entries` in the descriptor exceeded the entire
    `jacobian_entries` list (8 against 7): the counts were cached while the DAE
    system was built, but the jacobian can lose entries afterwards, so the
    cached value went stale and described an array larger than the real one.

  [1] `M=7` reaches the MODEL's own M (I = 1V x 7), not the multiplier
  [2] a case collision is REPORTED instead of silently dropping a value
  [3] the model whose descriptor was inconsistent still compiles and simulates
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


def build(name):
    osdi = os.path.join(HERE, name + ".osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name + ".va"), "-o", osdi],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, osdi


def run(deck_name, text):
    p = os.path.join(HERE, deck_name)
    with open(p, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", deck_name], cwd=HERE,
                           capture_output=True, text=True, timeout=180)
        return r.returncode, r.stdout + r.stderr
    finally:
        if os.path.exists(p):
            os.remove(p)


def main():
    # [1] an instance parameter named M must win over the $mfactor alias
    rc, osdi = build("mparam")
    if rc != 0:
        check("mparam.va compiles", False, f"rc={rc}")
    else:
        _, out = run("_m.cir",
                     "mfactor shadowing\nVa a 0 dc 1\nN1 a 0 mm M=7\n.model mm mparam\n"
                     ".control\npre_osdi mparam.osdi\nop\nprint i(va)\n.endc\n.end\n")
        m = re.search(r"i\(va\)\s*=\s*([-\d.eE+]+)", out)
        got = abs(float(m.group(1))) if m else None
        # model's own M: I = 1 V * 7 = 7.  As a multiplier it would be 7*(1*2) = 14.
        check("`M=7` sets the model's own M (I = 7), not the $mfactor multiplier",
              got is not None and abs(got - 7.0) < 1e-6, f"i(va)={got}")
        if os.path.exists(osdi):
            os.remove(osdi)

    # [2] a case collision must be reported
    rc, osdi = build("casecollide")
    if rc != 0:
        check("casecollide.va compiles", False, f"rc={rc}")
    else:
        _, out = run("_c.cir",
                     "case collision\nV1 a 0 dc 1\nN1 a b cc\n.model cc casecollide GAIN=3\n"
                     "Rl b 0 1e-9\n.control\npre_osdi casecollide.osdi\nop\nprint i(v1)\n"
                     ".endc\n.end\n")
        check("parameters differing only in case are reported, not silently dropped",
              "only in case" in out,
              next((l.strip()[:70] for l in out.splitlines() if "only in case" in l),
                   "no warning"))
        if os.path.exists(osdi):
            os.remove(osdi)

    # [3] the inconsistent-descriptor model still builds and simulates
    rc, osdi = build("jacentries")
    if rc != 0:
        check("jacentries.va compiles", False, f"rc={rc}")
    else:
        code, out = run("_j.cir",
                        "jacobian entries\nV1 a 0 dc 1\nN1 a b c je\n.model je jacentries\n"
                        "Rb b 0 1e3\nRc c 0 1e3\n.control\npre_osdi jacentries.osdi\nop\n"
                        "print i(v1)\n.endc\n.end\n")
        m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", out)
        check("the model whose descriptor was inconsistent simulates cleanly",
              code >= 0 and m is not None, f"rc={code} i(v1)={m.group(1) if m else None}")
        if os.path.exists(osdi):
            os.remove(osdi)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
