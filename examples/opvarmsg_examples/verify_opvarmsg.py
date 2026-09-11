#!/usr/bin/env python3
"""Enhancement-601: an operating-point quantity is named as one, and an integer
or string out of range shows its value.

D3 of the 2026-09-10 integration hunt: reading an operating-point variable
through the model name answered with E-560's instance-PARAMETER message --
"declared (* type="instance" *), or resolved per instance because its default
reads an instance parameter, lint L028" -- for something that is not a
parameter at all; a write got "has no parameter" or "no such parameter" for
a name that plainly exists. The read-only entries of the instance table (an
opvar, a terminal current, a built-in's `i`) are named as what they are now,
on the model and on the instance, read and write.

D4: the range refusal showed the value for a real parameter and omitted it
for an integer -- where a deck value of 0.4, rounded to 0, is the whole
question -- and for a string. All three show it now. The second half of D4,
a duplicate and an alias conflict on one line getting the generic "out of
range or the wrong type", was closed by Enhancement-597 and is pinned here.

Checks:
  [1] read an opvar / a terminal current through the model: the quantity
      message; a real instance parameter still gets the instance-parameter one
  [2] write an opvar through the model (the accessor form and altermod) and
      through the instance (the accessor form and `alter n1 ..`): read-only;
      a built-in's read-only `i` the same; an unknown name still "no such
      parameter"
  [3] integer out of range (0.4 -> 0 against [1:3]): the value shown;
      string outside its set: the value shown; real unchanged
  [4] `w=2 w=3 width=4`: the duplicate warning then the alias error
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
WORK = tempfile.mkdtemp(prefix="opvarmsg_")
N1, KM, R1 = "@" + "n1", "@" + "km", "@" + "r1"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "om.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule om(p, n);\ninout p, n; electrical p, n;\n'
            '(* type="instance" *) parameter real area = 1 from (0:inf);\n'
            '(* type="instance" *) parameter real w = 1 from (0:inf);\naliasparam width = w;\n'
            'parameter integer k = 1 from [1:3];\nparameter real x = 1 from (0:10] exclude 5;\n'
            'parameter string kind = "poly" from {"poly", "metal"};\n'
            '(* desc="k as real" *) real kk;\n'
            'analog begin\n  kk = k;\n  I(p,n) <+ V(p,n)*area*w/1k;\nend\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "om.va"), "-o", os.path.join(WORK, "om.osdi")], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(inst, card, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* opvarmsg {tag}\n.control\npre_osdi om.osdi\n.endc\nv1 a 0 1\n{inst}\nr1 a 0 1k\n{card}\n.control\nop\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


QTY = "is an operating-point quantity of the instances of model 'km' -- a value each instance computes (an operating-point variable, or a terminal current), not a parameter -- so the model has none"
PARAM = "is an INSTANCE parameter of model 'km' (declared (* type=\"instance\" *)"

print("Enhancement-601: opvar messages, and the value in an integer or string refusal\n")

# ------------------------------------------------------------- [1] ---
out = run("n1 a 0 km", ".model km om", f"print {KM}[kk]\nprint {KM}[i_p]\nprint {KM}[area]", "t1")
check("[1] an opvar read through the model: named as an operating-point quantity, not a parameter",
      f"'kk' {QTY}" in out and "type=\"instance\"" not in out.split("'kk'")[1].split("\n")[0], out[-400:])
check("[1] a terminal current through the model: the same", f"'i_p' {QTY}" in out, out[-300:])
check("[1] a real instance parameter through the model: still the instance-parameter message",
      f"'area' {PARAM}" in out, out[-300:])

# ------------------------------------------------------------- [2] ---
out = run("n1 a 0 km", ".model km om", f"alter {KM}[kk]=1\naltermod km kk=1\nalter {N1}[kk]=1\nalter n1 kk=2\nalter {R1}[i]=1\nalter {N1}[nosuch]=1", "t2")
check("[2] a write through the model (the accessor form and altermod): read-only, on the model or on an instance",
      out.count("'kk' is an operating-point quantity of the instances of model 'km' -- a value each instance computes, read-only -- so nothing can set it, on the model or on an instance") == 2, out[-500:])
check("[2] a write through the instance (the accessor form and alter n1 ..): read-only",
      out.count("'kk' is an operating-point quantity of n1 -- a value the instance computes (an operating-point variable, or a terminal current), read-only -- so nothing can set it") == 2, out[-500:])
check("[2] a built-in's read-only `i` gets the same; an unknown name is still 'no such parameter'",
      "'i' is an operating-point quantity of r1" in out and "Error: no such parameter nosuch." in out, out[-300:])

# ------------------------------------------------------------- [3] ---
out = run("n1 a 0 km", ".model km om k=0.4", "print v(a)", "t3")
check("[3] an integer out of range shows the (rounded) value: 'value 0; range from [1:3]'",
      "Parameter k of 'km' is out of bounds (value 0; range from [1:3])!" in out and "rounded to the nearest integer" in out, out[-300:])
out = run("n1 a 0 km", '.model km om kind="oxide"', "print v(a)", "t3b")
check("[3] a string outside its set shows the value: 'value \"oxide\"'",
      re.search(r"Parameter kind of 'km' is out of bounds \(value \"oxide\"; range from \{", out) is not None, out[-300:])
out = run("n1 a 0 km", ".model km om x=5", "print v(a)", "t3c")
check("[3] a real out of range is unchanged: 'value 5; range from (0:10] exclude {5}'",
      "Parameter x of 'km' is out of bounds (value 5; range from (0:10] exclude {5})!" in out, out[-300:])

# ------------------------------------------------------------- [4] ---
out = run("n1 a 0 km w=2 w=3 width=4", ".model km om", "print v(a)", "t4")
check("[4] `w=2 w=3 width=4`: the duplicate warning, then the alias error, not the generic refusal",
      "parameter 'w' is set more than once on this line" in out
      and "'w' and 'width' are the same parameter (aliasparam) and both are set on this line" in out
      and "out of range or the wrong type" not in out, out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
