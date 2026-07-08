#!/usr/bin/env python3
"""
verify_sscanf.py -- verifies Enhancement-105 ($sscanf format-base handling),
through the committed
openvaf-r + ngspice.

The scanf runtime parsed every integer with strtol base 0 (base inferred from
the INPUT prefix), ignoring the format string -- so "%h"/"%o"/"%b" did not
work. Now the conversion character selects the base.

  [1] sscanf_demo.va compiles
  [2] base conversions parse correctly: %h ff->255, %o 17->15, %b 1010->10,
      %d 42->42 (each would be wrong under the old base-0 behavior)
  [3] repeated conversion (%h %h) and mixed int/real (%d %g) still work; the
      $sscanf return value counts the matched fields
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

for f in ("sscanf_demo.osdi", "_ss.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

r = subprocess.run([OPENVAF, "sscanf_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "sscanf_demo.osdi"))
check("sscanf_demo.va compiles", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    deck = ("* sscanf\nvp pp 0 1.0\nn1 pp 0 m\n.model m sscanf_demo\n"
            ".control\npre_osdi sscanf_demo.osdi\nop\n"
            + "\n".join(f"echo {t} = $&@n1[{t}]" for t in
                        ["hex_v","oct_v","bin_v","dec_v","two_a","two_b","mix_i","mix_r","nm"])
            + "\n.endc\n.end\n")
    with open(os.path.join(HERE, "_ss.sp"), "w") as f:
        f.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_ss.sp"], capture_output=True, text=True, cwd=HERE)
    log = out.stdout + out.stderr
    for tag, exp in [("hex_v", 255), ("oct_v", 15), ("bin_v", 10), ("dec_v", 42)]:
        check(f"{tag} == {exp} (format base honored)", opval(log, tag) == exp, f"got {opval(log, tag)}")
    check("repeated %h %h -> 160, 255",
          opval(log, "two_a") == 160 and opval(log, "two_b") == 255,
          f"a={opval(log,'two_a')} b={opval(log,'two_b')}")
    check("mixed %d %g -> 7, 8.5 with match count 2",
          opval(log, "mix_i") == 7 and abs(opval(log, "mix_r") - 8.5) < 1e-9 and opval(log, "nm") == 2,
          f"i={opval(log,'mix_i')} r={opval(log,'mix_r')} nm={opval(log,'nm')}")

for f in ("sscanf_demo.osdi", "_ss.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
