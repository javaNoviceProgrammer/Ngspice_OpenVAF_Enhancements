#!/usr/bin/env python3
"""Enhancement-591: `.option saveused` knows the accessor spellings of v().

The scanner collected `v()`, `i()` and `@dev[param]` only. `vm()`, `vp()`,
`vr()`, `vi()`, `vdb()` and `vg()` -- cpitf.c's aliases of v() -- name the
same vectors and were invisible: `print v(in) vdb(out)` after an `ac` saved
`in` alone, `.meas ac gain find vdb(out)` failed "no such vector", and a block
that used only `vm(out)` worked by accident because the scan found nothing and
the option stood down (F2 of the 2026-09-09 dig).

Checks:
  [1] print v(in) vdb(out): both print, `out` is kept
  [2] each of vm vp vr vi vdb vg beside a v(): kept; upper case too
  [3] a two-node form vdb(out,in): both nodes kept
  [4] .meas ac ... vdb(out) and .print ac vm(out) dot cards beside a block
      that prints v(in): the measure works, the table is filled
  [5] a block using only vm(out): now restricts -- `out` kept, `in` not
  [6] i(v1) beside vm(out); a plain v(a,b) still verbatim; `@n1[ir]` kept
  [7] the classic under-save still applies to a node nobody names
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
WORK = tempfile.mkdtemp(prefix="saveforms_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "ores.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule ores(p, n); inout p, n; electrical p, n;\n'
            'parameter real r = 1e6; (* desc="i" *) real ir;\n'
            'analog begin I(p,n) <+ V(p,n)/r; ir = I(p,n); end\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "ores.va"), "-o", os.path.join(WORK, "ores.osdi")], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)

DECK = """v1 in 0 dc 1 ac 1 sin(0.5 0.5 1k)
r1 in out 1k
c1 out 0 100n
n1 out 0 om
.model om ores r=1e6
"""


def run(ctl, tag, cards=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* saveforms {tag}\n.option saveused\n.control\npre_osdi ores.osdi\n.endc\n{DECK}{cards}\n.control\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def value(out, name):
    m = re.search(r"(?mi)^" + re.escape(name) + r" = (\S+)", out)
    return m.group(1) if m else None


print("Enhancement-591: saveused and the v() accessor spellings\n")

# ------------------------------------------------------------- [1] ---
out = run("ac lin 1 1k 1k\nprint v(in) vdb(out)", "t1")
check("[1] print v(in) vdb(out): the dB form is printed, `out` was kept",
      value(out, "vdb(out)") is not None and "not available" not in out, out[-200:])

# ------------------------------------------------------------- [2] ---
for fn in ("vm", "vp", "vr", "vi", "vdb", "vg", "VM", "VDB"):
    out = run(f"ac lin 1 1k 1k\nprint v(in) {fn}(out)", "t2_" + fn)
    check(f"[2] {fn}(out) beside v(in) keeps `out`",
          value(out, f"{fn}(out)") is not None and "not available" not in out, out[-160:])

# ------------------------------------------------------------- [3] ---
out = run("ac lin 1 1k 1k\nprint v(0) vdb(out,in)\nprint length(out) length(in)", "t3")
check("[3] vdb(out,in) keeps both nodes",
      value(out, "vdb(out,in)") is not None and value(out, "length(out)") == "1.000000e+00"
      and value(out, "length(in)") == "1.000000e+00", out[-200:])

# ------------------------------------------------------------- [4] ---
out = run("ac dec 2 100 10k\nprint v(in)", "t4", ".meas ac gain find vdb(out) at=1k\n.print ac vm(out)")
m = re.search(r"(?m)^gain\s+=\s+(\S+)", out)
check("[4] .meas ac gain find vdb(out) beside a block printing v(in) works",
      m is not None and abs(float(m.group(1)) - (-1.4513)) < 0.01 and "no such vector" not in out,
      (m.group(1) if m else out[-200:]))
check("[4] .print ac vm(out) fills its table",
      re.search(r"(?m)^2\s+1\.0+e\+03\s+8\.46\d+e-01", out) is not None, "")

# ------------------------------------------------------------- [5] ---
out = run("ac lin 1 1k 1k\nprint vm(out)\nprint length(in)", "t5")
check("[5] a block using only vm(out) now restricts: `out` kept, `in` not",
      value(out, "vm(out)") is not None and "vector in is not available" in out, out[-200:])

# ------------------------------------------------------------- [6] ---
out = run("ac lin 1 1k 1k\nprint vm(out)\necho \"R6a: $&i(v1) $&v(in,out)\"\ntran 10u 20u\nprint `@n1[ir]`[1]\nprint vm(out)[1]".replace("`", ""), "t6")
ma = re.search(r"(?m)^R6a: (\S+) (\S+)$", out)
mb = value(out, "`@n1[ir]`[1]".replace("`", ""))
check("[6] i(v1) and a plain v(in,out) beside vm(out) still work",
      ma is not None and "not available" not in out, ma.group(0) if ma else out[-300:])
check("[6] `@n1[ir]` beside vm(out) is saved per point in the transient",
      mb is not None and abs(float(mb) - 4.995e-7) < 1e-9, mb or out[-200:])

# ------------------------------------------------------------- [7] ---
out = run("ac lin 1 1k 1k\nprint vdb(out)\nprint length(in)", "t7")
check("[7] a node nobody names is still not saved (the option's purpose)",
      "vector in is not available" in out, out[-160:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
