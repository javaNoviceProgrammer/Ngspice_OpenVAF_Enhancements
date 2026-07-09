#!/usr/bin/env python3
"""
verify_portflow.py -- verifies Enhancement-29 port-branch flow access `I(<port>)`,
end-to-end through the committed openvaf-r + ngspice.

`I(<p>)` reads the current flowing INTO the module through terminal `p`. It used to
return 0 (a TODO stub in sim_back's DAE builder + a hard-coded 0.0 in the OSDI
eval). Enhancement-29 gives it a real DAE unknown whose defining equation mirrors
node p's Kirchhoff residual, so it now reports the true port current -- resistive
AND reactive (displacement) current.

`portflow_demo.va` is a CCCS  I(out,com) = k*I(<in>)  whose input terminal is an
rin||cin load, so  I(<in>) = V(in,com)/rin + cin*dV/dt.  We check:

  1. RESISTIVE (DC):  I(<in>) = V/rin, so i(vout) = -k*vin/rin (was 0 before E-29);
  2. gain scaling:    i(vout)/i(vin) == k across several k;
  3. REACTIVE (AC):   with cin, |i(vout)| = k*|1/rin + j*w*cin|, and the current has
     the right in-phase (resistive) and quadrature (displacement) parts.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
Do NOT name the module cccs/vccs/vcvs -- those collide with ngspice built-ins.
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return r.stdout


def _num(tok):
    tok = tok.strip()
    if "," in tok:
        re, im = tok.split(",")
        return complex(float(re), float(im))
    return complex(float(tok), 0.0)


def measure(deck, *names):
    out = ngspice(deck)
    vals = {}
    for line in out.splitlines():
        for nm in names:
            if line.strip().lower().startswith(nm.lower() + " "):
                vals[nm] = _num(line.split("=", 1)[1])
    return vals


def dc_currents(vin, k, rin):
    deck = (
        f"* portflow dc\n"
        f"vin  in 0 dc {vin}\n"
        f"vout out 0 dc 0\n"
        f"n1 in out 0 cm\n"
        f".model cm portflow_cccs(k={k} rin={rin})\n"
        f".control\npre_osdi portflow_demo.osdi\nop\n"
        f"print i(vin) i(vout)\n.endc\n.end\n"
    )
    v = measure(deck, "i(vin)", "i(vout)")
    return v["i(vin)"].real, v["i(vout)"].real


def ac_currents(k, rin, cin, freq):
    deck = (
        f"* portflow ac (resistive + reactive)\n"
        f"vin  in 0 dc 0 ac 1\n"
        f"vout out 0 dc 0\n"
        f"n1 in out 0 cm\n"
        f".model cm portflow_cccs(k={k} rin={rin} cin={cin})\n"
        f".control\npre_osdi portflow_demo.osdi\nac lin 1 {freq} {freq}\n"
        f"print i(vin) i(vout)\n.endc\n.end\n"
    )
    v = measure(deck, "i(vin)", "i(vout)")
    return v["i(vin)"], v["i(vout)"]


def main():
    subprocess.run([OPENVAF, "portflow_demo.va", "-o", "portflow_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] resistive: I(<in>) senses V(in,com)/rin, so i(vout) = -k*vin/rin")
    vin, k, rin = 2.0, 10.0, 1e3
    iin, iout = dc_currents(vin, k, rin)
    exp_iin, exp_iout = -vin / rin, -k * vin / rin
    check("i(vin)  == -vin/rin",   abs(iin - exp_iin) < 1e-9,
          f"{iin:.6e} vs {exp_iin:.6e}")
    check("i(vout) == -k*vin/rin", abs(iout - exp_iout) < 1e-9,
          f"{iout:.6e} vs {exp_iout:.6e}  (was 0 before E-29)")

    print("[2] gain scaling: i(vout)/i(vin) == k for several k")
    for kk in (1.0, 5.0, 25.0, 100.0):
        iin, iout = dc_currents(3.0, kk, 2e3)
        ratio = iout / iin
        check(f"k={kk:g}", abs(ratio - kk) < 1e-6, f"ratio = {ratio:.6f}")

    print("[3] reactive: rin||cin port flow, i(<in>) = 1/rin + j*w*cin (displacement)")
    k, rin, cin = 10.0, 1e3, 1e-9
    freq = 159154.943091895               # w = 1e6  =>  w*cin = 1e-3, 1/rin = 1e-3
    w = 2.0 * math.pi * freq
    iin, iout = ac_currents(k, rin, cin, freq)
    exp_in = complex(1.0 / rin, w * cin)  # I(<in>)/V, |V|=1  -> 1e-3 + j*1e-3
    check("Re[i(vin)] == 1/rin (in-phase)",   abs(abs(iin.real) - 1.0 / rin) < 1e-6,
          f"{iin.real:.6e} vs {1.0/rin:.6e}")
    check("Im[i(vin)] == w*cin (quadrature)", abs(abs(iin.imag) - w * cin) < 1e-6,
          f"{iin.imag:.6e} vs {w*cin:.6e}")
    check("|i(vout)| == k*|i(<in>)|",         abs(abs(iout) - k * abs(exp_in)) < 1e-6,
          f"{abs(iout):.6e} vs {k*abs(exp_in):.6e}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
