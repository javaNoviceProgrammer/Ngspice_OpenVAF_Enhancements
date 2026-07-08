#!/usr/bin/env python3
"""
verify_stringcmp.py -- verifies Enhancement-106 (string relational comparison),
through the committed
openvaf-r + ngspice.

String `==`/`!=` already worked; the relational operators `<`, `<=`, `>`, `>=`
were rejected. They now perform a lexicographic comparison.

  [1] stringcmp_demo.va compiles (relational operators accept strings)
  [2] the comparisons are lexicographically correct: "abc"<"abd"=1, "abd">"abc"=1,
      "abc"<="abc"=1, "abc">="abd"=0, "abc"<"abc"=0, "abc"=="abc"=1
  [3] a string relational works as an `if` condition ("high"<"low" -> sel=1)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def opval(log, tag):
    m = re.search(rf"^{re.escape(tag)}\s*=\s*(-?[\d.eE+]+)", log, re.M)
    return float(m.group(1)) if m else None

for f in ("stringcmp_demo.osdi", "_sc.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

r = subprocess.run([OPENVAF, "stringcmp_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "stringcmp_demo.osdi"))
check("stringcmp_demo.va compiles (string relational operators)", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    deck = ("* string relational\nvp pp 0 1.0\nn1 pp 0 m\n.model m stringcmp_demo\n"
            ".control\npre_osdi stringcmp_demo.osdi\nop\n"
            + "\n".join(f"echo {t} = $&@n1[{t}]" for t in
                        ["lt_v","gt_v","le_v","ge_v","lteq_v","eq_v","sel"])
            + "\n.endc\n.end\n")
    with open(os.path.join(HERE, "_sc.sp"), "w") as f:
        f.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_sc.sp"], capture_output=True, text=True, cwd=HERE)
    log = out.stdout + out.stderr
    for tag, exp in [("lt_v", 1), ("gt_v", 1), ("le_v", 1), ("ge_v", 0), ("lteq_v", 0), ("eq_v", 1)]:
        check(f"{tag} == {exp}", opval(log, tag) == exp, f"got {opval(log, tag)}")
    check("string relational as if condition (\"high\"<\"low\" -> sel=1)",
          opval(log, "sel") == 1.0, f"got {opval(log, 'sel')}")

for f in ("stringcmp_demo.osdi", "_sc.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
