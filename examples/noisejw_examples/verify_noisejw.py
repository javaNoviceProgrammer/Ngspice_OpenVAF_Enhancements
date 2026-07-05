#!/usr/bin/env python3
"""
verify_noisejw.py -- verifies Enhancement-54: correct + node-free noise
factors (implicit-equation noise fix, op-dependent factors, ddt-of-noise as a
j*omega factor), end-to-end through the committed openvaf-r + ngspice.

Three defects/limitations fixed:
  * noise attached to implicit-equation contributions was silently DROPPED
    (build_implicit_equation never called add_noise): any source on the
    Evaluation::Equation path -- op-dependent factors, ddt-of-noise,
    correlation networks -- never reached the OSDI descriptor and the
    simulator reported NO noise for it;
  * the react optbarrier created when ddt() moves a value to the reactive
    dimension was never registered in the topology's contribution map, so
    prune_small_signal dropped the noise wave's coupling twin -- a hole in
    the Jacobian (zero transferred noise; PSP103's react_small_signal
    couplings were affected);
  * op-dependent factors (`gm * white_noise(..)`) and one ddt() in a noise
    chain now stay LINEAR (no extra internal unknown per source): the factor
    is a per-instance value evaluated at the operating point, and ddt()
    contributes the j*omega component of a complex factor
    (fac = re + j*omega*im). load_noise() fills [flat, react] signed power
    pairs per source (OSDI 0.7, stride 2) and ngspice's grouping sums
    complex amplitudes (a + j*omega*b)*T -- exact for single sources and for
    coherent same-named groups, including cancellation.

Method: the surrounding resistors' own thermal noise (the "floor") is
measured with a NOISELESS twin module of identical conductances, so every
check compares the DEVICE contribution against closed-form analytics with
the model's own constants (rtol 1e-6 on the total).

Checks:
  1. control: plain thermal noise exact; no internal nodes
  2. gm*white_noise: NO internal node (was one) + exact PSD
  3. ddt(cc*white_noise): NO internal node (was one) + exact w^2-shaped PSD
     at 1kHz / 100kHz / 1MHz
  4. ddt(k*flicker_noise): exact w^2 * kf/f^ef composition
  5. same-name flat+ddt: coherent complex sum S=(x^2+w^2 tau^2)*pwr, exact
  6. anti-phase cancellation incl. j*omega parts: exactly the measured floor
  7. one wave into two branches (correlation network; silently lost before):
     coherent cross-branch sum, exact
  8. mfactor m=4 on the ddt case: power and conductance both scale, exact

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

KB = 1.380649e-23  # the model's own `KB
T_DEV = 300.0
R = 1e3
RS = 1e3
RP = R * RS / (R + RS)


def run_deck(deck):
    with open(os.path.join(HERE, "_njw.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_njw.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    internal_nodes = len(re.findall(r"n[xd]#\w+ = ", out))
    pts = {}
    freq = None
    for line in out.splitlines():
        line = line.strip()
        mm = re.match(r"\d+\s+(\S+)\s+(\S+)\s*$", line)
        if mm:
            try:
                pts[float(mm.group(1))] = float(mm.group(2))
            except ValueError:
                pass
            continue
        # single-point sweeps print scalars instead of an indexed table
        mm = re.match(r"frequency = (\S+)", line)
        if mm:
            freq = float(mm.group(1))
        mm = re.match(r"onoise_spectrum = (\S+)", line)
        if mm and freq is not None:
            pts[freq] = float(mm.group(1))
    return internal_nodes, pts


def run_noise(model, m="", sweep="dec 2 1k 1meg"):
    deck = (f"* noise {model}\nVs in 0 DC 0.5 AC 1\nRs in a 1k\n"
            f"NX a 0 mm {m}\n.model mm {model}\n.control\nset numdgt=12\n"
            f"pre_osdi noisejw_demo.osdi\nop\nprint all\n"
            f"noise v(a) Vs {sweep}\nsetplot noise1\n"
            f"print frequency onoise_spectrum\n.endc\n.end\n")
    return run_deck(deck)


def run_noise_3t(model, sweep="dec 1 1k 1k"):
    deck = (f"* noise {model}\nVs in 0 DC 0.5 AC 1\nRs in a 1k\nRab a b 2k\n"
            f"ND a b 0 md\n.model md {model}\n.control\nset numdgt=12\n"
            f"pre_osdi noisejw_demo.osdi\nnoise v(a) Vs {sweep}\n"
            f"setplot noise1\nprint frequency onoise_spectrum\n.endc\n.end\n")
    return run_deck(deck)


def main():
    subprocess.run([OPENVAF, "noisejw_demo.va", "-o",
                    os.path.join(HERE, "noisejw_demo.osdi")],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True

    def check(label, got, want, rtol=1e-6):
        nonlocal ok
        good = abs(got - want) <= rtol * abs(want)
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.9e}, want {want:.9e}")

    def check_nodes(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: {got} internal node(s), want {want}")

    # measured resistor-noise floors (V^2/Hz), via noiseless twins
    _, sp = run_noise("njw_nonoise", sweep="dec 1 1k 1k")
    floor = sp[1e3] ** 2
    _, sp = run_noise("njw_nonoise", m="m=4", sweep="dec 1 1meg 1meg")
    floor_m4 = sp[1e6] ** 2
    _, sp = run_noise_3t("njw_twobranch_nn")
    floor_3t = sp[1e3] ** 2

    print("[1] control: plain thermal noise")
    nodes, sp = run_noise("njw_plain")
    check_nodes("no internal nodes", nodes, 0)
    dev = 4 * KB * T_DEV / R * RP**2
    check("onoise flat", sp[1e3], math.sqrt(dev + floor))

    print("[2] gm * white_noise: op-dependent factor, node-free (was 1 extra node)")
    nodes, sp = run_noise("njw_gmfac")
    check_nodes("no internal nodes", nodes, 0)
    gm = 1.0 / R + 0.1 * 0.25 / R  # V(a) = 0.25 V at the op
    dev = gm**2 * 4 * KB * T_DEV * R * RP**2
    check("onoise flat", sp[1e3], math.sqrt(dev + floor))

    print("[3] ddt(cc * white_noise): j*omega factor, node-free (was 1 extra node)")
    nodes, sp = run_noise("njw_induced")
    check_nodes("no internal nodes", nodes, 0)
    cc = 1e-9
    for f in (1e3, 1e5, 1e6):
        w = 2 * math.pi * f
        dev = (w * cc)**2 * 4 * KB * T_DEV * R * RP**2
        check(f"onoise @{f:g}Hz", sp[f], math.sqrt(dev + floor))

    print("[4] ddt(k * flicker_noise): w^2 * kf/f^ef composition")
    nodes, sp = run_noise("njw_flind")
    check_nodes("no internal nodes", nodes, 0)
    k, kf, ef = 1e-7, 1e-12, 1.2
    for f in (1e3, 1e6):
        w = 2 * math.pi * f
        dev = (w * k)**2 * kf / f**ef * RP**2
        check(f"onoise @{f:g}Hz", sp[f], math.sqrt(dev + floor))

    print("[5] same-name flat + ddt: coherent complex sum")
    nodes, sp = run_noise("njw_mix")
    check_nodes("no internal nodes", nodes, 0)
    tau, x = 1e-7, 0.5
    p = 4 * KB * T_DEV / R
    for f in (1e3, 1e6):
        w = 2 * math.pi * f
        dev = (x**2 + (w * tau)**2) * p * RP**2
        check(f"onoise @{f:g}Hz", sp[f], math.sqrt(dev + floor))

    print("[6] anti-phase cancellation incl. j*omega parts")
    _, sp = run_noise("njw_cancel")
    for f in (1e3, 1e6):
        check(f"measured floor @{f:g}Hz", sp[f], math.sqrt(floor))

    print("[7] one wave into two branches (was silently lost)")
    _, sp = run_noise_3t("njw_twobranch")
    # nodal transfers of the linear network (c grounded, `in` AC-shorted)
    g = [[1/RS + 1/R + 1/2e3, -1/2e3], [-1/2e3, 1/R + 1/2e3]]
    det = g[0][0]*g[1][1] - g[0][1]*g[1][0]
    ta, tb = g[1][1]/det, -g[0][1]/det   # current at a / at b -> v(a)
    dev = p * (ta + 0.5*tb)**2           # coherent (same wave)
    check("coherent cross-branch onoise", sp[1e3], math.sqrt(dev + floor_3t))

    print("[8] mfactor m=4 on the ddt case")
    _, sp = run_noise("njw_induced", m="m=4", sweep="dec 1 1meg 1meg")
    w = 2 * math.pi * 1e6
    rp4 = 1 / (1/RS + 4/R)
    dev = (w * cc)**2 * 4 * KB * T_DEV * R * 4 * rp4**2
    check("onoise @1MHz, m=4", sp[1e6], math.sqrt(dev + floor_m4))

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
