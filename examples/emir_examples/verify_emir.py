#!/usr/bin/env python3
"""
Enhancement-158: EMIR -- power-grid electromigration + IR-drop -- `emir` command.

`emir` analyses the power-distribution network after a DC solve and reports two
reliability metrics:

  * IR-drop -- how far each node sags below the supply rail under load
    (the resistive grid drops I*R between the pad and each tap).
  * Electromigration -- for each wire-segment resistor, the current DENSITY
    J = |I|/(w*thickness) and a Black's-equation lifetime MTTF/ref = (Jmax/J)^n.
    EM is driven by current density, not current, so a narrow wire can be the
    bottleneck even at modest current.

The test grid is a 3-segment ladder off a 1 V rail, each segment a resistor with
a different width, each tap drawing 0.1 A:

  rail --Rw1(w=2u)-- n1 --Rw2(w=1u)-- n2 --Rw3(w=0.5u)-- n3
                     |0.1A            |0.1A               |0.1A

Node voltages are exact by hand: n1=0.85, n2=0.75, n3=0.70 (currents 0.3/0.2/0.1
through Rw1/Rw2/Rw3). Current densities (thickness 0.5u): Rw1=3e11, Rw2=Rw3=4e11
A/m^2 -- so the widest wire carries the most current yet has the LOWEST density.

Checks (each under BOTH the Sparse and KLU solvers):
  [1] IR-drop -- worst drop is 0.30 V (30% of rail) at n3.
  [2] IR-drop scales linearly with load current (2x loads -> 2x drop).
  [3] EM -- J = I/(w*thick) exact, and the worst-density segment is the narrow
      low-current wire, NOT the high-current wide one.
  [4] Black's law -- MTTF ratio between two segments = (J2/J1)^n.
  [5] violation count -- with Jmax set between Rw1 and Rw3 density, exactly the
      two narrow segments fail.
  [6] rail auto-detect equals an explicit rail.
  [7] OSDI load -- an OSDI (Verilog-A) device sinking current at a tap is handled
      identically to a current source.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers
check_both_solvers(__file__)   # re-execs under BOTH solvers, injecting .option

SCRATCH = tempfile.mkdtemp(prefix="emir_verify_")
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
    with open(os.path.join(SCRATCH, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def grid(load="0.1", loads_osdi=False, emir_args="thick 0.5u jmax 3.5e11 tref 3.15e8"):
    pre = ".control\npre_osdi vares.osdi\n.endc\n" if loads_osdi else ""
    if loads_osdi:
        tap3 = "Nload n3 0 rl\n.model rl vares r=7\n"
    else:
        tap3 = f"Iload3 n3 0 dc {load}\n"
    return run_deck("g.cir", f"""* emir grid
{pre}Vdd vdd 0 dc 1.0
Rw1 vdd n1 0.5 w=2u
Rw2 n1 n2 0.5 w=1u
Rw3 n2 n3 0.5 w=0.5u
Iload1 n1 0 dc {load}
Iload2 n2 0 dc {load}
{tap3}.control
emir {emir_args}
.endc
.end
""")


def worst_drop(log):
    m = re.search(r"worst drop\s+([0-9.eE+-]+)\s*V\s+\(([0-9.]+)% of rail\)\s+at\s+(\S+)", log)
    return (float(m.group(1)), float(m.group(2)), m.group(3)) if m else (None, None, None)


def worst_j(log):
    m = re.search(r"worst J\s+([0-9.eE+-]+)\s*A/m2\s+at\s+(\S+)\s+\(MTTF\s+([0-9.eE+-]+)", log)
    return (float(m.group(1)), m.group(2), float(m.group(3))) if m else (None, None, None)


def em_rows(log):
    # segment  I  w  J  MTTF  status
    rows = {}
    for m in re.finditer(r"^\s+(rw\d)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+(FAIL|ok)\s*$",
                         log, re.M):
        rows[m.group(1)] = dict(i=float(m.group(2)), w=float(m.group(3)),
                                j=float(m.group(4)), mttf=float(m.group(5)),
                                status=m.group(6))
    return rows


# compile the OSDI load model
r = subprocess.run([OPENVAF, os.path.join(HERE, "vares.va"), "-o",
                    os.path.join(SCRATCH, "vares.osdi")],
                   capture_output=True, text=True, cwd=SCRATCH)
if not os.path.exists(os.path.join(SCRATCH, "vares.osdi")):
    check("vares.va compiles", False, r.stdout + r.stderr)
    raise SystemExit(1)

# ---------------------------------------------------------------------------
log = grid()
drop, pct, node = worst_drop(log)
jval, jseg, jmttf = worst_j(log)
rows = em_rows(log)

# [1] worst IR drop
check("[1] worst IR-drop 0.30 V (30%) at n3",
      node == "n3" and abs(drop - 0.30) < 1e-6 and abs(pct - 30.0) < 0.1,
      f"({drop} V, {pct}%, {node})")

# [2] linear scaling
log2 = grid(load="0.2")
drop2, _, _ = worst_drop(log2)
check("[2] IR-drop scales linearly with load (2x -> 2x)",
      drop2 is not None and abs(drop2 - 2 * drop) < 1e-6,
      f"({drop} -> {drop2} V)")

# [3] current density exact + narrow-wire-is-worst physics
# Rw3: I=0.1, w=0.5u, thick=0.5u -> J = 0.1/(0.5e-6*0.5e-6) = 4e11
j_ok = (rows and abs(rows["rw3"]["j"] - 4e11) / 4e11 < 1e-4
        and abs(rows["rw1"]["j"] - 3e11) / 3e11 < 1e-4)
density_physics = (jseg == "rw3"                          # worst density = narrow wire
                   and rows["rw1"]["i"] > rows["rw3"]["i"]  # yet rw1 carries MORE current
                   and rows["rw1"]["j"] < rows["rw3"]["j"]) # but LESS density
check("[3] J=I/(w*thick) exact; worst density is the narrow low-current wire",
      j_ok and density_physics,
      f"(rw1: I={rows['rw1']['i']} J={rows['rw1']['j']:.2g}; rw3: I={rows['rw3']['i']} J={rows['rw3']['j']:.2g})")

# [4] Black's-equation MTTF scaling: MTTF ~ J^-n, n=2
# MTTF(rw1)/MTTF(rw3) should equal (J_rw3/J_rw1)^2
ratio = rows["rw1"]["mttf"] / rows["rw3"]["mttf"]
expect = (rows["rw3"]["j"] / rows["rw1"]["j"]) ** 2
check("[4] Black's-equation MTTF ratio = (J2/J1)^n",
      abs(ratio - expect) / expect < 1e-3,
      f"({ratio:.4f} vs {expect:.4f})")

# [5] violation count: Jmax=3.5e11 sits between Rw1 (3e11) and Rw2/Rw3 (4e11)
m = re.search(r"(\d+)\s+segments? over Jmax", log)
nfail = int(m.group(1)) if m else -1
check("[5] exactly the 2 narrow segments exceed Jmax (Rw1 passes)",
      nfail == 2 and rows["rw1"]["status"] == "ok"
      and rows["rw2"]["status"] == "FAIL" and rows["rw3"]["status"] == "FAIL",
      f"({nfail} fail)")

# [6] rail auto-detect == explicit rail
loge = grid(emir_args="rail 1.0 thick 0.5u jmax 3.5e11")
drope, pcte, nodee = worst_drop(loge)
check("[6] rail auto-detect equals explicit rail=1.0",
      nodee == node and abs(drope - drop) < 1e-9,
      f"(auto {drop} vs explicit {drope})")

# [7] OSDI load sinking current at a tap
logo = grid(loads_osdi=True)
dropo, _, nodeo = worst_drop(logo)
rowso = em_rows(logo)
# n3 draws V(n3)/7 A through the OSDI device; grid still solves + EM computed
check("[7] OSDI (Verilog-A) current load handled like a source",
      nodeo == "n3" and dropo is not None and dropo > 0
      and "rw3" in rowso and rowso["rw3"]["j"] > 0,
      f"(worst drop {dropo} V at {nodeo})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
