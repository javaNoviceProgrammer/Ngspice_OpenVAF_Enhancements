#!/usr/bin/env python3
"""
verify_rcpss.py -- verifies periodic steady state (PSS) through the committed
ngspice: Enhancement-117 (PSS shipped + hardened) and Enhancement-118 (PSS runs
under KLU).

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

# --- KLU (Enhancement-118: PSS now converges under KLU via forced re-factor) ---
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

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
