#!/usr/bin/env python3
"""verify_measparam.py -- Enhancement-311: `param`/`expr` measurements in a .control block.

The `param` and `expr` measurement types are handled only by do_measure()'s second pass
(via nupa_eval), which the interactive/`.control` `meas` command bypasses -- it calls
get_measure2() directly, and get_measure2() has no param/expr case. So

    .meas tran pp param='a1-a2'      (dot-card)  worked,
    meas tran pp param='a1-a2'       (.control)  FAILED ("no such function as ...")

even though the same measurement is valid. Every form failed, down to a bare `param=a1`.

The fix routes a `param`/`expr` measurement in `com_meas` through the ordinary vector
expression evaluator: the prior results (a1, a2) are already single-valued ngspice
vectors, so `meas <an> <name> param=<expr>` is exactly `let <name> = (<expr>)`.

Working forms in a .control block: unquoted (param=a1-a2), quoted without internal spaces
(param='a1-a2'), and braces even WITH spaces (param={sqrt(a1*a1 + a2*a2)}). The single-quote
form with internal spaces (param='sqrt(a1*a1 + a2*a2)') is still broken -- but by the
.control shell's own quote pre-expansion, upstream of `meas`, not by this fix; use braces
for spaced expressions.

Oracle: a symmetric triangle (PWL) has max=+1, min=-1, so every expression over those has
an exact value.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control_meas, name):
    deck = f"""* control-block param/expr measurement
v1 a 0 dc 0 pwl(0 0 0.25m 1 0.5m 0 0.75m -1 1m 0)
r1 a 0 1k
.tran 1u 1m
.control
run
meas tran a1 max v(a)
meas tran a2 min v(a)
{control_meas}
.endc
.end
"""
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


def pp(out):
    m = re.search(r"^pp\s*=\s*([-\d.eE+]+)", out, re.M | re.I)
    return float(m.group(1)) if m else None


def close(control_meas, want, label, name):
    out = run(control_meas, name)
    got = pp(out)
    if got is None:
        check(label, False, "no value / measure failed")
        return
    rel = abs(got - want) / (abs(want) if abs(want) > 1e-12 else 1.0)
    check(label, rel <= 1e-4, f"got {got:.6g} want {want:.6g}")


print("Enhancement-311: param/expr measurements work in a .control block")

# a1 = max = 1, a2 = min = -1
close("meas tran pp param='a1-a2'", 2.0, "param='a1-a2' (quoted, no spaces)", "_1.cir")
close("meas tran pp param='a1 - a2'", 2.0, "param='a1 - a2' (quoted, spaces)", "_2.cir")
close("meas tran pp param=a1-a2", 2.0, "param=a1-a2 (unquoted single token)", "_3.cir")
close("meas tran pp param='(a1-a2)/2'", 1.0, "param='(a1-a2)/2' (parens)", "_4.cir")
close("meas tran pp expr='a1*a2'", -1.0, "expr='a1*a2' (expr type)", "_5.cir")
close("meas tran pp param={sqrt(a1*a1 + a2*a2)}", math.sqrt(2), "brace form with a function call + spaces", "_6.cir")
close("meas tran pp param='sqrt(a1*a1+a2*a2)'", math.sqrt(2), "quoted function call, no internal spaces", "_6b.cir")

# normal measurement types must be unaffected
out = run("meas tran pp max v(a)", "_7.cir")
close("meas tran pp max v(a)", 1.0, "normal 'max' still works (unchanged path)", "_8.cir")

for f in os.listdir(HERE):
    if f.startswith("_"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
