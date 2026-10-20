#!/usr/bin/env python3
"""Enhancement-913: SFFM's default frequencies are the manual's, carrier above modulation.

F4 of the 2026-10-19 correctness campaign. The manual's table gives SFFM's
carrier FC a default of 500/TSTOP and its modulation FM 5/TSTOP, so that the
default MDI of 90 is 0.9*FC/FM. Both sources had them swapped: `SFFM(0 1)`
over a 1 ms run was a 5 kHz carrier modulated at 500 kHz, and MDI was clamped
to FC/FM = 0.01 with "Warning: MDI in v1 limited to FC/FM".

The manual also orders the arguments two ways: its table and the sources
section's example `SFFM(0 1 10K 5 1K)` read VO VA FC MDI FM, as the code and
SPICE3 do, while its general-form line and its SFFM example
`SFFM(0 2 20 45 1k 1m 0 0)` read FM MDI FC. The code's order stays; when a
carrier comes out below its modulation, the clamp warning now says so.

Checks (both solvers, each source as V and I into 1 ohm):
  [1] SFFM(0 1) over 1 ms: FC = 500 kHz, FM = 5 kHz, MDI = 90 at every point,
      no warning (was FC 5 kHz, FM 500 kHz, MDI clamped to 0.01)
  [2] SFFM(0 1 1meg): FM defaults to 5 kHz, MDI 90 unclamped, no warning
      (was FM 500 kHz, MDI clamped to 2)
  [3] the manual's SFFM example in its general-form order: the warning names
      the carrier below the modulation and the order the code reads
  [4] the sources section's example SFFM(0 1 10K 5 1K): no warning, the
      waveform at every point
  [5] (control) a fully written SFFM(0 1 1meg 2 100k): unchanged
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
WORK = tempfile.mkdtemp(prefix="sffmdefault_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(spec, tag, stop="1m", step="0.5u"):
    """the source as a voltage source (v(a)) and a current source into 1 ohm (v(b))"""
    path = os.path.join(WORK, f"{tag}.cir")
    data = os.path.join(WORK, f"{tag}.txt")
    with open(path, "w") as f:
        f.write(f"* sffmdefault {tag}\nV1 a 0 {spec}\nI1 0 b {spec}\nR1 a 0 1\nR2 b 0 1\n"
                f".control\nset numdgt=15\nset wr_singlescale\ntran {step} {stop}\nwrdata {data} v(a) v(b)\n"
                ".endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    rows = []
    try:
        for ln in open(data):
            q = ln.split()
            try:
                rows.append(tuple(float(x) for x in q[:3]))
            except ValueError:
                pass
    except OSError:
        pass
    return rows, p.stdout + p.stderr


def sffm(t, VO, VA, FC, MDI, FM):
    return VO + VA * math.sin(2 * math.pi * FC * t + MDI * math.sin(2 * math.pi * FM * t))


def fits(rows, *a):
    w = max((abs(r[1] - sffm(r[0], *a)) for r in rows), default=float("inf"))
    same = bool(rows) and all(abs(r[1] - r[2]) < 1e-12 for r in rows)
    return w, same


print("Enhancement-913: SFFM's default frequencies\n")

rows, out = run("SFFM(0 1)", "bare")
w, same = fits(rows, 0.0, 1.0, 500e3, 90.0, 5e3)
check("[1] SFFM(0 1) over 1 ms: carrier 500 kHz, modulation 5 kHz, MDI 90 at every point, I = V "
      "(was a 5 kHz carrier at 500 kHz, MDI clamped to 0.01)", w < 1e-8 and same, f"{w:.1e}")
check("[1] ... and no MDI warning", "MDI in" not in out, out.strip().splitlines()[-1] if out.strip() else "")

rows, out = run("SFFM(0 1 1meg)", "fc")
w, same = fits(rows, 0.0, 1.0, 1e6, 90.0, 5e3)
check("[2] SFFM(0 1 1meg): the modulation defaults to 5/TSTOP = 5 kHz, MDI 90 unclamped, no warning "
      "(was 500 kHz, MDI clamped to 2)", w < 1e-8 and same and "MDI in" not in out, f"{w:.1e}")

rows, out = run("SFFM(0 2 20 45 1k 1m 0 0)", "manual", stop="5m", step="10u")
check("[3] the manual's SFFM example, in its general form's order: the warning names a carrier of 20 Hz "
      "below a modulation of 1000 Hz and the order SFFM reads",
      "FC = 20 Hz is below the modulation FM = 1000 Hz" in out and "SFFM reads VO VA FC MDI FM" in out,
      next((ln for ln in out.splitlines() if "MDI in" in ln), "no warning")[:120])

rows, out = run("SFFM(0 1 10K 5 1K)", "sources", stop="2m", step="1u")
w, same = fits(rows, 0.0, 1.0, 10e3, 5.0, 1e3)
check("[4] the sources section's example SFFM(0 1 10K 5 1K): no warning, the waveform at every point",
      w < 1e-8 and same and "MDI in" not in out, f"{w:.1e}")

rows, out = run("SFFM(0 1 1meg 2 100k)", "full", stop="20u", step="10n")
w, same = fits(rows, 0.0, 1.0, 1e6, 2.0, 1e5)
check("[5] (control) a fully written SFFM(0 1 1meg 2 100k): unchanged", w < 1e-8 and same, f"{w:.1e}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
