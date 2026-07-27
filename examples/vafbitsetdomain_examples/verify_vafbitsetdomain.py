#!/usr/bin/env python3
"""Enhancement-331: `BitSet::contains` panicked outside its domain.

`BitSet::contains` indexed `self.words[word_index]` with no bounds guard. A
`HybridBitSet` row that had switched to its DENSE representation kept the word
count it had at that moment, so once the live-derivative universe grew past 64
(one word) a query for a higher element panicked --
"index out of bounds: the len is 1 but the index is 1" -- via
`HybridBitSet::contains` <- `populate_reachable`, crashing the SHIPPED compiler.

The sparse representation never had this problem: `SparseBitSet::contains` is a
search over a `Vec` and is total for any element. So the SAME logical query on the
SAME logical set returned `false` while the set was sparse and CRASHED once it went
dense -- the representation, which `HybridBitSet` exists to hide, leaking out as a
panic. An element beyond the domain cannot have been inserted (`insert` grows the
domain), so "not contained" is the only correct answer, and it is now what both
representations give.

  [1] 66 nested `ddx` (past the 64-bit word boundary) compiles   (pre-fix: panic)
  [2] and the boundary is genuinely crossed -- 64 and 128+ deep also compile
  [3] higher-order derivatives are still EXACT: making `contains` total must not
      silently drop a live derivative
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


def compile_file(path, out, timeout=180):
    if os.path.exists(out):
        os.remove(out)
    try:
        r = subprocess.run([OPENVAF, path, "-o", out], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "HANG", ""


def main():
    # [1] the committed deep-nesting reproducer
    osdi = os.path.join(HERE, "bitsetdomain.osdi")
    rc, out = compile_file(os.path.join(HERE, "bitsetdomain.va"), osdi)
    sig = next((l for l in out.splitlines() if "panicked" in l or "index out of bounds" in l), "")
    check("66 nested `ddx` (past the 64-bit word boundary) compiles",
          rc == 0 and os.path.exists(osdi), f"rc={rc} {sig[:60]}")
    if os.path.exists(osdi):
        os.remove(osdi)

    # [2] sweep across the boundary, generated so the check is not a single point
    def nested(n):
        e = "V(a,b)*V(a,b)"
        for _ in range(n):
            e = "ddx((%s)*V(a,b), V(a,b))" % e
        return ('`include "disciplines.vams"\n'
                "module _n(a,b); inout a,b; electrical a,b;\n"
                "  analog I(a,b) <+ 1.0e-3*(%s);\nendmodule\n" % e)

    bad = []
    for n in (64, 65, 128, 129):
        p = os.path.join(HERE, "_n%d.va" % n)
        with open(p, "w") as f:
            f.write(nested(n))
        o = os.path.join(HERE, "_n%d.osdi" % n)
        rcn, _ = compile_file(p, o)
        if rcn != 0:
            bad.append(f"n={n}: rc={rcn}")
        for q in (p, o):
            if os.path.exists(q):
                os.remove(q)
    check("nesting across the word boundary (64/65/128/129) all compile", not bad,
          "; ".join(bad) if bad else "")

    # [3] the numeric guard -- higher-order derivatives must stay exact
    osdi2 = os.path.join(HERE, "nested_exact.osdi")
    rc2, _ = compile_file(os.path.join(HERE, "nested_exact.va"), osdi2)
    if rc2 != 0:
        check("higher-order derivatives are still exact", False, f"compile rc={rc2}")
    else:
        deck = os.path.join(HERE, "_ne.cir")
        with open(deck, "w") as f:
            f.write("nested ddx exactness\n"
                    "V1 n1 0 dc 2\nN1 n1 0 m1\n"
                    "V2 n2 0 dc 2\nN2 n2 0 m2\n"
                    "V3 n3 0 dc 2\nN3 n3 0 m3\n"
                    ".model m1 nd1\n.model m2 nd2\n.model m3 nd3\n"
                    ".control\npre_osdi nested_exact.osdi\nop\n"
                    "print i(v1) i(v2) i(v3)\n.endc\n.end\n")
        try:
            rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                                capture_output=True, text=True, timeout=120)
            o = rr.stdout + rr.stderr
        finally:
            for q in (deck, osdi2):
                if os.path.exists(q):
                    os.remove(q)

        def val(n):
            m = re.search(rf"i\(v{n}\)\s*=\s*([-\d.eE+]+)", o)
            return float(m.group(1)) if m else None
        # V=2: d/dV(V^3)=3V^2=12, d2=6V=12, d3=6 ; scaled by 1 mS, source current negative
        want = (-12.0e-3, -12.0e-3, -6.0e-3)
        got = (val(1), val(2), val(3))
        ok = all(g is not None and abs(g - w) < 1e-9 for g, w in zip(got, want))
        check("higher-order derivatives are still exact (3V^2, 6V, 6)", ok, str(got))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
