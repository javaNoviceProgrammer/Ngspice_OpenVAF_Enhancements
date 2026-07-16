#!/usr/bin/env python3
"""Enhancement-207: `eye` -- eye-diagram / jitter analysis for high-speed links.

`eye <expr> -ui <T>` post-processes a transient waveform into an eye diagram and
the standard serial-link metrics: it auto-detects the two logic rails and the
decision threshold, finds every threshold crossing, estimates the UI phase and
each crossing's time-interval error (TIE) -> jitter RMS / peak-to-peak, measures
the eye height (vertical opening at the sampling instant) and eye width (UI minus
jitter pp, plus the width at BER 1e-12 via the Gaussian-RJ tail), and folds the
waveform modulo 2*UI into the `eye_wave` vs `eye_t` vectors (whose scatter plot IS
the eye diagram).

The checks drive it with signals whose metrics are KNOWN:

  [clean]   an ideal 0/1 clock (perfectly periodic edges) -> ~0 jitter, a full-UI
            open eye, and recovered rails [0, 1] / amplitude 1.
  [jitter]  a clock whose edges carry a KNOWN injected Gaussian timing jitter
            (sigma) -> the reported eye_jitter_rms / _pp match the injected values,
            and eye_width tracks UI - jitter_pp.
  [vectors] the folded eye (`eye_wave` vs `eye_t`) and the scalar result vectors
            are published.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import random
import statistics
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0
UI = 0.5e-9


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    passed += bool(ok); failed += (not ok)


def pwl_clock(sigj, seed, N=200, tr=8e-12):
    """A 0/1 clock with a UI grid; each edge displaced by N(0, sigj). Returns
    (pwl string, injected TIE rms, injected TIE pp)."""
    random.seed(seed)
    edges, lvl = [], 0
    for k in range(1, N):
        tk = k * UI + (random.gauss(0, sigj) if sigj > 0 else 0.0)
        edges.append((tk, lvl, 1 - lvl)); lvl = 1 - lvl
    pts = ["0 0"]
    for (tk, a, b) in edges:
        pts.append(f"{tk - tr/2:.6e} {a}"); pts.append(f"{tk + tr/2:.6e} {b}")
    ties = [edges[i][0] - (i + 1) * UI for i in range(len(edges))]
    inj_rms = statistics.pstdev(ties) if sigj > 0 else 0.0
    inj_pp = (max(ties) - min(ties)) if sigj > 0 else 0.0
    return " ".join(pts), inj_rms, inj_pp, N


def run_eye(pwl, N, prints):
    deck = (f"* eye test\nV1 out 0 PWL({pwl})\nR1 out 0 1k\n.tran 0.002n {N*0.5}n\n"
            f".control\n  run\n  eye v(out) -ui 0.5n -tstart 2n\n"
            + "".join(f"  print {p}\n" for p in prints) + ".endc\n.end\n")
    open(os.path.join(HERE, "_e.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_e.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=180)
    out = r.stdout + r.stderr
    vals = {}
    for line in out.splitlines():
        if "=" in line and "Reset" not in line and "Circuit" not in line:
            p = line.split("=")
            nm = p[0].strip().split()[-1] if p[0].strip() else ""
            try:
                vals[nm] = float(p[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    return vals, out


print("Enhancement-207: eye diagram / jitter analysis")

# ---- 1) clean ideal clock: ~0 jitter, full eye, rails [0,1] ----------------------
pwl, _, _, N = pwl_clock(0.0, 1)
v, out = run_eye(pwl, N, ["eye_level0", "eye_level1", "eye_amplitude",
                          "eye_jitter_rms", "eye_jitter_pp", "eye_height", "eye_width"])
check("[clean] an ideal 0/1 clock recovers rails [0,1] and amplitude 1",
      abs(v.get("eye_level0", 9) - 0) < 0.02 and abs(v.get("eye_level1", 9) - 1) < 0.02
      and abs(v.get("eye_amplitude", 0) - 1) < 0.02,
      f"(level0 {v.get('eye_level0')}, level1 {v.get('eye_level1')})")
check("[clean] a perfectly periodic clock has ~zero jitter and a full-UI open eye",
      v.get("eye_jitter_rms", 9) < 1e-13 and v.get("eye_width", 0) > 0.98 * UI
      and v.get("eye_height", 0) > 0.98,
      f"(jitter {v.get('eye_jitter_rms')} s, width {v.get('eye_width')} s, height {v.get('eye_height')})")

# ---- 2) known injected Gaussian jitter -> eye recovers it ------------------------
SIG = 20e-12
pwl, inj_rms, inj_pp, N = pwl_clock(SIG, 42)
v2, out2 = run_eye(pwl, N, ["eye_jitter_rms", "eye_jitter_pp", "eye_width", "eye_ui"])
jr, jp = v2.get("eye_jitter_rms"), v2.get("eye_jitter_pp")
check("[jitter] the reported RMS jitter matches the known injected Gaussian jitter",
      jr is not None and abs(jr - inj_rms) < 0.15 * inj_rms,
      f"(measured {1e12*jr:.2f} ps vs injected {1e12*inj_rms:.2f} ps)" if jr else out2[-300:])
check("[jitter] the reported peak-to-peak jitter matches the injected span",
      jp is not None and abs(jp - inj_pp) < 0.15 * inj_pp,
      f"(measured {1e12*jp:.2f} ps vs injected {1e12*inj_pp:.2f} ps)" if jp else "")
check("[width] the eye width equals UI minus the peak-to-peak jitter",
      jp is not None and abs(v2.get("eye_width", 0) - (UI - jp)) < 0.02 * UI,
      f"(eye_width {v2.get('eye_width')} s, UI-pp {UI - jp if jp else 0} s)")

# ---- 3) the folded-eye + scalar vectors are published, and wrdata-able ----------
v3, out3 = run_eye(pwl, N, ["length(eye_wave)", "length(eye_t)"])
check("[vectors] the folded eye is published as 'eye_wave' vs 'eye_t' for plotting",
      v3.get("length(eye_wave)", 0) > 100 and v3.get("length(eye_t)", 0) > 100,
      f"(eye_wave {v3.get('length(eye_wave)')} pts, eye_t {v3.get('length(eye_t)')} pts)")

# eye_wave / eye_t must live in their own plot so wrdata (which pairs a vector with
# its scale) does not crash on a length mismatch with the long transient time scale.
datf = os.path.join(HERE, "_ew.dat")
deck = (f"* eye wrdata\nV1 out 0 PWL({pwl})\nR1 out 0 1k\n.tran 0.002n {N*0.5}n\n"
        f".control\n  run\n  eye v(out) -ui 0.5n -tstart 2n\n  wrdata {datf} eye_wave\n.endc\n.end\n")
open(os.path.join(HERE, "_e.cir"), "w").write(deck)
r = subprocess.run([NGSPICE, "-b", os.path.join(HERE, "_e.cir")], cwd=HERE,
                   capture_output=True, text=True, timeout=180)
nrows = sum(1 for _ in open(datf)) if os.path.exists(datf) else 0
check("[wrdata] `wrdata eye_wave` writes the folded eye without crashing "
      "(eye_wave and its scale eye_t share their own plot)",
      r.returncode == 0 and nrows > 100, f"(rc {r.returncode}, {nrows} rows)")
if os.path.exists(datf):
    os.remove(datf)

for f in ("_e.cir",):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
