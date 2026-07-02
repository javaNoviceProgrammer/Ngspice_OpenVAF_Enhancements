#!/usr/bin/env python3
"""
verify_disable.py -- verify the `disable <named_block>;` statement added in
Enhancement-9, end-to-end through version10's own openvaf-r + ngspice.

`disable` is Verilog-A's early-exit mechanism (there is no `break`/`continue`).
We check both idioms:

  * break    -- `break_demo.va`: a loop wrapped in a named block; disabling the
                block breaks the loop, and the contribution after it still runs.
                Rtot = STOP * Rbase, so V(out) = Rtot/(Rtot+1k).
  * continue -- `continue_demo.va`: the loop *body* is the named block; disabling
                it skips the rest of the current iteration. Over 8 iterations
                exactly 4 add, so Rtot = 4*Rbase and V(out) = 4000/5000 = 0.8.

Each device is the lower leg of a 1k-over-Rtot divider driven by 1 V.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPENVAF = os.path.join(HERE, "..", "OpenVAF-master", "target", "release", "openvaf-r")
NGSPICE = os.path.join(HERE, "..", "ngspice-46", "build", "src", "ngspice")
RBASE = 1000.0
R1 = 1000.0


def vout(model, args=""):
    subprocess.run([OPENVAF, model + ".va", "-o", model + ".osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = f"""* disable
vin a 0 dc 1
r1 a b 1k
n1 b 0 mm
.model mm {model}({args})
.control
pre_osdi {model}.osdi
op
print all
.endc
.end
"""
    with open(os.path.join(HERE, "_d.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("b = "):
            return float(line.split("=")[1])
    raise RuntimeError(f"no V(b):\n{out}")


def divider(n):
    Rtot = n * RBASE
    return Rtot / (Rtot + R1)


def main():
    ok = True
    print("break (disable a named block wrapping the loop -> loop breaks):")
    for stop in [2, 4, 8]:
        got = vout("break_demo", f"STOP={stop}")
        exp = divider(stop)
        good = abs(got - exp) < 1e-4
        ok &= good
        print(f"  STOP={stop:2d} -> {stop} iters  V(b)={got:.5f}  expected={exp:.5f}  "
              f"{'PASS' if good else 'FAIL'}")

    print("continue (disable the loop-body block -> skip iteration):")
    got = vout("continue_demo")
    exp = divider(4)  # 4 of 8 iterations add
    good = abs(got - exp) < 1e-4
    ok &= good
    print(f"  8 iters, 4 add   V(b)={got:.5f}  expected={exp:.5f}  "
          f"{'PASS' if good else 'FAIL'}")

    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
