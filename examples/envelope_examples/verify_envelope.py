#!/usr/bin/env python3
"""
verify_envelope.py -- Enhancement-154: Envelope Following (`envelope` command).

Envelope following computes the slow amplitude/phase envelope of a carrier-driven
circuit by sampling the state once per carrier period and jumping M periods at a
time with an IMPLICIT (backward-Euler + monodromy) envelope step. The implicit step
is what makes it STABLE on high-Q / resonant circuits, where the naive explicit
(forward-Euler) envelope jump blows up.

Checked end-to-end through the committed ngspice, under BOTH linear solvers:

  [1] the `envelope` command runs and returns a plottable envelope (samples << periods).
  [2] CORRECTNESS: on a high-Q RLC tank rung up by an on-resonance carrier, the EF
      amplitude 2|V1|(a) matches a full `.tran` (same fundamental-Fourier measure) at
      the envelope sample times, across the whole ring-up.
  [3] STEADY STATE: the EF amplitude converges to the transient's steady-state value.
  [4] STABILITY / EFFICIENCY: EF tracks 3000 carrier periods of a Q~3000 resonator
      with only a few dozen envelope samples and stays BOUNDED (the implicit step;
      an explicit envelope jump diverges on this circuit).
  [5] a moderate-Q tank is also tracked within tolerance.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

SCRATCH = tempfile.mkdtemp(prefix="ef_verify_")
FC = 5.032921e6                      # tank resonance 1/(2*pi*sqrt(1u*1n))
T  = 1.0 / FC
_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run(deck):
    with open(os.path.join(SCRATCH, "_e.cir"), "w") as f:
        f.write(deck)
    subprocess.run([NGSPICE, "-b", "_e.cir"], capture_output=True, text=True,
                   timeout=180, cwd=SCRATCH)


def load(fname):
    p = os.path.join(SCRATCH, fname)
    if not os.path.exists(p):
        return [], []
    xs, ys = [], []
    for line in open(p):
        parts = line.split()
        if len(parts) >= 2:
            try:
                xs.append(float(parts[0])); ys.append(float(parts[1]))
            except ValueError:
                pass
    return xs, ys


TANK = ("v1 s 0 sin(0 1 {fc})\n"
        "l1 s a 1u\n"
        "c1 a 0 1n\n"
        "r1 a 0 {R}\n").format(fc=f"{FC:.6e}", R="{R}")


def tank_deck(R):
    return TANK.replace("{R}", str(R))


def ef_samples(R, tstop, extra=""):
    run(f"""* envelope
{tank_deck(R)}.control
  envelope a {FC:.6e} {tstop:g} {extra}
  wrdata ef.txt a_amp
.endc
.end
""")
    return load("ef.txt")


def tran_amp(R, tstop, sample_times):
    """full transient; return dict t->fundamental amplitude 2|V1| of v(a) over [t,t+T]."""
    tend = (max(sample_times) if sample_times else tstop) + 3 * T
    run(f"""* tran ref
{tank_deck(R)}.control
  tran {T/128:.6e} {tend:g} 0 {T/128:.6e}
  wrdata tr.txt v(a)
.endc
.end
""")
    tt, vv = load("tr.txt")
    out = {}
    for tc in sample_times:
        re_ = im_ = 0.0
        prev = None
        for i in range(len(tt)):
            if tt[i] < tc or tt[i] >= tc + T:
                continue
            w = 2 * math.pi * FC * (tt[i] - tc)
            gr, gi = vv[i] * math.cos(w), -vv[i] * math.sin(w)
            if prev is not None:
                dt = tt[i] - prev[0]
                re_ += 0.5 * (gr + prev[1]) * dt
                im_ += 0.5 * (gi + prev[2]) * dt
            prev = (tt[i], gr, gi)
        out[tc] = 2.0 * math.hypot(re_, im_) / T
    return out


print("Enhancement-154: envelope following")

# ---- high-Q resonator: correctness + steady state + efficiency ----------------
R_HQ, TSTOP_HQ = 100000.0, 596e-6         # Q ~ 3162, ~3000 carrier periods
et, ea = ef_samples(R_HQ, TSTOP_HQ)
nper = TSTOP_HQ * FC
check("[1] `envelope` returns a plottable envelope (samples << carrier periods)",
      len(et) >= 5 and len(et) < 0.2 * nper,
      f"{len(et)} samples for ~{nper:.0f} periods")

if et:
    ref = tran_amp(R_HQ, TSTOP_HQ, et)
    worst = 0.0
    for tc, a in zip(et, ea):
        r = ref.get(tc, 0.0)
        if r > 5.0:
            worst = max(worst, abs(a - r) / r)
    check("[2] EF amplitude tracks the full .tran across the ring-up (<6%)",
          worst < 0.06, f"max rel err = {worst*100:.2f}%")

    # steady state: last EF sample vs tran fundamental there
    r_end = ref.get(et[-1], 0.0)
    check("[3] EF converges to the transient steady-state amplitude (<4%)",
          r_end > 5.0 and abs(ea[-1] - r_end) / r_end < 0.04,
          f"EF {ea[-1]:.1f} vs tran {r_end:.1f}")

    # stability: bounded, monotone-ish ring-up, no blow-up
    finite = all(math.isfinite(v) for v in ea)
    bounded = max(abs(v) for v in ea) < 10.0 * (r_end if r_end > 0 else 1e9)
    check("[4] EF stays BOUNDED over 3000 periods (implicit step; explicit diverges)",
          finite and bounded, f"peak |amp| = {max(ea):.1f}")

# ---- moderate-Q tank: accuracy in a different regime ---------------------------
R_MQ, TSTOP_MQ = 10000.0, 40e-6           # Q ~ 316
mt, ma = ef_samples(R_MQ, TSTOP_MQ)
if mt:
    mref = tran_amp(R_MQ, TSTOP_MQ, mt)
    worst = max((abs(a - mref[tc]) / mref[tc]
                 for tc, a in zip(mt, ma) if mref.get(tc, 0) > 5.0), default=1.0)
    check("[5] moderate-Q (Q~316) tank tracked within tolerance (<5%)",
          worst < 0.05, f"max rel err = {worst*100:.2f}%")

print(f"\n{'ALL PASS' if _fail == 0 else 'FAILURES'}: {_fail} failed check(s)")
sys.exit(0 if _fail == 0 else 1)
