#!/usr/bin/env python3
"""
verify_signalflow.py -- verifies Enhancement-36 probe-only branches (ideal
ammeter semantics) and flow-only signal-flow systems, end-to-end through
the committed openvaf-r + ngspice.

The DAE only materialised CONTRIBUTED branches; a branch that was merely PROBED
read 0 and conducted nothing (open circuit). E-36 synthesises the LRM's 0V-source
(short) equation for probe-only branches, which fixes ideal ammeters, CCCS on a
sense branch, and the whole flow-only (`current` discipline) signal-flow style.

`signalflow_demo.va` packs all four system styles. We check:

  1. ideal AMMETER (probe-only named branch): shorts p->n (the series 2V/1k loop
     conducts its full 2 mA -- it used to be OPEN) and reads it (v(out) = 2V);
  2. the ammeter reads DISPLACEMENT current in AC (series 1nF at w=1e6:
     |i| = 1 mA at +90 deg -> v(out) = j*1V);
  3. CCCS current MIRROR on a probe-only sense branch: 3 mA in -> 6 mA out;
  4. potential-only signal-flow chain (voltage discipline): 1.5V * 3 * 2 = 9V;
  5. flow-only signal-flow chain (current discipline): 1 mA -> x5 -> 1k
     transimpedance = 5V, with the probed signal net sitting at 0V (shorted by
     the probe -- textbook signal-flow semantics).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE


def run(deck, *names):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        for nm in names:
            if line.strip().lower().startswith(nm.lower() + " "):
                tok = line.split("=", 1)[1].strip()
                if "," in tok:
                    re_, im_ = tok.split(",")
                    vals[nm] = complex(float(re_), float(im_))
                else:
                    vals[nm] = complex(float(tok), 0.0)
    return vals


def main():
    subprocess.run([OPENVAF, "signalflow_demo.va", "-o", "signalflow_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    pre = "pre_osdi signalflow_demo.osdi\n"

    print("[1] ideal ammeter: probe-only branch shorts AND reads (used to be open/0)")
    v = run("* ammeter dc\nvs s 0 dc 2\nr1 s a 1k\nn1 a 0 out am\n"
            ".model am ammeter_tz(rtz=1k)\nrl out 0 1e6\n"
            f".control\n{pre}op\nprint v(out) i(vs)\n.endc\n.end\n",
            "v(out)", "i(vs)")
    check("i(vs) == -2mA (branch conducts)", abs(v["i(vs)"] + 2e-3) < 1e-9,
          f"{v['i(vs)'].real:.6e}")
    check("v(out) == 2V (reads the current)", abs(v["v(out)"] - 2.0) < 1e-9,
          f"{v['v(out)'].real:.6e}")

    print("[2] ammeter reads displacement current in AC (series 1nF, w=1e6)")
    v = run("* ammeter ac\nvs s 0 dc 0 ac 1\nc1 s a 1n\nn1 a 0 out am\n"
            ".model am ammeter_tz(rtz=1k)\nrl out 0 1e6\n"
            f".control\n{pre}ac lin 1 159154.943091895 159154.943091895\n"
            "print v(out)\n.endc\n.end\n", "v(out)")
    check("v(out) == j*1V (wC*rtz at +90deg)",
          abs(v["v(out)"] - 1j) < 1e-6, f"{v['v(out)']}")

    print("[3] CCCS current mirror on a probe-only sense branch (3mA -> 6mA)")
    v = run("* mirror\nvin a 0 dc 3\nr1 a inp 1k\nn1 inp onp 0 mm\n"
            ".model mm cmirror(k=2)\nvout onp 0 dc 0\n"
            f".control\n{pre}op\nprint i(vin) i(vout)\n.endc\n.end\n",
            "i(vin)", "i(vout)")
    check("i(vin) == -3mA (sense shorts)", abs(v["i(vin)"] + 3e-3) < 1e-9,
          f"{v['i(vin)'].real:.6e}")
    check("i(vout) == -6mA (mirrored x2)", abs(v["i(vout)"] + 6e-3) < 1e-9,
          f"{v['i(vout)'].real:.6e}")

    print("[4] potential-only signal-flow chain (voltage discipline): 1.5 * 3 * 2 = 9")
    v = run("* sf chain\nvin in 0 dc 1.5\nn1 in mid g3\nn2 mid out g2\n"
            ".model g3 sfgain(k=3)\n.model g2 sfgain(k=2)\nrl out 0 1e6\n"
            f".control\n{pre}op\nprint v(mid) v(out)\n.endc\n.end\n",
            "v(mid)", "v(out)")
    check("v(mid) == 4.5", abs(v["v(mid)"] - 4.5) < 1e-9, f"{v['v(mid)'].real:g}")
    check("v(out) == 9", abs(v["v(out)"] - 9.0) < 1e-9, f"{v['v(out)'].real:g}")

    print("[5] flow-only signal-flow chain (current discipline): 1mA -> x5 -> 1k = 5V")
    v = run("* iflow chain\nn1 s1 im1\nn2 s1 s2 im2\nn3 s2 vout 0 im3\n"
            ".model im1 isrc(i0=1e-3)\n.model im2 igain(k=5)\n.model im3 i2v(rtz=1k)\n"
            f".control\n{pre}op\nprint v(vout) v(s1)\n.endc\n.end\n",
            "v(vout)", "v(s1)")
    check("v(vout) == 5V (used to be 0 -- probes were dead)",
          abs(v["v(vout)"] - 5.0) < 1e-9, f"{v['v(vout)'].real:g}")
    check("v(s1) == 0 (signal net shorted by its probe)",
          abs(v["v(s1)"]) < 1e-9, f"{v['v(s1)'].real:g}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
