#!/usr/bin/env python3
"""Enhancement-504: the domain guards, on the route the compiler cannot see.

Enhancement-479 taught openvaf-r's const-domain guards to see a `localparam` as
well as a literal. But a `parameter` can be overridden from the deck, so the
compiler correctly does NOT refuse one -- a default is the model author's
business, which is the rule Enhancement-426 settled. That leaves the ordinary
case completely unguarded: a model ships a sensible default, a deck overrides it
with something outside the operator's domain, and nothing checks it afterwards.

Round 61 measured what that cost:

  * `transition` with a negative rise time is an UNSTABLE INTEGRATOR. `pos_max`
    is 1/trise and bounds dy/dt from above in the tracking loop, so a negative
    trise inverts the clamp and the loop integrates AWAY from its input. A 0->1
    signal reached **-24 V**, and unbounded with it: -120 V over a longer run,
    and larger still as |trise| shrinks.
  * `$bound_step` with a negative argument wrote Enhancement-24's SENTINEL, which
    does not mean "bound the step" but "a $discontinuity happened here". The
    model was announcing a discontinuity on every evaluation and the transient
    never returned.
  * `$bound_step(1e-18)` -- a perfectly LEGAL positive request -- was taken
    literally: >150 s with no output, no error, and no "timestep too small",
    because that test compares against CKTdelmin (~5e-20 here), far below what
    was asked for. The step was not too small for the solver; it was too small
    to finish.
  * `$discontinuity(0)` outside any conditional pinned the timestep to the last
    accepted delta, which could then never grow, and the run crawled forever.
    `$discontinuity(-1)` is fine and stays fine -- it means "no discontinuity".
  * `white_noise(p)` with p < 0 produced noise BIT-IDENTICAL to `+p`: the
    simulator takes `sqrt(fabs(pwr))`, so the sign was simply gone.
  * `idtmod` with a zero modulus divided by it, returned NaN, and took the
    analysis down with "Timestep too small; cause unrecorded" -- naming neither
    the model nor the call.

Each is fixed where the value is still the USER's. The noise power is clamped at
the `white_noise` argument and deliberately NOT in ngspice, because by the time
the power reaches osdinoise.c the contribution factor has been folded into it as
`fac*|fac|` and Enhancement-42 uses that sign to sum same-named sources
coherently -- check [12] holds that. The two step-control fixes are in ngspice,
because no compiler can know how long an analysis window is.

WITHDRAWN from round 61: an out-of-range ARRAY index returning element 0. The
site says why -- Enhancement-489 chose a select chain precisely so that no index
can read out of bounds, and records that returning NaN was considered and
rejected because a run-time index may be transiently out of range mid-solve.
That is a decision, not a defect.
"""

import atexit
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_rt_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


OSDI = os.path.join(HERE, "_rt_rtdom.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "rtdom.va"), "-o", OSDI],
                   capture_output=True, text=True, timeout=300, cwd=HERE)
if not os.path.exists(OSDI):
    print("  FAIL  rtdom.va compiles  [%s]" % (r.stdout + r.stderr).strip()[-200:])
    sys.exit(1)


def run(card, ctl, tag, extra="", timeout=120):
    """Returns (rc, out, seconds). A TIMEOUT is a finding, not an error."""
    p = os.path.join(HERE, f"_rt_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"rtdomain\nVa a 0 PULSE(0 1 1n 0.1n 0.1n 5n 10n)\n"
                f"N1 a 0 o mm\n.model mm rtdom {card}\nRo o 0 1meg\n{extra}"
                f".control\npre_osdi {OSDI}\noption noacct\nset numdgt=12\n"
                f"{ctl}\n.endc\n.end\n")
    t0 = time.time()
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                            capture_output=True, text=True, timeout=timeout,
                            errors="replace")
        return rr.returncode, rr.stdout + rr.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return None, "[TIMEOUT]", time.time() - t0


def wave(out):
    return [float(x) for x in re.findall(r"^\s*\d+\s+\S+\s+(\S+)", out, re.M)
            if re.match(r"^-?[\d.]+e?[-+]?\d*$", x)]


TRAN = ".tran 0.05n 12n\n"

print("Enhancement-504: a domain the compiler cannot see is still a domain")

# ---------------------------------------------------------------------------
# [1]-[5]  transition
# ---------------------------------------------------------------------------
print("\n  transition -- a negative rise time was an unstable integrator")

rc, out, _ = run("tr=0.5n tf=0.5n", "run\nprint v(o)", "t0", TRAN)
base = wave(out)
check("[1] a good rise/fall still produces a 0..1 transition",
      base and -1e-9 <= min(base) and max(base) <= 1.001,
      f"[{min(base):.4g}, {max(base):.4g}]" if base else "no data")

for i, (card, lbl) in enumerate([("tr=-0.5n tf=0.5n", "rise < 0   (was -24 V)"),
                                 ("tr=0.5n tf=-0.5n", "fall < 0   (was +24 V)"),
                                 ("tr=-0.1n tf=-0.1n", "both < 0   (was -120 V)")]):
    rc, out, _ = run(card, "run\nprint v(o)", f"t{i+1}", TRAN)
    v = wave(out)
    check(f"[{2+i}] {lbl} stays inside the signal range",
          bool(v) and min(v) >= -1e-6 and max(v) <= 1.001,
          f"[{min(v):.4g}, {max(v):.4g}]" if v else "no data")

