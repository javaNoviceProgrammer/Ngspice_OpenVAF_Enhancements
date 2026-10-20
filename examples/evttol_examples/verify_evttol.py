#!/usr/bin/env python3
"""Enhancement-911: cross/above tolerances are honored, and no longer warned about.

LRM 5.10.3.1 (Figure 5-6): "The event shall occur after the threshold
crossing, and while the signal remains in the box defined by actual crossing
and expr_tol and time_tol", and "If expr_tol is specified, time_tol shall also
be specified and both tolerances shall be satisfied at the crossing."

The compiler warned that every nonzero tolerance was "accepted but not
honored". Since Enhancement-759 the event lands the step on its crossing, so
the warning was false, but not entirely: the landing aimed at the box's end
and accepted an iterate up to half a width beyond it (a landing a whole
width), and `expr_tol` only ever stopped a landing.

Checks (both solvers):
  [1] time_tol = 10 ns on a 1 MHz sine at a 20 ns step: the event within
      10 ns of the crossing (E-908: 10.72 ns)
  [2] time_tol = 1 ns on a ramp at a 100 ns step: the event in the middle of
      its box, 0.5 ns after the crossing (E-908: on its end, 1.000 ns)
  [3] a slow ramp with time_tol = 1 ms and expr_tol = 0.2: within 1 ms (E-908:
      5.6 ms -- the expression was within expr_tol, so it did not land)
  [4] the sine with time_tol = 10 ns and expr_tol = 1 mV: the expression within
      1 mV of the threshold where the body ran (E-908: 67 mV), and within
      10 ns
  [5] above() the same, at both rises: within 1 mV (E-908: 13 mV)
  [6] control: the default tolerances count all 20 crossings of 10 periods,
      each within 2e-3 of the step
  [7] the model, every tolerance a parameter, compiles without a tolerance
      warning
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="evttol_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


r = subprocess.run([VAF, os.path.join(HERE, "evttol.va"), "-o", os.path.join(WORK, "evttol.osdi")],
                   capture_output=True, text=True)
check("evttol.va compiles", r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.returncode else "")
COMPILE_OUT = r.stdout + r.stderr


def events(src, tran, params, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* evttol {tag}\n{src}\nN1 c out mm\nR1 out 0 1k\n.model mm tolp({params})\n"
                f".control\npre_osdi evttol.osdi\n{tran}\n.endc\n.end\n")
    out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300, cwd=WORK).stdout
    return [(float(t), float(x)) for _, t, x in re.findall(r"EV (\d+) t=(\S+) x=(\S+)", out)]


print("Enhancement-911: cross/above tolerances\n")
SINE = "V1 c 0 sin(0 1 1meg)"

# ------------------------------------------------------------- [1] ---
ev = events(SINE, "tran 20n 1.2u", "vth=0 ttol=10n dir=-1", "sine_t")
d = ev[0][0] - 0.5e-6 if ev else None
check("[1] time_tol = 10 ns on a 1 MHz sine: the event within 10 ns of the crossing (E-908: 10.72 ns)",
      len(ev) == 1 and 0 <= d <= 10e-9, f"{d:+.3e} s" if d is not None else str(ev))

# ------------------------------------------------------------- [2] ---
ev = events("V1 c 0 pwl(0 0 1u 1)", "tran 100n 1u", "ttol=1n dir=1", "ramp_t")
d = ev[0][0] - 500e-9 if ev else None
check("[2] time_tol = 1 ns on a ramp: the event in the middle of its box, 0.5 ns after the crossing "
      "(E-908: on its end, 1.000 ns)", len(ev) == 1 and abs(d - 0.5e-9) <= 0.1e-9,
      f"{d:+.4e} s" if d is not None else str(ev))

# ------------------------------------------------------------- [3] ---
ev = events("V1 c 0 pwl(0 0 1 1)", "tran 100m 1", "ttol=1m xtol=0.2 dir=1", "slow_tx")
d = ev[0][0] - 0.5 if ev else None
check("[3] a slow ramp, time_tol = 1 ms and expr_tol = 0.2: within 1 ms (E-908: 5.6 ms, expr_tol "
      "waived the landing)", len(ev) == 1 and 0 <= d <= 1e-3, f"{d:+.3e} s" if d is not None else str(ev))

# ------------------------------------------------------------- [4] ---
ev = events(SINE, "tran 20n 1.2u", "vth=0 ttol=10n xtol=1m dir=-1", "sine_tx")
d = ev[0][0] - 0.5e-6 if ev else None
x = ev[0][1] if ev else None
check("[4] the sine with time_tol = 10 ns and expr_tol = 1 mV: within 1 mV of the threshold "
      "(E-908: 67 mV) and within 10 ns", len(ev) == 1 and abs(x) <= 1e-3 and 0 <= d <= 10e-9,
      f"{x:+.3e} V at {d:+.3e} s" if ev else str(ev))

# ------------------------------------------------------------- [5] ---
ev = events(SINE, "tran 20n 1.2u", "vth=0.3 ttol=10n xtol=1m useabove=1", "above_tx")
rises = [math.asin(0.3) / (2 * math.pi * 1e6) + k * 1e-6 for k in (0, 1)]
ok = len(ev) == 2 and all(0 <= x <= 1e-3 and 0 <= t - r <= 10e-9 for (t, x), r in zip(ev, rises))
check("[5] above() the same, at both rises: within 1 mV of the threshold (E-908: 13 mV)", ok,
      ", ".join(f"{x:+.3e} V at {t - r:+.3e} s" for (t, x), r in zip(ev, rises)))

# ------------------------------------------------------------- [6] ---
ev = events(SINE, "tran 5n 10u 0 5n", "vth=0.3 dir=0", "sine_default")
a0 = math.asin(0.3)
ex = sorted(t for k in range(11) for t in (a0 / (2 * math.pi * 1e6) + k * 1e-6,
                                           (math.pi - a0) / (2 * math.pi * 1e6) + k * 1e-6) if 0 < t < 10e-6)
err = max((abs(t - e) / 5e-9 for (t, _), e in zip(ev, ex)), default=float("inf")) if len(ev) == len(ex) else float("inf")
check("[6] (control) the default tolerances: all 20 crossings, each within 2e-3 of the step",
      len(ev) == 20 and err <= 2e-3, f"{len(ev)} events, {err:.2e}")

# ------------------------------------------------------------- [7] ---
check("[7] the model's nonzero tolerances draw no warning (E-908: 'accepted but not honored', four times)",
      "not honored" not in COMPILE_OUT and "needs a time tolerance" not in COMPILE_OUT,
      COMPILE_OUT.strip().splitlines()[0] if COMPILE_OUT.strip() else "")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
