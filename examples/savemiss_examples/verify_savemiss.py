#!/usr/bin/env python3
"""Enhancement-600: one warning for a saved opvar, none for an inferred save;
and a missing model says why -- an unknown type, or bins that do not cover.

D1 of the 2026-09-10 integration hunt: a `save` of an OSDI opvar before any analysis
printed TWO warnings for the one item -- the device's own "is an
operating-point variable and no operating point has been computed" (from the
ask beginPlot makes to check the name) and E-418's "has no value yet ... It is
recorded per point once an analysis runs" -- and printed them for a save
`.option saveused` inferred and the author never wrote. The device is quiet
under the probe now, and an inferred save gets no warning at all (E-496's rule
for the unmatched-name warning).

D2: an `n` line whose `.model` card names a type nothing defines got "Unable
to find definition of model ma" -- the card is in the deck; pass 1 dropped it
for the unknown type, and its own "Unknown model type resa - ignored" is lost
whenever the card sits after the line that uses it, which is the usual layout
(and what a plain `osdi` in the control block, run after the netlist, leads
to). An instance outside every bin of a binned model got the same sentence.
Both say what happened now, with the type and the line, or the bins and the
instance's l and w.

Checks:
  [1] an explicit `save` of two opvars before a dc: exactly one warning per
      item, the device's line absent; the per-point recording unchanged
  [2] `.option saveused` inferring the same: no warning at all
  [3] a plain `print` of an opvar before any analysis still gets the device's line
  [4] the unknown type, card after the instance: the message names the card,
      its line, the type and `pre_osdi`; card before the instance: the same
      after pass 1's own warning
  [5] an OSDI bin miss and a BSIM4 bin miss: the bins and the instance's l/w
  [6] a bin hit and a genuinely missing model are unchanged
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
WORK = tempfile.mkdtemp(prefix="savemiss_")
N1 = "@" + "n1"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "tm.va"), "w") as f:
    f.write('`include "disciplines.vams"\n`include "constants.vams"\nmodule tm(p, n);\ninout p, n; electrical p, n;\n'
            'parameter real r0 = 1k from (0:inf);\nparameter real tc = 0.01;\n'
            '(* type="instance" *) parameter real w = 1 from (0:inf);\n(* type="instance" *) parameter real l = 1 from (0:inf);\n'
            '(* desc="device temperature K" *) real tk;\n(* desc="resistance" *) real rt;\n'
            'analog begin\n  tk = $temperature;\n  rt = r0 * (1 + tc*(tk - 300.15)) * l / w;\n  I(p,n) <+ V(p,n)/rt;\nend\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "tm.va"), "-o", os.path.join(WORK, "tm.osdi")], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(body, ctl, tag, pre="pre_osdi tm.osdi", opts=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* savemiss {tag}\n.control\n{pre}\n.endc\n{body}\n{opts}\n.control\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


DEV = f"Warning: {N1}[rt] is an operating-point variable and no operating point has been computed"
SAVE = f"Warning: save '{N1}[rt]': 'rt' has no value yet"

print("Enhancement-600: the saved-opvar warnings, and a missing model's reason\n")

# ------------------------------------------------------------- [1] ---
out = run("v1 a 0 1\nn1 a 0 tm\n.model tm tm", f"save {N1}[rt] {N1}[tk] all\ndc temp 27 127 50\nprint {N1}[rt]", "t1")
check("[1] an explicit save before the dc: one warning per item, the device's own line absent",
      out.count(SAVE) == 1 and out.count("'tk' has no value yet") == 1 and DEV not in out
      and out.count("operating-point variable") == 2, out[-400:])
rows = re.findall(r"(?m)^\d\s+\S+\s+(\S+)\s*$", out)
check("[1] ...and the per-point recording is unchanged (1000, 1500, 2000)",
      [float(x) for x in rows[:3]] == [1000.0, 1500.0, 2000.0], f"{rows}")

# ------------------------------------------------------------- [2] ---
out = run("v1 a 0 1\nn1 a 0 tm\nr1 a 0 1k\n.model tm tm", f"dc v1 0.5 1 0.5\nprint {N1}[rt] v(a)", "t2", opts=".option saveused")
check("[2] under .option saveused the inferred save draws no warning at all",
      "operating-point variable" not in out and "has no value yet" not in out and "1.00000000e+03" in out, out[-300:])

# ------------------------------------------------------------- [3] ---
out = run("v1 a 0 1\nn1 a 0 tm\n.model tm tm", f"print {N1}[rt]", "t3")
check("[3] a plain read before any analysis still says the operating point is not computed",
      DEV in out, out[-300:])

# ------------------------------------------------------------- [4] ---
out = run("v1 a 0 1\nn1 a 0 ma\n.model ma resa r=1500", "op\nprint v(a)", "t4", pre="set foo=1")
check("[4] unknown type, card after the instance: the card, its line, the type and pre_osdi are named",
      re.search(r'Unable to find definition of model ma: the \.model ma card \(line \d+\) names the type "resa", which no built-in device and no loaded OSDI or XSPICE library defines', out) is not None
      and "`pre_osdi <file.osdi>`" in out and "an `osdi` command without the prefix runs after it" in out, out[-500:])
out = run(".model ma resa r=1500\nv1 a 0 1\nn1 a 0 ma", "op\nprint v(a)", "t4b", pre="set foo=1")
check("[4] card before the instance: pass 1's own warning, then the same explanation",
      "Unknown model type resa - ignored" in out and 'names the type "resa"' in out, out[-500:])
out = run("v1 a 0 1\nn1 a 0 ma\n.model ma tm", "osdi tm.osdi\nop\nprint v(a)", "t4c", pre="set foo=1")
check("[4] the late `osdi` in the control block lands on the same explanation",
      re.search(r'the \.model ma card \(line \d+\) names the type "tm"', out) is not None and "too late for this card" in out, out[-500:])

# ------------------------------------------------------------- [5] ---
BINS = (".model nv.1 tm r0=100 lmin=0.1u lmax=1u wmin=0.1u wmax=10u\n"
        ".model nv.2 tm r0=200 lmin=1u lmax=10u wmin=0.1u wmax=10u")
out = run("v1 a 0 1\nn3 a 0 nv w=1u l=50u\n" + BINS, "op\nprint v(a)", "t5")
check("[5] an OSDI instance outside every bin: the bins and the instance's l and w are named",
      "Unable to find definition of model nv: 2 bins of it are in the deck (" in out
      and "nv.1 l=[1e-07:1e-06] w=[1e-07:1e-05]" in out and "nv.2 l=[1e-06:1e-05] w=[1e-07:1e-05]" in out
      and "none covers this instance's l=5e-05 w=1e-06" in out, out[-500:])
out = run("vd d 0 1\nvg g 0 1\nm1 d g 0 0 nch w=1u l=50u\n"
          ".model nch.1 nmos level=14 version=4.8.1 lmin=0.1u lmax=1u wmin=0.1u wmax=10u\n"
          ".model nch.2 nmos level=14 version=4.8.1 lmin=1u lmax=10u wmin=0.1u wmax=10u", "op\nprint v(d)", "t5b", pre="set foo=1")
check("[5] a BSIM4 instance outside every bin: the same (was 'could not find a valid modelname')",
      "Unable to find definition of model nch: 2 bins of it are in the deck" in out
      and "none covers this instance's l=5e-05 w=1e-06" in out and "could not find a valid modelname" not in out, out[-500:])

# ------------------------------------------------------------- [6] ---
out = run("v1 a 0 1\nn1 a 0 nv w=1u l=0.5u\nn2 a 0 nv w=1u l=5u\n" + BINS, "op\nprint i(v1)", "t6")
m = re.search(r"(?m)^i\(v1\) = (\S+)", out)
check("[6] a bin hit is unchanged: nv.1 (100 ohm * 0.5) and nv.2 (200 ohm * 5) in parallel, 21 mA",
      m is not None and abs(float(m.group(1)) + 21e-3) < 1e-9, out[-200:])
out = run("v1 a 0 1\nn1 a 0 nosuch", "op\nprint v(a)", "t6b", pre="set foo=1")
check("[6] a model that is nowhere in the deck: the plain sentence, as before",
      re.search(r"Unable to find definition of model nosuch\s*$", out, re.M) is not None, out[-300:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
