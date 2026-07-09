#!/usr/bin/env python3
"""
verify_localparam.py -- verify the corrected `localparam` semantics of
Enhancement-9 against ngspice, using version10's own openvaf-r + ngspice.

The device `rdiv` is a linear conductance `GAIN*G = GAIN/R` (with GAIN=2). We
place it as the lower leg of a 1k-over-rdiv voltage divider driven by 1 V and
read the divider output V(out) = Rdev / (Rdev + 1k), where Rdev = R/GAIN.

For each `.model rdiv(...)` override we compare V(out) against the value
expected under LRM-correct localparam rules:

  * overriding `R`            -> takes effect (Rdev = R/2)
  * overriding `G` or `GAIN`  -> ignored (localparams are not overridable)

A non-zero exit status means a mismatch.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers
GAIN = 2.0
R1 = 1000.0


def compile_va():
    subprocess.run([OPENVAF, "rdiv.va", "-o", "rdiv.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def vout(model_args):
    deck = f"""* localparam test
vin a 0 dc 1
r1 a b 1k
n1 b 0 mm
.model mm rdiv({model_args})
.control
pre_osdi rdiv.osdi
op
print all
.endc
.end
"""
    with open(os.path.join(HERE, "_t.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_t.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("b = "):
            return float(line.split("=")[1])
    raise RuntimeError(f"no V(b) for '{model_args}':\n{out}")


def expected(R):
    Rdev = R / GAIN
    return Rdev / (Rdev + R1)


def main():
    compile_va()
    # (model args, effective R after LRM-correct override rules)
    cases = [
        ("",                 1000.0),   # defaults
        ("R=2000",           2000.0),   # R overridable -> takes effect
        ("R=500",             500.0),
        ("G=0.5",            1000.0),   # localparam G override ignored
        ("GAIN=10",          1000.0),   # localparam GAIN override ignored
        ("R=4000 G=9 GAIN=9", 4000.0),  # only R applies; G, GAIN ignored
    ]
    ok = True
    for args, R_eff in cases:
        got = vout(args)
        exp = expected(R_eff)
        rel = abs(got - exp) / abs(exp)
        good = rel < 1e-4
        ok &= good
        print(f"  rdiv({args:18s}) V(out)={got:.6f}  expected={exp:.6f}  "
              f"{'PASS' if good else 'FAIL'}")
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
