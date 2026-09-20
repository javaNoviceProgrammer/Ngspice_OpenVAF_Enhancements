#!/usr/bin/env python3
"""
verify_opvar.py -- verifies Enhancement-69: operating-point-variable
(opvar) access end-to-end through the committed openvaf-r + ngspice.

Verilog-A module variables carrying a (* desc="..." *) attribute are
exposed as OSDI operating-point variables. The audit probed every access
path and found the surface FULLY WORKING -- a validation deliverable
(E-57/E-60/E-66 precedent, no source changes):

  * `.op` access via `print @inst[var]` -- real AND integer opvars exact;
    a variable WITHOUT a desc attribute is correctly not exposed (clean
    "no such parameter" error, no crash);
  * per-point recording via `.save @inst[var]` in `.tran` (both real and
    integer opvars -- the E-32 outitf fix pinned at last), `.dc` sweeps,
    and `.ac` (op-value per frequency point);
  * `.meas` works on opvar vectors: MAX/MIN/AVG and the WHEN/RISE form
    (verified against the analytic crossing time asin(0.5)/2pi);
  * two instances of one model keep distinct opvars (@n1 vs @n2);
  * string opvars display through `show <inst>`; the VECTOR path
    (`print @inst[strvar]`) is inherently numeric and fails with a clear
    message (pinned) rather than a crash.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

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


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.eE+-]+)", log)
    return float(m.group(1)) if m else float("nan")


out, ok = compile_va("opvar_demo.va")
ok2 = compile_va("opvar_str.va")[1]
if not (ok and ok2):
    check("models compile", False)
    raise SystemExit(1)

print("[1] .op access: real + integer opvars exact, undescribed vars hidden")
log = run_deck("_op.cir", """* opvar op
.control
pre_osdi opvar_demo.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm opvdemo
.op
.control
run
set numdgt=10
print @n1[ids] @n1[gm] @n1[region]
print @n1[hidden]
.endc
.end
""")
check("ids == 1 mA, gm == 1 mS exact",
      abs(grab(log, "@n1[ids]") - 1e-3) < 1e-12 and abs(grab(log, "@n1[gm]") - 1e-3) < 1e-12)
check("integer opvar region == 2", grab(log, "@n1[region]") == 2.0)
check("variable without (*desc*) is not exposed (clean error)",
      "no such parameter hidden" in log)

print("[2] .tran per-point recording + .meas on opvar vectors")
log = run_deck("_tr.cir", """* opvar tran
.control
pre_osdi opvar_demo.osdi
.endc
V1 a 0 SIN(0.5 0.5 1meg)
N1 a 0 mm
.model mm opvdemo
.save all @n1[ids] @n1[region]
.tran 2n 1u
.control
run
set numdgt=10
print length(@n1[ids]) length(@n1[region])
meas tran ipk MAX @n1[ids]
meas tran ravg AVG @n1[region]
.endc
.end
""")
n_r = grab(log, "length(@n1[ids])")
n_i = grab(log, "length(@n1[region])")
check("real + integer vectors recorded, equal length",
      n_r > 100 and n_r == n_i, f"({n_r:.0f} points)")
check("meas MAX == 1 mA (sine peak)", abs(grab(log, "ipk") - 1e-3) < 2e-8)
check("meas AVG(region) ~ 1.5 (half the period above 0.5)",
      abs(grab(log, "ravg") - 1.5) < 0.02)

print("[3] .dc sweep per-point (exact values, integer step at 0.75)")
log = run_deck("_dc.cir", """* opvar dc
.control
pre_osdi opvar_demo.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm opvdemo
.save @n1[ids] @n1[region]
.dc V1 0 1 0.25
.control
run
set numdgt=10
print @n1[ids] @n1[region]
.endc
.end
""")
rows = re.findall(r"^\d+\s+([0-9.eE+-]+)\s+(-?[0-9.eE+-]+)\s+(-?[0-9.eE+-]+)",
                  log, re.M)
ok3 = len(rows) == 5 and all(
    abs(float(i) - float(v) * 1e-3) < 1e-15 and float(rg) == (2.0 if float(v) > 0.5 else 1.0)
    for v, i, rg in rows)
check("5 sweep points: ids == V/1k exact, region flips above 0.5 V", ok3)

print("[4] .ac recording + distinct instances")
log = run_deck("_ac.cir", """* opvar ac + two instances
.control
pre_osdi opvar_demo.osdi
.endc
V1 a 0 DC 1 AC 1
N1 a 0 mm
.model mm opvdemo
N2 a 0 mm2
.model mm2 opvdemo r=2e3
.save @n1[ids] @n2[ids]
.ac lin 3 1k 3k
.control
run
set numdgt=10
print @n1[ids] @n2[ids]
.endc
.end
""")
rows = re.findall(r"^\d+\s+[0-9.eE+-]+\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", log, re.M)
check("3 AC points, @n1 == 1 mA and @n2 == 0.5 mA (distinct instances)",
      len(rows) == 3 and all(abs(float(a) - 1e-3) < 1e-12 and abs(float(b) - 5e-4) < 1e-12
                             for a, b in rows))

print("[5] .meas WHEN on an opvar (analytic crossing time)")
log = run_deck("_wh.cir", """* meas WHEN opvar
.control
pre_osdi opvar_demo.osdi
.endc
V1 a 0 SIN(0 1 1meg)
N1 a 0 mm
.model mm opvdemo
.save @n1[ids]
.tran 1n 1u
.control
run
set numdgt=10
meas tran tcross WHEN @n1[ids]=0.5m RISE=1
.endc
.end
""")
want = math.asin(0.5) / (2 * math.pi) * 1e-6   # 83.333 ns
got = grab(log, "tcross")
check("crossing at asin(0.5)/2pi us", abs(got - want) < 1e-10, f"({got:.6g} s)")

print("[6] string opvars: show works, vector path errs clearly")
log = run_deck("_st.cir", """* string opvar
.control
pre_osdi opvar_str.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm opvstr
.op
.control
run
show n1
print @n1[modename]
.endc
.end
""")
check("show displays the string value", "high" in log)
check("vector access gives the clear string-value error (no crash)",
      "can not handle string value" in log and "modename" in log)

# Enhancement-680 (hunt F10 of 2026-09-19): under `.option interp` the two
# interpolation routines of outitf.c read every "special" vector -- an opvar,
# an instance parameter -- through the IFvalue union's double, so an INTEGER
# opvar's four bytes landed under the previous vector's upper bytes: a
# constant 2 printed as 9.88e-324 and then as the previous column's value,
# on the file path (`.print tran` in batch) and the plot path (a control-block
# `print`) alike. They read it by its type now, as the other output paths do
# (Enhancement-32). A pulse 0.4 -> 0.6 V at 2 us: region 1 -> 2, ids = V/1k.
print("[7] .option interp: integer opvars on the file and the plot path (E-680)")


def table(log, ncol):
    """{time: [values...]} from a `.print`/`print` table with ncol data columns"""
    rows = {}
    for line in log.splitlines():
        parts = line.split()
        if len(parts) == ncol + 2 and parts[0].isdigit():
            try:
                rows[round(float(parts[1]) * 1e6, 3)] = [float(x) for x in parts[2:]]
            except ValueError:
                pass
    return rows


def interp_ok(rows):
    before = all(t in rows and rows[t][0] == 1.0 and abs(rows[t][1] - 0.4e-3) < 1e-12 for t in (0.0, 0.5, 1.0, 1.5))
    after = all(t in rows and rows[t][0] == 2.0 and abs(rows[t][1] - 0.6e-3) < 1e-12 for t in (2.5, 3.0, 3.5, 4.0))
    return before and after


INTERP_DECK = """* opvar interp {path}
.control
pre_osdi opvar_demo.osdi
.endc
V1 a 0 PULSE(0.4 0.6 2u 1n 1n 5u 10u)
N1 a 0 mm
.model mm opvdemo
.option interp
{cards}
.end
"""
log = run_deck("_ip.cir", INTERP_DECK.format(path="file", cards=".tran 0.5u 4u\n.print tran @n1[region] @n1[ids]"))
rows = table(log, 2)
check("file path (.print tran in batch): region reads 1 then 2 on the grid, ids beside it is V/1k, nothing misaligned",
      len(rows) >= 9 and interp_ok(rows), f"{[(t, rows[t]) for t in sorted(rows)][:3]}")
check("...and `.option interp` is a known option word: no 'unknown option' warning for a setting the run honours",
      "unknown option 'interp'" not in log and "Interpolated raw file data" in log, "")
# the plot path records an opvar per point only when it is saved; a bare
# `print @n1[x]` after the run is the one current value
log = run_deck("_ipp.cir", INTERP_DECK.format(path="plot", cards=".save @n1[region] @n1[ids]\n.control\ntran 0.5u 4u\nprint @n1[region] @n1[ids]\n.endc"))
rows = table(log, 2)
check("plot path (a control-block print of the saved vectors): the same",
      len(rows) >= 9 and interp_ok(rows), f"{[(t, rows[t]) for t in sorted(rows)][:3]}")
log = run_deck("_ipn.cir", INTERP_DECK.format(path="no interp", cards=".tran 0.5u 4u\n.print tran @n1[region] @n1[ids]").replace(".option interp\n", ""))
rows = table(log, 2)
check("(control) without interp the accepted points read the same integers",
      len(rows) > 9 and all(v[0] in (1.0, 2.0) for v in rows.values()), f"{len(rows)} rows")

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
