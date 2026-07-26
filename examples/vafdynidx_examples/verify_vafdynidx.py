#!/usr/bin/env python3
"""Enhancement-328: a dynamic array index used directly as a contribution RHS.

`BodyRef::get_expr` funnelled every `BitSelect` into `resolve_path`, which only
resolves `Ty::Var`/`Ty::Param`/... and `panic!`s otherwise. A dynamically-indexed
array read has no backing variable -- inference types it `Ty::Val(..)` and records
it out-of-band in `dynamic_index_refs` -- so `get_expr` was not total, and callers
that merely probe an expression's SHAPE crashed the SHIPPED compiler with
"invalid HIR: path BitSelect { .. } was not resolved".

`lower_expr` never hit it because it short-circuits on `dynamic_index()` first,
which is exactly why `x = g[k]; I <+ V*x;` compiled while `I <+ V*g[k];` did not.

Compiling is not the bar -- the read must select the RIGHT element:

  [1] the model compiles                        (pre-fix: compiler panic)
  [2] each index selects its own element        (g[k] = (k+1) mS at V=1)
  [3] the "read into a temp first" spelling, which always worked, still agrees
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


def main():
    osdi = os.path.join(HERE, "dynidx.osdi")
    if os.path.exists(osdi):
        os.remove(osdi)
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, "dynidx.va"), "-o", osdi],
                           capture_output=True, text=True, timeout=120)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = "HANG", ""
    sig = next((l for l in out.splitlines() if "panicked at" in l), "")
    check("dynamic array index in a contribution compiles", rc == 0 and os.path.exists(osdi),
          f"rc={rc} {sig[:60]}")
    if rc != 0:
        print(f"\nFAILURES: {passed}/{checks} passed")
        sys.exit(1)

    deck = os.path.join(HERE, "_dyn.cir")
    lines = ["dynamic index selection\n"]
    for k in range(4):
        lines.append(f"V{k} n{k} 0 dc 1\nN{k} n{k} 0 m{k}\n.model m{k} dynidx k={k}\n")
    lines.append(".control\npre_osdi dynidx.osdi\nop\n"
                 "print i(v0) i(v1) i(v2) i(v3)\n.endc\n.end\n")
    with open(deck, "w") as f:
        f.write("".join(lines))
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                            capture_output=True, text=True, timeout=120)
        out = rr.stdout + rr.stderr
    finally:
        if os.path.exists(deck):
            os.remove(deck)

    got, wrong = [], []
    for k in range(4):
        m = re.search(rf"i\(v{k}\)\s*=\s*([-\d.eE+]+)", out)
        v = float(m.group(1)) if m else None
        got.append(v)
        want = -(k + 1) * 1.0e-3          # g[k] = (k+1) mS at V = 1, source current negative
        if v is None or abs(v - want) > 1e-12:
            wrong.append(f"k={k}: got {v}, want {want}")
    check("each index selects its own element (g[k] = (k+1) mS)", not wrong,
          "; ".join(wrong) if wrong else str(got))

    # [3] the always-working spelling must agree
    tmp = os.path.join(HERE, "_tmp.va")
    with open(tmp, "w") as f:
        f.write('`include "disciplines.vams"\n'
                "module _tmp(a,b); inout a,b; electrical a,b;\n"
                "  parameter integer k = 0 from [0:3];\n"
                "  real g[0:3]; real x;\n"
                "  analog begin\n"
                "    g[0]=1.0e-3; g[1]=2.0e-3; g[2]=3.0e-3; g[3]=4.0e-3;\n"
                "    x = g[k];\n"
                "    I(a,b) <+ V(a,b) * x;\n"
                "  end\nendmodule\n")
    tosdi = os.path.join(HERE, "_tmp.osdi")
    try:
        rt = subprocess.run([OPENVAF, tmp, "-o", tosdi], capture_output=True, text=True, timeout=120)
        ok_t = rt.returncode == 0
        vals_t = []
        if ok_t:
            d2 = os.path.join(HERE, "_dyn2.cir")
            l2 = ["temp spelling\n"]
            for k in range(4):
                l2.append(f"V{k} n{k} 0 dc 1\nN{k} n{k} 0 t{k}\n.model t{k} _tmp k={k}\n")
            l2.append(".control\npre_osdi _tmp.osdi\nop\nprint i(v0) i(v1) i(v2) i(v3)\n.endc\n.end\n")
            with open(d2, "w") as f:
                f.write("".join(l2))
            try:
                r2 = subprocess.run([NGSPICE, "-b", os.path.basename(d2)], cwd=HERE,
                                    capture_output=True, text=True, timeout=120)
                o2 = r2.stdout + r2.stderr
            finally:
                if os.path.exists(d2):
                    os.remove(d2)
            for k in range(4):
                m = re.search(rf"i\(v{k}\)\s*=\s*([-\d.eE+]+)", o2)
                vals_t.append(float(m.group(1)) if m else None)
        agree = ok_t and all(a is not None and b is not None and abs(a - b) < 1e-15
                             for a, b in zip(got, vals_t))
        check("agrees with the `x = g[k]` spelling that always worked", agree,
              f"{vals_t}" if not agree else "")
    finally:
        for p_ in (tmp, tosdi):
            if os.path.exists(p_):
                os.remove(p_)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
