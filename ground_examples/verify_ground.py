#!/usr/bin/env python3
"""
verify_ground.py -- verify that the Verilog-A `ground` net-type works, and that
all four declaration orderings compile to an identical, correct device, using
version10's own openvaf-r + ngspice.

Each model is a one-terminal resistor from terminal `a` to an internal `ground`
node. Placed as the lower leg of a 1k-over-R divider driven by 1 V, the output
node sits at V = R/(R+1k) -- which only holds if `gnd` is correctly collapsed to
the global 0 V reference.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPENVAF = os.path.join(HERE, "..", "OpenVAF-master", "target", "release", "openvaf-r")
NGSPICE = os.path.join(HERE, "..", "ngspice-46", "build", "src", "ngspice")

# The four accepted ground-declaration orderings (module name -> ground decl).
FORMS = {
    "gel": "ground electrical gnd;",       # net-type first
    "egr": "electrical ground gnd;",       # discipline first (fixed in Enh-9)
    "tsa": "electrical gnd; ground gnd;",  # two-step
    "tsb": "ground gnd; electrical gnd;",  # two-step, reversed
}
R = 2000.0
R1 = 1000.0


def model_src(name, ground_decl):
    return (
        '`include "disciplines.vams"\n'
        f"module {name}(a);\n"
        "    inout a; electrical a;\n"
        f"    {ground_decl}\n"
        "    parameter real R = 1000.0 from (0:inf);\n"
        "    analog I(a, gnd) <+ V(a, gnd) / R;\n"
        "endmodule\n"
    )


def vout(name):
    subprocess.run([OPENVAF, name + ".va", "-o", name + ".osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = f"""* ground test
vin a 0 dc 1
r1 a b 1k
n1 b mm
.model mm {name}(R={R})
.control
pre_osdi {name}.osdi
op
print all
.endc
.end
"""
    with open(os.path.join(HERE, "_g.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_g.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    vals = {}
    for line in out.splitlines():
        line = line.strip()
        if " = " in line and not line.startswith("."):
            k, _, v = line.partition(" = ")
            try:
                vals[k] = float(v)
            except ValueError:
                pass
    return vals


def main():
    expected = R / (R + R1)  # 0.6667
    ok = True
    print(f"expect V(a)=1.0, V(b)={expected:.4f} (Rdev={R:g}, divider {R:g}/{R+R1:g}):")
    for name, decl in FORMS.items():
        with open(os.path.join(HERE, name + ".va"), "w") as fh:
            fh.write(model_src(name, decl))
        v = vout(name)
        good = (abs(v.get("a", 0) - 1.0) < 1e-6 and
                abs(v.get("b", 0) - expected) < 1e-4)
        ok &= good
        print(f"  {decl:30s} a={v.get('a')}  b={v.get('b')}  "
              f"{'PASS' if good else 'FAIL'}")
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
