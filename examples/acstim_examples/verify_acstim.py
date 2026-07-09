#!/usr/bin/env python3
"""
verify_acstim.py -- verifies Enhancement-26 `ac_stim(...)` (baseline: crash-fix +
correct large-signal semantics), end-to-end through the committed openvaf-r +
ngspice.

`ac_stim` previously crashed the compiler (`unreachable!()`) on any contributing
use. It now lowers to its correct large-signal value (0), per the LRM, so a model
using it compiles and simulates. `acstim_demo.va` exercises all four signature
forms; because each is 0 in DC/transient, the terminal current is `g*V(a,b)`
whether or not the ac_stim terms are included. We check:

  1. the model COMPILES (it used to crash openvaf-r);
  2. DC and transient currents equal g*V(a,b) and are IDENTICAL with the ac_stim
     terms on vs off -- i.e. ac_stim correctly contributes 0 in the large-signal
     domain.

(The AC-domain small-signal injection is a separate follow-up; not tested here.)

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

G = 1.0e-3


def last(fname):
    with open(os.path.join(HERE, fname)) as fh:
        return float(fh.read().split()[-1])


def current(analysis, use_stim, vbias=1.0):
    if analysis == "dc":
        sweep = f"dc vin {vbias} {vbias} 1"
    else:
        sweep = "tran 1u 2u"
    deck = (f"* acstim {analysis} use={use_stim}\nvin a 0 dc {vbias}\nn1 a 0 dm\n"
            f".model dm acstim_demo(use_stim={use_stim})\n"
            f".control\npre_osdi acstim_demo.osdi\n{sweep}\n"
            f"wrdata _o.txt i(vin)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return -last("_o.txt")


def main():
    # (1) compile -- this alone used to crash openvaf-r with an internal panic
    r = subprocess.run([OPENVAF, "acstim_demo.va", "-o", "acstim_demo.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "acstim_demo.osdi"))

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] ac_stim compiles (used to crash the compiler)")
    check("model with ac_stim compiles", compiled)
    if not compiled:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] ac_stim contributes 0 in the large-signal domain (DC & transient)")
    for analysis in ("dc", "tran"):
        i_on = current(analysis, 1, 1.0)
        i_off = current(analysis, 0, 1.0)
        expect = G * 1.0
        check(f"{analysis}: I == g*V and unchanged by ac_stim",
              abs(i_on - expect) < 1e-12 and abs(i_on - i_off) < 1e-15,
              f"with={i_on:.6g}  without={i_off:.6g}  expect={expect:.6g}")

    # ------------------------------------------------------------------
    # Enhancement-51: the AC injection itself
    # ------------------------------------------------------------------
    def ac_point(model, load, freq="1k"):
        deck = (f"* E-51 {model}\nNDUT out nm\n{load}\n.model nm {model}\n"
                f".control\npre_osdi acstim_demo.osdi\nac lin 1 {freq} {freq}\n"
                "print v(out)\n.endc\n.end\n")
        with open(os.path.join(HERE, "_a.cir"), "w") as fh:
            fh.write(deck)
        out = subprocess.run([NGSPICE, "-b", "_a.cir"], cwd=HERE,
                             capture_output=True, text=True, timeout=120).stdout
        for line in out.splitlines():
            st = line.strip().lower()
            if st.startswith("v(out) "):
                re_s, im_s = line.split("=", 1)[1].split(",")
                return complex(float(re_s), float(im_s))
        return None

    print("[3] AC injection: voltage stimulus = 1∠0 exactly")
    v = ac_point("acstim_v", "R1 out 0 1G")
    check("v(out) == 1+0j", v is not None and abs(v - 1) < 1e-9, f"got {v}")

    print("[4] magnitude + phase (radians): 2∠90° = j2")
    v = ac_point("acstim_mp", "R1 out 0 1G")
    check("v(out) == 0+2j", v is not None and abs(v - 2j) < 1e-9, f"got {v}")

    print("[5] non-matching analysis name stays inactive")
    v = ac_point("acstim_other", "R1 out 0 1G")
    check("v(out) == 0", v is not None and abs(v) < 1e-12, f"got {v}")

    print("[6] current stimulus into 1k: -1000 (contribution sign)")
    v = ac_point("acstim_i", "R1 out 0 1k")
    check("v(out) == -1000", v is not None and abs(v + 1000) < 1e-6, f"got {v}")

    print("[7] embedded RC test bench: 1-pole transfer")
    v = ac_point("acstim_rc", "R1 out 0 1G")
    check("|H(fc)| = 0.7071 at -45 deg",
          v is not None and abs(abs(v) - 0.7071068) < 1e-4
          and abs(v.imag / v.real + 1.0) < 1e-3, f"got {v}")
    v = ac_point("acstim_rc", "R1 out 0 1G", freq="100k")
    check("|H(100 fc)| ~ 0.01",
          v is not None and abs(abs(v) - 0.0099995) < 1e-5, f"got {abs(v)}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
