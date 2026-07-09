#!/usr/bin/env python3
"""
verify_filemacro.py -- verifies Enhancement-85 (F4): the LRM's predefined
`__FILE__/`__LINE__ macros, end-to-end through the committed openvaf-r +
ngspice.

`srcloc.va` strobes its own location once directly and once through a
`define body. Checks:
  [1] the model compiles (the macros used to be "macro not declared" errors)
  [2] `__FILE__ expands to the basename (machine-portable provenance)
  [3] `__LINE__ at the direct use reports that exact line
  [4] `__LINE__ inside a `define body reports the DEFINITION site
      (textual pre-pass semantics, documented)
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

src = open(os.path.join(HERE, "srcloc.va")).read().splitlines()
direct_line = next(i for i, l in enumerate(src, 1) if '"direct' in l)
define_line = next(i for i, l in enumerate(src, 1) if l.startswith("`define WHERE"))

r = subprocess.run([OPENVAF, "srcloc.va"], capture_output=True, text=True, cwd=HERE)
check("srcloc.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:100])

r = subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
m_direct = re.search(r"direct (\S+):(\d+)", log)
m_macro = re.search(r"macro-site (\S+):(\d+)", log)
check("direct strobe printed", m_direct is not None)
check("`__FILE__ is the basename", m_direct and m_direct.group(1) == "srcloc.va",
      m_direct.group(1) if m_direct else "-")
check(f"direct `__LINE__ == {direct_line}", m_direct and int(m_direct.group(2)) == direct_line,
      m_direct.group(2) if m_direct else "-")
check(f"`define-body `__LINE__ == {define_line} (definition site)",
      m_macro and int(m_macro.group(2)) == define_line, m_macro.group(2) if m_macro else "-")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
