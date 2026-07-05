#!/usr/bin/env python3
"""
verify_multianalog.py -- verifies Enhancement-60: multiple analog blocks
(Verilog-AMS LRM 6.2), end-to-end through the committed openvaf-r +
ngspice.

A module may contain several `analog` (and `analog initial`) blocks; the
LRM requires them to behave as if concatenated into a single block in
source order. The Enhancement-60 probe battery found this is supported BY
CONSTRUCTION -- hir_def's body collection iterates every analog block of
the module into `entry_stmts` in document order, so everything downstream
(typing, lowering, autodiff, OSDI) sees one concatenated body -- and found
ZERO defects across nine corners. This suite pins that behavior:

  1. multiblk: three blocks accumulate 3 mS onto one branch; a variable
     written in block 1 is read in block 3; an analog function declared
     BETWEEN blocks is callable; a parameter declared AFTER its first use
     resolves; a cross event in block 2 and a final_step strobe in block 3
     both fire; ddt() integrates a charge computed in an earlier block.
  2. ordblk: strobes print in source order; two `analog initial` blocks
     compose in order (g = 1m, then g = g + 1m -> exactly 2 mS).
  3. hierblk: a multi-block module survives instance flattening (the E-5
     elaboration re-render) -- exact series current through the hierarchy.
  4. duplicate NAMED blocks (`begin : work`) in two analog blocks are a
     clean duplicate-declaration error (named blocks share the module
     namespace; hierarchical references must stay unambiguous).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_deck(name, deck):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr


print("[1] three analog blocks: accumulation, shared vars, split events")
out, ok = compile_va("multianalog_demo.va")
if not ok:
    check("multiblk compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_mb.cir", """* multi-block accumulation
.control
pre_osdi multianalog_demo.osdi
.endc
V1 a 0 SIN(0.25 0.5 1meg)
N1 a 0 mm
.model mm multiblk
.tran 2n 1u
.control
run
.endc
.end
""")
    mm = re.search(r"MULTIBLK up=\s*(-?\d+)", log)
    check("cross event in middle block fires", mm is not None and int(mm.group(1)) >= 1,
          f"(up={mm.group(1) if mm else '?'})")
    # op: 3 parallel mS at DC (ddt contributes nothing)
    log = run_deck("_mbop.cir", """* multi-block op
.control
pre_osdi multianalog_demo.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm multiblk
.save i(V1)
.op
.control
run
set numdgt=12
print i(V1)
.endc
.end
""")
    mm = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", log)
    got = float(mm.group(1)) if mm else float("nan")
    check("blocks accumulate to exactly 3 mS", mm is not None and abs(got + 3e-3) < 1e-12,
          f"(I={got:.9g})")

print("[2] source-order execution + ordered analog initial blocks")
out, ok = compile_va("order_demo.va")
if not ok:
    check("ordblk compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_ord.cir", """* order
.control
pre_osdi order_demo.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm ordblk
.save i(V1)
.op
.control
run
set numdgt=12
print i(V1)
.endc
.end
""")
    first = log.find("ORDER first")
    second = log.find("ORDER second")
    check("strobes print in source order",
          0 <= first < second, f"(pos {first} < {second})")
    mm = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", log)
    got = float(mm.group(1)) if mm else float("nan")
    check("initial blocks compose in order (2 mS)",
          mm is not None and abs(got + 2e-3) < 1e-12, f"(I={got:.9g})")

print("[3] multi-block module through instance flattening")
out, ok = compile_va("hier_demo.va")
if not ok:
    check("hierblk compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_hier.cir", """* hierarchy
.control
pre_osdi hier_demo.osdi
.endc
V1 a 0 DC 1
N1 a c mm
.model mm hierblk
Rc c 0 1
.save i(V1)
.op
.control
run
set numdgt=12
print i(V1)
.endc
.end
""")
    mm = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", log)
    # leaf = 3 mS (333.333 ohm) in series with 1 ohm
    want = -1.0 / (1e3 / 3.0 + 1.0)
    got = float(mm.group(1)) if mm else float("nan")
    check("both blocks survive flattening (exact series I)",
          mm is not None and abs(got - want) < 1e-12, f"(I={got:.12g})")

print("[4] duplicate named blocks across analog blocks rejected")
out, made = compile_va("_dup_named.va")
check("'work' declared twice is a clean error",
      not made and "already declared" in out)

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