# a negative rise must mean the SAME as zero (instantaneous), not the same as +tr
rc, o_neg, _ = run("tr=-2n tf=-2n", "run\nprint v(o)", "t4", ".tran 0.1n 8n\n")
rc, o_zero, _ = run("tr=0 tf=0", "run\nprint v(o)", "t5", ".tran 0.1n 8n\n")
rc, o_pos, _ = run("tr=2n tf=2n", "run\nprint v(o)", "t6", ".tran 0.1n 8n\n")
n, z, p = wave(o_neg), wave(o_zero), wave(o_pos)
same_zero = len(n) == len(z) and all(abs(x - y) < 1e-9 for x, y in zip(n, z))
# Enhancement-512: differing LENGTHS are themselves proof the waveforms
# differ -- requiring equal lengths first made this check report "the
# same" the moment a real rate-limited ramp needed more timepoints than
# the instantaneous case (102 vs 119). The assertion is unchanged: a
# negative rise must not behave like a positive one.
diff_pos = len(n) != len(p) or any(abs(x - y) > 1e-6 for x, y in zip(n, p))
check("[5] a negative rise means ZERO (instantaneous), not its magnitude",
      same_zero and diff_pos,
      f"== tr=0: {same_zero}, != tr=+2n: {diff_pos}")

# ---------------------------------------------------------------------------
# [6]-[9]  $bound_step
# ---------------------------------------------------------------------------
print("\n  $bound_step -- a step bound that never returned")

rc, out, dt = run("mode=1 bs=1n", "run\nprint v(o)", "b0", TRAN)
check("[6] a sensible bound still runs", rc == 0 and wave(out), f"{dt:.1f}s")

for i, (bs, lbl) in enumerate([("-1n", "negative (wrote E-24's sentinel)"),
                               ("0", "zero")]):
    rc, out, dt = run(f"mode=1 bs={bs}", "run\nprint v(o)", f"b{i+1}", TRAN)
    check(f"[{7+i}] a {lbl} bound is dropped, not obeyed",
          rc == 0 and bool(wave(out)) and dt < 30,
          "HANG" if rc is None else f"rc={rc} in {dt:.1f}s")

rc, out, dt = run("mode=1 bs=1e-18", "run\nprint v(o)", "b3", TRAN)
check("[9] an absurdly tiny but LEGAL bound terminates and is named",
      rc == 0 and dt < 60 and "bound_step" in out,
      "HANG" if rc is None else f"rc={rc} in {dt:.1f}s, "
      + ("named" if "bound_step" in out else "NOT NAMED"))

# ---------------------------------------------------------------------------
# [10]-[11]  $discontinuity
# ---------------------------------------------------------------------------
print("\n  $discontinuity -- announcing one on every evaluation")

rc, out, dt = run("disc=-1", "run\nprint v(o)", "d0", TRAN)
check("[10] degree -1 (no discontinuity) is untouched and silent",
      rc == 0 and dt < 30 and "discontinuity on every" not in out,
      f"rc={rc} in {dt:.1f}s")

rc, out, dt = run("disc=0", "run\nprint v(o)", "d1", TRAN)
check("[11] degree 0 on every evaluation terminates and is named",
      rc == 0 and dt < 60 and "discontinuity on every" in out,
      "HANG" if rc is None else f"rc={rc} in {dt:.1f}s, "
      + ("named" if "discontinuity on every" in out else "NOT NAMED"))

# ---------------------------------------------------------------------------
# [12]-[14]  noise power
# ---------------------------------------------------------------------------
print("\n  white_noise -- a negative power is not its magnitude")

NOISE = "noise v(o) va dec 10 1e3 1e6 1\nprint onoise_total"


def total(card, tag):
    p = os.path.join(HERE, f"_rt_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"rtdomain noise\nVa a 0 dc 0 ac 1\nN1 a o mm\n.model mm rtdom {card}\n"
                f"Ro o 0 1k\n.control\npre_osdi {OSDI}\noption noacct\nset numdgt=12\n"
                f"{NOISE}\n.endc\n.end\n")
    rr = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                        capture_output=True, text=True, timeout=180, errors="replace")
    m = re.findall(r"onoise_total\s*=\s*(\S+)", rr.stdout + rr.stderr)
    return float(m[-1]) if m else None


pos = total("mode=3 npw=1e-20", "n0")
zero = total("mode=3 npw=0", "n1")
neg = total("mode=3 npw=-1e-20", "n2")
check("[12] a positive power still makes noise", pos is not None and zero is not None
      and pos > zero * 1.5, f"{pos} vs floor {zero}")
check("[13] a NEGATIVE power is not treated as its magnitude",
      neg is not None and pos is not None and abs(neg - pos) > 1e-12,
      f"neg={neg}  pos={pos}")
check("[14] a negative power behaves as zero",
      neg is not None and zero is not None and abs(neg - zero) < 1e-15,
      f"neg={neg}  zero={zero}")

# ---------------------------------------------------------------------------
# [15]-[16]  idtmod
# ---------------------------------------------------------------------------
print("\n  idtmod -- a zero modulus divided by it")

rc, out, _ = run("mode=2 md=1n", "run\nprint v(o)", "i0", TRAN)
v_ok = wave(out)
check("[15] a positive modulus still wraps the integral",
      bool(v_ok) and max(v_ok) <= 1.05e-9, f"max={max(v_ok):.4g}" if v_ok else "no data")

rc, out, _ = run("mode=2 md=0", "run\nprint v(o)", "i1", TRAN)
v_z = wave(out)
check("[16] a zero modulus falls back to the unwrapped integral, no NaN",
      rc == 0 and bool(v_z) and not any(x != x for x in v_z)
      and "too small" not in out.lower(),
      f"rc={rc} max={max(v_z):.4g}" if v_z else f"rc={rc} no data")

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
