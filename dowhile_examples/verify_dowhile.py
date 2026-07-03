#!/usr/bin/env python3
"""
verify_dowhile.py -- verifies the Enhancement-19 `do ... while` loop end-to-end
through version11's own openvaf-r + ngspice.

`dowhile_demo` runs a `do` loop that accumulates `count` and reports it as a gain
V(out) = count * 1e-3 * V(in). Because a `do` loop runs its body once before the
first condition test, count = max(n, 1). We check across the loop count `n`
(overridden per .model), including the defining n=0 case where the body still
runs exactly once.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE


def gain(n):
    deck = (f"* dowhile n={n}\nvin in 0 dc 1\nn1 in out mm\n.model mm dowhile_demo(n={n})\n"
            f".control\npre_osdi dowhile_demo.osdi\ndc vin 1 1 1\nwrdata _d.txt v(out)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_d.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE, capture_output=True, text=True)
    with open(os.path.join(HERE, "_d.txt")) as fh:
        return float(fh.read().split()[-1])


def main():
    subprocess.run([OPENVAF, "dowhile_demo.va", "-o", "dowhile_demo.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    print(f"{'n':>3} {'count (=V(out)*1000)':>22} {'expected max(n,1)':>18}  result")
    for n in (0, 1, 2, 5, 10):
        count = round(gain(n) * 1e3)
        exp = max(n, 1)   # the body always runs at least once
        good = count == exp
        ok = ok and good
        print(f"{n:>3} {count:>22} {exp:>18}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
