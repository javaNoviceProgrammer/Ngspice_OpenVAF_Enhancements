#!/usr/bin/env python3
"""
verify_idtassert.py -- verifies Enhancement-52: the idt() assert/reset forms,
end-to-end through the committed openvaf-r + ngspice.

idt(expr, ic, assert[, tol]) resets the integral to `ic` while `assert` is
nonzero and resumes integration from `ic` on release. The old formulation's
reactive residual JUMPED at the reset onset (charge: integrated value -> ic),
which the transient integrator saw as an impulse -- externally-driven resets
mostly survived, but a self-referential reset (V(out) > threshold) rang
chaotically and ran away (reached ~400 V on a 1 V/s ramp). E-52 keeps the
charge smooth (react = output, always), implements reset as a stiff
first-order decay to ic (tau = 10us), and bounds the timestep only while the
decay is active (trapezoidal deadbeat region), releasing the bound once
settled so long holds stay fast.

Checks (exact):
  1. external reset: ramp 0.5 -> 1.5 in 1 s; held at 0.5 during the pulse;
     resumed to 1.5 one second after release
  2. op-dependent integrand + reset active AT the op + tol form: held 0.25,
     then 0.25 + 2 V/s after release
  3. self-referential reset stays BOUNDED at the threshold (max = 1.0; used
     to run away to ~400)
  4. relaxation oscillator (idt + hysteretic cross-event reset): peaks 1.0,
     valleys at ic, period 1.0 s, no undershoot

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def run(deck, *names):
    with open(os.path.join(HERE, "_i.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_i.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=180).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                try:
                    vals[nm] = float(line.split("=", 1)[1].split("at=")[0])
                except ValueError:
                    pass
    return vals


def main():
    subprocess.run([OPENVAF, "idtassert_demo.va", "-o", "idtassert_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=2e-3):
        nonlocal ok
        good = got is not None and abs(got - want) < tol
        ok = ok and good
        gs = "None" if got is None else f"{got:.6e}"
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {gs}, want {want:.6e}")

    print("[1] externally-reset integrator")
    deck = ("* e52\nVr rst 0 DC 0 PULSE(0 1 2 1n 1n 1 4)\nNDUT rst out nm\nRL out 0 1G\n"
            ".model nm idtreset\n.tran 0.01 4\n.control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran v1 FIND v(out) AT=1.0\nmeas tran v2 FIND v(out) AT=2.5\n"
            "meas tran v3 FIND v(out) AT=4.0\n.endc\n.end\n")
    v = run(deck, "v1", "v2", "v3")
    check("ramp: 0.5 + 1 s", v.get("v1"), 1.5)
    check("held at ic during reset", v.get("v2"), 0.5)
    check("resumed: ic + 1 s", v.get("v3"), 1.5)

    print("[2] op-dependent integrand, reset at the op, tol form")
    deck = ("* e52b\nVr rst 0 DC 1 PULSE(1 0 2 1n 1n 10 20)\nVi in 0 DC 2\n"
            "NDUT rst in out nm\nRL out 0 1G\n.model nm idtreset2\n.tran 0.01 4\n"
            ".control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran v0 FIND v(out) AT=0.5\nmeas tran v1 FIND v(out) AT=3.0\n.endc\n.end\n")
    v = run(deck, "v0", "v1")
    check("held at ic while reset at op", v.get("v0"), 0.25)
    check("resumed at 2 V/s", v.get("v1"), 2.25)

    print("[3] self-referential reset stays bounded (used to reach ~400)")
    deck = ("* e52c\nNDUT out nm\nRL out 0 1G\n.model nm idtselfreset\n.tran 0.005 3.5\n"
            ".control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran vmax MAX v(out) FROM=0.1 TO=3.4\n.endc\n.end\n")
    v = run(deck, "vmax")
    check("max = threshold", v.get("vmax"), 1.0)

    print("[4] relaxation oscillator: idt + hysteretic reset")
    deck = ("* e52d\nNDUT out nm\nRL out 0 1G\n.model nm idtosc\n.tran 0.002 5\n"
            ".control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran vmax MAX v(out) FROM=0.2 TO=4.8\n"
            "meas tran vmin MIN v(out) FROM=1.2 TO=4.8\n"
            "meas tran t1 WHEN v(out)=0.99 RISE=1\n"
            "meas tran t2 WHEN v(out)=0.99 RISE=2\n.endc\n.end\n")
    v = run(deck, "vmax", "vmin", "t1", "t2")
    check("peaks at the upper threshold", v.get("vmax"), 1.0)
    check("valleys at ic, no undershoot", v.get("vmin"), 0.0, 1e-3)
    period = None
    if v.get("t1") is not None and v.get("t2") is not None:
        period = v["t2"] - v["t1"]
    check("period = 1 s (full ramp)", period, 1.0, 2e-2)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
