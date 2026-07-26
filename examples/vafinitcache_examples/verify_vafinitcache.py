#!/usr/bin/env python3
"""Enhancement-326: init cache slots must be typed by a same-namespace lookup.

`sim_back`'s `build_init_itern` inserts INIT-function values into
`collapse_implicit` (it stores `val_map[&val]`), but `build_init_cache` tested
MAIN-function values against that set. A `mir::Value` is a bare u32 index, so the
comparison did not fail loudly -- it silently succeeded whenever the two
independent value counters happened to collide.

On a collision the slot's recorded `hir::Type` was wrong: an f64 cache slot was
stamped `Type::Bool`, which lowers to i8. The store side then emitted
`trunc double .. to i8`, and the noise loader read the slot back as a RAW i8
straight into `fmul i8 %x, double %y`. The assertions build's LLVM verifier
rejected that IR; the SHIPPED release carried it into LLVM and died with
EXC_BAD_ACCESS inside DoubleAPFloat::multiply (SIGSEGV).

  [1] the reproducer compiles at all      (pre-fix: SIGSEGV, no .osdi)
  [2] the emitted module is VALID IR      (pre-fix: verifier rejected it)
  [3] it loads and simulates to a finite operating point
  [4] its noise analysis runs and is finite -- the mis-typed slot WAS the noise
      power, so this is the check that the value is now read as a real
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
    osdi = os.path.join(HERE, "initcache.osdi")
    if os.path.exists(osdi):
        os.remove(osdi)

    # [1] compiles (pre-fix this SIGSEGV'd -- a signal, i.e. negative returncode)
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, "initcache.va"), "-o", osdi],
                           capture_output=True, text=True, timeout=120)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = "HANG", ""
    check("the reproducer compiles (was a SIGSEGV in LLVM)", rc == 0 and os.path.exists(osdi),
          f"rc={rc}")
    if rc != 0:
        print(f"\nFAILURES: {passed}/{checks} passed")
        sys.exit(1)

    # [2] no invalid-IR complaint anywhere in the output
    bad = [m for m in ("Both operands to a binary operator are not of the same type",
                       "Trunc only operates on integer",
                       "Do not know how to promote this operator") if m in out]
    check("no invalid-IR diagnostics from the LLVM verifier", not bad,
          "; ".join(bad) if bad else "")

    # [3]+[4] it loads, has a finite operating point, and noise runs finite
    deck = os.path.join(HERE, "_ic.cir")
    with open(deck, "w") as f:
        f.write("initcache\n"
                "V1 n1 0 dc 1 ac 1\n"
                "N1 n1 0 icmod\n"
                ".model icmod initcache p=1.0 s=1\n"
                "R1 n1 0 1k\n"
                ".control\n"
                "pre_osdi initcache.osdi\n"
                "op\n"
                "print v(n1)\n"
                "noise v(n1) V1 dec 5 1 1k\n"
                "print onoise_total\n"
                ".endc\n.end\n")
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                            capture_output=True, text=True, timeout=180)
        nout = rr.stdout + rr.stderr
    finally:
        if os.path.exists(deck):
            os.remove(deck)

    m = re.search(r"v\(n1\)\s*=\s*([-\d.eE+]+)", nout)
    vop = float(m.group(1)) if m else None
    check("loads and has a finite operating point",
          vop is not None and abs(vop) < 1e30 and vop == vop, str(vop))

    # --- [4] NUMERIC guard: the mis-typed slot WAS the noise power, so check its
    # magnitude against the closed form rather than merely "finite". The device is
    # 1e-3 S in parallel with a 1 Meg series resistor; a white_noise(P) current
    # source into that resistance gives v_n^2 = P * R^2 per Hz, so over [1,100] Hz
    # onoise_total = sqrt(P * R^2 * BW). Read as an i8 instead of an f64 the power
    # is garbage and this misses by orders of magnitude. ---
    osdi_n = os.path.join(HERE, "initcache_noise.osdi")
    if os.path.exists(osdi_n):
        os.remove(osdi_n)
    rn = subprocess.run([OPENVAF, os.path.join(HERE, "initcache_noise.va"), "-o", osdi_n],
                        capture_output=True, text=True, timeout=120)
    if rn.returncode != 0:
        check("the noise-observable model compiles", False, f"rc={rn.returncode}")
    else:
        deck2 = os.path.join(HERE, "_icn.cir")
        with open(deck2, "w") as f:
            f.write("initcache noise\n"
                    "V1 in 0 dc 0 ac 1\n"
                    "R1 in n2 1meg\n"
                    "N1 n2 0 nm\n"
                    ".model nm initcache_noise p=4e-18 s=1\n"
                    ".control\n"
                    "pre_osdi initcache_noise.osdi\n"
                    "noise v(n2) V1 dec 2 1 100\n"
                    "print onoise_total\n"
                    ".endc\n.end\n")
        try:
            r2 = subprocess.run([NGSPICE, "-b", os.path.basename(deck2)], cwd=HERE,
                                capture_output=True, text=True, timeout=180)
            out2 = r2.stdout + r2.stderr
        finally:
            for p_ in (deck2, osdi_n):
                if os.path.exists(p_):
                    os.remove(p_)
        mn = re.search(r"onoise_total\s*=\s*([-\d.eE+]+)", out2)
        got = float(mn.group(1)) if mn else None
        R = 1.0 / (1.0e-3 + 1.0e-6)          # device conductance || 1 Meg
        want = (4.0e-18 * R * R * 99.0) ** 0.5
        ok = got is not None and got > 0 and abs(got - want) / want < 0.02
        check("the cache-slot noise POWER reads back as a real "
              f"(onoise_total ~ {want:.3e})", ok, f"got {got}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
