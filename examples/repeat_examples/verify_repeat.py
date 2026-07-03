#!/usr/bin/env python3
"""
verify_repeat.py -- verify the `repeat (count) statement` loop added in
Enhancement-9, end-to-end through version10's own openvaf-r + ngspice.

`repeat_demo` builds a series resistance Rtot = round(count) * Rbase with a
`repeat` loop. As the lower leg of a 1k-over-Rtot divider driven by 1 V,
V(out) = Rtot/(Rtot+1k) -- so V(out) directly reports how many times the loop
body ran. We check integer counts, real counts (round-to-nearest), and the
zero-iteration case.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
RBASE = 1000.0
R1 = 1000.0


def vout(count):
    subprocess.run([OPENVAF, "repeat_demo.va", "-o", "repeat_demo.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = f"""* repeat
vin a 0 dc 1
r1 a b 1k
n1 b 0 mm
.model mm repeat_demo(count={count} Rbase={RBASE})
.control
pre_osdi repeat_demo.osdi
op
print all
.endc
.end
"""
    with open(os.path.join(HERE, "_r.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_r.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("b = "):
            return float(line.split("=")[1])
    raise RuntimeError(f"no V(b):\n{out}")


def round_half_away(x):
    import math
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def expected(count):
    n = round_half_away(count)
    # For n <= 0 the loop body never runs, Rtot stays 0, and the device is just
    # the 1e12-ohm leakage leg -> open -> V(out) ~ 1.0.
    Rtot = n * RBASE if n > 0 else 1.0e12
    return Rtot / (Rtot + R1)


def main():
    # (count value, note)
    cases = [0, 1, 2, 4, 3.4, 3.6, 2.5, 10]
    ok = True
    for c in cases:
        got = vout(c)
        exp = expected(c)
        good = abs(got - exp) < 2e-3
        ok &= good
        print(f"  count={str(c):5s} -> round={round_half_away(c):2d} iters  "
              f"V(b)={got:.5f}  expected={exp:.5f}  {'PASS' if good else 'FAIL'}")
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
