#!/usr/bin/env python3
"""Enhancement-203: .meas ac gain_margin / phase_margin (+ batch vdb/vp auto-save).

ngspice's `.measure` already covers TRIG/TARG, FIND...WHEN, AVG/RMS/INTEG/DERIV, etc.
The one loop-stability quantity it lacked was AC margins: there was no gain_margin /
phase_margin function, and the manual recipe `FIND vdb WHEN vp=-180' cannot work
because `vp()' is wrapped to (-180,180] -- the phase never actually equals -180.

This adds `phase_margin` and `gain_margin` to `.meas ac`, computed on the UNWRAPPED
phase: phase_margin = 180 + phase at the unity-gain (0 dB) crossover; gain_margin =
-gain(dB) at the -180 deg phase crossover; each also reports its crossover frequency.

The checks build loop-gain responses whose margins are known in closed form (buffered
one-pole sections, so the poles are exactly where we place them), and compare. A final
check exercises a batch (dot-card) `.meas ac ... vdb(out)` -- which used to mis-parse
the `db' suffix in the auto-save pass ("can't parse 'vd'") and leave the node unsaved.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import math
import cmath
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    open(os.path.join(HERE, "_m.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_m.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    vals = {}
    for line in out.splitlines():
        if "=" in line:                     # meas prints "name = value unit at= freq"
            p = line.split("=")
            name = p[0].strip()
            try:
                vals[name] = float(p[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    return vals, out


# ---- a buffered N-pole loop gain: DC gain A, each pole at its own freq ----------
def loop_deck(A, poles_hz, measures):
    """poles_hz: list of pole frequencies. Buffered RC sections (independent poles)."""
    s = [f"* loop gain A={A}, poles={poles_hz}"]
    s.append("V1 in 0 AC 1")
    s.append(f"E0 n0 0 in 0 {A}")
    node = "n0"
    for k, fp in enumerate(poles_hz):
        R = 1.0 / (2 * math.pi * fp * 1e-9)      # C = 1nF -> R sets the pole
        out = "out" if k == len(poles_hz) - 1 else f"x{k}"
        s.append(f"Rp{k} {node} {out} {R:.6e}")
        s.append(f"Cp{k} {out} 0 1e-9")
        if k < len(poles_hz) - 1:
            s.append(f"Eb{k} y{k} 0 {out} 0 1")   # buffer to next section
            node = f"y{k}"
    s.append(".ac dec 400 1 1g")
    s.append(".control")
    s.append("run")
    s += measures
    s.append(".endc")
    s.append(".end")
    return "\n".join(s)


def analytic_margins(A, poles_hz):
    """Return (phase_margin_deg, gain_margin_db or None) of A / prod(1+jf/fk)."""
    def H(f):
        h = complex(A, 0)
        for fp in poles_hz:
            h /= complex(1.0, f / fp)
        return h
    fs = [10 ** (0 + 9 * k / 4000) for k in range(4001)]      # 1 Hz .. 1 GHz
    gdb = [20 * math.log10(abs(H(f))) for f in fs]
    ph = []
    off = 0.0
    prev = 0.0
    for f in fs:
        p = math.degrees(cmath.phase(H(f)))
        if ph:
            dp = p - prev
            if dp > 180:
                off -= 360
            elif dp < -180:
                off += 360
        prev = p
        ph.append(p + off)
    pm = gm = None
    for i in range(1, len(fs)):
        if pm is None and ((gdb[i-1] >= 0 > gdb[i]) or (gdb[i-1] < 0 <= gdb[i])):
            t = (0 - gdb[i-1]) / (gdb[i] - gdb[i-1])
            pm = 180 + (ph[i-1] + t * (ph[i] - ph[i-1]))
        if gm is None and ((ph[i-1] >= -180 > ph[i]) or (ph[i-1] < -180 <= ph[i])):
            t = (-180 - ph[i-1]) / (ph[i] - ph[i-1])
            gm = -(gdb[i-1] + t * (gdb[i] - gdb[i-1]))
    return pm, gm


# ================= 1) stable 2-pole loop: phase margin, infinite gain margin =====
A, poles = 100.0, [1e3, 1e6]
pm_exp, gm_exp = analytic_margins(A, poles)      # gm_exp is None (2 poles -> inf)
vals, out = run(loop_deck(A, poles,
                          ["meas ac pm phase_margin v(out)",
                           "meas ac gm gain_margin  v(out)"]))
if "pm" in vals:
    check("[phase_margin] a stable 2-pole loop's phase margin matches the closed form "
          "(computed on the unwrapped phase, at the 0 dB crossover)",
          abs(vals["pm"] - pm_exp) < 1.0, f"(meas {vals['pm']:.2f} deg, analytic {pm_exp:.2f} deg)")
else:
    check("[phase_margin] a stable 2-pole loop's phase margin matches the closed form",
          False, out[-300:])

check("[gain_margin] a 2-pole loop is reported as having no -180 deg crossover "
      "(infinite gain margin), not a bogus number", "gm" not in vals,
      "(correctly reported no phase crossover)" if "gm" not in vals else f"(got {vals.get('gm')})")


# ================= 2) 3-pole loop: both margins finite, match closed form ========
A3, poles3 = 50.0, [1e6, 1e6, 1e6]
pm3_exp, gm3_exp = analytic_margins(A3, poles3)
vals, out = run(loop_deck(A3, poles3,
                          ["meas ac pm phase_margin v(out)",
                           "meas ac gm gain_margin  v(out)"]))
if "pm" in vals and pm3_exp is not None:
    check("[phase_margin] a 3-pole loop's phase margin matches the closed form",
          abs(vals["pm"] - pm3_exp) < 1.5, f"(meas {vals['pm']:.2f}, analytic {pm3_exp:.2f} deg)")
else:
    check("[phase_margin] a 3-pole loop's phase margin matches the closed form", False, out[-300:])

if "gm" in vals and gm3_exp is not None:
    check("[gain_margin] the same loop's gain margin (gain at the unwrapped -180 deg "
          "phase crossover) matches the closed form", abs(vals["gm"] - gm3_exp) < 1.0,
          f"(meas {vals['gm']:.2f}, analytic {gm3_exp:.2f} dB)")
else:
    check("[gain_margin] the same loop's gain margin matches the closed form", False, out[-300:])


# ================= 3) batch (dot-card) .meas ac vdb(out) auto-save ===============
# In batch mode the measure auto-save pass used to mis-parse the db/p suffix
# ("can't parse 'vd'") and leave v(out) unsaved -> "no data saved for AC". A plain
# RC low-pass, measured with vdb(out) as DOT-CARDS (no .control), must now work.
batch = """* batch .meas ac with vdb(out) -- no .control block
V1 in 0 AC 1
R1 in out 1k
C1 out 0 1n
.ac dec 50 1k 100meg
.meas ac dcg  FIND vdb(out) AT=1k
.meas ac bw3  WHEN vdb(out)=-3
.end
"""
vals, out = run(batch)
ok = ("dcg" in vals and "bw3" in vals and
      "can't parse" not in out and "no data saved" not in out.lower())
check("[batch] a batch `.meas ac ... vdb(out)` auto-saves the node and runs "
      "(the db/p suffix truncation that broke this is fixed)", ok,
      f"(dcg {vals.get('dcg')} dB, bw {vals.get('bw3')} Hz)" if ok else out[-300:])

# tidy
for f in ("_m.cir",):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
