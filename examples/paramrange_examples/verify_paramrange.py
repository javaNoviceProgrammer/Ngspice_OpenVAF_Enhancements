#!/usr/bin/env python3
"""
verify_paramrange.py -- verifies Enhancement-56: parameter DEFAULTS exempt
from range validation (the CMC "disabled by default" idiom), clean setup
diagnostics for model configuration rejections, and the noise-analysis
singular-matrix crash fix, end-to-end through the committed openvaf-r +
ngspice.

Found by the VA_TEST end-to-end sweep (op/ac/tran/noise on all 92 standalone
corpus models):
  * OpenVAF range-checked parameter DEFAULT values at setup. CMC-standard
    models declare defaults OUTSIDE the parameter's own range as the
    "feature disabled" state (diode_cmc's `CORECOVERY = 0.0 from (0.0:1.0]`,
    FBH-HBT's `Fb = 0.0 from (0.0:inf)`, ...) and expect ranges to bind only
    user-GIVEN values -- the stock CMC models were rejected at setup with
    "Parameter ... is out of bounds". Defaults are now exempt; given values
    are still validated (both range and exclude constraints).
  * a Verilog-A $fatal/$finish raised during SETUP (models validating their
    configuration, e.g. HiSIM's port/COSUBNODE guards) surfaced as ngspice's
    baffling "impossible error - can't occur". It now reports "a Verilog-A
    device rejected its configuration during setup ($finish raised)".
  * a singular AC matrix during NOISE analysis crashed ngspice with an
    assertion (noisean.c ignored NIacIter's return; the adjoint solve then
    ran on an unfactored matrix -> SIGABRT). It now aborts the noise
    analysis cleanly; the noise analysis also honors E-55's deferred
    $finish/$stop raised at its operating point.

Checks:
  1. out-of-range DEFAULTS accepted: the demo model (two CMC-idiom
     parameters) sets up and solves at defaults; exact conductance
  2. GIVEN out-of-range value rejected ("out of bounds"), both for the
     exclusive-range form and the exclude-list form
  3. GIVEN in-range values accepted; exact conductance including the enabled
     feature path
  4. the real-world crash reproducer (hisimsoi with a $finish-rejected
     configuration, singular AC matrix): the noise analysis aborts CLEANLY
     with the new diagnostics -- before E-56 this was a SIGABRT
  5. the stock CMC diode_cmc from VA_TEST compiles + runs op/ac/noise at
     default parameters (the real-world regression that exposed the defect)

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

# the VA_TEST corpus lives in this repository (checks 4-5 use it)
DIODE_CMC = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main",
                         "code", "diode_cmc", "vacode", "diode_cmc.va")


def run(deck):
    with open(os.path.join(HERE, "_pr.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_pr.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr, r.returncode


def deck(model_line, analyses, osdi="paramrange_demo.osdi"):
    # series resistor so the output node is not clamped by the ideal source
    return (f"* pr test\nVs in 0 DC 0.5 AC 1\nRs in a 1k\nNX a 0 mm\n{model_line}\n"
            f".control\nset numdgt=10\npre_osdi {osdi}\n{analyses}\n.endc\n.end\n")


def main():
    subprocess.run([OPENVAF, "paramrange_demo.va", "-o", "paramrange_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    def get_i(out):
        m = re.search(r"vs#branch\s*=\s*(\S+)", out)
        return float(m.group(1)) if m else None

    print("[1] out-of-range DEFAULTS accepted (CMC 'disabled' idiom)")
    out, _ = run(deck(".model mm prng", "op\nprint all"))
    i = get_i(out)
    check("no bounds complaint", "out of bounds" not in out)
    check("solves with feature off: I = V/(Rs+r) = 0.25mA",
          i is not None and abs(i + 0.25e-3) < 1e-9)

    print("[2] GIVEN out-of-range values rejected")
    out, _ = run(deck(".model mm prng feature=0.0", "op\nprint all"))
    check("excluded range bound rejected (feature=0.0 given)",
          "out of bounds" in out)
    out, _ = run(deck(".model mm prng mode=0.0", "op\nprint all"))
    check("exclude-list value rejected (mode=0.0 given)",
          "out of bounds" in out)
    out, _ = run(deck(".model mm prng feature=2.0", "op\nprint all"))
    check("beyond-range value rejected (feature=2.0 given)",
          "out of bounds" in out)

    print("[3] GIVEN in-range values accepted")
    out, _ = run(deck(".model mm prng feature=0.5", "op\nprint all"))
    i = get_i(out)
    check("no bounds complaint", "out of bounds" not in out)
    # device conductance 1.5/r in series with Rs: I = 0.5/(1k + 1k/1.5)
    check("feature path enabled: I = 0.3mA",
          i is not None and abs(i + 0.3e-3) < 1e-9)

    print("[4] singular AC matrix in noise: clean abort, no crash (hisimsoi)")
    hisimsoi = os.path.join(os.path.dirname(DIODE_CMC), "..", "..", "hisimsoi",
                            "vacode", "hisimsoi.va")
    if os.path.exists(hisimsoi):
        subprocess.run([OPENVAF, hisimsoi, "-o", "_hisimsoi.osdi"],
                       cwd=HERE, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # all 6 terminals connected with COBCNODE=0: the model $finish-rejects
        # the configuration in eval; before E-56 the noise run then CRASHED on
        # an assert (unfactored singular AC matrix in the adjoint solve)
        d = ("* hisimsoi singular noise\nV0 s0 0 DC 0.1 AC 1\nR0 s0 t0 100\n"
             + "".join(f"V{i} s{i} 0 DC {0.1+0.02*i}\nR{i} s{i} t{i} 100\n"
                       for i in range(1, 5))
             + "NDUT t0 t1 t2 t3 t4 0 mmod\n.model mmod hisimsoi_va\n"
               ".control\npre_osdi _hisimsoi.osdi\n"
               "noise v(t0) V0 dec 1 1k 1k\necho STILL_ALIVE\n.endc\n.end\n")
        with open(os.path.join(HERE, "_pr.cir"), "w") as fh:
            fh.write(d)
        r = subprocess.run([NGSPICE, "-b", "_pr.cir"], cwd=HERE,
                           capture_output=True, text=True, timeout=120)
        out, rc = r.stdout + r.stderr, r.returncode
        check("ngspice did not crash (was SIGABRT)",
              "STILL_ALIVE" in out and rc in (0, 1) and "Assertion" not in out)
        check("noise aborted cleanly with the new diagnostic",
              "aborting the noise analysis" in out)
    else:
        print("  SKIP  VA_TEST corpus not found")

    print("[5] the stock CMC diode_cmc runs at defaults (real-world regression)")
    if os.path.exists(DIODE_CMC):
        subprocess.run([OPENVAF, DIODE_CMC, "-o", "_diode_cmc.osdi"],
                       cwd=HERE, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        d = deck(".model mm DIODE_CMC",
                 "op\nprint all\nac dec 2 1k 1meg\n"
                 "noise v(a) Vs dec 2 1k 1meg\nsetplot noise1\n"
                 "print onoise_spectrum", osdi="_diode_cmc.osdi")
        out, _ = run(d)
        check("no bounds complaint (CORECOVERY default)",
              "out of bounds" not in out)
        vals = [float(m.group(1)) for m in
                re.finditer(r"^\d+\s+\S+\s+(\S+)\s*$", out, re.M)]
        check("noise spectrum produced and positive",
              len(vals) >= 3 and all(v > 0 for v in vals))
    else:
        print("  SKIP  VA_TEST corpus not found")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
