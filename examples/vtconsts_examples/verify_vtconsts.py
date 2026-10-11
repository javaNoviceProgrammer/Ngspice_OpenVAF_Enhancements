#!/usr/bin/env python3
"""verify_vtconsts.py -- Enhancement-862: $vt uses the model's own P_K and P_Q.

F7 of the third robustness campaign of 2026-10-10.

openvaf-r's $vt took the 2019 exact SI values whatever the model included, and
its comment said the shipped constants.vams defaulted `P_K and `P_Q to the same
set. The default is NIST1998 (E-519 kept it, as the 2023 LRM asks), so inside
one model `$vt(T)` sat 1.05e-6 below `P_K*T/`P_Q. $vt now uses the model's
`P_K and `P_Q when it defines both -- the header's default, its NIST2018 branch
or the model's own -- computed in the order `P_K*T/`P_Q evaluates in, so the
two agree to the bit. A model that names no constants keeps the 2019 values.

  [1] the default header: $vt(300.15) is `P_K*300.15/`P_Q to the bit (1.05e-6
      apart on E-861)
  [2] (control) ... with PHYSICAL_CONSTANTS_NIST2018: the same, at the 2019 values
  [3] $vt without an argument and `P_K*$temperature/`P_Q, at 27 C and 85 C
  [4] a model's own P_K and P_Q, ngspice's CODATA 2014 pair: $vt is ngspice's
      boltz*T/echarge
  [5] (control) no constants named: $vt is the 2019 SI kT/q, as before

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="vtconsts_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def model(name, head, body):
    va = os.path.join(WORK, name + ".va")
    with open(va, "w") as f:
        f.write('`include "disciplines.vams"\n%s\nmodule %s(a, b);\n    inout a, b; electrical a, b;\n'
                '    analog begin\n%s\n    end\nendmodule\n' % (head, name, body))
    osdi = os.path.join(WORK, name + ".osdi")
    p = subprocess.run([OPENVAF, va, "-o", osdi], cwd=WORK, capture_output=True, text=True, timeout=300)
    return osdi if os.path.exists(osdi) else None, p.stdout + p.stderr


def run(name, osdi, control):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\nn1 a b %s\n.model %s %s\n.control\npre_osdi %s\nset numdgt=17\n%s\n.endc\n.end\n"
                % (name, name, name, name, osdi, control))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    out = p.stdout + p.stderr
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"^(\S+) = (\S+)$", out, re.M)
            if re.match(r"^[-+0-9.]", m.group(2))}


PAIR = "        V(a) <+ $vt(300.15);\n        V(b) <+ `P_K * 300.15 / `P_Q;"

# [1]
osdi, log = model("vtdef", '`include "constants.vams"', PAIR)
got = run("vtdef", osdi, "op\nprint v(a) v(b)") if osdi else {}
check("[1] the default header: $vt(300.15) is `P_K*300.15/`P_Q to the bit",
      got.get("v(a)") is not None and got.get("v(a)") == got.get("v(b)"),
      "%r vs %r" % (got.get("v(a)"), got.get("v(b)")) if osdi else log[-200:])

# [2]
osdi, log = model("vt18", '`define PHYSICAL_CONSTANTS_NIST2018\n`include "constants.vams"', PAIR)
got = run("vt18", osdi, "op\nprint v(a) v(b)") if osdi else {}
want = 1.380649e-23 * 300.15 / 1.602176634e-19
check("[2] (control) with PHYSICAL_CONSTANTS_NIST2018: the same, at the 2019 values",
      got.get("v(a)") == got.get("v(b)") == want, "%r %r" % (got.get("v(a)"), got.get("v(b)")))

# [3]
osdi, log = model("vttemp", '`include "constants.vams"',
                  "        V(a) <+ $vt;\n        V(b) <+ `P_K * $temperature / `P_Q;")
ok = osdi is not None
vals = []
if osdi:
    for t in (27, 85):
        got = run("vttemp", osdi, "set temp = %d\nop\nprint v(a) v(b)" % t)
        vals.append((got.get("v(a)"), got.get("v(b)")))
        ok = ok and got.get("v(a)") is not None and got.get("v(a)") == got.get("v(b)")
check("[3] $vt without an argument and `P_K*$temperature/`P_Q agree at 27 C and 85 C", ok, "%r" % vals)

# [4]
osdi, log = model("vtng", "`define P_K 1.38064852e-23\n`define P_Q 1.6021766208e-19",
                  "        V(a) <+ $vt(300.15);\n        V(b) <+ 0;")
got = run("vtng", osdi, "op\nlet kq = boltz * 300.15 / echarge\nprint v(a) kq") if osdi else {}
check("[4] a model's own P_K and P_Q (ngspice's CODATA 2014 pair): $vt is ngspice's boltz*T/echarge",
      got.get("v(a)") is not None and got.get("v(a)") == got.get("kq"), "%r vs %r" % (got.get("v(a)"), got.get("kq")))

# [5]
osdi, log = model("vtnone", "", "        V(a) <+ $vt(300.15);\n        V(b) <+ 0;")
got = run("vtnone", osdi, "op\nprint v(a)") if osdi else {}
want = (1.380649e-23 / 1.602176634e-19) * 300.15
check("[5] (control) no constants named: $vt is the 2019 SI kT/q, as before",
      got.get("v(a)") == want, "%r vs %r" % (got.get("v(a)"), want))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
