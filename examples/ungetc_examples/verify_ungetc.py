#!/usr/bin/env python3
"""
verify_ungetc.py -- verifies Enhancement-108 (the $ungetc file-input function),
through the committed
openvaf-r + ngspice.

$ungetc(c, fd) pushes character c back so the next $fgetc(fd) returns it (a
one-character peek/pushback), returning c on success. It complements $fgetc
(Enhancement-107).

  [1] ungetc_demo.va compiles ($ungetc recognized)
  [2] pushback works: after $ungetc(c), the next $fgetc returns c again, and
      $ungetc returns the pushed character
  [3] one-char look-ahead parses the leading integer and leaves the first
      non-digit in the stream (the classic $ungetc use)
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

# fixed input: leading integer 4271 then a non-digit ';'
TEXT = "4271;rest\n"
with open(os.path.join(HERE, "ungetc_input.txt"), "w") as f:
    f.write(TEXT)

for f in ("ungetc_demo.osdi", "_ug.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

r = subprocess.run([OPENVAF, "ungetc_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "ungetc_demo.osdi"))
check("ungetc_demo.va compiles ($ungetc recognized)", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    deck = ("* ungetc\nvp pp 0 1.0\nn1 pp 0 m\n.model m ungetc_demo\n"
            ".control\npre_osdi ungetc_demo.osdi\nop\n"
            + "\n".join(f"echo {t} = $&@n1[{t}]" for t in
                        ["first","ur","reread","value","stopch"])
            + "\n.endc\n.end\n")
    with open(os.path.join(HERE, "_ug.sp"), "w") as f:
        f.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_ug.sp"], capture_output=True, text=True, cwd=HERE)
    log = out.stdout + out.stderr
    first = ord(TEXT[0])
    check(f"first char == {first} ('{TEXT[0]}')", opval(log, "first") == first,
          f"got {opval(log, 'first')}")
    check(f"$ungetc returns the pushed char ({first})", opval(log, "ur") == first,
          f"got {opval(log, 'ur')}")
    check("re-read after $ungetc returns the same char", opval(log, "reread") == first,
          f"got {opval(log, 'reread')}")
    check("leading integer parsed == 4271", opval(log, "value") == 4271,
          f"got {opval(log, 'value')}")
    check("first non-digit left in stream is ';'", opval(log, "stopch") == ord(';'),
          f"got {opval(log, 'stopch')}")

for f in ("ungetc_demo.osdi", "_ug.sp", "ungetc_input.txt"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
