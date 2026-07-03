#!/usr/bin/env python3
"""
verify_paramset.py -- verifies Enhancement-21 Verilog-AMS `paramset` blocks,
end-to-end through version11's own openvaf-r + ngspice.

`paramset_demo.va` defines one behavioural module `conductor` and three
paramsets that specialise it (`res_1k`, `res_kohm`, `varistor`). For each we
drive a known bias and check the terminal current against the closed form for
the *bound* parameter values -- proving that:

  * a constant binding takes effect  (res_1k: r = 1 kOhm);
  * a binding computed from the paramset's own card parameter takes effect
    (res_kohm: g0 = 1/(kohm*1000));
  * an unbound target parameter stays settable from the card (varistor: g0),
    while a bound one (k) is driven by the paramset (kv);
  * the derivative flows through the paramset -- the AC conductance
    gm = dI/dV = g0*(1 + 2*k*V) matches (autodiff Jacobian through the twin);
  * the base module `conductor` still works independently.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE

OSDI = os.path.join(HERE, "paramset_demo.osdi")


def run(deck, ac=False):
    """Write `deck`, run ngspice batch, return the last column of `_o.txt` as float."""
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    with open(os.path.join(HERE, "_o.txt")) as fh:
        return float(fh.read().split()[-1])


def dc_current(model_line, inst_model, vbias):
    deck = (
        f"* paramset dc\nvin a 0 dc {vbias}\nn1 a 0 {inst_model}\n{model_line}\n"
        f".control\npre_osdi paramset_demo.osdi\ndc vin {vbias} {vbias} 1\n"
        f"wrdata _o.txt i(vin)\n.endc\n.end\n"
    )
    return -run(deck)  # branch current out of the source = -i(vin)


def ac_gm(model_line, inst_model, vbias):
    deck = (
        f"* paramset ac\nvin a 0 dc {vbias} ac 1\nn1 a 0 {inst_model}\n{model_line}\n"
        f".control\npre_osdi paramset_demo.osdi\nac lin 1 1 1\n"
        f"wrdata _o.txt mag(i(vin))\n.endc\n.end\n"
    )
    return run(deck)


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(b))


def main():
    subprocess.run([OPENVAF, "paramset_demo.va", "-o", OSDI], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    checks = []  # (label, got, expected)

    # res_1k: fixed 1 kOhm -> I = V/1000
    i = dc_current(".model m res_1k", "m", 1.0)
    checks.append(("res_1k        I(1V)  = V/1kOhm", i, 1.0 / 1000.0))

    # res_kohm(kohm=2): r = 2 kOhm -> I = V/2000
    i = dc_current(".model m res_kohm(kohm=2)", "m", 1.0)
    checks.append(("res_kohm(k=2) I(1V)  = V/2kOhm", i, 1.0 / 2000.0))

    # res_kohm(kohm=0.5): r = 500 Ohm -> I = V/500
    i = dc_current(".model m res_kohm(kohm=0.5)", "m", 1.0)
    checks.append(("res_kohm(.5)  I(1V)  = V/500 ", i, 1.0 / 500.0))

    # varistor(g0=2e-3, kv=0.5): k bound to kv, g0 passes through.
    # I = g0*(1+k*V)*V at V=0.4 = 2e-3*(1+0.5*0.4)*0.4
    g0, kv, vb = 2e-3, 0.5, 0.4
    i = dc_current(f".model m varistor(g0={g0} kv={kv})", "m", vb)
    checks.append(("varistor      I(0.4) nonlinear", i, g0 * (1 + kv * vb) * vb))

    # varistor: bound k is NOT settable from the card -> setting k=9 is ignored,
    # k stays kv (=0.5). Same current as above.
    i = dc_current(f".model m varistor(g0={g0} kv={kv} k=9)", "m", vb)
    checks.append(("varistor      bound k not settable", i, g0 * (1 + kv * vb) * vb))

    # AC: gm = dI/dV = g0*(1 + 2*k*V) through the paramset (autodiff Jacobian).
    gm = ac_gm(f".model m varistor(g0={g0} kv={kv})", "m", vb)
    checks.append(("varistor      AC gm = g0(1+2kV)", gm, g0 * (1 + 2 * kv * vb)))

    # base module `conductor` still works independently (overrides didn't leak).
    i = dc_current(".model m conductor(g0=3e-3 k=0)", "m", 1.0)
    checks.append(("conductor     base module intact", i, 3e-3))

    ok = True
    print(f"{'check':40} {'got':>16} {'expected':>16}  result")
    for label, got, exp in checks:
        good = approx(got, exp)
        ok = ok and good
        print(f"{label:40} {got:>16.9g} {exp:>16.9g}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
