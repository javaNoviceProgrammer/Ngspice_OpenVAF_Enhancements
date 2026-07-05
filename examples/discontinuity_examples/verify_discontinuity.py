#!/usr/bin/env python3
"""
verify_discontinuity.py -- verifies Enhancement-24 `$discontinuity(n)`, end-to-end
through version11's own openvaf-r + ngspice (which also required an ngspice-side
change: OSDItrunc honours the discontinuity via the bound_step slot).

`disc_demo.va` is a conductance switch (I = g*V(a,b), g jumps at V(a,b)=vth) that
announces `$discontinuity(0)` while in the switched region. `$discontinuity(n)`
tells the simulator to limit the transient timestep there rather than extrapolate
across the event. We run the SAME transient with the announcement on and off and
check that:

  * the announcement forces many more (finer) timepoints in the switched region
    -- i.e. the discontinuity actually limits the timestep;
  * the DC operating point is identical either way (the announcement changes only
    timestep control, never the computed solution).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    return subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                          capture_output=True, text=True).stdout


def tran_timepoints(announce):
    out = ngspice(
        f"* disc tran announce={announce}\n"
        f"vin in 0 dc 1\nn1 in out dm\ncx out 0 1n\n"
        f".model dm disc_demo(announce={announce})\n"
        f".tran 1u 100u 0 20u\n"
        f".control\npre_osdi disc_demo.osdi\nrun\n"
        f"let np = length(v(out))\nprint np\n.endc\n.end\n"
    )
    for line in out.splitlines():
        if line.strip().startswith("np"):
            return int(float(line.split("=")[1]))
    return -1


def op_current(announce):
    out = ngspice(
        f"* disc op announce={announce}\n"
        f"vin in 0 dc 1\nn1 in out dm\nrl out 0 1meg\n"
        f".model dm disc_demo(announce={announce})\n"
        f".control\npre_osdi disc_demo.osdi\nop\nprint i(vin)\n.endc\n.end\n"
    )
    for line in out.splitlines():
        if "i(vin)" in line:
            return float(line.split("=")[1])
    return None


def main():
    subprocess.run([OPENVAF, "disc_demo.va", "-o", "disc_demo.osdi"],
                   cwd=HERE, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    n_off = tran_timepoints(0)
    n_on = tran_timepoints(1)
    fine = n_on > 10 * n_off
    ok = ok and fine
    print("[1] transient timestep limiting")
    print(f"  {'PASS' if fine else 'FAIL'}  timepoints: announce=0 -> {n_off},  "
          f"announce=1 -> {n_on}   ({n_on / max(n_off,1):.0f}x finer)")

    i_off = op_current(0)
    i_on = op_current(1)
    same = i_off is not None and i_on is not None and abs(i_off - i_on) < 1e-12
    ok = ok and same
    print("[2] solution unchanged by the announcement (only timestep control differs)")
    print(f"  {'PASS' if same else 'FAIL'}  i(vin): announce=0 -> {i_off},  announce=1 -> {i_on}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
