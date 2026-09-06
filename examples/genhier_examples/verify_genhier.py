#!/usr/bin/env python3
"""
verify_genhier.py -- hierarchical names into generate blocks (Enhancement-564,
from the 2026-09-05 book audit), end-to-end through the committed openvaf-r +
ngspice:

  1. `V(blk.x)` reaches a named if-block's net; `V(genblk02.y)` an unlabelled
     block's (LRM 6.6.3: numbered in textual order, a leading zero added because
     `genblk2` is a declared name); `V(g1[0].z)`, `V(g1[1].z)` a loop's
     iterations; `V(g1[0].genblk1.w)` a block nested in a loop; `V(two.q)` a
     case arm; `V(g1[0].r1.mid)` an instance inside a loop -- the sum pinned as
     a current
  2. the single-item generate branch (`if (c) electrical y; else electrical y;`)
     parses, and a `case` after it is elaborated
  3. the refusals: a member the block does not declare; a loop index the loop
     never took

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


def refused(src, needle):
    r = subprocess.run([OPENVAF, os.path.join("refused", src)],
                       cwd=HERE, capture_output=True, text=True)
    log = r.stdout + r.stderr
    return r.returncode != 0 and needle in log, log


def op_current(osdi, model, vin):
    deck = (f"* genhier\nvin a 0 dc {vin}\nn1 a 0 dm\n.model dm {model}\n"
            f".control\npre_osdi {osdi}\nop\nprint i(vin)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    for line in out.splitlines():
        if line.strip().lower().startswith("i(vin) "):
            return float(line.split("=", 1)[1])
    return None


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] genhier.va compiles: named, implicit, loop, nested, case and instance paths")
    built, log = compile_va("genhier.va", "genhier.osdi")
    check("openvaf-r genhier.va", built, "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] the generated nets read back through their hierarchical names")
    for vin in (1.0, 2.0):
        # 32.5 V of generated nets, plus the two leaves' mid nets at 0.5 vin each,
        # plus the two leaves' own conductances 1e-3 and 2e-3
        exp = 1e-3 * 32.5 + 1e-3 * (0.5 * vin + 0.5 * vin) + (1e-3 + 2e-3) * vin
        i = op_current("genhier.osdi", "genhier", vin)
        check(f"vin = {vin:g}: i = -{exp:.6g}", i is not None and abs(i + exp) < 1e-9, f"i = {i!r}")

    print("[3] the refusals")
    for src, needle in (
        ("no_member.va", "'blk.nosuch' names nothing declared in generate block 'blk'"),
        ("out_of_range.va", "'g1[5].z' names nothing declared in generate block 'g1'"),
    ):
        r, log = refused(src, needle)
        check(f"refused/{src}: {needle}", r, "" if r else log.strip().splitlines()[0])

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
