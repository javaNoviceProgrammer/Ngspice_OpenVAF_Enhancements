#!/usr/bin/env python3
"""Enhancement-338: a full 64-bit bus range hung ngspice and grew without bound.

The array/bus expansion (Enhancement-221) rewrites a token `base[lo:hi]` into
scalar node names, guarded by `BUS_MAX_WIDTH` (8192) so an absurd range is left
literal instead of expanded. The width was computed as `hi - lo + 1` in signed
`long`, which OVERFLOWS for the full span:

    a[-9223372036854775808:9223372036854775807]

Signed overflow is undefined behaviour; in practice it wrapped to a small value,
so the guard saw a tiny width and let it through. The loop then stepped from
LONG_MIN toward LONG_MAX -- roughly 1.8e19 iterations, appending to a string each
time. ngspice hung and reached 7.6 GB after 9 seconds from ONE netlist line, and
the released binary did the same.

Netlists are untrusted input, so this is a resource-exhaustion defect.

The fix computes the span in UNSIGNED arithmetic (exact for every pair of longs)
and compares the span rather than the width, so the `+ 1` cannot overflow either;
`strtol` setting ERANGE now also rejects an endpoint too large to represent.

  [1] every 64-bit extreme range completes promptly instead of hanging
  [2] and does not balloon memory
  [3] ordinary buses still expand, including at the 8192 boundary
  [4] one past the boundary is still left literal -- the guard is intact
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text, timeout=30):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(text)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return "HANG", "", time.time() - t0
    finally:
        if os.path.exists(p):
            os.remove(p)


def main():
    # [1] the committed deck holds every 64-bit extreme
    with open(os.path.join(HERE, "busoverflow.cir")) as f:
        deck = f.read()
    rc, out, dt = run("_bo.cir", deck)
    check("all 64-bit extreme bus ranges complete instead of hanging",
          rc != "HANG", f"rc={rc} in {dt:.1f}s")

    # [2] and each individually, with a memory ceiling
    slow = []
    for tok in ("a[-9223372036854775808:9223372036854775807]",
                "a[9223372036854775807:-9223372036854775808]",
                "a[-9223372036854775807:9223372036854775806]",
                "a[-99999999999999999999:99999999999999999999]"):
        rc, _, dt = run("_one.cir",
                        f"one\nV1 in 0 dc 1\nR1 {tok} r=2k\nRl in 0 1k\n"
                        ".control\nop\n.endc\n.end\n", timeout=20)
        if rc == "HANG" or dt > 10:
            slow.append(f"{tok[:32]}: {dt:.1f}s")
    check("each extreme range individually completes promptly", not slow,
          "; ".join(slow) if slow else "")

    # [3] ordinary buses still expand, including at the guard boundary
    rc, out, _ = run("_ok.cir",
                     # V1 drives the bus element itself, so current actually flows
                     # through the expanded pair: a[0] -2k- a[1] -4k- gnd
                     "ok\nV1 a[0] 0 dc 3\nR1 a[0:1] 2k\nR2 a[1] 0 4k\n"
                     ".control\nop\nlisting expand\nprint i(v1)\n.endc\n.end\n")
    m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", out)
    i1 = float(m.group(1)) if m else None
    check("ordinary bus still expands and solves (series 2k+4k -> 0.5 mA)",
          "a[0] a[1]" in out and i1 is not None and abs(i1 + 0.5e-3) < 1e-9,
          f"i(v1)={i1}")

    rc, out, _ = run("_w.cir",
                     "w\nV1 in 0 dc 1\nR1 a[0:8191] r=2k\nRl in 0 1k\n"
                     ".control\nop\nlisting expand\n.endc\n.end\n", timeout=60)
    check("the BUS_MAX_WIDTH boundary (width 8192) still expands", "a[8191]" in out)

    # [4] one past the boundary stays literal
    rc, out, _ = run("_w2.cir",
                     "w\nV1 in 0 dc 1\nR1 a[0:8192] r=2k\nRl in 0 1k\n"
                     ".control\nop\nlisting expand\n.endc\n.end\n", timeout=60)
    check("width 8193 is still left literal -- the guard is intact",
          "a[0:8192]" in out)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
