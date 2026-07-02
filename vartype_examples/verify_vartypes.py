#!/usr/bin/env python3
"""
verify_vartypes.py -- verify real / integer / string analog-block variables,
including an uninitialized `string` variable (which used to crash the compiler),
end-to-end through version10's own openvaf-r + ngspice.

The `vartypes` device is a conductance built from all three variable types:
`count` (integer) resistors of `Rbase` (real) ohms combined per `mode` (string).
Placed as the lower leg of a 1k-over-Rtot divider, V(out) = Rtot/(Rtot+1k).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPENVAF = os.path.join(HERE, "..", "OpenVAF-master", "target", "release", "openvaf-r")
NGSPICE = os.path.join(HERE, "..", "ngspice-46", "build", "src", "ngspice")


def vout(model_args=""):
    subprocess.run([OPENVAF, "vartypes.va", "-o", "vartypes.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = f"""* vartypes
vin a 0 dc 1
r1 a b 1k
n1 b 0 mm
.model mm vartypes({model_args})
.control
pre_osdi vartypes.osdi
op
print all
.endc
.end
"""
    with open(os.path.join(HERE, "_v.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_v.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("b = "):
            return float(line.split("=")[1])
    raise RuntimeError(f"no V(b):\n{out}")


def main():
    # Defaults: count=2, mode defaults "" -> set to "series", Rtot = Rbase*2 = 2000.
    # V(b) = 2000 / (2000 + 1000) = 0.6667. Rbase overridable (real parameter).
    Rbase = 1500.0
    got_default = vout("")
    got_over = vout(f"Rbase={Rbase}")
    exp_default = 2000.0 / 3000.0
    exp_over = (Rbase * 2) / (Rbase * 2 + 1000.0)
    ok = True
    for label, got, exp in [
        ("default (uninit string -> \"\" -> \"series\")", got_default, exp_default),
        ("Rbase=1500 (real param override)", got_over, exp_over),
    ]:
        good = abs(got - exp) < 1e-4
        ok &= good
        print(f"  {label:44s} V(b)={got:.6f}  expected={exp:.6f}  "
              f"{'PASS' if good else 'FAIL'}")
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
