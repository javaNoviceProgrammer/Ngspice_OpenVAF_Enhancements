#!/usr/bin/env python3
"""Enhancement-337: `x * 0 -> 0` is retained for floats, deliberately.

Enhancement-335 removed the IEEE-unsound algebraic rewrites. `x * 0 -> 0` is
unsound in exactly the same way -- `inf * 0` and `NaN * 0` are NaN, not 0 -- and
was removed with them. Running the 92-model corpus campaign afterwards showed
HiSIM2's DC drain current had moved by 10x (1.30e-4 -> 1.33e-5 at Vg=0.7, Vd=1.0).

Bisecting the E-335 gates one at a time identified `x * 0` as the sole cause. That
is itself the diagnosis: `x * 0` is EXACT for every finite x, so the result could
only change if the operand were inf or NaN -- the model produces a non-finite
intermediate there and the fold was silently absorbing it.

What actually triggers the fold: one operand must be the interned CONSTANT zero and
the other a RUNTIME value. If both are constant, const_eval folds `0 * inf` to NaN
first (correctly) and the rewrite never applies; a zero-valued PARAMETER is a runtime
value and does not trigger it either. So this guards the case where a constant-zero
coefficient multiplies a runtime term that happens to be non-finite. With no evidence
that the un-folded answer is the physically correct one, changing a production model's
result by 10x is not a trade worth making for purity. The rewrites that actually
produced wrong answers stay removed.

  [1] a constant-zero coefficient kills a RUNTIME +inf term instead of poisoning it
  [2] the E-335 removals SURVIVE: x/x, sqrt(x)*sqrt(x) and exp(ln x) are still NaN
      outside their domains
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
    return {n: (float(m.group(1)) if (m := re.search(rf"{re.escape(n)}\s*=\s*([-\d.eE+]+)", t))
                else None) for n in nodes}


def main():
    # [1] a zero flag must kill a non-finite term
    rc, osdi = build("mulzero")
    if rc != 0:
        check("mulzero.va compiles", False, f"rc={rc}")
    else:
        v = sim("_mz.cir",
                "mulzero\nV1 a 0 dc 1\nVz z 0 dc 0\nN1 a 0 z m\n.model m mulzero\n"
                f".control\npre_osdi {os.path.basename(osdi)}\nop\nprint i(v1)\n.endc\n.end\n",
                ["i(v1)"])
        got = v["i(v1)"]
        # only the 1 mS conductance should contribute: I = -1 mA, finite
        check("a constant-zero coefficient kills a runtime +inf term",
              got is not None and abs(got - (-1.0e-3)) < 1e-12, f"i(v1)={got}")
        if os.path.exists(osdi):
            os.remove(osdi)

    # [2] the E-335 removals must survive
    rc, osdi = build("mulzero_ieee")
    if rc != 0:
        check("mulzero_ieee.va compiles", False, f"rc={rc}")
    else:
        nodes = ["o1", "o2", "o3"]
        res = "\n".join(f"R{i} {n} 0 1e12" for i, n in enumerate(nodes))
        v = sim("_mi.cir",
                "ieee kept\nVz z 0 dc 0\nVw w 0 dc -4\n"
                f"N1 z w {' '.join(nodes)} m\n.model m mulzero_ieee\n{res}\n"
                f".control\npre_osdi {os.path.basename(osdi)}\nop\n"
                f"print {' '.join('v(%s)' % n for n in nodes)}\n.endc\n.end\n",
                [f"v({n})" for n in nodes])
        ok = all(v[f"v({n})"] == 1.0 for n in nodes)
        check("E-335 removals survive: x/x, sqrt(x)*sqrt(x), exp(ln x) still NaN",
              ok, ", ".join(f"{n}={v['v(%s)' % n]}" for n in nodes))
        if os.path.exists(osdi):
            os.remove(osdi)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
