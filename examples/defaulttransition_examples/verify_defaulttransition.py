#!/usr/bin/env python3
"""
verify_defaulttransition.py -- verifies Enhancement-47: the `default_transition
compiler directive (+ the transition() signature fix), end-to-end through
the committed openvaf-r + ngspice.

`default_transition <time> sets the default rise/fall time for transition()
filters that omit those arguments (LRM; 0 = instantaneous without the
directive). Previously the directive was a hard error ("macro
'`default_transition' has not been declared" -- unlike `default_discipline,
which the preprocessor deliberately captures). The value is recorded by the
preprocessor (last directive wins, file-level granularity), exposed through
the CompilationDB, and used by transition() lowering for the no-args and
delay-only forms; explicit rise/fall arguments always win.

Two pre-existing defects fixed along the way:
  * the TRANSITION signature table was one argument SHORT per entry: a
    3-argument transition(s, td, trise) CRASHED the compiler (args[3] out of
    bounds) and 4-argument calls only worked by accident through the tol
    signature; the true 5-argument tol form did not resolve at all;
  * the slew/transition tracking loop's clamp has a zero derivative when
    saturated, so the DC Jacobian diagonal vanished whenever the input
    started a full swing away from the state (singular operating point,
    garbage transient without uic). In DC the filter is now the LRM's static
    identity (y = x), selected via the integration-enable parameter.

All checks drive a timer-flipped 0/1 state through transition() variants
(flips at t=0 and t=4u):
  1. bare transition() + `default_transition 1u -> 1u ramp: half-cross at
     0.5u, plateau 1, clean DC op (no uic, no singular matrix)
  2. transition(s, 0.2u) + directive -> delay then 1u ramp (half at 0.7u)
  3. explicit args win: 2u rise ramp -> half-cross at 1.0u
  4. all arities compile and run, incl. the crashing 3-arg and 5-arg forms
  5. WITHOUT the directive: bare transition() stays instantaneous
  6. `default_transition inside `ifdef FALSE is ignored (preprocessor order)

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE


def compile_va(src, osdi):
    subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, osdi)], cwd=HERE,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(deck, *names):
    with open(os.path.join(HERE, "_d.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    out = r.stdout
    vals = {"_singular": float("singular matrix" in out + r.stderr)}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def deck(model, osdi, meas):
    return (f"* E-47 {model}\nNDUT out 0 nm\nR1 out 0 1k\n.model nm {model}\n"
            f".tran 0.02u 3u\n.control\npre_osdi {osdi}\nrun\n{meas}\n.endc\n.end\n")


def main():
    compile_va("dtdemo.va", "dtdemo.osdi")
    compile_va("dtdemo_none.va", "dtdemo_none.osdi")

    ok = True

    def check(label, got, want, tol=2e-2):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.6e}, want {want:.6e}")

    print("[1] bare transition() + `default_transition 1u (clean DC, no uic)")
    v = run(deck("dt_bare", "dtdemo.osdi",
                 "meas tran t_half WHEN v(out)=0.5 CROSS=1\n"
                 "meas tran v_top FIND v(out) AT=2.5u"), "t_half", "v_top")
    check("no singular matrix", v["_singular"], 0.0, 0.5)
    check("half-cross at 0.5u (1u ramp)", v["t_half"], 0.5e-6, 3e-8)
    check("plateau = 1", v["v_top"], 1.0, 1e-6)

    print("[2] transition(s, 0.2u): delay + the 1u default ramp (flip at 1u)")
    v = run(deck("dt_delay", "dtdemo.osdi",
                 "meas tran t_half WHEN v(out)=0.5 CROSS=1"), "t_half")
    check("half-cross at 1u + 0.2u delay + 0.5u", v["t_half"], 1.7e-6, 3e-8)

    print("[3] explicit rise time wins over the directive")
    v = run(deck("dt_forms", "dtdemo.osdi",
                 "meas tran t_half WHEN v(out)=0.4375 CROSS=1\n"
                 "meas tran v_top FIND v(out) AT=2.9u"), "t_half", "v_top")
    check("half-amplitude at 1.0u (2u ramp)", v["t_half"], 1.0e-6, 5e-8)
    check("plateau = 0.875 (all arities live)", v["v_top"], 0.875, 1e-6)

    print("[4] no directive: bare transition() stays instantaneous")
    v = run(deck("dt_none", "dtdemo_none.osdi",
                 "meas tran v_early FIND v(out) AT=0.05u"), "v_early")
    check("already 1 at 0.05u", v["v_early"], 1.0, 1e-6)

    print("[5] directive inside a false `ifdef is ignored")
    src = ('`include "disciplines.vams"\n'
           "`ifdef NEVER\n`default_transition 1u\n`endif\n"
           "module dtcond(a, c);\n  inout a, c; electrical a, c;\n  integer s;\n"
           "  analog begin\n    @(timer(0, 4u)) s = 1 - s;\n"
           "    V(a,c) <+ transition(s);\n  end\nendmodule\n")
    with open(os.path.join(HERE, "_cond.va"), "w") as fh:
        fh.write(src)
    compile_va("_cond.va", "_cond.osdi")
    v = run(deck("dtcond", "_cond.osdi",
                 "meas tran v_early FIND v(out) AT=0.05u"), "v_early")
    check("still instantaneous", v["v_early"], 1.0, 1e-6)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
