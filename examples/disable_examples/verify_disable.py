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
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers
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

    # Enhancement-661 (hunt F18 of 2026-09-18): VAMS-2023 A.6.4 allows `disable`
    # only inside an analog event block; the loop idioms above are an openvaf
    # extension, said under L011 (break/continue are the standard loop exits,
    # LRM 5.11). Inside `@(initial_step)` no word. And a named `begin : b` block
    # inside an analog function -- legal, with or without a disable -- crashed
    # the compiler ("block is named", the E-646 local-variable walk).
    def compile_text(name, src, *flags):
        with open(os.path.join(HERE, name + ".va"), "w") as fh:
            fh.write(src)
        r = subprocess.run([OPENVAF, *flags, name + ".va", "-o", name + ".osdi"], cwd=HERE,
                           capture_output=True, text=True)
        os.remove(os.path.join(HERE, name + ".va"))   # scratch, not a committed model
        return r.returncode, r.stdout + r.stderr

    r = subprocess.run([OPENVAF, "break_demo.va", "-o", "break_demo.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    log = r.stdout + r.stderr
    good = (r.returncode == 0 and log.count("warning[L011]: `disable` outside an event control is an openvaf extension") == 1
            and "a loop exit is `break` or `continue` (LRM 5.11)" in log)
    ok &= good
    print(f"  break_demo: `disable` outside an event control -> L011 once, naming break/continue  {'PASS' if good else 'FAIL'}")

    rc, log = compile_text("_evt", '`include "disciplines.vams"\nmodule evt_demo(p, n);\ninout p, n; electrical p, n;\n'
                           'integer s;\nanalog begin @(initial_step) begin : blk s = 1; disable blk; s = 2; end\n'
                           'I(p, n) <+ V(p, n) * 1e-3; end\nendmodule\n')
    good = rc == 0 and "L011" not in log and "warning" not in log
    ok &= good
    print(f"  `disable` inside an @(initial_step) block: standard, no word  {'PASS' if good else 'FAIL'}")

    rc, log = compile_text("_fnb", '`include "disciplines.vams"\nmodule fnb_demo(p, n);\ninout p, n; electrical p, n;\n'
                           'analog function real f; input x; real x; begin : b f = 2 * x; end endfunction\n'
                           'analog I(p, n) <+ V(p, n) * 1e-3 * f(1.0);\nendmodule\n')
    good = rc == 0 and "crashed" not in log and "warning" not in log
    ok &= good
    print(f"  a named block inside an analog function compiles (crashed: 'block is named')  {'PASS' if good else 'FAIL'}")
    if good:
        deck = "* fnb\nvin a 0 dc 1\nn1 a 0 mm\n.model mm fnb_demo\n.control\npre_osdi _fnb.osdi\nop\nprint i(vin)\n.endc\n.end\n"
        with open(os.path.join(HERE, "_d.cir"), "w") as fh:
            fh.write(deck)
        out = subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE, capture_output=True, text=True).stdout
        good = "i(vin) = -2.00000e-03" in out
        ok &= good
        print(f"  ...and runs: f(1) = 2 -> i = -2 mA  {'PASS' if good else 'FAIL'}")

    rc, log = compile_text("_fnd", '`include "disciplines.vams"\nmodule fnd_demo(p, n);\ninout p, n; electrical p, n;\n'
                           'analog function real f; input x; real x; begin : b f = x; disable b; f = 2 * x; end endfunction\n'
                           'analog I(p, n) <+ V(p, n) * 1e-3 * f(1.0);\nendmodule\n')
    good = rc == 0 and log.count("warning[L011]: `disable` in an analog function is an openvaf extension") == 1
    ok &= good
    print(f"  `disable` inside an analog function: compiles, L011 worded for a function  {'PASS' if good else 'FAIL'}")
    if good:
        deck = "* fnd\nvin a 0 dc 1\nn1 a 0 mm\n.model mm fnd_demo\n.control\npre_osdi _fnd.osdi\nop\nprint i(vin)\n.endc\n.end\n"
        with open(os.path.join(HERE, "_d.cir"), "w") as fh:
            fh.write(deck)
        out = subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE, capture_output=True, text=True).stdout
        good = "i(vin) = -1.00000e-03" in out
        ok &= good
        print(f"  ...and the disable ends the block: f(1) = 1 -> i = -1 mA  {'PASS' if good else 'FAIL'}")

    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
