#!/usr/bin/env python3
"""Enhancement-335: IEEE 754 / IEEE 1364 semantics the compiler was not honouring.

Three independent wrong answers, all on ordinary code, none of them a crash:

  * `!=` on reals was an ORDERED compare (`fcmp one`), which is FALSE whenever an
    operand is NaN. So `x != x` -- the canonical isnan idiom -- silently returned
    false, and `a != b` was not the complement of `a == b`.
  * A shift distance outside 0..=31 was passed to the hardware. AArch64 masks it
    to 5 bits, so `1 << 32` evaluated `1 << 0` == 1 where IEEE 1364 requires 0
    (the right operand of a shift is unsigned, so a negative distance is 0 too).
  * The simplifier applied identities that hold over the reals but not over IEEE
    doubles -- `x/x -> 1`, `x-x -> 0`, `x*0 -> 0`, `sqrt(x)*sqrt(x) -> x`,
    `exp(ln x) -> x`, `cosh(acosh x) -> x`. Each is exactly how a compact model
    guards a domain, so folding them replaced a deliberate NaN with a plausible
    wrong number.

  [1] `x != x` is TRUE for NaN, and `!=` is the complement of `==`
  [2] out-of-range shift distances give 0, at RUNTIME (not just as literals)
  [3] ordinary shifts are unaffected
  [4] `x/x`, `sqrt(x)*sqrt(x)` and `exp(ln x)` all yield NaN outside their domain
  [5] genuine floating-point cancellation is preserved, and non-cancelling
      arithmetic still is not perturbed
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(name):
    osdi = os.path.join(HERE, name + ".osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name + ".va"), "-o", osdi],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, osdi


def sim(deck_name, text, nodes):
    p = os.path.join(HERE, deck_name)
    with open(p, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", deck_name], cwd=HERE,
                           capture_output=True, text=True, timeout=180)
        t = r.stdout + r.stderr
    finally:
        if os.path.exists(p):
            os.remove(p)
    out = {}
    for n in nodes:
        m = re.search(rf"v\({n}\)\s*=\s*([-\d.eE+]+)", t)
        out[n] = float(m.group(1)) if m else None
    return out


def main():
    rc, osdi = build("ieee")
    if rc != 0:
        check("ieee.va compiles", False, f"rc={rc}")
        print("\nFAILURES: 0/1 passed")
        sys.exit(1)

    nodes = ["o_ne", "o_cmp", "o_shl", "o_shr", "o_div", "o_sqrt", "o_explog"]
    res = "\n".join(f"R{i} {n} 0 1e12" for i, n in enumerate(nodes))
    v = sim("_ieee.cir",
            "ieee semantics\nVz z 0 dc 0\nVw w 0 dc -4\nVn n 0 dc 0\n"
            f"N1 z w n {' '.join(nodes)} m\n.model m ieee\n{res}\n"
            f".control\npre_osdi {os.path.basename(osdi)}\nop\n"
            f"print {' '.join('v(%s)' % n for n in nodes)}\n.endc\n.end\n",
            nodes)
    if os.path.exists(osdi):
        os.remove(osdi)

    check("`x != x` is TRUE for NaN (the isnan idiom works)",
          v["o_ne"] == 1.0, f"got {v['o_ne']}")
    check("`!=` is the complement of `==` even with NaN",
          v["o_cmp"] == 1.0, f"got {v['o_cmp']}")
    check("runtime `1 << 32` is 0, and `(-1) >> 32` is 0",
          v["o_shl"] == 0.0 and v["o_shr"] == 0.0,
          f"shl={v['o_shl']} shr={v['o_shr']}")
    check("x/x, sqrt(x)*sqrt(x) and exp(ln x) are NaN outside their domain",
          v["o_div"] == 1.0 and v["o_sqrt"] == 1.0 and v["o_explog"] == 1.0,
          f"div={v['o_div']} sqrt={v['o_sqrt']} explog={v['o_explog']}")

    # [3]+[5] ordinary arithmetic must be untouched, and real cancellation kept
    name = "_ok"
    with open(os.path.join(HERE, name + ".va"), "w") as f:
        f.write('`include "disciplines.vams"\n'
                "module _ok(w, s1, s2, c1, c2);\n"
                "  inout w; output s1, s2, c1, c2;\n"
                "  electrical w, s1, s2, c1, c2;\n"
                "  parameter integer n3 = 3;\n"
                "  analog begin\n"
                "     V(s1) <+ 1 << n3;                       // 8\n"
                "     V(s2) <+ 256 >> n3;                     // 32\n"
                "     V(c1) <+ (V(w) + 1.0e16) - 1.0e16;      // w=0.5 -> 0 (cancels)\n"
                "     V(c2) <+ (V(w) + 1.0e3)  - 1.0e3;       // w=0.5 -> 0.5 (does not)\n"
                "  end\nendmodule\n")
    rc2, osdi2 = build(name)
    if rc2 != 0:
        check("ordinary shifts and cancellation behave", False, f"rc={rc2}")
    else:
        v2 = sim("_ok.cir",
                 "ok\nVw w 0 dc 0.5\nN1 w s1 s2 c1 c2 m\n.model m _ok\n"
                 "R1 s1 0 1e12\nR2 s2 0 1e12\nR3 c1 0 1e12\nR4 c2 0 1e12\n"
                 f".control\npre_osdi {os.path.basename(osdi2)}\nop\n"
                 "print v(s1) v(s2) v(c1) v(c2)\n.endc\n.end\n",
                 ["s1", "s2", "c1", "c2"])
        check("ordinary shifts are unaffected (1<<3 = 8, 256>>3 = 32)",
              v2["s1"] == 8.0 and v2["s2"] == 32.0, f"{v2['s1']}, {v2['s2']}")
        check("genuine cancellation kept, non-cancelling arithmetic exact",
              v2["c1"] == 0.0 and abs(v2["c2"] - 0.5) < 1e-12,
              f"cancel={v2['c1']} nocancel={v2['c2']}")
    for p in (os.path.join(HERE, name + ".va"), osdi2 if rc2 == 0 else ""):
        if p and os.path.exists(p):
            os.remove(p)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
