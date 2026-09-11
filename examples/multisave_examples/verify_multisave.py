#!/usr/bin/env python3
"""Enhancement-602: two dot cards naming one vector for different analyses keep
both analyses, and a batch run evaluates the .meas cards of every analysis.

N6 of the 2026-09-10 integration hunt. `.print dc v(a)` beside `.print tran
v(a)` in a batch deck: "no data saved for Transient analysis; analysis not
run". Each card registers `a` as a save restricted to its analysis, and
`settrace`'s dedup kept one save per node NAME, whatever the restriction, so
the transient had no save at all. A `.meas dc ... v(a)` beside a `.tran` lost
the transient the same way, and a `.meas tran` beside a `.dc` lost the dc.
The insert-time sibling of the ft_getSaves dedup Enhancement-594 fixed.

Behind it, two more of the batch flow: after a `run` with several analysis
cards, do_measure() was called for the LAST analysis only, so the other
analyses' `.meas` cards were skipped in silence; and the "Measurements for ..."
header was chosen by the first card's type before the card was matched, so it
named the wrong analysis or stood over nothing.

Checks (built-in devices; batch mode with dot cards):
  [1] .print dc v(a) + .print tran v(a), both orders: both analyses run
  [2] .meas dc beside .tran, .meas tran beside .dc: both analyses run and
      both measures evaluate, each under its own header
  [3] dc, tran and ac with a measure each: three headers, three values
  [4] what must stay deduplicated: .save v(a) then .print tran v(a); two
      .print tran cards on the same vector -- one save, the run as before
  [5] an OSDI device in the same shapes
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="multisave_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "rr.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule rr(p, n);\ninout p, n; electrical p, n;\nparameter real r = 1k from (0:inf);\n'
            'analog I(p,n) <+ V(p,n)/r;\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "rr.va"), "-o", os.path.join(WORK, "rr.osdi")], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)

CKT = "v1 a 0 dc 1 ac 1 sin(0 1 1k)\nr1 a b 1k\nr2 b 0 1k\n"


def run(cards, tag, ckt=CKT, pre=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* multisave {tag}\n{pre}{ckt}{cards}\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def rows(out):
    return [int(m) for m in re.findall(r"No\. of Data Rows : (\d+)", out)]


LOST = "no data saved for"
print("Enhancement-602: one save per name and analysis, and every analysis's measures\n")

# ------------------------------------------------------------- [1] ---
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.print dc v(a)\n.print tran v(a)", "t1")
check("[1] .print dc v(a) + .print tran v(a): both analyses run (3 and 108 rows), nothing lost",
      LOST not in out and sorted(rows(out)) == [3, 108], f"{rows(out)} {out[-200:]}")
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.print tran v(a)\n.print dc v(a)", "t1b")
check("[1] ...and in the other order", LOST not in out and sorted(rows(out)) == [3, 108], f"{rows(out)}")

# ------------------------------------------------------------- [2] ---
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.meas dc vmax max v(a)\n.print tran v(a)", "t2")
check("[2] .meas dc beside .tran: the transient runs, and the dc measure is evaluated under its header",
      LOST not in out and sorted(rows(out)) == [3, 108] and "Measurements for DC Analysis" in out
      and re.search(r"(?m)^vmax\s+=\s+1\.0+e\+00", out) is not None, out[-300:])
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.meas tran tmax max v(a)\n.print dc v(a)", "t2b")
check("[2] .meas tran beside .dc: the dc runs, and the transient measure is evaluated",
      LOST not in out and sorted(rows(out)) == [3, 108] and "Measurements for Transient Analysis" in out
      and re.search(r"(?m)^tmax\s+=\s+9\.99\d*e-01", out) is not None, out[-300:])
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.meas dc vmax max v(a)\n.meas tran tmax max v(a)", "t2c")
check("[2] both measures: both evaluated, each under its own header, no header over nothing",
      re.search(r"Measurements for DC Analysis\s*\n\s*\nvmax\s+=", out) is not None
      and re.search(r"Measurements for Transient Analysis\s*\n\s*\ntmax\s+=", out) is not None
      and out.count("Measurements for") == 2, out[-400:])

# ------------------------------------------------------------- [3] ---
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.ac lin 1 1k 1k\n.meas dc vmax max v(a)\n.meas tran tmax max v(a)\n.meas ac amax max vm(a)", "t3")
check("[3] dc, tran and ac with a measure each: three headers, three values",
      out.count("Measurements for") == 3 and all(re.search(rf"(?m)^{n}\s+=", out) for n in ("vmax", "tmax", "amax"))
      and LOST not in out, out[-500:])

# ------------------------------------------------------------- [4] ---
out = run(".save v(a)\n.tran 10u 1m\n.print tran v(a)", "t4")
check("[4] .save v(a) then .print tran v(a): one save, the run as before", LOST not in out and rows(out) == [108], f"{rows(out)}")
out = run(".tran 10u 1m\n.print tran v(a)\n.print tran v(a) v(b)", "t4b")
check("[4] two .print tran cards on one vector: the run as before, both tables (each paginated over 108 points)",
      LOST not in out and rows(out) == [108] and out.count("Index   time            v(a)            \n") >= 1 and "v(a)            v(b)" in out, f"{rows(out)}")

# ------------------------------------------------------------- [5] ---
OCKT = "v1 a 0 dc 1 ac 1 sin(0 1 1k)\nn1 a b om\nn2 b 0 om\n.model om rr r=1k\n"
out = run(".dc v1 0 1 0.5\n.tran 10u 1m\n.meas dc vmax max v(b)\n.meas tran tmax max v(b)\n.print dc v(b)\n.print tran v(b)", "t5", ckt=OCKT, pre=".control\npre_osdi rr.osdi\n.endc\n")
check("[5] the same with OSDI devices: both analyses, both measures",
      LOST not in out and sorted(rows(out)) == [3, 108] and re.search(r"(?m)^vmax\s+=\s+5\.0+e-01", out) is not None
      and re.search(r"(?m)^tmax\s+=\s+4\.99\d*e-01", out) is not None, out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
