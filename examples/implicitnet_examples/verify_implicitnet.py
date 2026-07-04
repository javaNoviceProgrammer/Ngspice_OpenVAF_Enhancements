#!/usr/bin/env python3
"""
verify_implicitnet.py -- verifies Enhancement-41 implicit nets in instance
connections, end-to-end through the committed openvaf-r + ngspice.

A plain identifier used in an instance port connection that names nothing
declared in the enclosing module is implicitly declared as a scalar net whose
discipline derives from the connected port (the Verilog-A appendix excludes
`default_discipline, so port derivation stands in for discipline resolution).
Before E-41 this was a hard error ("'mid' was not found in the current scope").

`implicitnet_demo.va` chains two ser2k submodules (each with its own implicit
internal net `w`) through an implicit top-level `mid`, mixing positional and
named connection forms. We check:

  1. it COMPILES (used to error);
  2. the DC resistance is exactly 4k -- proving `mid` joined the instances AND
     the two nested `w` nets stayed DISTINCT after flattening (a cross-instance
     short would read 2k);
  3. conflicting-discipline connections are a hard error with a clear message;
  4. an undeclared identifier inside V() access remains an error (implicit
     declaration is structural-only).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE


def compile_va(src, dst):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst)), \
        (r.stdout + r.stderr)


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] implicit nets COMPILE (used to be 'not found in the current scope')")
    built, log = compile_va("implicitnet_demo.va", "implicitnet_demo.osdi")
    check("openvaf-r implicitnet_demo.va", built,
          "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] DC resistance == 4k (mid joins; nested w nets stay distinct)")
    deck = ("* implicit nets\nvin in 0 dc 4\nn1 in out dm\n.model dm implicitnet_demo\n"
            "vout out 0 dc 0\n.control\npre_osdi implicitnet_demo.osdi\nop\n"
            "print i(vin)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    i = next(float(l.split("=", 1)[1]) for l in out.splitlines()
             if l.strip().lower().startswith("i(vin) "))
    check("i(vin) == -1mA (4V / 4k)", abs(i + 1e-3) < 1e-12,
          f"i = {i:.6e} (a cross-instance short would give -2e-3)")

    print("[3] conflicting disciplines on one implicit net -> hard error")
    with open(os.path.join(HERE, "_c.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module rn(p, n); inout p, n; electrical p, n;\n"
                 "  analog I(p,n) <+ V(p,n)/1e3;\nendmodule\n"
                 "module ts(t); inout t; thermal t;\n"
                 "  analog Pwr(t) <+ 1e-3*Temp(t);\nendmodule\n"
                 "module ic(in, out); inout in, out; electrical in, out;\n"
                 "  rn rA(.p(in), .n(mid));\n"
                 "  ts tB(.t(mid));\nendmodule\n")
    built, log = compile_va("_c.va", "_c.osdi")
    check("rejected with 'conflicting disciplines'",
          (not built) and "conflicting" in log, "clean error" if not built else "ACCEPTED")

    print("[4] undeclared identifier in V() access remains an error")
    with open(os.path.join(HERE, "_g.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module g(a, c); inout a, c; electrical a, c;\n"
                 "  analog I(a,c) <+ V(ghost, c)*1e-3;\nendmodule\n")
    built, log = compile_va("_g.va", "_g.osdi")
    check("rejected ('not found')", (not built) and "not found" in log,
          "clean error" if not built else "ACCEPTED")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
