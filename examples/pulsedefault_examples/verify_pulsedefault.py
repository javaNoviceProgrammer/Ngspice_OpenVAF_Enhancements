#!/usr/bin/env python3
"""Enhancement-910: a voltage source's PULSE with PW or PER left out.

F2 of the 2026-10-19 correctness campaign. The manual (4.1.1) gives PW and PER
a default of TSTOP, and the current source and SPICE3 read them that way: a
PULSE without a period is one pulse. The voltage source took an omitted PER as
TR + TF + PW and an omitted PW as 0, so `PULSE(0 1 1u 1u 1u 5u)` repeated
every 7 us (a third rising edge at 15.5 us), and `PULSE(0 1 1u 1u 1u)` was a
2 us triangle wave. Its breakpoints followed the same rule, and those of an
explicit PER=0, which Enhancement-446 had made a single pulse in the load
only, still repeated.

Checks (both solvers):
  [1] PULSE(0 1 1u 1u 1u 5u): one pulse -- 0.5 at 1.5 us, 1 at 4 us, 0.5 at
      7.5 us, 0 at 10, 15.5 and 30 us -- and the V and I sources agree at every
      point
  [2] PULSE(0 1 1u 1u 1u): rises and stays at 1 (5, 12.5 and 30 us), as the I
      source
  [3] the V and I sources put their time points at the same times, with PER
      left out and with PER=0 (the breakpoints of a repeating pulse are gone)
  [4] controls: a written period repeats as before, PER=0 is one pulse, a
      negative PW is a zero-width pulse, and a pulse count of 2 stops after
      two
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="pulsedefault_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def wave(spec, tag, stop="40u", step="0.1u"):
    """the PULSE as a voltage source (v(a)) and a current source into 1 ohm (v(b))"""
    path = os.path.join(WORK, f"{tag}.cir")
    data = os.path.join(WORK, f"{tag}.txt")
    with open(path, "w") as f:
        f.write(f"* pulsedefault {tag}\nV1 a 0 PULSE({spec})\nI1 0 b PULSE({spec})\nR1 a 0 1\nR2 b 0 1\n"
                f".control\nset numdgt=15\nset wr_singlescale\ntran {step} {stop}\nwrdata {data} v(a) v(b)\n"
                ".endc\n.end\n")
    subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    rows = []
    try:
        with open(data) as f:
            for ln in f:
                p = ln.split()
                try:
                    rows.append(tuple(float(x) for x in p[:3]))
                except ValueError:
                    pass
    except OSError:
        pass
    return rows


def at(rows, t):
    """linear interpolation of both columns at t"""
    for (t0, a0, b0), (t1, a1, b1) in zip(rows, rows[1:]):
        if t0 <= t <= t1:
            w = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return a0 + w * (a1 - a0), b0 + w * (b1 - b0)
    return None, None


def near(x, want, tol=1e-9):
    return x is not None and abs(x - want) <= tol


print("Enhancement-910: PULSE with PW or PER left out\n")

# ------------------------------------------------------------- [1] ---
rows = wave("0 1 1u 1u 1u 5u", "noper")
want = ((1.5e-6, 0.5), (4e-6, 1.0), (7.5e-6, 0.5), (10e-6, 0.0), (15.5e-6, 0.0), (30e-6, 0.0))
got = [at(rows, t)[0] for t, _ in want]
check("[1] PULSE(0 1 1u 1u 1u 5u): one pulse, 0.5 / 1 / 0.5 / 0 / 0 / 0 at 1.5, 4, 7.5, 10, 15.5 and 30 us "
      "(was a repeat every 7 us)", all(near(g, w) for g, (_, w) in zip(got, want)),
      " ".join("%.3g" % g if g is not None else "None" for g in got))
check("[1] ... the voltage and the current source agree at every point",
      rows and all(abs(a - b) <= 1e-12 for _, a, b in rows), f"{len(rows)} points")

# ------------------------------------------------------------- [2] ---
rows = wave("0 1 1u 1u 1u", "nopw")
got = [at(rows, t)[0] for t in (1.5e-6, 5e-6, 12.5e-6, 30e-6)]
check("[2] PULSE(0 1 1u 1u 1u): 0.5 at 1.5 us, then 1 at 5, 12.5 and 30 us (was a 2 us triangle)",
      all(near(g, w) for g, w in zip(got, (0.5, 1.0, 1.0, 1.0))),
      " ".join("%.3g" % g if g is not None else "None" for g in got))
check("[2] ... as the current source", rows and all(abs(a - b) <= 1e-12 for _, a, b in rows),
      f"{len(rows)} points")


# ------------------------------------------------------------- [3] ---
def grid(spec, tag):
    """time points of the V source alone, and of the I source alone"""
    out = []
    for dev in (f"V1 a 0 PULSE({spec})\nR1 a 0 1", f"I1 0 a PULSE({spec})\nR1 a 0 1"):
        path = os.path.join(WORK, f"{tag}{len(out)}.cir")
        data = os.path.join(WORK, f"{tag}{len(out)}.txt")
        with open(path, "w") as f:
            f.write(f"* grid\n{dev}\n.control\nset numdgt=15\nset wr_singlescale\ntran 0.5u 40u\n"
                    f"wrdata {data} v(a)\n.endc\n.end\n")
        subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
        try:
            out.append([float(ln.split()[0]) for ln in open(data) if ln.strip()])
        except (OSError, ValueError, IndexError):
            out.append([])
    return out


for spec, what in (("0 1 1u 1u 1u 5u", "PER left out"), ("0 1 1u 1u 1u 5u 0", "PER=0")):
    gv, gi = grid(spec, "g" + str(len(what)))
    same = len(gv) == len(gi) and gv and all(abs(x - y) <= 1e-15 for x, y in zip(gv, gi))
    check(f"[3] {what}: the voltage source's time points are the current source's", same,
          f"{len(gv)} and {len(gi)} points")

# ------------------------------------------------------------- [4] ---
rows = wave("0 1 1u 1u 1u 2u 5u", "per5")
got = [at(rows, t)[0] for t in (3e-6, 5e-6, 8e-6, 13e-6)]
check("[4] (control) a written period of 5 us repeats: 1, 0, 1, 1 at 3, 5, 8 and 13 us",
      all(near(g, w) for g, w in zip(got, (1.0, 0.0, 1.0, 1.0))),
      " ".join("%.3g" % g if g is not None else "None" for g in got))
rows = wave("0 1 1u 1u 1u 2u 0", "per0")
got = [at(rows, t)[0] for t in (3e-6, 8e-6, 13e-6)]
check("[4] (control) PER=0 is one pulse (E-446): 1, 0, 0 at 3, 8 and 13 us",
      all(near(g, w) for g, w in zip(got, (1.0, 0.0, 0.0))),
      " ".join("%.3g" % g if g is not None else "None" for g in got))
rows = wave("0 1 1u 1u 1u -1u 5u", "pwneg")
got = [at(rows, t)[0] for t in (1.5e-6, 2.5e-6, 4e-6)]
check("[4] (control) a negative PW is a zero-width pulse on the voltage source: 0.5, 0.5, 0",
      all(near(g, w) for g, w in zip(got, (0.5, 0.5, 0.0))),
      " ".join("%.3g" % g if g is not None else "None" for g in got))
rows = wave("0 1 1u 1u 1u 2u 5u 2", "np2")
got = [at(rows, t)[0] for t in (3e-6, 8e-6, 13e-6)]
check("[4] (control) a count of 2 stops after two pulses: 1, 1, 0 at 3, 8 and 13 us",
      all(near(g, w) for g, w in zip(got, (1.0, 1.0, 0.0))),
      " ".join("%.3g" % g if g is not None else "None" for g in got))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
