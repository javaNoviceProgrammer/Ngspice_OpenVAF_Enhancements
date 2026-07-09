#!/usr/bin/env python3
"""
verify_pyplotexport.py -- verifies Enhancement-99 (pyplot vector export formats
+ figure size), through the committed ngspice.

`set pyplot_terminal=svg|pdf` renders the plot headless (matplotlib Agg) to
<file>.svg / <file>.pdf, alongside the png format from Enhancement-94.
`set pyplot_figsize="W,H"` sets the figure size in inches (quote the value so
ngspice keeps the comma). Both are honoured by the multi-panel path too.

  [1] pyplot_terminal=svg writes a valid <file>.svg (XML/SVG)
  [2] pyplot_terminal=pdf writes a valid <file>.pdf (%PDF magic)
  [3] pyplot_terminal=png still writes a valid <file>.png (unchanged)
  [4] pyplot_figsize="8,3" -> figsize=(8, 3) in the subplots() call
  [5] no pyplot_figsize -> subplots() without a figsize argument
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def magic(name, head):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p) or os.path.getsize(p) < 1000:
        return False
    with open(p, "rb") as f:
        return f.read(len(head)) == head

def pyfile(name):
    p = os.path.join(HERE, name)
    return open(p).read() if os.path.isfile(p) else ""

ARTIFACTS = []
for base in ("expsvg", "exppdf", "exppng"):
    for ext in (".py", ".data", ".svg", ".pdf", ".png"):
        ARTIFACTS.append(base + ext)
for a in ARTIFACTS + ["deck.sp"]:
    p = os.path.join(HERE, a)
    if os.path.exists(p):
        os.remove(p)

deck = """* pyplot export-format demo (Enhancement-99)
V1 in 0 SIN(0 1 1k)
R1 in out 1k
C1 out 0 100n
.tran 5u 2m
.control
run
set pyplot_terminal=svg
set pyplot_figsize="8,3"
pyplot expsvg v(in) v(out)
set pyplot_terminal=pdf
pyplot exppdf v(in) v(out)
set pyplot_terminal=png
unset pyplot_figsize
pyplot exppng v(in) v(out)
.endc
.end
"""
with open(os.path.join(HERE, "deck.sp"), "w") as f:
    f.write(deck)
subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)

check("pyplot_terminal=svg writes a valid SVG",
      magic("expsvg.svg", b"<?xml"))
check("pyplot_terminal=pdf writes a valid PDF",
      magic("exppdf.pdf", b"%PDF"))
check("pyplot_terminal=png still writes a valid PNG",
      magic("exppng.png", b"\x89PNG\r\n\x1a\n"))
check("pyplot_figsize=\"8,3\" -> figsize=(8, 3) in subplots()",
      "figsize=(8, 3)" in pyfile("expsvg.py"))
check("no pyplot_figsize -> subplots() without figsize",
      "figsize=(" not in pyfile("exppng.py"))

for a in ARTIFACTS + ["deck.sp"]:
    p = os.path.join(HERE, a)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
