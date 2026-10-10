#!/usr/bin/env python3
"""verify_uicstart.py -- Enhancement-852: a `uic` transient has its t = 0 point.

F8 of the second robustness campaign of 2026-10-10.

`uic` loads the circuit once and solves nothing at t = 0, so dctran wrote no
point there: the run began at the first step, and `meas` and `fourier` with it.
The point at t = 0 is now solved -- each capacitor at its initial voltage, each
inductor at its initial current, the sources at t = 0 -- with a step a
millionth of the first, and a second solve from that point gives the finite
currents where a source makes a capacitor jump. Everything is put back before
the first step, so the run after t = 0 is the run without the point.

  [1] an RC under uic with .ic v(2)=0.3: time[0] = 0, v(2) = 0.3, v(1) = 0
  [2] a divider a source drives, at t = 0: 1.25 V, and the source's current
  [3] a diode, a capacitor with ic=, an inductor with ic= and an .ic a source
      contradicts: the source's 5 V, the inductor's 1 mA, 10 V across 10 kOhm
  [4] a CMOS inverter whose supply node starts at 0 V: the supply's current at
      t = 0 is finite, not the impulse of its capacitances' jump
  [5] after t = 0, the samples are those of the same run with tstart = 1e-30,
      which writes no t = 0 point
  [6] `meas tran find v(2) at=0` reads the initial condition
  [7] (control) without uic, time[0] = 0 is the operating point
  [8] (control) uic with tstart > 0: no point before tstart

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="uicstart_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, netlist, tran, vecs, extra=""):
    """run `tran` and return (rows of [time, vecs...] as text, output)"""
    out = os.path.join(WORK, name + ".txt")
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\nset wr_singlescale\n%s\n%s\nwrdata %s %s\n.endc\n.end\n"
                % (name, netlist, tran, extra, out, vecs))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300,
                       errors="replace")
    rows = [line.split() for line in open(out)] if os.path.exists(out) else []
    return rows, p.stdout + p.stderr


def near(a, b, tol):
    return abs(a - b) <= tol * max(abs(b), 1e-30)


RC = "v1 1 0 pwl(0 0 1n 1)\nr1 1 2 1k\nc1 2 0 1p\nvs 3 0 dc 2.5\nr3 3 4 1k\nr4 4 0 1k\n.ic v(2)=0.3"
VECS = "v(1) v(2) v(4) i(vs)"

# [1], [2], [6]
rows, out = run("rc", RC, "tran 10p 5n uic", VECS, "meas tran v0 find v(2) at=0\nprint v0")
r0 = [float(x) for x in rows[0]] if rows else [float("nan")] * 5
check("[1] an RC under uic with .ic v(2)=0.3: time[0] = 0, v(2) = 0.3, v(1) = 0 (first step on E-844)",
      r0[0] == 0.0 and near(r0[2], 0.3, 1e-8) and r0[1] == 0.0, " ".join(rows[0]) if rows else "no rows")
check("[2] a divider a source drives, at t = 0: 1.25 V, and the source's current -1.25 mA",
      r0[0] == 0.0 and near(r0[3], 1.25, 1e-12) and near(r0[4], -1.25e-3, 1e-12),
      f"v(4) {r0[3]!r}, i(vs) {r0[4]!r}")
m = re.search(r"^v0 = (\S+)", out, re.M)
v0 = float(m.group(1)) if m else float("nan")
check("[6] `meas tran find v(2) at=0` reads the initial condition, 0.3 (out of interval on E-844)",
      near(v0, 0.3, 1e-8), f"got {v0!r}")

# [3]
DL = ("v1 1 0 dc 5\nr1 1 2 1k\nd1 2 0 dmod\nc1 2 0 1n ic=0.2\nl1 1 5 1u ic=1m\nr5 5 0 10k\n"
      ".model dmod d is=1e-14\n.ic v(1)=3")
rows, out = run("dl", DL, "tran 1n 100n uic", "v(1) v(2) i(l1) v(5)")
r0 = [float(x) for x in rows[0]] if rows else [float("nan")] * 5
check("[3] diode, capacitor ic=, inductor ic=, and an .ic the source contradicts: 5 V, 0.2 V, 1 mA, 10 V",
      r0[0] == 0.0 and r0[1] == 5.0 and near(r0[2], 0.2, 1e-6) and near(r0[3], 1e-3, 1e-5)
      and near(r0[4], 10.0, 1e-5), " ".join(rows[0]) if rows else "no rows")

# [4]
INV = ("vdd vdd 0 3\nvin in 0 pulse(0 3 1n 0.2n 0.2n 3n 8n)\nm1 out in 0 0 nm w=1u l=0.18u\n"
       "m2 out in vdd vdd pm w=2u l=0.18u\ncl out 0 10f\n"
       ".model nm nmos level=1 vto=0.5 kp=200u cgso=1e-10 cgdo=1e-10\n"
       ".model pm pmos level=1 vto=-0.5 kp=100u cgso=1e-10 cgdo=1e-10\n.ic v(out)=1.5")
rows, out = run("inv", INV, "tran 10p 20n uic", "v(out) i(vdd)")
r0 = [float(x) for x in rows[0]] if rows else [float("nan")] * 3
r1 = [float(x) for x in rows[1]] if len(rows) > 1 else [float("nan")] * 3
check("[4] a CMOS inverter whose supply node starts at 0 V: i(vdd) at t = 0 is finite and below the "
      "first step's",
      r0[0] == 0.0 and abs(r0[2]) < abs(r1[2]) and abs(r0[2]) < 1e-2,
      f"t=0 {r0[2]!r} A, first step {r1[2]!r} A")

# [5]
rows_a, _ = run("rca", RC, "tran 10p 5n 0 0.1n uic", VECS)
rows_b, _ = run("rcb", RC, "tran 10p 5n 1e-30 0.1n uic", VECS)
check("[5] after t = 0, the samples are those of the same run with tstart = 1e-30, bit for bit",
      len(rows_a) > 2 and rows_a[0][0] == "0.00000000000000000e+00" and rows_a[1:] == rows_b,
      f"{len(rows_a)} and {len(rows_b)} rows")

# [7], [8]
rows, out = run("op", RC.replace(".ic v(2)=0.3", ""), "tran 10p 5n", VECS)
r0 = [float(x) for x in rows[0]] if rows else [float("nan")] * 5
check("[7] (control) without uic, time[0] = 0 is the operating point: v(2) = 0, v(4) = 1.25",
      r0[0] == 0.0 and r0[2] == 0.0 and near(r0[3], 1.25, 1e-12), " ".join(rows[0]) if rows else "no rows")
rows, out = run("ts", RC, "tran 10p 5n 1n uic", VECS)
t0 = float(rows[0][0]) if rows else float("nan")
check("[8] (control) uic with tstart = 1 ns: no point before tstart", t0 >= 1e-9, f"time[0] {t0!r}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
