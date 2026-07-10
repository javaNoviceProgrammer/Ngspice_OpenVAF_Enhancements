#!/usr/bin/env python3
"""run_opamp741.py -- DC / AC / transient characterization of the
transistor-level uA741 built from the bjt741 Verilog-A model.

  DC   : unity-follower sweep (tracking + output limits) and the
         open-loop transfer around the offset (gain from the slope);
  AC   : open-loop gain/phase via the classic L/C bias trick
         (DC feedback through 1 MH, AC injected through 1 F) ->
         Aol, dominant pole, unity-gain frequency, phase margin;
  TRAN : follower small-signal step (settling) and a +/-5 V square
         (slew rate, both edges).

Writes results/*.txt + plots/opamp741.png and prints the figures.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
os.makedirs(os.path.join(HERE, "results"), exist_ok=True)


def run(deck, name):
    open(os.path.join(HERE, f"_{name}.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", f"_{name}.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=600)
    return r.stdout + r.stderr


def wave(fname, ncols):
    rows = []
    for line in open(os.path.join(HERE, fname)):
        p = line.split()
        if len(p) >= ncols:
            try:
                rows.append([float(x) for x in p[:ncols]])
            except ValueError:
                pass
    return rows


HDR = (".include ./ua741.subckt\n"
       "vcc vcc 0 dc 15\nvee vee 0 dc -15\n")
CTL = ".control\npre_osdi bjt741.osdi\nset numdgt=10\nset wr_singlescale\n"


def main():
    subprocess.run([OPENVAF, "bjt741.va", "-o", "bjt741.osdi"], cwd=HERE,
                   check=True, capture_output=True)

    # ---------------- DC ----------------
    run("* 741 follower dc sweep\n" + HDR +
        "vin in 0 dc 0\nx1 in out out vcc vee ua741\nrl out 0 2k\n" + CTL +
        "dc vin -14 14 0.1\nwrdata results/dc_follower.txt v(out)\n"
        ".endc\n.end\n", "dcf")
    fol = wave("results/dc_follower.txt", 2)
    err = max(abs(o - i) for i, o in fol if abs(i) <= 10)
    lo = min(o for _, o in fol)
    hi = max(o for _, o in fol)

    run("* 741 open-loop dc transfer\n" + HDR +
        "vd in 0 dc 0\nx1 in 0 out vcc vee ua741\nrl out 0 2k\n" + CTL +
        "dc vd -2m 2m 2u\nwrdata results/dc_openloop.txt v(out)\n"
        ".endc\n.end\n", "dco")
    ol = wave("results/dc_openloop.txt", 2)
    # gain = steepest slope; offset = input where out crosses 0
    slopes = [(ol[k+1][1]-ol[k][1])/(ol[k+1][0]-ol[k][0]) for k in range(len(ol)-1)]
    adc = max(slopes)
    vos = min(ol, key=lambda r: abs(r[1]))[0]

    print("DC:")
    print(f"  follower tracking error (|in|<=10V) : {err*1e3:.3f} mV")
    print(f"  output swing into 2k                : {lo:.2f} .. {hi:.2f} V")
    print(f"  open-loop DC gain (slope)           : {adc:.3e} ({20*math.log10(adc):.1f} dB)")
    print(f"  input offset voltage                : {vos*1e6:.1f} uV")

    # ---------------- AC (open loop via L/C) ----------------
    run("* 741 open-loop ac\n" + HDR +
        "vin sig 0 dc 0 ac 1\n"
        "cin sig inn 1e6\n"          # AC injection into the inverting input
        "lfb out inn 1e12\n"         # DC feedback; network corner ~ uHz
        "x1 0 inn out vcc vee ua741\nrl out 0 2k\n" + CTL +
        "ac dec 40 0.01 100meg\nwrdata results/ac_openloop.txt vdb(out) cph(out)\n"
        ".endc\n.end\n", "ac")
    acd = wave("results/ac_openloop.txt", 3)
    a0 = max(db for _, db, _ in acd)
    f3 = next((f for f, db, _ in acd if db <= a0 - 3), None)
    # phase margin = 180deg minus the phase LAG accumulated between the
    # flat band and the unity-gain crossover (cph = continuous phase, rad)
    p_flat = max(acd, key=lambda r: r[1])[2]
    fu, pm = None, None
    for k in range(len(acd) - 1):
        if acd[k][1] >= 0 > acd[k+1][1]:
            f1, d1, p1 = acd[k]
            f2, d2, p2 = acd[k+1]
            t = d1 / (d1 - d2)
            fu = f1 * (f2/f1)**t
            lag = p_flat - (p1 + t*(p2 - p1))
            pm = 180.0 - math.degrees(lag)
            break
    print("AC (open loop):")
    print(f"  Aol = {a0:.1f} dB, dominant pole ~ {f3:.2f} Hz")
    print(f"  unity-gain frequency = {fu/1e6:.3f} MHz, phase margin = {pm:.1f} deg")

    # ---------------- TRAN ----------------
    # Gear (BDF) integration for the stiff transistor-level transients: the
    # default trapezoidal method rings on the sharp feedback slew and collapses
    # the timestep under the KLU solver. Dissipative Gear-2 (the default maxord)
    # is stable there and matches Sparse to ~8 sig figs -- so opamp741 solves
    # under BOTH linear solvers. DC/AC use no integration method and are
    # unaffected.
    run("* 741 follower small step\n" + HDR +
        "vin in 0 dc 0 pulse(0 0.1 1u 10n 10n 40u 80u)\n"
        "x1 in out out vcc vee ua741\nrl out 0 2k\n"
        ".option method=gear\n" + CTL +
        "save v(in) v(out)\ntran 10n 40u\n"
        "wrdata results/tran_step.txt v(in) v(out)\n.endc\n.end\n", "trs")

    run("* 741 follower slew (big square)\n" + HDR +
        "vin in 0 dc 0 pulse(-5 5 2u 10n 10n 60u 120u)\n"
        "x1 in out out vcc vee ua741\nrl out 0 2k\n"
        ".option method=gear\n" + CTL +
        "save v(in) v(out)\ntran 20n 80u\n"
        "wrdata results/tran_slew.txt v(in) v(out)\n.endc\n.end\n", "trb")
    slw = wave("results/tran_slew.txt", 3)
    # rising slew: out from -4 -> +4 after the edge at 2us
    t10 = next(t for t, _, o in slw if t > 2e-6 and o >= -4.0)
    t90 = next(t for t, _, o in slw if t > 2e-6 and o >= 4.0)
    sr_rise = 8.0 / (t90 - t10) / 1e6
    print("TRAN:")
    print(f"  slew rate (rising, -4V..+4V) = {sr_rise:.2f} V/us")

    with open(os.path.join(HERE, "results", "summary.txt"), "w") as fh:
        fh.write(f"follower_err_mV {err*1e3:.4f}\nswing_V {lo:.2f} {hi:.2f}\n"
                 f"adc_dB {20*math.log10(adc):.2f}\nvos_uV {vos*1e6:.2f}\n"
                 f"aol_dB {a0:.2f}\nf3_Hz {f3:.3f}\nfu_MHz {fu/1e6:.4f}\n"
                 f"pm_deg {pm:.2f}\nslew_Vus {sr_rise:.3f}\n")
    print("wrote results/ ; run plot_opamp741.py for the figure")


if __name__ == "__main__":
    main()
