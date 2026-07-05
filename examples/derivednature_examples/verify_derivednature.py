#!/usr/bin/env python3
"""
verify_derivednature.py -- verifies Enhancement-39 derived natures (and deriving
natures from disciplines), end-to-end through the committed openvaf-r + ngspice.

Before E-39 the `: parent` clause of a nature silently produced NO parent link
(parser emitted a NAME_REF where the AST wanted a Path), so the fully-implemented
inheritance machinery in hir_ty was unreachable: derived natures without their own
units/access rejected the inherited access function, `nature X : electrical.flow;`
did not parse at all, and a discipline-qualified ddt_nature attribute hard-panicked
the OSDI nature-descriptor builder.

`derivednature_demo.va` packs the full matrix (5 modules). We check:

  1. it COMPILES (three of the five constructs used to fail/crash);
  2. runtime conductances are exact for every module -- proving the inherited
     access functions genuinely resolve:
       dn_nature      g=1e-3  (access I inherited from Current)
       dn_discipline  g=2e-3  (natures derived from electrical.flow/.potential)
       dn_access      g=5e-3  (derived nature with its own access name I2)
       dn_chain       g=3e-3  (access inherited through a two-level chain)
  3. the ddt_nature = electrical.potential module (dn_attr) loads in ngspice
     (its OSDI descriptor is well-formed -- building it used to panic).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE


def run(deck, *names):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        for nm in names:
            if line.strip().lower().startswith(nm.lower() + " "):
                vals[nm] = float(line.split("=", 1)[1])
    return vals


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] the full derived-nature matrix COMPILES")
    r = subprocess.run([OPENVAF, "derivednature_demo.va", "-o", "derivednature_demo.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("openvaf-r derivednature_demo.va", r.returncode == 0,
          "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[0])
    if r.returncode != 0:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] inherited access functions resolve: exact conductances")
    cases = [("dn_nature", 1e-3, "access I inherited from Current"),
             ("dn_discipline", 2e-3, "derived from electrical.flow/.potential"),
             ("dn_access", 5e-3, "own access name I2"),
             ("dn_chain", 3e-3, "two-level chain")]
    for mod, g, why in cases:
        v = run(f"* {mod}\nvin a 0 dc 2\nn1 a 0 dm\n.model dm {mod}\n"
                ".control\npre_osdi derivednature_demo.osdi\nop\n"
                "print i(vin)\n.endc\n.end\n", "i(vin)")
        check(f"{mod}: I == -{g:g}*2 ({why})", abs(v["i(vin)"] + 2 * g) < 1e-12,
              f"i = {v['i(vin)']:.6e}")

    print("[3] discipline-qualified ddt_nature descriptor loads (used to panic)")
    v = run("* dn_attr\nn1 a 0 dm\n.model dm dn_attr\nr1 a 0 1k\n"
            ".control\npre_osdi derivednature_demo.osdi\nop\nprint v(a)\n.endc\n.end\n",
            "v(a)")
    check("dn_attr simulates", "v(a)" in v, f"v(a) = {v.get('v(a)')}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
