#!/usr/bin/env python3
"""verify_sweepbounds.py -- Enhancement-270: the `sweep` command validates its
numeric bounds.

`sweep`'s `<start> <stop> <step>` (and `lin|dec|oct <N> <start> <stop>`) parser
read each bound with `sw_num`, which silently returns 0 for a non-numeric token
(`ft_numparse` fails -> `atof("x") == 0`). Two consequences, both found by an
ASan/UBSan fuzz of the command:

  * a typo'd bound became a 0-valued endpoint, so `sweep r1 1k xk 1k` turned into a
    `1k -> 0` range and ran the sanity-capped maximum of 100000 analyses -- a
    minutes-long apparent hang;
  * an overflowing bound (`1e400` -> `inf`) fed the point-count `(int) floor(...)`
    cast -> **undefined behaviour** (`inf` outside the range of `int`), flagged by
    UBSan at com_sweep.c.

A third shape has the same effect with *finite* bounds: an absurd point count --
a tiny step (`1n 1u 1e-30`), a huge `lin <N>` (which used to skip even the clamp
and do a multi-GB alloc), or a tiny `dec`/`oct` spacing -- requested millions of
points, silently capped at SW_MAXPTS and run as 100000 analyses (another hang).

Fixed: `sw_isfinitenum` requires each bound to be a finite number (rejecting both
non-numeric tokens and inf/NaN); an absurd point count (> SW_MAXPTS) is now a clean
"too many points" error instead of a silent clamp-and-run; and the start/stop/step
count is bounded *before* the `(int)` cast. A bad bound now errors quickly instead
of hanging or tripping UB.

The test passes iff each malformed sweep errors quickly (no hang, no crash) and
each valid sweep still produces the right points. Reported via exit code (0 = pass).
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* sweep-bounds test\nr1 a b 1k\nr2 b 0 1k\nv1 a 0 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=20):
    deck = BASE + ".control\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_sb.cir")
    with open(path, "w") as f:
        f.write(deck)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]", time.time() - t0


print("Enhancement-270: sweep validates numeric bounds (no hang, no UB)")

# [1] overflowing bound 1e400 -> inf (was UBSan (int)inf) -- now a clean error, fast.
rc, out, dt = run("sweep r1 1k 1e400 1")
check("[1] overflow bound `1e400` -> clean error (was (int)inf UB), fast",
      rc == 0 and "non-numeric" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [2] non-numeric bound (was a 100000-point runaway hang) -- clean error, fast.
rc, out, dt = run("sweep lin 1 x 1n 1u")
check("[2] non-numeric bound -> clean error (was a runaway hang), fast",
      rc == 0 and "non-numeric" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [3] a typo'd suffix bound `xk` -- also caught, fast.
rc, out, dt = run("sweep r1 1k xk 1k")
check("[3] typo'd bound `xk` -> clean error, no runaway", rc == 0 and dt < 10,
      f"rc={rc} {dt:.1f}s")

# [4] lin/dec/oct non-numeric N/bounds -> clean error.
rc, out, dt = run("sweep r1 dec x 1 10")
check("[4] non-numeric dec <N> -> clean error", rc == 0 and dt < 10, f"rc={rc} {dt:.1f}s")

# [5] a VALID start/stop/step sweep still produces the right points.
rc, out, dt = run("sweep r1 1k 3k 1k -output i=i(v1)\nprint i")
vals = [float(x) for x in re.findall(r"(-?\d\.\d+e[-+]\d+)", out)]
# i(v1) = -1/(r1+1k): r1=1k,2k,3k -> -5e-4, -3.33e-4, -2.5e-4
ok5 = (len(vals) >= 3
       and abs(abs(vals[0]) - 5.0e-4) < 1e-6
       and abs(abs(vals[1]) - 1.0 / 3e3) < 1e-6
       and abs(abs(vals[2]) - 2.5e-4) < 1e-6)
check("[5] a valid `1k 3k 1k` sweep still produces the correct points",
      ok5, f"{[round(v, 6) for v in vals[:3]]}")

# [6] a valid lin/list sweep still works.
rc, out, dt = run("sweep r1 lin 3 1k 3k -output i=i(v1)\nprint i")
n = len(re.findall(r"^\s*\d+\s", out, re.M))
check("[6] a valid `lin 3 1k 3k` sweep still runs (3 points)", rc == 0 and n >= 3,
      f"rc={rc} rows={n}")

# [7] a tiny step over a wide range -> ~1e24 points (was capped at 100000 and run).
rc, out, dt = run("sweep r1 1n 1u 1e-30")
check("[7] tiny step `1n 1u 1e-30` -> `too many points`, fast (was a 100000-pt hang)",
      rc == 0 and "too many points" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [8] a huge lin <N> (used to skip the clamp entirely -> multi-GB alloc).
rc, out, dt = run("sweep r1 lin 999999999 1k 5k")
check("[8] huge `lin 999999999` -> `too many points`, fast (was a multi-GB alloc)",
      rc == 0 and "too many points" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [9] a tiny dec spacing over a wide range -> millions of points.
rc, out, dt = run("sweep r1 dec 100000 1e-30 1e30")
check("[9] wide `dec` range -> `too many points`, fast",
      rc == 0 and "too many points" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
