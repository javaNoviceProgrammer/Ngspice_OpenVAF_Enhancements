#!/usr/bin/env python3
"""
verify_operators.py -- verifies Enhancement-37 operator correctness, end-to-end
through the committed openvaf-r + ngspice.

`operator_audit.va` holds five self-checking modules (integer arithmetic, real
arithmetic, relational/logical, bitwise/shifts, ternary/concat). Every check that
fails adds a distinct power of two to a score emitted on a signal-flow output, so
v(out) == 0 <=> every check in that family passes, and any nonzero value is a
bitmask pinpointing the failing check.

The audit found -- and E-37 fixed -- three real defects:
  * `~x` was lowered as arithmetic negation (~12 gave -12, not -13);
  * constant folding of `>>` sign-extended (arithmetic `>>>` semantics), so
    -16 >> 2 gave -4 instead of the zero-filled 1073741820 (the runtime LLVM
    path was already correct -- only constant folding disagreed with it);
  * the ternary operator rejected string operands (`c ? "a" : "b"`).

Checks here:
  1. the audit file compiles (string ternaries used to be a type error);
  2. all five family scores read exactly 0 (60+ individual operator checks);
  3. the three formerly-broken cases are additionally asserted directly.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

FAMILIES = ["op_arith_int", "op_arith_real", "op_rel", "op_bit", "op_tern"]


def run(deck, *names):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        for nm in names:
            if line.strip().lower().startswith(nm.lower() + " "):
                vals[nm] = float(line.split("=", 1)[1])
    return vals


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] the audit compiles (string ternaries used to be a type error)")
    r = subprocess.run([OPENVAF, "operator_audit.va", "-o", "operator_audit.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("openvaf-r operator_audit.va", r.returncode == 0,
          "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[0])
    if r.returncode != 0:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] all five operator-family scores are exactly 0")
    inst = "".join(f"n{i+1} o{i+1} m{i+1}\n" for i in range(5))
    mods = "".join(f".model m{i+1} {f}\n" for i, f in enumerate(FAMILIES))
    loads = "".join(f"r{i+1} o{i+1} 0 1e6\n" for i in range(5))
    prints = " ".join(f"v(o{i+1})" for i in range(5))
    deck = ("* operator audit\n" + inst + mods + loads +
            f".control\npre_osdi operator_audit.osdi\nop\nprint {prints}\n.endc\n.end\n")
    v = run(deck, *[f"v(o{i+1})" for i in range(5)])
    for i, fam in enumerate(FAMILIES):
        score = v[f"v(o{i+1})"]
        check(f"{fam}: score == 0", score == 0.0,
              f"score = {score:g}" + ("" if score == 0 else "  <- failing-check bitmask"))

    print("[3] the three formerly-broken cases, asserted directly")
    with open(os.path.join(HERE, "_fix.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module op_fix(out); output out; voltage out;\n"
                 "  integer s; string t;\n"
                 "  analog begin\n"
                 "    s = 0;\n"
                 "    if (!((~12) == -13))              s = s + 1;\n"
                 "    if (!((-16 >> 2) == 1073741820))  s = s + 2;\n"
                 '    t = (1 > 0) ? "yes" : "no";\n'
                 '    if (!(t == "yes"))                s = s + 4;\n'
                 "    V(out) <+ s;\n  end\nendmodule\n")
    r = subprocess.run([OPENVAF, "_fix.va", "-o", "_fix.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("fix-cases compile", r.returncode == 0)
    v = run("* fixes\nn1 o m\n.model m op_fix\nr1 o 0 1e6\n"
            ".control\npre_osdi _fix.osdi\nop\nprint v(o)\n.endc\n.end\n", "v(o)")
    check("~12 == -13, -16>>2 == 1073741820, string ternary", v["v(o)"] == 0.0,
          f"score = {v['v(o)']:g}")

    print("[4] constant-folded and runtime results agree for every operator")
    # Every check above uses LITERAL operands, so it only ever exercises the
    # constant folder (mir_opt/const_eval.rs). But E-37's shift bug was precisely
    # a DISAGREEMENT between the folder and the runtime LLVM path -- the folder
    # sign-extended `>>` while codegen was already correct -- so a literals-only
    # test exercises just the side that happened to be broken, and would miss the
    # same class of bug landing on the other side.
    #
    # Every operator therefore has two independent implementations that must
    # agree. Here the left operand is laundered through $rtoi(V(in)) so it is a
    # genuine runtime unknown that cannot be folded, and each check compares it
    # against the identical expression written with literals. A nonzero score
    # means const and runtime disagree -- whichever side is wrong.
    with open(os.path.join(HERE, "_cvr.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module op_cvr(out, in); output out; voltage out;\n"
                 "  input in; voltage in;\n"
                 "  integer s, x, y;\n"
                 "  analog begin\n"
                 "    x = $rtoi(V(in));   // deck drives -16: runtime, unfoldable\n"
                 "    y = x + 9;          // -7, still a runtime value\n"
                 "    s = 0;\n"
                 "    if ((x >>  2) != (-16 >>  2))  s = s + 1;      // E-37 bug 2\n"
                 "    if ((x >>> 2) != (-16 >>> 2))  s = s + 2;\n"
                 "    if ((x <<  2) != (-16 <<  2))  s = s + 4;\n"
                 "    if ((x >>  1) != (-16 >>  1))  s = s + 8;\n"
                 "    if ((y /   3) != (-7  /   3))  s = s + 16;     // trunc toward 0\n"
                 "    if ((y %   3) != (-7  %   3))  s = s + 32;     // sign of dividend\n"
                 "    if ((x &  12) != (-16 &  12))  s = s + 64;\n"
                 "    if ((x |  12) != (-16 |  12))  s = s + 128;\n"
                 "    if ((x ^  12) != (-16 ^  12))  s = s + 256;\n"
                 "    if ((x ~^ 12) != (-16 ~^ 12))  s = s + 512;\n"
                 "    if ((~x)      != (~(-16)))     s = s + 1024;\n"
                 "    if ((-x)      != (-(-16)))     s = s + 2048;\n"
                 "    if ((y *   3) != (-7  *   3))  s = s + 4096;\n"
                 "    if ((y **  3) != (-7  **  3))  s = s + 8192;\n"
                 "    V(out) <+ s;\n  end\nendmodule\n")
    r = subprocess.run([OPENVAF, "_cvr.va", "-o", "_cvr.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("const-vs-runtime module compiles", r.returncode == 0,
          "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[0])
    v = run("* const vs runtime\nvin i 0 dc -16\nn1 o i m\n.model m op_cvr\n"
            "r1 o 0 1e6\n.control\npre_osdi _cvr.osdi\nop\nprint v(o)\n.endc\n.end\n",
            "v(o)")
    check("14 operators: constant-folded == runtime (score is a failing-op bitmask)",
          v.get("v(o)") == 0.0, f"score = {v.get('v(o)')}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
