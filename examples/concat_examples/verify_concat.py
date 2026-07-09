#!/usr/bin/env python3
"""
verify_concat.py -- verifies Enhancement-34 `{...}` concatenation and `{n{...}}`
replication, end-to-end through the committed openvaf-r + ngspice.

Before E-34, `{...}` was parsed as just another spelling of the `'{...}` array
aggregate: whole arrays could not appear inside it, `{n{...}}` did not parse, and
string operands made a (useless) string array instead of a concatenated string.

`concat_demo.va` assembles a 6-tap coefficient vector by concatenation +
replication (`w = {half1, {3{k2}}, 3.0*k2}`), feeds a concat-built vector to an
averaging function (`avg4({1, 3, 2.0, 2.0})`, integer scalars cast), and gates the
output on a runtime string concatenation (`{"con","cat"} == "concat"`). We check:

  1. it COMPILES (array operands / replication / string concat all used to fail);
  2. the DC conductance equals scale * sum(w) exactly -- proving every piece:
     G = 2.0 * (k1 + 2k1 + 3*k2 + 3k2) = 2.0*(3*k1 + 6*k2);
  3. replication diagnostics: `{0{x}}` and a non-literal count are clean errors;
  4. `'{...}` aggregates are untouched (regression covered by array_examples).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def compile_va(src, dst):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst)), \
        (r.stdout + r.stderr)


def dc_current(k1, k2, v):
    deck = (
        "* concat dc\n"
        f"vin a 0 dc {v}\n"
        "n1 a 0 dm\n"
        f".model dm concat_demo(k1={k1} k2={k2})\n"
        ".control\npre_osdi concat_demo.osdi\n"
        f"dc vin {v} {v} 1\nwrdata _o.txt i(vin)\n.endc\n.end\n"
    )
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return float(open(os.path.join(HERE, "_o.txt")).read().split()[1])


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] concat + replication + string concat COMPILES")
    built, log = compile_va("concat_demo.va", "concat_demo.osdi")
    check("openvaf-r concat_demo.va", built,
          "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] DC conductance == scale*sum(w) == 2*(3*k1 + 6*k2)")
    for k1, k2, v in ((1e-3, 2e-3, 1.0), (0.5e-3, 1e-3, 2.0)):
        g_exp = 2.0 * (3.0 * k1 + 6.0 * k2)
        i = dc_current(k1, k2, v)
        check(f"k1={k1:g} k2={k2:g}: I == -{g_exp:g}*{v:g}",
              abs(i + g_exp * v) < 1e-12, f"i = {i:.9e}")

    print("[3] replication diagnostics")
    for code, label in ((r"x = {0{1.0}};", "{0{...}} rejected"),
                        (r"x = {tau{1.0}};", "non-literal count rejected")):
        with open(os.path.join(HERE, "_d.va"), "w") as fh:
            fh.write('`include "disciplines.vams"\n'
                     'module concat_d(a,c); inout a,c; electrical a,c;\n'
                     'parameter real tau = 2.0;\nreal x[0:1];\n'
                     f'analog begin\n{code}\nI(a,c) <+ 1e-3*V(a,c);\nend\nendmodule\n')
        built, log = compile_va("_d.va", "_d.osdi")
        check(label, (not built) and "replication count" in log,
              "clean error" if not built else "WRONGLY ACCEPTED")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
