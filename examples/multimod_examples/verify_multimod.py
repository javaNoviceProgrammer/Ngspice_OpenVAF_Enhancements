#!/usr/bin/env python3
"""
verify_multimod.py -- Enhancement-76: multi-module .osdi libraries,
end-to-end through the committed openvaf-r + ngspice.

A single .va file may hold many modules; openvaf-r compiles every one into
the .osdi as its own OSDI descriptor and ngspice's pre_osdi registers each
descriptor as a device type. This suite pins the whole packaging surface:

  [1] three modules from one .osdi simulate side by side, exact values;
  [2] a multi-module file where one module INSTANTIATES another: the
      flattened parent and the standalone child coexist as device types;
  [3] paramset blocks mix with plain modules in one library;
  [4] model-card type names are case-insensitive (SPICE convention);
  [5] a module name duplicated across two loaded libraries WARNS and keeps
      the first registration (it used to shadow silently -- a stale-library
      trap);
  [6] loading the same .osdi twice notes "already loaded" and skips;
  [7] a module named like a built-in device (vcvs) no longer crashes
      ngspice: the module is refused with a message naming the built-in and
      the remedy, and the instance line gets a clean "Expected OSDI [or
      nport] device" error that names the built-in the card resolved to
      (this was the documented Enhancement-29 segfault gotcha, now retired);
  [9]-[12] the 2026-09-04 hunt's name-collision findings: a module named
      like a `.model` type KEYWORD (`res`) is refused with the reason, the
      `.model` card that then binds to the built-in warns that the Verilog-A
      model is not the one simulating, and so does the built-in's own device
      letter (a `d` line on a module named `diode`); two modules in one .osdi
      whose names differ only in case warn, naming both spellings; and
      `pre_osdi -f` on a built-in-colliding module no longer REPLACES the
      built-in for the session.
  [8] the underlying stock defect is fixed on its own: a .model card
      naming a card-less built-in type (vcvs), referenced by an ordinary
      MOS instance with NO OSDI involved, errors cleanly instead of
      dereferencing the device's NULL model-parameter table.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
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


def compile_va(src, out):
    subprocess.run([OPENVAF, src, "-o", out], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(deck, name):
    open(os.path.join(HERE, f"_{name}.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", f"_{name}.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def val(out, expr):
    m = re.search(rf"{re.escape(expr)}\s*=\s*([-\d.e+]+)", out)
    return float(m.group(1)) if m else None


def main():
    for f in ("trio.va", "hier.va", "psmix.va", "dup1.va", "dup2.va", "vcvs.va",
              "namecase.va", "namekw.va", "namedio.va"):
        compile_va(f, f.replace(".va", ".osdi"))

    print("[1] three modules, one .osdi")
    rc, out = run("* trio\nvin in 0 dc 1\nn1 in 0 ma\nn2 in 0 mb\nn3 in o3 mc\n"
                  "r3 o3 0 1k\n.model ma res_a(r=1k)\n.model mb cond_b(g=2m)\n"
                  ".model mc gainer_c(k=3.0)\n.control\npre_osdi trio.osdi\nop\n"
                  "print -i(vin) v(o3)\n.endc\n.end\n", "t1")
    check("res_a + cond_b currents sum exactly (3 mA)",
          val(out, "-i(vin)") is not None and abs(val(out, "-i(vin)") - 3e-3) < 1e-12)
    check("gainer_c gain exact (v(o3) = 3)",
          val(out, "v(o3)") is not None and abs(val(out, "v(o3)") - 3.0) < 1e-9)

    print("[2] flattened parent + standalone child coexist")
    rc, out = run("* hier\nvin in 0 dc 1\nn1 in 0 mtop\nn2 in 0 mleaf\n"
                  ".model mtop top()\n.model mleaf leaf(r=500)\n"
                  ".control\nset numdgt=12\npre_osdi hier.osdi\nop\n"
                  "print -i(vin)\n.endc\n.end\n",
                  "t2")
    check("top (1k+2k series) + leaf(500) = 2.3333 mA exact",
          val(out, "-i(vin)") is not None
          and abs(val(out, "-i(vin)") - (1.0 / 3000 + 1.0 / 500)) < 1e-12)

    print("[3] paramset + plain modules in one library")
    rc, out = run("* psmix\nvin in 0 dc 1\nn1 in 0 mf\nn2 in 0 mo\n"
                  ".model mf fat()\n.model mo other()\n"
                  ".control\npre_osdi psmix.osdi\nop\nprint -i(vin)\n.endc\n.end\n",
                  "t3")
    check("paramset fat(250) + other(4k) = 4.25 mA exact",
          val(out, "-i(vin)") is not None
          and abs(val(out, "-i(vin)") - 4.25e-3) < 1e-12)

    print("[4] case-insensitive model-card type")
    rc, out = run("* case\nvin in 0 dc 1\nn1 in 0 ma\n.model ma RES_A(r=1k)\n"
                  ".control\npre_osdi trio.osdi\nop\nprint -i(vin)\n.endc\n.end\n",
                  "t4")
    check("RES_A resolves to res_a (1 mA)",
          val(out, "-i(vin)") is not None and abs(val(out, "-i(vin)") - 1e-3) < 1e-12)

    print("[5] duplicate module across two libraries: warn, first wins")
    rc, out = run("* dup\nvin in 0 dc 1\nn1 in 0 mm\n.model mm dup()\n"
                  ".control\npre_osdi dup1.osdi\npre_osdi dup2.osdi\nop\n"
                  "print -i(vin)\n.endc\n.end\n", "t5")
    check("warning names the duplicate device",
          'device "dup" is already registered' in out)
    check("first registration wins deterministically (1k -> 1 mA)",
          val(out, "-i(vin)") is not None and abs(val(out, "-i(vin)") - 1e-3) < 1e-12)

    print("[6] loading the same library twice")
    rc, out = run("* dbl\nvin in 0 dc 1\nn1 in 0 ma\n.model ma res_a(r=1k)\n"
                  ".control\npre_osdi trio.osdi\npre_osdi trio.osdi\nop\n"
                  "print -i(vin)\n.endc\n.end\n", "t6")
    check("second load noted and skipped", "already loaded" in out)
    check("simulation unaffected (1 mA)",
          val(out, "-i(vin)") is not None and abs(val(out, "-i(vin)") - 1e-3) < 1e-12)

    print("[7] module named like a built-in (the E-29 segfault, retired)")
    rc, out = run("* builtin clash\nvin in 0 dc 1\nn1 in 0 mm\n.model mm vcvs()\n"
                  ".control\npre_osdi vcvs.osdi\nop\nprint -i(vin)\n.endc\n.end\n",
                  "t7")
    check("no crash (used to SIGSEGV)", rc >= 0 and rc < 128)
    check("refused, naming the built-in and the remedy",
          'module "vcvs" (from "vcvs.osdi") has the same name as ngspice\'s '
          'built-in' in out and "Rename the module" in out)
    check("instance line gets a clean error that names the built-in",
          "Expected OSDI" in out   # E-242 broadened this to "OSDI or nport device"
          and 'model "mm" is ngspice\'s built-in' in out)

    print("[9] a module named like a .model type KEYWORD (res)")
    rc, out = run("* keyword clash\nvin in 0 dc 1\nn1 in 0 mm\n.model mm res r=2000\n"
                  ".control\npre_osdi namekw.osdi\nop\nprint -i(vin)\n.endc\n.end\n",
                  "t9")
    check("refused at load with the keyword named",
          "`.model` type keyword for the built-in Resistor" in out
          and 'module "res"' in out)
    check("the .model card says the built-in will simulate, not the Verilog-A model",
          '.model mm: type "res" is ngspice\'s built-in Resistor' in out
          and "does NOT reach it" in out)
    check("the N line names the built-in and the refused module",
          'model "mm" is ngspice\'s built-in Resistor' in out
          and 'module "res" loaded from "namekw.osdi" was refused' in out)

    print("[10] the silent half: the built-in's own device letter")
    rc, out = run("* d-line clash\nvin in 0 dc 0.6\nr1 in a 100\nd1 a 0 md\n"
                  ".model md diode is=1e-20\n"
                  ".control\npre_osdi namedio.osdi\nop\nprint v(a)\n.endc\n.end\n",
                  "t10")
    check("the card warns that the built-in Diode simulates in the module's place",
          '.model md: type "diode" is ngspice\'s built-in Diode' in out
          and 'module "diode" loaded from "namedio.osdi" was refused' in out)
    check("...and it does run (the built-in), so the warning is the only signal",
          val(out, "v(a)") is not None)

    print("[11] two modules differing only in case, one .osdi")
    rc, out = run("* case pair\nvin in 0 dc 1\nn1 in 0 m1\n.model m1 Foo\n"
                  "v2 b 0 dc 1\nn2 b 0 m2\n.model m2 foo\n"
                  ".control\npre_osdi namecase.osdi\nop\nprint -i(vin)\nprint -i(v2)\n.endc\n.end\n",
                  "t11")
    check("warned, naming both spellings and this same library",
          'device "foo" is already registered as "Foo" by this same library' in out
          and "differ only in case" in out)
    check("first module wins for both cards (1 mA, not foo's 7 mA) -- as the warning says",
          val(out, "-i(vin)") is not None and abs(val(out, "-i(vin)") - 1e-3) < 1e-12
          and val(out, "-i(v2)") is not None and abs(val(out, "-i(v2)") - 1e-3) < 1e-12)

    print("[12] pre_osdi -f on a built-in-colliding module keeps the built-in")
    rc, out = run("* reload swap\nvin in 0 dc 0.6\nr1 in a 100\nd1 a 0 md\n"
                  ".model md d(is=1e-14)\n"
                  ".control\npre_osdi namedio.osdi\npre_osdi -f namedio.osdi\nop\n"
                  "print v(a)\nshowmod md\n.endc\n.end\n", "t12")
    check("the reload registers nothing and says so",
          'reloaded "namedio.osdi" (0 of 1 device registered)' in out)
    check("a plain `d` card is still the built-in junction diode "
          "(it used to become the Verilog-A module for the session)",
          "Junction Diode model" in out and "loaded with OSDI" not in out)

    print("[8] stock shape: .model of a card-less built-in, no OSDI")
    rc, out = run("* stock clash\nvin in 0 dc 1\nr1 in 0 1k\nm1 a b c d mm\n"
                  ".model mm vcvs()\n.control\nop\n.endc\n.end\n", "t8")
    check("no crash (used to SIGSEGV in find_model_parameter)",
          rc >= 0 and rc < 128)

    n_pass = sum(checks)
    n_fail = len(checks) - n_pass
    print()
    print(("ALL PASS" if n_fail == 0 else "FAILURES")
          + f": {n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
