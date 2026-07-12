#!/usr/bin/env python3
"""
verify_phasenoise.py -- Enhancement-140: autonomous HB for oscillators + phase noise.

`hbosc <oscnode> <K> [fguess] [tstab]` solves an OSCILLATOR's periodic steady state --
the harmonics AND the (unknown) oscillation frequency -- by a bordered Newton around a
transient seed (the conversion matrix dF/dV is singular in the phase direction, so the
system is bordered with dF/dw0 and a phase gauge). `phasenoise <fstart> <fstop> [pts]`
then reports L(df): the adjoint of the conversion matrix at OFFSET df, with the unit at
the carrier sideband, folds the device noise to the output; as df -> 0 the limit-cycle
matrix goes singular through the phase mode, so the folded noise blows up as 1/df^2 --
the phase-noise skirt -- normalized to the carrier power.

Test oscillator: an LC tank (f0 ~ 5.03 MHz) with a cubic negative resistance
`i = -g0 V + g3 V^3`; describing-function amplitude A = sqrt(4 g0 / (3 g3)).

Checks (numpy-free, parsed from stdout):

  [1] autonomous HB converges     -- finds f0 ~ 5.03 MHz
  [2] amplitude = describing fn   -- |V1| = A/2 with A = sqrt(4 g0/3 g3)
  [3] -20 dB/dec skirt near carrier -- L(1k) - L(10k) ~ 20 dB (1/df^2)
  [4] flattens far from carrier   -- slope well under 20 dB/dec out at the noise floor
  [5] thermal scaling L ~ T       -- doubling the temperature raises L by 3 dB
  [6] no op-point                 -- `phasenoise` with no `hbosc` errors cleanly
  [7] KLU vs Sparse               -- solver-independent
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_pn"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def osc_freq(out):
    m = re.search(r"oscillation frequency f0 = ([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None

def fundamental(out):
    """|V| of the oscillator node's fundamental (harmonic 1) from the hbosc table."""
    m = re.search(r"^\s+n\s+1\s+[-\d.eE+]+\s+([-\d.eE+]+)", out, re.M)
    return float(m.group(1)) if m else None

def carrier_power(out):
    m = re.search(r"carrier power ([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None

def Ldf(out):
    """phasenoise table -> {offset: L(df) dBc/Hz}."""
    d = {}
    started = False
    for line in out.splitlines():
        if "offset [Hz]" in line and "L(df)" in line:
            started = True; continue
        if started:
            m = re.match(r"\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s*$", line)
            if m:
                d[float(m.group(1))] = float(m.group(2))
            elif line.strip() and "Note:" not in line:
                break
    return d


def deck(g0="2m", g3="5m", temp=None, opt="", pn="phasenoise 1k 10meg 5"):
    t = f".options temp={temp}\n" if temp is not None else ""
    return (f"* LC oscillator phase noise\n"
            f"L1 n 0 1u\nC1 n 0 1n\nBnl 0 n I = {g0}*V(n) - {g3}*V(n)*V(n)*V(n)\n"
            f"R1 n 0 100k\n.ic V(n)=0.1\n{t}{opt}"
            f".control\nhbosc n 5 5.0329meg 60u\n{pn}\n.endc\n.end\n")


print("Enhancement-140: oscillator phase noise (autonomous HB + PPV)")

out = run(deck())
f0 = osc_freq(out)
check("autonomous HB converges to an oscillation (f0 ~ 5.03 MHz)",
      f0 is not None and abs(f0 - 5.03e6) < 0.1e6, f"f0={f0}")

# describing-function amplitude A = sqrt(4 g0/(3 g3)); stored |V1| = A/2.
A = math.sqrt(4 * 2e-3 / (3 * 5e-3))
v1 = fundamental(out)
check("fundamental amplitude matches the describing function",
      v1 is not None and abs(v1 - A/2 * 2) < 0.05 * A,   # table prints single-sided A=2|V1|
      f"|V1|_table={v1} A={A:.4f}")

L = Ldf(out)
sk = L.get(1e3, 0) - L.get(1e4, 0)          # near-carrier decade slope (dB)
check("-20 dB/dec phase-noise skirt near the carrier (1/df^2)",
      L and 18.0 <= sk <= 22.0, f"L(1k)-L(10k)={sk:.2f} dB")

far = L.get(1e6, 0) - L.get(1e7, 0)         # far-out decade slope -> flattens
check("phase noise flattens into the noise floor far from carrier",
      L and far < 15.0, f"L(1M)-L(10M)={far:.2f} dB")
check("physical phase-noise level (not the unphysical -300 dBc/Hz)",
      L and -180.0 < L.get(1e4, -999) < -80.0, f"L(10k)={L.get(1e4)}")

# thermal noise ~ T, so doubling the absolute temperature raises L by 10log10(2)=3 dB.
l300 = Ldf(run(deck(temp="26.85", pn="phasenoise 10k 10k 1"))).get(1e4)
l600 = Ldf(run(deck(temp="326.85", pn="phasenoise 10k 10k 1"))).get(1e4)
dL = (l600 - l300) if (l300 is not None and l600 is not None) else None
check("thermal scaling: doubling T raises L by 3 dB",
      dL is not None and abs(dL - 3.01) < 0.3, f"dL={dL} dB")

out = run("* no osc\nR1 n 0 1k\n.control\nphasenoise 1k 1meg 3\n.endc\n.end\n")
check("phasenoise with no oscillator operating point errors cleanly",
      "no oscillator operating point" in out and "PhaseNoise:" not in out)

lk = Ldf(run(deck(opt=".options klu\n"))).get(1e4)
ls = Ldf(run(deck(opt=".options sparse\n"))).get(1e4)
check("phase noise solver-independent: KLU vs Sparse identical",
      lk is not None and ls is not None and abs(lk - ls) < 1e-3, f"klu={lk} sparse={ls}")

# [.] DOT-CARD PARITY (Enhancement-163): top-level `.hbosc` and `.phasenoise`
# netlist cards must run the same E-140 engines as the commands in a .control
# block, straight from the deck, with order preserved (hbosc sets up the
# oscillator PSS that phasenoise then uses). Compare the oscillation frequency and
# a phase-noise point against the command form.
_dot = ("* LC oscillator phase noise (dotcard)\n"
        "L1 n 0 1u\nC1 n 0 1n\nBnl 0 n I = 2m*V(n) - 5m*V(n)*V(n)*V(n)\n"
        "R1 n 0 100k\n.ic V(n)=0.1\n"
        ".hbosc n 5 5.0329meg 60u\n.phasenoise 1k 10meg 5\n.end\n")
_dout = run(_dot)
_cout = run(deck())
_f_dot, _f_cmd = osc_freq(_dout), osc_freq(_cout)
_l_dot, _l_cmd = Ldf(_dout).get(1e4), Ldf(_cout).get(1e4)
check("`.hbosc` + `.phasenoise` dot-cards run in batch and match the commands",
      _f_dot is not None and _f_cmd is not None and _f_dot == _f_cmd
      and _l_dot is not None and _l_cmd is not None and _l_dot == _l_cmd,
      f"f0 dot={_f_dot}/cmd={_f_cmd}, L(1e4) dot={_l_dot}/cmd={_l_cmd}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
