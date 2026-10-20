#!/usr/bin/env python3
"""Enhancement-912: a current source's SFFM and AM read their delay and phases.

F3 of the 2026-10-19 correctness campaign. E-318 fixed the voltage source's
SFFM and AM before their delay; the current source kept the old code:

* SFFM(VO VA FC MDI FM TD PHASEM PHASEC) read PHASEM from the TD slot and
  PHASEC from PHASEM's, dropped the last argument, and never applied TD:
  SFFM(0 1 1meg 2 100k 5u 30 60) took a modulation phase of 5e-6 degrees and
  a carrier phase of 30, and started at t = 0 (0.5 at the operating point
  where the voltage source gives 0.888651).
* AM returned 0 before its delay -- and at t = 0 and the operating point even
  without one -- so they lost the offset VO.

Checks (both solvers):
  [1] the SFFM current source: 0.888651 at the operating point (was 0.5)
  [2] ... held at that value to TD = 5 us
  [3] ... at every accepted point within 1e-9 of the manual's waveform
  [4] ... equal to the voltage source with the same line at every point
  [5] the AM current source: 0.5 at the operating point (was 0), held to TD,
      within 1e-9 of the waveform and equal to the voltage source
  [6] AM without a delay: 0.5 at the operating point and t = 0 (was 0), the
      waveform after, I = V
  [7] (control) SFFM without a delay or phases: unchanged, I = V
"""
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="isrcmod_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(spec, tag, stop="20u", step="10n"):
    """the source as a voltage source (v(a)) and a current source into 1 ohm (v(b));
    returns the operating point (va, vb) and the transient rows (t, va, vb)"""
    path = os.path.join(WORK, f"{tag}.cir")
    data = os.path.join(WORK, f"{tag}.txt")
    with open(path, "w") as f:
        f.write(f"* isrcmod {tag}\nV1 a 0 {spec}\nI1 0 b {spec}\nR1 a 0 1\nR2 b 0 1\n"
                f".control\nset numdgt=15\nset wr_singlescale\nop\nprint v(a) v(b)\n"
                f"tran {step} {stop}\nwrdata {data} v(a) v(b)\n.endc\n.end\n")
    out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK).stdout
    op = {}
    for ln in out.splitlines():
        p = ln.split("=")
        if len(p) == 2 and p[0].strip() in ("v(a)", "v(b)"):
            op[p[0].strip()] = float(p[1])
    rows = []
    try:
        for ln in open(data):
            p = ln.split()
            try:
                rows.append(tuple(float(x) for x in p[:3]))
            except ValueError:
                pass
    except OSError:
        pass
    return op.get("v(a)"), op.get("v(b)"), rows


def sffm(t, VO, VA, FC, MDI, FM, TD=0.0, PM=0.0, PC=0.0):
    pm, pc = math.radians(PM), math.radians(PC)
    if t - TD <= 0:
        return VO + VA * math.sin(pc + MDI * math.sin(pm))
    x = t - TD
    return VO + VA * math.sin(2 * math.pi * FC * x + pc + MDI * math.sin(2 * math.pi * FM * x + pm))


def am(t, VO, VMO, VMA, FM, FC, TD=0.0, PM=0.0, PC=0.0):
    pm, pc = math.radians(PM), math.radians(PC)
    if t - TD <= 0:
        return VO + (VMO + VMA * math.sin(pm)) * math.sin(pc)
    x = t - TD
    return VO + (VMO + VMA * math.sin(2 * math.pi * FM * x + pm)) * math.sin(2 * math.pi * FC * x + pc)


def worst(rows, f, col):
    return max((abs(r[col] - f(r[0])) for r in rows), default=float("inf"))


print("Enhancement-912: a current source's SFFM and AM\n")

# ----------------------------------------------------------- [1]-[4] ---
P = (0.0, 1.0, 1e6, 2.0, 1e5, 5e-6, 30.0, 60.0)
va, vb, rows = run("SFFM(0 1 1meg 2 100k 5u 30 60)", "sffm")
start = sffm(0.0, *P)
check(f"[1] SFFM(0 1 1meg 2 100k 5u 30 60) as a current source: {start:.6f} at the operating point (was 0.5)",
      vb is not None and abs(vb - start) < 1e-6, f"{vb}")
pre = [r for r in rows if r[0] <= 5e-6]
check("[2] ... held at that value up to TD = 5 us (it started at t = 0)",
      pre and all(abs(r[2] - start) < 1e-9 for r in pre), f"{len(pre)} points")
w = worst(rows, lambda t: sffm(t, *P), 2)
check("[3] ... at every accepted point within 1e-9 of the manual's waveform", w < 1e-9, f"{w:.1e}")
check("[4] ... equal to the voltage source with the same line at every point",
      rows and all(abs(r[1] - r[2]) < 1e-12 for r in rows) and abs(va - vb) < 1e-9,
      f"{len(rows)} points")

# ---------------------------------------------------------------- [5] ---
Q = (0.5, 1.0, 0.5, 1e5, 1e6, 5e-6)
va, vb, rows = run("AM(0.5 1 0.5 100k 1meg 5u)", "am")
w = worst(rows, lambda t: am(t, *Q), 2)
pre = [r for r in rows if r[0] <= 5e-6]
check("[5] AM(0.5 1 0.5 100k 1meg 5u) as a current source: 0.5 at the operating point and up to TD "
      "(was 0), within 1e-9 of the waveform, equal to the voltage source",
      vb is not None and abs(vb - 0.5) < 1e-6 and pre and all(abs(r[2] - 0.5) < 1e-9 for r in pre)
      and w < 1e-9 and all(abs(r[1] - r[2]) < 1e-12 for r in rows),
      f"op {vb}, worst {w:.1e}")

# ---------------------------------------------------------------- [6] ---
va, vb, rows = run("AM(0.5 1 0.5 100k 1meg)", "am0")
w = worst(rows, lambda t: am(t, 0.5, 1.0, 0.5, 1e5, 1e6), 2)
check("[6] AM(0.5 1 0.5 100k 1meg), no delay: 0.5 at the operating point and t = 0 (was 0), within 1e-9 "
      "of the waveform, I = V",
      vb is not None and abs(vb - 0.5) < 1e-6 and rows and abs(rows[0][2] - 0.5) < 1e-9 and w < 1e-9
      and all(abs(r[1] - r[2]) < 1e-12 for r in rows), f"op {vb}, worst {w:.1e}")

# ---------------------------------------------------------------- [7] ---
va, vb, rows = run("SFFM(0.2 1 1meg 2 100k)", "sffm0")
w = worst(rows, lambda t: sffm(t, 0.2, 1.0, 1e6, 2.0, 1e5), 2)
check("[7] (control) SFFM(0.2 1 1meg 2 100k): unchanged, within 1e-9 of the waveform, I = V",
      w < 1e-9 and rows and all(abs(r[1] - r[2]) < 1e-12 for r in rows), f"{w:.1e}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
