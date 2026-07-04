#!/usr/bin/env python3
"""
verify_intstate.py -- verifies Enhancement-32 integer persistent/event-state
variables (and their opvar exposure), end-to-end through the committed
openvaf-r + ngspice.

Before E-32, ANY integer variable holding persistent state crashed the compiler
(the OSDI state slot was hardcoded f64, so the state load fed integer MIR ops with
doubles -> LLVM ISel abort / segfault). A companion ngspice patch also lets integer
opvars be recorded per-timepoint (they were masked out of output vectors and
reported "OUTpData: unsupported data type").

`intstate_demo.va` drives a 2V/1kHz sine into an edge counter:

  1. it COMPILES (integer persistent state used to abort the compiler);
  2. the integer @(cross) counter n counts EXACTLY the upward vth-crossings
     (5 cycles -> n == 5), read back from the opvar;
  3. n's per-timepoint waveform is a clean staircase 0,1,2,3,4,5 stepping at the
     analytic crossing times (t = asin(vth/A)/(2*pi*f) + k/f) -- proves both the
     integer state persistence AND the ngspice integer-vector recording;
  4. the integer @(initial_step) flag reads 1;
  5. regression: the REAL running-peak opvar (E-7 behaviour) still reads the
     sine amplitude.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE

AMP, FREQ, VTH, CYCLES = 2.0, 1e3, 1.0, 5


def run_tran():
    deck = (
        "* integer state opvar tran\n"
        f"vin a 0 sin(0 {AMP} {FREQ})\n"
        "n1 a 0 dm\n"
        f".model dm intstate_demo(vth={VTH})\n"
        ".control\npre_osdi intstate_demo.osdi\n"
        "save @n1[n] @n1[started] @n1[vpeak] v(a)\n"
        f"tran 10u {CYCLES/FREQ}\n"
        "wrdata _o.txt @n1[n] @n1[started] @n1[vpeak]\n"
        ".endc\n.end\n"
    )
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    rows = []
    for line in open(os.path.join(HERE, "_o.txt")):
        v = line.split()
        if v:
            # wrdata layout: t n t started t vpeak
            rows.append((float(v[0]), float(v[1]), float(v[3]), float(v[5])))
    return rows, (r.stdout + r.stderr)


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] integer persistent/event state COMPILES (used to crash the compiler)")
    r = subprocess.run([OPENVAF, "intstate_demo.va", "-o",
                        os.path.join(HERE, "intstate_demo.osdi")],
                       cwd=HERE, capture_output=True, text=True)
    check("openvaf-r intstate_demo.va", r.returncode == 0,
          "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[0])
    if r.returncode != 0:
        print("\nSOME FAILED")
        sys.exit(1)

    rows, log = run_tran()
    check("no 'unsupported data type' from ngspice", "unsupported data type" not in log)

    print(f"[2] @(cross) integer counter: n == {CYCLES} upward {VTH}V crossings")
    n_final = rows[-1][1]
    check(f"final n == {CYCLES}", n_final == float(CYCLES), f"n = {n_final}")

    print("[3] staircase: distinct values exactly 0..5, steps at analytic crossing times")
    seen, first_t = [], {}
    for t, n, _, _ in rows:
        if n not in first_t:
            first_t[n] = t
            seen.append(n)
    check("values are 0,1,2,3,4,5 in order", seen == [float(k) for k in range(CYCLES + 1)],
          f"saw {seen}")
    t0 = math.asin(VTH / AMP) / (2.0 * math.pi * FREQ)     # first upward crossing
    terr = max(abs(first_t[float(k)] - (t0 + (k - 1) / FREQ)) for k in range(1, CYCLES + 1))
    check("step times match analytic crossings (< 20us)", terr < 20e-6,
          f"max |terr| = {terr*1e6:.2f} us")

    print("[4] @(initial_step) integer flag reads 1")
    check("started == 1", all(s == 1.0 for _, _, s, _ in rows[1:]),
          f"final started = {rows[-1][2]}")

    print("[5] regression: REAL running-peak opvar (E-7) still works")
    vpeak = rows[-1][3]
    check(f"vpeak ~= {AMP}", abs(vpeak - AMP) < 5e-3, f"vpeak = {vpeak}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
