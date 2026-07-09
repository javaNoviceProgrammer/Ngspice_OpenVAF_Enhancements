#!/usr/bin/env python3
"""
verify_dynphys.py -- Enhancement-75: DYNAMIC physics validation of compiled
industry models, end-to-end through the committed openvaf-r + ngspice.
The companion of Enhancement-57's physcheck (which validated the static
laws): where physcheck asked "are the DC curves, Jacobians and noise
right?", this suite asks "are the CHARGES right?" -- it exercises the
reactive paths of the toolchain (ddt() lowering, the reactive autodiff
Jacobian, the jw AC stamping, and the transient integrator) against
physics that must hold across analyses. Uses the VA_TEST corpus (checks
are skipped if it is absent).

  1. PSP103 Cgg: the gate capacitance from AC (Im(ig)/w, the jw reactive
     Jacobian) equals the gate capacitance from a slow transient ramp
     (ig/(dVg/dt), the integrator on the same charge model) across the
     accumulation-to-inversion transition -- the same physics through two
     entirely different code paths.
  2. Charge conservation: over a closed gate-bias loop (0 -> 1.2 -> 0 V)
     the net gate charge integrates to ~zero relative to the one-way
     charge -- PSP103's charge model is conservative, and the integrator
     preserves that.
  3. diode_cmc junction charge: the leakage-subtracted transient integral
     of the diode current over a reverse ramp equals the integral of the
     AC-measured C(V) over the same bias interval (the physical
     charge-extraction technique) -- and C(V) decreases monotonically
     under reverse bias.
  4. Linear response: a PSP103 common-source stage driven with a small
     transient sine reproduces the .ac prediction in BOTH amplitude and
     phase (quadrature-demodulated steady state) at 1 MHz and 10 MHz --
     the reactive matrix is the same matrix in both analyses.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import bisect
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers
CORPUS = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main", "code")


def compile_model(rel, name):
    src = os.path.join(CORPUS, rel)
    if not os.path.exists(src):
        return None
    # relative paths only: openvaf-r embeds the given source path into the
    # .osdi provenance and generated artifacts must stay machine-portable
    subprocess.run([OPENVAF, os.path.relpath(src, HERE), "-o", f"_{name}.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"_{name}.osdi"


def run(deck, name):
    cir = os.path.join(HERE, f"_dp_{name}.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def read_wave(name):
    rows = []
    for line in open(os.path.join(HERE, name)):
        p = line.split()
        if len(p) >= 2:
            try:
                rows.append((float(p[0]), float(p[1])))
            except ValueError:
                pass
    return rows


def trapz(rows, fn=lambda t, v: v):
    return sum((rows[k + 1][0] - rows[k][0]) * 0.5
               * (fn(*rows[k]) + fn(*rows[k + 1])) for k in range(len(rows) - 1))


def ac_complex(out, vec):
    m = re.search(rf"{re.escape(vec)}\s*=\s*([-\d.e+]+),\s*([-\d.e+]+)", out)
    return (float(m.group(1)), float(m.group(2))) if m else None


def main():
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    if not os.path.isdir(CORPUS):
        print("VA_TEST corpus not found -- nothing to validate")
        print("ALL PASS")
        return 0

    # ------------------------------------------------------------------ [1]
    print("[1] PSP103 Cgg: AC (jw Jacobian) vs slow transient ramp (integrator)")
    psp = compile_model("psp103/vacode/psp103.va", "psp")
    f0 = 1e6

    def cgg_ac(vg):
        out = run(f"* cgg ac\nVg g 0 DC {vg} AC 1\nVd d 0 DC 0.05\n"
                  f"NX d g 0 0 mm\n.model mm PSP103VA\n"
                  f".control\nset numdgt=12\npre_osdi {psp}\n"
                  f"ac lin 1 {f0} {f0}\nprint all\n.endc\n.end\n", "cggac")
        b = ac_complex(out, "vg#branch")
        return -b[1] / (2 * math.pi * f0) if b else None

    rate = 1.2 / 120e-6  # V/s of the ramp
    run(f"* cgg tran\nVg g 0 DC 0 pwl(0 0 120u 1.2)\nVd d 0 DC 0.05\n"
        f"NX d g 0 0 mm\n.model mm PSP103VA\n"
        f".control\nset numdgt=12\npre_osdi {psp}\nsave i(vg)\n"
        f"tran 20n 120u\nwrdata _dp_cggtran.dat i(vg)\n.endc\n.end\n", "cggtran")
    ramp = read_wave("_dp_cggtran.dat")
    worst, pairs = 0.0, []
    for vg in (0.2, 0.4, 0.6, 0.8, 1.0):
        ca = cgg_ac(vg)
        t, i = min(ramp, key=lambda r: abs(r[0] - vg / rate))
        ct = -i / rate
        pairs.append((vg, ca, ct))
        worst = max(worst, abs(ct - ca) / ca)
    for vg, ca, ct in pairs:
        print(f"        Vg={vg:.1f}: AC {ca*1e15:9.3f} fF | tran {ct*1e15:9.3f} fF")
    check(f"Cgg identical through both paths at 5 biases (worst rel {worst:.2e})",
          worst < 5e-3)
    check("Cgg rises monotonically into inversion",
          all(pairs[k + 1][1] > pairs[k][1] for k in range(len(pairs) - 1)))

    # ------------------------------------------------------------------ [2]
    print("[2] charge conservation over a closed gate-bias loop")
    run(f"* qloop\nVg g 0 DC 0 pwl(0 0 60u 1.2 120u 0)\nVd d 0 DC 0.05\n"
        f"NX d g 0 0 mm\n.model mm PSP103VA\n"
        f".control\nset numdgt=12\npre_osdi {psp}\nsave i(vg)\n"
        f"tran 20n 120u\nwrdata _dp_qloop.dat i(vg)\n.endc\n.end\n", "qloop")
    loop = read_wave("_dp_qloop.dat")
    q_net = trapz(loop)
    q_one = trapz(loop, lambda t, v: abs(v))
    check(f"net loop charge / one-way charge = {abs(q_net)/q_one:.2e} (< 1e-3)",
          abs(q_net) / q_one < 1e-3)

    # ------------------------------------------------------------------ [3]
    print("[3] diode_cmc: junction charge -- transient extraction vs AC C(V)")
    dio = compile_model("diode_cmc/vacode/diode_cmc.va", "dio")

    def cap_ac(vr):
        out = run(f"* dio cv\nVa a 0 DC {-vr} AC 1\nNX a 0 mm\n"
                  f".model mm DIODE_CMC\n"
                  f".control\nset numdgt=12\npre_osdi {dio}\n"
                  f"ac lin 1 {f0} {f0}\nprint all\n.endc\n.end\n", "diocv")
        b = ac_complex(out, "va#branch")
        return -b[1] / (2 * math.pi * f0) if b else None

    grid = [k * 0.05 for k in range(41)]  # 0 .. 2 V reverse
    caps = [cap_ac(vr) for vr in grid]
    dq_ac = sum(0.05 * 0.5 * (caps[k] + caps[k + 1]) for k in range(40))
    check("C(V) monotone decreasing under reverse bias",
          all(caps[k + 1] < caps[k] for k in range(40)))

    run(f"* dio dc\nVa a 0 DC 0\nNX a 0 mm\n.model mm DIODE_CMC\n"
        f".control\nset numdgt=12\npre_osdi {dio}\ndc Va 0 -2 -0.005\n"
        f"wrdata _dp_diodc.dat i(va)\n.endc\n.end\n", "diodc")
    dc = sorted(read_wave("_dp_diodc.dat"))
    vs = [r[0] for r in dc]

    def i_leak(v):
        i = max(1, min(len(dc) - 1, bisect.bisect_left(vs, v)))
        (v0, i0), (v1, i1) = dc[i - 1], dc[i]
        return i0 + (v - v0) / (v1 - v0) * (i1 - i0)

    run(f"* dio q\nVa a 0 DC 0 pwl(0 0 200u -2)\nNX a 0 mm\n"
        f".model mm DIODE_CMC\n"
        f".control\nset numdgt=12\npre_osdi {dio}\nsave i(va)\n"
        f"tran 40n 200u\nwrdata _dp_dioq.dat i(va)\n.endc\n.end\n", "dioq")
    vrate = -2.0 / 200e-6
    disp = [(t, i - i_leak(vrate * t)) for t, i in read_wave("_dp_dioq.dat")]
    dq_tran = abs(trapz(disp))
    rel = abs(dq_tran - dq_ac) / dq_ac
    check(f"dQ transient {dq_tran:.3e} C == integral of AC C(V) {dq_ac:.3e} C "
          f"(rel {rel:.2e})", rel < 2e-2)

    # ------------------------------------------------------------------ [4]
    print("[4] PSP103 stage: transient sine reproduces the .ac response")
    CKT = "Vdd vdd 0 DC 1.2\nRL vdd d 1k\nNX d g 0 0 mm\n.model mm PSP103VA\n"
    for f in (1e6, 1e7):
        out = run(f"* cs ac\nVg g 0 DC 0.9 AC 1\n{CKT}"
                  f".control\nset numdgt=12\npre_osdi {psp}\n"
                  f"ac lin 1 {f} {f}\nprint v(d)\n.endc\n.end\n", "csac")
        re_h, im_h = ac_complex(out, "v(d)")
        mag_ac = math.hypot(re_h, im_h)
        ph_ac = math.degrees(math.atan2(im_h, re_h))

        amp, T = 1e-3, 1 / f
        run(f"* cs tran\nVg g 0 DC 0.9 sin(0.9 {amp} {f})\n{CKT}"
            f".control\nset numdgt=12\npre_osdi {psp}\nsave v(d)\n"
            f"tran {T/400} {14*T}\nwrdata _dp_cstran.dat v(d)\n.endc\n.end\n",
            "cstran")
        seg = [(t, v) for t, v in read_wave("_dp_cstran.dat")
               if 10 * T <= t <= 14 * T]
        vavg = sum(v for _, v in seg) / len(seg)
        w = 2 * math.pi * f
        a = trapz(seg, lambda t, v: (v - vavg) * math.cos(w * t)) * 2 / (4 * T)
        b = trapz(seg, lambda t, v: (v - vavg) * math.sin(w * t)) * 2 / (4 * T)
        mag_tr = math.hypot(a, b) / amp
        ph_tr = math.degrees(math.atan2(a, b))
        dmag = abs(mag_tr - mag_ac) / mag_ac
        dph = abs((ph_tr - ph_ac + 180) % 360 - 180)
        check(f"|H| at {f/1e6:.0f} MHz: tran {mag_tr:.6f} vs AC {mag_ac:.6f} "
              f"(rel {dmag:.2e})", dmag < 1e-3)
        check(f"phase at {f/1e6:.0f} MHz: tran {ph_tr:.3f} vs AC {ph_ac:.3f} deg "
              f"(diff {dph:.3f})", dph < 0.1)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
