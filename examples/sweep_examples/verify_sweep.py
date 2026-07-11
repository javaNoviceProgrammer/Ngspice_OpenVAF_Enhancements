#!/usr/bin/env python3
"""
verify_sweep.py -- Enhancement-146: the universal `sweep` command and `.sweep` card.

`sweep` varies ANY circuit knob over a range and records outputs into a plot -- a
generalization of `.dc`, which can only step a source, resistor or device instance
parameter. `sweep` additionally handles model parameters (`@<model>[<p>]`, via
`altermod`) and symbolic `.param` values (via `alterparam` + `reset`), auto-detecting
which kind each knob is.

Each check sweeps a knob over a circuit with a KNOWN analytic response and confirms
the recorded curve:

  [1] instance/resistor: `sweep R1` over a divider == the built-in `.dc R1` (the
      generalization is faithful) and == the analytic R2/(R1+R2).
  [2] voltage source: `sweep V1` gives the linear v(out) = V1*R2/(R1+R2).
  [3] model parameter: `sweep @rmod[r]` (Verilog-A model `r`, via altermod).
  [4] symbolic `.param`: `sweep rtop`.
  [5] the same divider result from all three knob kinds -> auto-detection routes
      each to the right mechanism.
  [6] the `.sweep` CARD form == the `sweep` command form (and does not recurse on a
      `.param` re-source).
  [7] AC inner analysis with a named output: `sweep C1 ... -output gain=mag(v(out))`
      matches the analytic low-pass |H(1kHz)|.
  [8] transient inner analysis: settled node voltage vs a swept resistor.
  [9] sweep specs: `lin N`, `list`, and `start stop step` give the right points.
  [10] multiple `-output`s are all recorded.

It is a front-end command, independent of the linear solver, so it is checked once.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck):
    p = os.path.join(HERE, "_sw.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def table(out, ncol):
    """parse the numeric rows of a `print` table into a list of tuples."""
    rows = []
    for ln in out.splitlines():
        m = re.match(r"^\s*\d+\s+(.*)$", ln)
        if not m:
            continue
        nums = re.findall(r"[-+]?\d[\d.eE+-]*", m.group(1))
        if len(nums) >= ncol:
            rows.append(tuple(float(x) for x in nums[:ncol]))
    return rows


osdi = os.path.join(HERE, "resmod.osdi")
subprocess.run([OPENVAF, os.path.join(HERE, "resmod.va"), "-o", osdi],
               capture_output=True, text=True, timeout=120)

print("Enhancement-146: universal sweep command + .sweep card")

# [1] instance/resistor sweep == .dc == analytic
d_sweep = ("sweep resistor\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
           "sweep R1 1k 5k 1k -output vo=v(out)\nprint r1 vo\n.endc\n.end\n")
o1 = run(d_sweep)
rows1 = table(o1, 2)                    # (R1, v(out))
analytic = lambda R: 1000.0 / (R + 1000.0)
ok1 = len(rows1) == 5 and all(abs(v - analytic(r)) < 1e-6 for r, v in rows1)
check(f"instance sweep R1 == analytic R2/(R1+R2) ({len(rows1)} pts)", ok1,
      str(rows1))
# cross-check vs built-in .dc R1
d_dc = ("dc resistor\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
        "dc R1 1k 5k 1k\nprint v(out)\n.endc\n.end\n")
rows_dc = table(run(d_dc), 2)           # (R1, v(out))
ok1b = len(rows_dc) == 5 and all(abs(a[1] - b[1]) < 1e-9 for a, b in zip(rows1, rows_dc))
check("instance sweep matches built-in .dc R1 exactly", ok1b)

# [2] voltage-source sweep
d2 = ("sweep source\nV1 in 0 dc 1\nR1 in out 2k\nR2 out 0 1k\n.control\n"
      "sweep V1 0 4 1 -output vo=v(out)\nprint v1 vo\n.endc\n.end\n")
rows2 = table(run(d2), 2)
ok2 = len(rows2) == 5 and all(abs(v - vin * (1000.0 / 3000.0)) < 1e-6
                              for vin, v in rows2)
check(f"voltage-source sweep V1 -> linear v(out) ({len(rows2)} pts)", ok2, str(rows2))

# [3] model-parameter sweep (Verilog-A model r, via altermod)
d3 = ("sweep model param\nV1 in 0 dc 1\nN1 in out rmod\nR2 out 0 1k\n"
      ".model rmod resmod r=1k\n.control\n"
      f"pre_osdi {osdi}\n"
      "sweep @rmod[r] 1k 5k 1k -output vo=v(out)\nprint vo\n.endc\n.end\n")
o3 = run(d3)
rows3 = table(o3, 2)                    # (idx-scale?, vo) -> actually (r?, vo); print vo only -> 1 col + index
vals3 = [r[-1] for r in table(o3, 1)]
ok3 = ("model param" in o3 and len(vals3) == 5 and
       all(abs(v - analytic(1000.0 * (i + 1))) < 1e-6 for i, v in enumerate(vals3)))
check(f"model-param sweep @rmod[r] (altermod) -> analytic ({len(vals3)} pts)", ok3,
      str(vals3))

# [4] symbolic .param sweep
d4 = ("sweep dot param\n.param rtop=1k\nV1 in 0 dc 1\nR1 in out {rtop}\n"
      "R2 out 0 1k\n.control\n"
      "sweep rtop 1k 5k 1k -output vo=v(out)\nprint vo\n.endc\n.end\n")
o4 = run(d4)
vals4 = [r[-1] for r in table(o4, 1)]
ok4 = (".param" in o4 and len(vals4) == 5 and
       all(abs(v - analytic(1000.0 * (i + 1))) < 1e-6 for i, v in enumerate(vals4)))
check(f"symbolic .param sweep rtop (alterparam+reset) -> analytic ({len(vals4)} pts)",
      ok4, str(vals4))

# [5] auto-detection: the three kinds all report the right routing
ok5 = ("(instance/device)" in o1 and "(model param)" in o3 and "(.param)" in o4)
check("auto-detection routes instance / model / .param to the right mechanism", ok5)

# [6] the `.sweep` CARD form == the command form, and does not recurse
d6 = ("sweep card\n.param rtop=1k\nV1 in 0 dc 1\nR1 in out {rtop}\nR2 out 0 1k\n"
      ".sweep rtop 1k 5k 1k -output vo=v(out)\n.control\nprint vo\n.endc\n.end\n")
o6 = run(d6)
vals6 = [r[-1] for r in table(o6, 1)]
ok6 = ("overflow" not in o6.lower() and o6.count("sweep: rtop") <= 1 and
       len(vals6) == 5 and all(abs(a - b) < 1e-9 for a, b in zip(vals4, vals6)))
check("`.sweep` card == command form and does not recurse on the .param re-source",
      ok6, str(vals6))

# [7] AC inner analysis, named output, vs analytic low-pass
Cs = [100e-9, 200e-9, 300e-9, 400e-9]
Hana = [1.0 / math.sqrt(1 + (2 * math.pi * 1e3 * 1e3 * C) ** 2) for C in Cs]
d7 = ("sweep ac\nV1 in 0 ac 1\nR1 in out 1k\nC1 out 0 100n\n.control\n"
      "sweep C1 lin 4 100n 400n -analysis ac lin 1 1k 1k -output gain=mag(v(out))\n"
      "print gain\n.endc\n.end\n")
vals7 = [r[-1] for r in table(run(d7), 1)]
ok7 = len(vals7) == 4 and all(abs(v - h) < 1e-4 for v, h in zip(vals7, Hana))
check(f"AC sweep C1, named output gain -> analytic |H(1kHz)| ({len(vals7)} pts)",
      ok7, str(vals7))

# [8] transient inner analysis: settled node voltage vs swept resistor
d8 = ("sweep tran\nV1 in 0 dc 1\nR1 in mid 1k\nR2 mid 0 1k\nC1 mid 0 1u\n.control\n"
      "sweep R1 lin 3 1k 3k -analysis tran 10u 5m -output vs=v(mid)\n"
      "print vs\n.endc\n.end\n")
vals8 = [r[-1] for r in table(run(d8), 1)]
ok8 = len(vals8) == 3 and all(abs(v - analytic(1000.0 * (i + 1))) < 1e-3
                              for i, v in enumerate(vals8))
check(f"transient sweep R1 -> settled v(mid) ({len(vals8)} pts)", ok8, str(vals8))

# [9] sweep specs: lin N, list, start/stop/step give the right point counts
n_lin = len(table(run(d_sweep.replace("sweep R1 1k 5k 1k",
                                      "sweep R1 lin 7 1k 5k")), 2))
n_list = len(table(run(d_sweep.replace("sweep R1 1k 5k 1k",
                                       "sweep R1 list 1k 2k 4k 8k")), 2))
n_step = len(rows1)
check(f"sweep specs: lin 7 ->7, list(4) ->4, step(1k..5k) ->5 (got {n_lin},{n_list},{n_step})",
      n_lin == 7 and n_list == 4 and n_step == 5, f"{n_lin},{n_list},{n_step}")

# [10] multiple outputs recorded
d10 = ("sweep multi\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
       "sweep R1 1k 3k 1k -output vo=v(out) -output ii=i(v1)\nprint vo ii\n.endc\n.end\n")
rows10 = table(run(d10), 3)             # (R1?, vo, ii) -> print vo ii -> idx + 2 cols
rows10 = table(run(d10), 2)
ok10 = len(rows10) == 3 and all(abs(vo - analytic(1000.0 * (i + 1))) < 1e-6 and
                                abs(ii + 1.0 / (1000.0 * (i + 1) + 1000.0)) < 1e-9
                                for i, (vo, ii) in enumerate(rows10))
check("two -output vectors both recorded (v(out) and i(v1))", ok10, str(rows10))

if os.path.exists(osdi):
    os.remove(osdi)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
