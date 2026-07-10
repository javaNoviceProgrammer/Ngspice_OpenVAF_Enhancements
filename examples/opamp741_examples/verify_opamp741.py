#!/usr/bin/env python3
"""
verify_opamp741.py -- Enhancement-83: the transistor-level uA741 demo,
end-to-end through the committed openvaf-r + ngspice.

A compact Gummel-Poon-flavored BJT written in Verilog-A (bjt741.va, one
module serving NPN and PNP via type=+/-1) powers the textbook Fairchild
741 topology (ua741.subckt, 20 transistors: Q1-Q7 input stage with active
load, Q8-Q13 mirrors + Widlar bias, Q16/Q17 Miller stage with the 30 pF
Cc, class-AB Q14/Q20 output). The datasheet-class figures of merit then
EMERGE from the topology rather than being programmed in.

  [1] the BJT model itself: at a Gummel point the base current is exactly
      ic_fwd/BF, and the PNP is the exact polarity mirror of the NPN;
  [2] DC (run_opamp741.py): follower tracking, output swing, open-loop
      gain from the DC slope, input offset;
  [3] AC: open-loop gain, unity-gain frequency, phase margin -- plus the
      single-pole consistency identity Aol * f3dB ~ fu (Miller
      compensation doing its textbook job);
  [4] transient: slew rate in the classic 741 window and clean
      small-step settling.

Windows are generous (this is a demonstrative model, not silicon):
Aol > 90 dB, fu in 0.3..1.5 MHz, PM in 55..105 deg, slew 0.3..0.9 V/us,
|Vos| < 2 mV.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = []


def check(label, cond):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def main():
    print("[1] bjt741 model: Gummel point + NPN/PNP mirror")
    subprocess.run([OPENVAF, "bjt741.va", "-o", "bjt741.osdi"], cwd=HERE,
                   check=True, capture_output=True)
    deck = ("* bjt sanity\nvb b 0 dc 0.65\nvc c 0 dc 3.0\n"
            "nq1 c b 0 npn1\n.model npn1 bjt741(type=1)\n"
            "vpe pe 0 dc -0.65\nvpc pc 0 dc -3.0\n"
            "nq2 pc pe 0 pnp1\n.model pnp1 bjt741(type=-1)\n"
            ".control\npre_osdi bjt741.osdi\nset numdgt=12\nop\n"
            "print i(vc) i(vb) i(vpc) i(vpe)\n.endc\n.end\n")
    open(os.path.join(HERE, "_v_bjt.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_v_bjt.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    vals = {k: float(v) for k, v in
            re.findall(r"i\((v\w+)\)\s*=\s*([-\d.e+]+)", out)}
    ic, ib = -vals["vc"], -vals["vb"]
    # ib = ic_fwd/BF where ic = ic_fwd*(1 + vcb/VAF); vcb=2.35, VAF=100
    icfwd = ic / (1.0 + 2.35/100.0)
    check("beta relation ib == ic_fwd/200 (rel "
          f"{abs(ib - icfwd/200)/(icfwd/200):.1e} < 1e-3)",
          abs(ib - icfwd/200)/(icfwd/200) < 1e-3)
    check("PNP is the exact polarity mirror of the NPN",
          abs(vals["vpc"] + vals["vc"]) < 1e-15
          and abs(vals["vpe"] + vals["vb"]) < 1e-15)

    print("[2][3][4] full characterization (run_opamp741.py)")
    r = subprocess.run([sys.executable, "run_opamp741.py"], cwd=HERE,
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        print(r.stdout[-800:], r.stderr[-400:])
        check("characterization run completed", False)
    else:
        s = dict(line.split(None, 1) for line in
                 open(os.path.join(HERE, "results", "summary.txt"))
                 if line.strip())
        err = float(s["follower_err_mV"])
        lo, hi = (float(x) for x in s["swing_V"].split())
        adc = float(s["adc_dB"])
        vos = float(s["vos_uV"])
        aol = float(s["aol_dB"])
        f3 = float(s["f3_Hz"])
        fu = float(s["fu_MHz"])
        pm = float(s["pm_deg"])
        sr = float(s["slew_Vus"])
        check(f"follower tracks (|err| = {err:.2f} mV < 5)", err < 5.0)
        check(f"output swing beyond +/-12 V (got {lo:.1f}..{hi:.1f})",
              lo < -12.0 and hi > 12.0)
        check(f"open-loop DC gain > 90 dB (got {adc:.1f})", adc > 90.0)
        check(f"input offset |{vos:.0f}| uV < 2000", abs(vos) < 2000.0)
        check(f"AC Aol in 95..115 dB (got {aol:.1f})", 95.0 <= aol <= 115.0)
        check(f"unity-gain frequency in 0.3..1.5 MHz (got {fu:.3f})",
              0.3 <= fu <= 1.5)
        check(f"phase margin in 55..105 deg (got {pm:.1f})",
              55.0 <= pm <= 105.0)
        # single-pole (Miller) identity: Aol_lin * f3 ~ fu
        fu_pred = 10**(aol/20.0) * f3 / 1e6
        check(f"Miller identity Aol*f3 ~ fu ({fu_pred:.2f} vs {fu:.2f} MHz, "
              f"rel {abs(fu_pred-fu)/fu:.2f} < 0.3)",
              abs(fu_pred - fu)/fu < 0.3)
        check(f"slew rate in the 741 window 0.3..0.9 V/us (got {sr:.2f})",
              0.3 <= sr <= 0.9)

    print("[5] E-128 dynorder robustness on the stiff 741 slew")
    # The big +/-5 V square-wave follower slew is a stiff transistor-level
    # transient. Letting the Gear order climb during the slew used to collapse
    # the timestep ("Timestep too small"); the E-128 order controller now holds
    # the order low after each pulse breakpoint and walks it back down on a high
    # rejection rate, so dynamic-order control completes it -- and to the same
    # answer as fixed low-order Gear.
    def slew_final(opts):
        deck = ("* 741 follower slew (E-128 dynorder robustness)\n"
                ".include ./ua741.subckt\n"
                "vcc vcc 0 dc 15\nvee vee 0 dc -15\n"
                "vin in 0 dc 0 pulse(-5 5 2u 10n 10n 60u 120u)\n"
                "x1 in out out vcc vee ua741\nrl out 0 2k\n"
                f".option {opts}\n"
                ".control\npre_osdi bjt741.osdi\nset numdgt=10\ntran 20n 80u\n"
                "let vend = v(out)[length(v(out))-1]\nprint vend\n.endc\n.end\n")
        open(os.path.join(HERE, "_v_slew.cir"), "w").write(deck)
        r = subprocess.run([NGSPICE, "-b", "_v_slew.cir"], cwd=HERE,
                           capture_output=True, text=True, timeout=300)
        out = r.stdout + r.stderr
        m = re.search(r"vend\s*=\s*([-\d.e+]+)", out)
        return ("Timestep too small" not in out,
                float(m.group(1)) if m else None)
    ref_ok, ref_v = slew_final("method=gear maxord=2")           # fixed low-order Gear
    dyn_ok, dyn_v = slew_final("method=gear maxord=3 dynorder")   # dynamic high-order
    check("dynorder completes the stiff 741 slew (no timestep collapse)", dyn_ok)
    check(f"dynorder slew answer matches the Gear-2 reference "
          f"(dyn {dyn_v} vs ref {ref_v})",
          dyn_ok and ref_ok and dyn_v is not None and ref_v is not None
          and abs(dyn_v - ref_v) < 5e-3 * abs(ref_v) + 1e-3)

    n_pass = sum(checks)
    n_fail = len(checks) - n_pass
    print()
    print(("ALL PASS" if n_fail == 0 else "FAILURES")
          + f": {n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
