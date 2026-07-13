#!/usr/bin/env python3
"""Enhancement-176: driven-mode PSS shooting (robustness + ~1000x speedup).

ngspice's PSS (the Lannutti shooting) was built for autonomous oscillators: it
HUNTS the fundamental frequency, and to resolve that hunt it forces a
breakpoint grid whose spacing is proportional to steady_coeff. On the driven
circuits that the whole periodic small-signal stack (E-117..126: pac, pnoise,
pxf, psp) runs on, that grid is a catastrophe: at the decks' steady_coeff=5e-6
the spacing is sub-picosecond, i.e. MILLIONS of forced timesteps per shooting
cycle (measured: 9.6e6 accepted points by t=2us on a 3-node varactor circuit,
~33 s of CPU per 1 us of circuit time). Worse, the frequency estimate can
never settle exactly on the source frequency, so the period residual floors
and shooting on some circuits NEVER converges (the varactor deck ran 17+
minutes without converging).

E-176 adds a DRIVEN mode, auto-detected when the circuit contains a
time-varying independent source (SIN/PULSE/... V or I source -- funcTGiven):
  * the period is pinned to the exact source period: no frequency estimation,
    no estimator breakpoint grid -- each shooting cycle runs at plain-transient
    speed (the varactor now converges to err ~ 8e-9 in 17 cycles / 0.3 s);
  * the shooting-phase max step is clamped to T/psspoints so the orbit is
    integrated on the SAME discretization as the retained samples (without the
    clamp the LTE control converges to the fixed point of a coarse ~T/38-step
    discretization, several percent off the true orbit -- the retained swing
    read 0.1651 where the analytic answer is 0.15718);
  * the post-FFT "relaunch at the strongest spectral line" is disabled when
    driven (a rectifier-like circuit with a dominant harmonic must NOT retain
    the wrong period);
  * the AUTONOMOUS (oscillator) path is untouched.

The measured speedups on this machine: rc_pss 4 min -> 0.05 s, the full rfpss
battery (5 verifies) minutes-each -> < 0.5 s each, psp 406 s -> 0.9 s, and the
varactor PAC deck (17+ min, unconverged) -> 0.05 s, converged. rfanalyses and
rfpss are no longer excluded from the regression sweep, and their KLU passes
are enabled (0.14 s).

Checks:
  [1] driven detection fires on a driven deck and the retained fundamental is
      EXACTLY the source frequency (the old hunt returned 999999.8976 Hz).
  [2] retained orbit is analytically exact: osc-node swing == |H(1MHz)| for the
      linear RC (guards the T/psspoints step clamp).
  [3] retained samples are consistent: the time-domain plot spans exactly one
      period and its endpoint returns to its start value (periodicity of the
      retained data itself).
  [4] the direct .pac on a PUMPED VARACTOR matches transient ground truth on
      the +-1 conversion sidebands (this closes the E-175 loop with the direct
      PAC path -- it was too slow to run before E-176).
  [5] an autonomous deck (no time-varying source) does NOT trigger driven mode
      (the oscillator path keeps its vintage behavior).

Runs under both solvers via the dual-solver harness.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_deck(name, deck):
    path = os.path.join(HERE, name)
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return r.stdout + r.stderr


# ---------- [1]+[2]+[3] linear RC .pss ----------
deck = """* driven rc pss
V1 a 0 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n
.pss 1meg 1u b 1024 10 50 5u
.control
run
setplot pss1
wrdata pssdriven_td.csv v(b)
.endc
.end
"""
out = run_deck("_rc.cir", deck)
check("[1] driven mode detected (message present)",
      "driven circuit detected" in out)
m = re.search(r"retained: .* at f = ([\d.eE+]+) Hz", out)
check("[1] retained fundamental EXACTLY the source frequency (1e6)",
      m is not None and float(m.group(1)) == 1.0e6,
      f"(got {m.group(1) if m else 'none'})")
msw = re.search(r"osc-node swing\s*\[\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\]", out)
H = 1.0 / math.hypot(1.0, 2 * math.pi * 1e6 * 1e-6)   # |H| = 0.157175
ok = msw is not None and abs(max(abs(float(msw.group(1))), abs(float(msw.group(2)))) - H) / H < 0.001
check("[2] retained swing == |H(1MHz)| = 0.157175 within 0.1% (step-clamp guard)",
      ok, f"(swing {msw.groups() if msw else 'none'})")
rows = [tuple(map(float, l.split())) for l in
        open(os.path.join(HERE, "pssdriven_td.csv")) if l.strip()]
t = [r[0] for r in rows]
v = [r[1] for r in rows]
span_ok = abs((t[-1] - t[0]) - 1e-6) < 2e-9
per_ok = abs(v[-1] - v[0]) < 1e-4 * max(abs(x) for x in v)
check("[3] retained period is self-consistent (span == T, endpoint returns to start)",
      span_ok and per_ok,
      f"(span {t[-1]-t[0]:.4g}, wraparound {abs(v[-1]-v[0]):.3g})")

# ---------- [4] direct .pac on the pumped varactor vs transient truth ----------
subprocess.run([OPENVAF, os.path.join(HERE, "varcap.va"),
                "-o", os.path.join(HERE, "varcap.osdi")], check=True, cwd=HERE)
VC = """.control
pre_osdi varcap.osdi
.endc
V1 a 0 SIN(0 1 1meg) AC 1
R1 a b 1k
N1 b 0 vc
.model vc varcap c0=1n alpha=0.5
.option reltol=1e-5
"""
# transient ground truth (independent of all PSS/PAC machinery):
# both tones in series, exact one-beat Fourier projection
deck = """* truth two-tone
.control
pre_osdi varcap.osdi
.endc
V1 x 0 SIN(0 1 1meg)
V2 a x SIN(0 1m 250k)
R1 a b 1k
N1 b 0 vc
.model vc varcap c0=1n alpha=0.5
.option reltol=1e-5
.tran 0.5n 60u 56u 0.5n
.control
run
wrdata pssdriven_tr.csv v(b)
.endc
.end
"""
run_deck("_tr.cir", deck)
d = [tuple(map(float, l.split())) for l in
     open(os.path.join(HERE, "pssdriven_tr.csv")) if l.strip()]
tt = [x[0] for x in d]
vv = [x[1] for x in d]
Tb = 4e-6
tend = tt[-1]
NS = 8192
tu = [tend - Tb + Tb * i / NS for i in range(NS)]
import bisect


def interp(tq):
    i = bisect.bisect_left(tt, tq)
    if i <= 0:
        return vv[0]
    if i >= len(tt):
        return vv[-1]
    fr = (tq - tt[i-1]) / (tt[i] - tt[i-1])
    return vv[i-1] + fr * (vv[i] - vv[i-1])


vu = [interp(x) for x in tu]


def comp(f):
    re_ = sum(vu[i] * math.cos(2*math.pi*f*tu[i]) for i in range(NS)) * 2.0 / NS
    im_ = -sum(vu[i] * math.sin(2*math.pi*f*tu[i]) for i in range(NS)) * 2.0 / NS
    return math.hypot(re_, im_) * 1e3          # per 1 V of stimulus


truth_lsb1, truth_usb1 = comp(750e3), comp(1.25e6)

deck = "* direct pac varactor\n" + VC + \
       ".pac 1meg 1u b 1024 6 50 5u lin 1 250k 250k 1\n.control\nrun\nset numdgt=10\nprint b_usb1 b_lsb1\n.endc\n.end\n"
out = run_deck("_pac.cir", deck)
pv = {}
for m2 in re.finditer(r"^(b_usb1|b_lsb1) = ([-\d.eE+]+),([-\d.eE+]+)", out, re.M):
    pv[m2.group(1)] = math.hypot(float(m2.group(2)), float(m2.group(3)))
ok = ("b_usb1" in pv and "b_lsb1" in pv
      and abs(pv["b_usb1"] - truth_usb1) <= 0.01 * truth_usb1
      and abs(pv["b_lsb1"] - truth_lsb1) <= 0.01 * truth_lsb1)
check("[4] direct .pac varactor sidebands match transient truth within 1% "
      "(E-175 closure; pre-E-176 this deck ran 17+ min unconverged)",
      ok, f"(pac lsb1={pv.get('b_lsb1', 0):.5g} truth={truth_lsb1:.5g}; "
          f"pac usb1={pv.get('b_usb1', 0):.5g} truth={truth_usb1:.5g})")

# ---------- [5] autonomous deck: driven mode must NOT trigger ----------
deck = """* autonomous lc (dc supply only)
L1 out 0 1m
C1 out 0 10p
B1 out 0 I=-1m*v(out)+0.25m*v(out)*v(out)*v(out)
.ic v(out)=0.1
.pss 1.59mega 3u out 512 6 20 1m uic
.control
run
.endc
.end
"""
out = run_deck("_osc.cir", deck)
check("[5] autonomous circuit does NOT trigger driven mode (oscillator path preserved)",
      "driven circuit detected" not in out)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
