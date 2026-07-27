#!/usr/bin/env python3
"""Enhancement-330: `ddx` in a runtime loop hung the compiler forever.

`live_derivative_fixpoint` asks, for every derivative live at a `ddx` call, for
one of order+1. A loop back edge can feed that result back into the ddx's own
argument, so round n always produces order n+1: the fixpoint GROWS THE VERY
LATTICE IT ITERATES OVER and therefore has no fixed point. Profiling showed 99.8%
of samples in `raise_order_with`, resident memory climbing, and no termination
after 15 minutes -- true non-termination, not merely slow.

There is no finite MIR that implements it (iteration k needs the k-th derivative
and the trip count is not a compile-time constant), so it is ill-formed rather
than legal-but-expensive. `ddx` IS an analog operator by openvaf's own
classification, and LRM 4.5.1 forbids analog operators in non-genvar loops --
`ddt`/`idt`/`transition`/`laplace_*` were already rejected there; `ddx` carried an
exemption that is right for `if` but wrong for loops.

  [1] the hanging shape is now a clean compile error, promptly  (was: forever)
  [2] the error names the operator and cites the LRM rule
  [3] `ddx` outside a loop -- including inside `if`/`else`, which the CMC corpus
      uses in 192 places -- still compiles
  [4] and is still numerically exact there (d/dV of V^2 = 2V)
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name, timeout=60):
    src = os.path.join(HERE, name + ".va")
    osdi = os.path.join(HERE, name + ".osdi")
    if os.path.exists(osdi):
        os.remove(osdi)
    t0 = time.time()
    try:
        r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return "HANG", "", time.time() - t0


def main():
    # [1]+[2] the hanging shape is rejected cleanly and quickly
    rc, out, dt = compile_va("ddxloop_bad")
    check("ddx in a runtime loop is rejected instead of hanging",
          rc != "HANG" and rc != 0, f"rc={rc} in {dt:.1f}s")
    check("the error names the operator and cites LRM 4.5.1",
          "ddx" in out and "not allowed in loops" in out and "4.5.1" in out,
          out.strip().splitlines()[0][:70] if out.strip() else "no output")

    # [3]+[4] ddx outside a loop still works, and is still exact
    osdi = os.path.join(HERE, "ddxloop_ok.osdi")
    rc2, out2, _ = compile_va("ddxloop_ok")
    check("ddx outside a loop (incl. inside `if`) still compiles", rc2 == 0, f"rc={rc2}")
    if rc2 == 0:
        deck = os.path.join(HERE, "_dl.cir")
        with open(deck, "w") as f:
            f.write("ddx outside loop\nV1 n1 0 dc 3\nN1 n1 0 okmod\n"
                    ".model okmod ddxloop_ok\n"
                    ".control\npre_osdi ddxloop_ok.osdi\nop\nprint i(v1)\n.endc\n.end\n")
        try:
            rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                                capture_output=True, text=True, timeout=120)
            o = rr.stdout + rr.stderr
        finally:
            for p_ in (deck, osdi):
                if os.path.exists(p_):
                    os.remove(p_)
        m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", o)
        got = float(m.group(1)) if m else None
        # V=3 > 0 so the `if` branch is taken: d/dV(V^2) = 2V = 6, scaled by 1 mS
        check("and is still numerically exact there (i = -6 mA)",
              got is not None and abs(got - (-6.0e-3)) < 1e-9, str(got))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
