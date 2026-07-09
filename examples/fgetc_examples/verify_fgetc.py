#!/usr/bin/env python3
"""
verify_fgetc.py -- verifies Enhancement-107 (the $fgetc file-input function),
through the committed
openvaf-r + ngspice.

$fgetc(fd) reads one character and returns its integer code, or -1 (EOF) at end
of file. It completes the file I/O family ($fgets/$fscanf/$ftell/...).

  [1] fgetc_demo.va compiles ($fgetc recognized)
  [2] the first two characters read back as their ASCII codes
  [3] a while loop over $fgetc counts and sums the remaining characters and
      terminates at the -1 EOF sentinel
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def opval(log, tag):
    m = re.search(rf"^{re.escape(tag)}\s*=\s*(-?[\d.eE+]+)", log, re.M)
    return float(m.group(1)) if m else None

# fixed input file so the expected values are deterministic
TEXT = "Hello, VA!\n"
with open(os.path.join(HERE, "fgetc_input.txt"), "w") as f:
    f.write(TEXT)

for f in ("fgetc_demo.osdi", "_gc.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

r = subprocess.run([OPENVAF, "fgetc_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "fgetc_demo.osdi"))
check("fgetc_demo.va compiles ($fgetc recognized)", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    deck = ("* fgetc\nvp pp 0 1.0\nn1 pp 0 m\n.model m fgetc_demo\n"
            ".control\npre_osdi fgetc_demo.osdi\nop\n"
            + "\n".join(f"echo {t} = $&@n1[{t}]" for t in
                        ["c1","c2","nchar","csum","last"])
            + "\n.endc\n.end\n")
    with open(os.path.join(HERE, "_gc.sp"), "w") as f:
        f.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_gc.sp"], capture_output=True, text=True, cwd=HERE)
    log = out.stdout + out.stderr
    check(f"1st char '{TEXT[0]}' == {ord(TEXT[0])}", opval(log, "c1") == ord(TEXT[0]),
          f"got {opval(log, 'c1')}")
    check(f"2nd char '{TEXT[1]}' == {ord(TEXT[1])}", opval(log, "c2") == ord(TEXT[1]),
          f"got {opval(log, 'c2')}")
    rest = TEXT[2:]
    check(f"remaining char count == {len(rest)}", opval(log, "nchar") == len(rest),
          f"got {opval(log, 'nchar')}")
    check(f"sum of remaining codes == {sum(map(ord, rest))}",
          opval(log, "csum") == sum(map(ord, rest)), f"got {opval(log, 'csum')}")
    check("EOF returns -1", opval(log, "last") == -1, f"got {opval(log, 'last')}")

for f in ("fgetc_demo.osdi", "_gc.sp", "fgetc_input.txt"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
