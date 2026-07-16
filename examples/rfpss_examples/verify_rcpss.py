#!/usr/bin/env python3
"""
verify_rcpss.py -- verifies periodic steady state (PSS) and the RF periodic
small-signal suite built on it through the committed ngspice: Enhancement-117 (PSS
shipped + hardened), Enhancement-118 (PSS runs under KLU), Enhancement-119 (the
periodic operating point is retained), Enhancement-120 (periodic Jacobian
harmonics G_k, C_k), and Enhancement-121 (the PAC conversion-matrix engine --
assemble (2M+1)N harmonic blocks and solve).

PSS was experimental: gated behind `--enable-pss` (so `.pss` was unimplemented in
every shipped build) and, when enabled, it flooded stderr with ~230 lines of
shooting-loop trace per run. E-117 makes PSS build by default and routes the
per-iteration trace through `set ngdebug`. E-117 also had to guard `.pss` to the
Sparse solver because it hung under KLU; E-118 fixes that (KLU reused stale pivots
via `klu_refactor`, inflating the truncation error into a ~20M-step run -- now a
full re-factor is forced each PSS step under KLU) so PSS runs under both solvers.

This runs a driven RC low-pass through `.pss` under BOTH linear solvers and checks
the periodic steady state matches the analytic AC response, and that the two
solvers agree:

  [sparse] `.pss` implemented; converges to ~1 MHz; fundamental == |H(1MHz)| =
           0.15714 (R=1k, C=1n); clean default output (no trace)
  [klu]    not refused; converges (was a hang); fundamental correct; matches sparse

NOTE: PSS is a shooting method (it simulates many drive periods), and it runs
under both solvers here, so this deck takes ~5-6 minutes total.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import klu_enabled as _klu_enabled

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def run(solver):
    """Run rc_pss.cir under `solver` ('sparse' or 'klu') -> combined log."""
    with open(os.path.join(HERE, "rc_pss.cir")) as f:
        deck = f.read()
    # inject the solver option as the 2nd line (after the title)
    lines = deck.split("\n")
    lines.insert(1, f".option {solver}")
    name = f"_rcpss_{solver}.cir"
    with open(os.path.join(HERE, name), "w") as f:
        f.write("\n".join(lines))
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    os.remove(os.path.join(HERE, name))
    return r.stdout + r.stderr

def parse(log):
    """(converged_freq, fundamental_magnitude) from a PSS log, or (None, None)."""
    m = re.search(r"predicted fundamental frequency is\s+([-\d.eE+]+)\s*Hz", log)
    freq = float(m.group(1)) if m else None
    fund = None
    for line in log.splitlines():
        p = line.split()
        if len(p) == 3 and p[0] == "1":
            try:
                ffreq, fmag = float(p[1]), abs(float(p[2]))
                if abs(ffreq - f0) / f0 < 0.05:
                    fund = fmag
                    break
            except ValueError:
                pass
    return freq, fund

# analytic fundamental of the RC low-pass at the 1 MHz drive
R, C, f0 = 1e3, 1e-9, 1e6
H = 1.0 / math.hypot(1.0, 2 * math.pi * f0 * R * C)   # 0.157136...

# --- Sparse (default) ---
slog = run("sparse")
check("`.pss` is implemented", "unimplemented dot command" not in slog,
      "PSS not built into this ngspice")
sfreq, sfund = parse(slog)
check("[sparse] PSS converges and reports the fundamental frequency",
      "Convergence reached" in slog and sfreq is not None, "no convergence line")
check(f"[sparse] fundamental frequency ~ 1 MHz (got {sfreq})",
      sfreq is not None and abs(sfreq - f0) / f0 < 0.01, str(sfreq))
check(f"[sparse] fundamental magnitude == |H(1MHz)| = {H:.5f} (got {sfund})",
      sfund is not None and abs(sfund - H) / H < 0.02, str(sfund))
trace = sum(1 for ln in slog.splitlines()
            if re.search(r"Shooting cycle iteration|Updated guessed frequency|IN_PSS", ln))
check(f"[sparse] clean default output -- no shooting-loop trace ({trace} lines)",
      trace == 0, f"{trace} trace lines leaked")

# --- Enhancement-119: the periodic operating point is retained past the analysis
#     (the substrate PAC/pnoise/PXF will linearize around) ---
mret = re.search(r"operating point retained:\s*(\d+)\s*samples x\s*(\d+)\s*unknowns"
                 r"\s*x\s*(\d+)\s*states at f =\s*([-\d.eE+]+)", slog)
check("[E-119] periodic operating point is retained", mret is not None,
      "no 'operating point retained' line")
if mret:
    nsamp, nunk, nst, retf = (int(mret.group(1)), int(mret.group(2)),
                              int(mret.group(3)), float(mret.group(4)))
    check(f"[E-119] retained dims: 1024 samples x 3 unknowns x 2 states "
          f"(got {nsamp}x{nunk}x{nst})",
          nsamp == 1024 and nunk == 3 and nst == 2)
    check(f"[E-119] retained fundamental freq == PSS freq (got {retf})",
          sfreq is not None and abs(retf - sfreq) / f0 < 1e-6)
# the self-check proves the RETAINED samples hold the real waveform: a node in
# periodic steady state must swing, and its peak equals the fundamental amplitude
msw = re.search(r"osc-node swing\s*\[\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\]", slog)
check("[E-119] retained-data self-check present", msw is not None)
if msw:
    vmin, vmax = float(msw.group(1)), float(msw.group(2))
    peak = max(abs(vmin), abs(vmax))
    check(f"[E-119] retained osc-node swing peak == |H(1MHz)| = {H:.5f} "
          f"(got {peak:.5f})", abs(peak - H) / H < 0.02, f"peak {peak}")

# --- Enhancement-120: periodic small-signal Jacobian harmonics at the osc node.
#     For this linear RC the Jacobian is time-invariant, so G(t)=1/R1 and C(t)=C1
#     with no harmonics -- and the extracted DC values must equal those exactly. ---
def jac(tag):
    m = re.search(tag + r":\s*DC\s*=\s*([-\d.eE+]+)\s*[SF](.*)", slog)
    if not m:
        return None, None
    dc = float(m.group(1))
    harms = [abs(float(x)) for x in re.findall(r"=\s*([-\d.eE+]+)", m.group(2))]
    return dc, (max(harms) if harms else 0.0)
gdc, gh = jac("G\\(t\\)")
cdc, ch = jac("C\\(t\\)")
check("[E-120] periodic Jacobian is reported", gdc is not None and cdc is not None)
check(f"[E-120] G(t) DC conductance == 1/R1 = {1/R:.4g} S (got {gdc})",
      gdc is not None and abs(gdc - 1/R) / (1/R) < 0.01, str(gdc))
check(f"[E-120] G(t) is time-invariant -- harmonics ~ 0 (max |Gk| = {gh})",
      gh is not None and gh < 1e-9, str(gh))
check(f"[E-120] C(t) DC capacitance == C1 = {C:.4g} F (got {cdc})",
      cdc is not None and abs(cdc - C) / C < 0.01, str(cdc))
check(f"[E-120] C(t) is time-invariant -- harmonics ~ 0 (max |Ck| = {ch})",
      ch is not None and ch < 1e-12, str(ch))

# --- Enhancement-121: PAC conversion matrix. The full periodic Jacobian G_k, C_k
#     is assembled into the (2M+1)N harmonic conversion matrix
#         H_{nm} = G_{n-m} + j*omega_m*C_{n-m},  omega_m = 2*pi*(f_in + m*f0)
#     and solved with a unit current injected at the osc node in the 0-th sideband.
#     For this LINEAR RC the off-diagonal harmonic blocks (G_k, C_k, k!=0) vanish,
#     so H is block-diagonal: the 0-block is exactly the AC matrix at f_in, and the
#     solve returns the AC driving-point impedance at f_in = f0/2 with NO conversion
#     to the +-1 sidebands. Analytic driving-point |Z| = 1/|1/R + j*2*pi*f_in*C|. ---
f_in = 0.5 * f0
Zana = 1.0 / math.hypot(1.0 / R, 2 * math.pi * f_in * C)   # ~303.3 Ohm at 0.5 MHz
mpac = re.search(r"PAC conversion matrix:\s*f_in\s*=\s*([-\d.eE+]+)\s*Hz", slog)
check("[E-121] PAC conversion matrix is assembled and solved", mpac is not None)
sb = {}
for idx, _freq, mag in re.findall(
        r"sideband\s*([+-]\d+)\s*\(([-\d.eE+]+)\s*Hz\):\s*\|V\|\s*=\s*([-\d.eE+]+)", slog):
    sb[int(idx)] = float(mag)
mzexp = re.search(r"driving-point\s*\|Z\|\s*=\s*([-\d.eE+]+)\s*Ohm", slog)
zexp = float(mzexp.group(1)) if mzexp else None
check(f"[E-121] input frequency == f0/2 = {f_in:.4g} Hz",
      mpac is not None and abs(float(mpac.group(1)) - f_in) / f_in < 1e-6,
      mpac.group(1) if mpac else None)
check("[E-121] all three sidebands (-1, 0, +1) reported", set(sb) >= {-1, 0, 1})
check(f"[E-121] reported driving-point |Z| == analytic {Zana:.4g} Ohm (got {zexp})",
      zexp is not None and abs(zexp - Zana) / Zana < 0.02, str(zexp))
check(f"[E-121] PAC sideband-0 |V| == driving-point |Z| = {Zana:.4g} Ohm "
      f"(got {sb.get(0)})",
      0 in sb and abs(sb[0] - Zana) / Zana < 0.02, str(sb.get(0)))
conv = max(sb.get(1, 0.0), sb.get(-1, 0.0))
check(f"[E-121] linear circuit -> no conversion to +-1 sidebands "
      f"(max |V_sb| = {conv:.3g} << sideband-0 {sb.get(0, 0):.4g})",
      0 in sb and sb[0] > 0 and conv / sb[0] < 1e-6, f"conv {conv}")

# --- KLU (Enhancement-118: PSS now converges under KLU via forced re-factor) ---
# KLU re-factors every shooting step, so this 1024-sample PSS is minutes-slow under
# KLU. It is SPARSE-only in the regular suite; set NG_SLOW_KLU=1 to run the KLU pass
# (re-checking the E-118 fix). See docs/.../ngspice_solver_notes.md.
if _klu_enabled():
    klog = run("klu")
    kfreq, kfund = parse(klog)
    check("[klu] PSS is NOT refused (no 'option KLU' guard)",
          "not supported with 'option KLU'" not in klog)
    check("[klu] PSS converges under KLU (was a timestep-explosion hang)",
          "Convergence reached" in klog and kfreq is not None, "no convergence line")
    check(f"[klu] fundamental magnitude == |H(1MHz)| = {H:.5f} (got {kfund})",
          kfund is not None and abs(kfund - H) / H < 0.02, str(kfund))
    check(f"[klu] matches sparse -- freq {kfreq} vs {sfreq}, fund {kfund} vs {sfund}",
          kfreq is not None and sfreq is not None
          and abs(kfreq - sfreq) / f0 < 1e-6
          and kfund is not None and sfund is not None
          and abs(kfund - sfund) / H < 1e-3)
else:
    print("  SKIP  [klu] PSS pass (heavy 1024-sample re-factor; NG_SLOW_KLU=1 to run)")

# --- Enhancement-210: the `.pss` dot-card auto-runs in batch (no `.control run`
#     needed, like `.hb`/`.tran`), and the frequency-domain PSS spectrum is now
#     published as COMPLEX vectors (mag + phase, like the hb command's E-209
#     vectors and like AC node vectors) instead of magnitude-only. ---
def run_deck(txt):
    p = os.path.join(HERE, "_e210.cir")
    with open(p, "w") as f:
        f.write(txt)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=HERE)
    os.remove(p)
    return r.stdout + r.stderr

# a driven diode rectifier -> harmonics with clearly non-trivial phase
_diode = ("* e210\nV1 in 0 SIN(0 1 1meg)\nR1 in a 100\nD1 a out DMOD\n"
          "Rl out 0 1k\n.model DMOD D(IS=1e-12 N=1.2)\n")

a = run_deck(_diode + ".pss 1meg 20u 1 1024 8 50 5m uic\n.end\n")
check("[E-210] `.pss` dot-card auto-runs in batch (no `.control run` needed)",
      "Convergence reached" in a and "no simulations run" not in a,
      "did not auto-run in batch")

b = run_deck(_diode + ".pss 1meg 20u 1 1024 8 50 5m uic\n.control\n"
             "print vm(out) vp(out)\n.endc\n.end\n")
rowvals = {}
for line in b.splitlines():
    p = line.split()
    if len(p) == 4 and p[0].isdigit():
        try:
            rowvals[int(p[0])] = (float(p[2]), float(p[3]))   # (vm, vp[rad])
        except ValueError:
            pass
has_mag = 1 in rowvals and rowvals[1][0] > 1e-3
has_phase = any(abs(v[1]) > 0.5 for k, v in rowvals.items() if k >= 1)   # vp in radians
check("[E-210] frequency-domain PSS spectrum is complex -- vm() and vp() both resolve",
      has_mag and has_phase,
      f"mag={has_mag} phase={has_phase} rows={len(rowvals)}")

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
