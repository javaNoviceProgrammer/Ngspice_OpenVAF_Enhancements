#!/usr/bin/env python3
"""verify_sweepbus.py -- Enhancement-267: the `sweep` command records bus/array
nodes under their natural names, and `-output` accepts a bus range.

A node may be named `ph[0]` (an array/bus node, Enhancement-221). When `sweep`
recorded such an output it built the result-vector name by mapping every non
-alphanumeric character to '_', so `ph[0]` became `ph_0_` -- the sweep plot showed
`ph_0_`, `ph_1_`, ... instead of `ph[0]`, `ph[1]`, .... The name sanitization is
now applied only to the appended `_<knob>_<value>` segments (which carry a float),
leaving the user's base name -- brackets and all -- intact. Separately, a bare
`-output` token that is a bus range `ph[0:3]` is expanded into one output per
index (`ph[0]`, `ph[1]`, `ph[2]`, `ph[3]`), matching the netlist bus expansion.

Checks (a four-tap bus divider, ph[0..3] = rl_k/(rt+rl_k)):
  [1] `-output ph[0:3]` records four vectors named ph[0]..ph[3] (range expanded).
  [2] the mangled names ph_0_.. are GONE from the sweep plot.
  [3] the recorded values are the correct divider ratios.
  [4] a plain (non-bus) `-output v(out)` is unaffected.

Solver-agnostic (names/values are solver-independent); drives ngspice directly.
Exit 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run_deck(text):
    path = os.path.join(tempfile.gettempdir(), "sweepbus_in.cir")
    with open(path, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", path],
                           capture_output=True, text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


DIVIDER = (
    "* bus divider (first line is the SPICE title)\n"   # title line: SPICE ignores line 1
    "r0 in ph[0] {rt}\nrl0 ph[0] 0 1k\n"
    "r1 in ph[1] {rt}\nrl1 ph[1] 0 2k\n"
    "r2 in ph[2] {rt}\nrl2 ph[2] 0 3k\n"
    "r3 in ph[3] {rt}\nrl3 ph[3] 0 4k\n"
    "v1 in 0 1\n"
    ".param rt=1k\n")

print("Enhancement-267: sweep records bus/array nodes under their natural names")

# [1]+[2]: -output ph[0:3] range-expands to ph[0]..ph[3]; ph_0_.. must be absent.
out = run_deck(DIVIDER + ".control\nsweep rt 1k 3k 1k -output ph[0:3]\ndisplay\n.endc\n.end\n")
have_bracket = sum(1 for k in range(4) if re.search(rf"\bph\[{k}\]\s*:", out))
have_mangled = any(re.search(rf"\bph_{k}_\b", out) for k in range(4))
check("[1] -output ph[0:3] records ph[0]..ph[3] (range expanded, natural names)",
      have_bracket == 4, f"{have_bracket}/4 bracketed names")
check("[2] mangled ph_0_ / ph_1_ names are gone", not have_mangled,
      "found ph_N_" if have_mangled else "none")

# [3]: values are the correct divider ratios rl_k/(rt+rl_k) at rt=1k
#      ph[0]=1k/2k=0.5, ph[1]=2k/3k=0.667, ph[2]=3k/4k=0.75, ph[3]=4k/5k=0.8
out = run_deck(DIVIDER + ".control\nsweep rt 1k 3k 1k -output ph[0:3]\n"
                         "print ph[0] ph[1] ph[2] ph[3]\n.endc\n.end\n")
row0 = next((ln for ln in out.splitlines() if re.match(r"\s*0\s", ln)), "")
vals = [float(x) for x in re.findall(r"[-+]?\d\.\d+e[-+]\d+", row0)]
expect = [0.5, 2/3, 0.75, 0.8]
ok3 = len(vals) >= 4 and all(abs(vals[i] - expect[i]) < 1e-3 for i in range(4))
check("[3] recorded values are the correct divider ratios",
      ok3, f"got {[round(v,4) for v in vals[:4]]} want {[round(e,4) for e in expect]}")

# [4]: a plain node output is unaffected (regression guard).
out = run_deck("* plain divider (title)\nr1 in out 1k\nr2 out 0 1k\nv1 in 0 1\n"
               ".control\nsweep r1 1k 3k 1k -output vo=v(out)\ndisplay\n.endc\n.end\n")
check("[4] plain -output vo=v(out) still recorded normally",
      re.search(r"\bvo\s*:", out) is not None, "vo present" if "vo" in out else "vo missing")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
