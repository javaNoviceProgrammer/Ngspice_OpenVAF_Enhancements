#!/usr/bin/env python3
"""
verify_qpss_sweep.py -- Enhancement-142: input-frequency sweep for the two-tone
small-signal analyses. `qpac`/`qpnoise`/`qpxf` gain a `dec|oct|lin` sweep of f_in that
builds an ngspice plot (magnitude vs frequency) -- conversion gain, noise figure and
image-rejection curves -- matching how .ac/.pnoise/.pxf sweep.

Each swept point reuses the same single-frequency solve, so the swept value at a given
f_in must equal the single-frequency result there.

Checks (numpy-free; the swept plot is current after the command, read with `print`):

  [1] qpac sweep    -- swept |(0,0) response| at f = single-frequency qpac (0,0)
  [2] qpxf sweep    -- swept xf at f = single-frequency qpxf (0,0)
  [3] qpnoise sweep -- swept onoise at f = single-frequency qpnoise onoise
  [4] frequency dependence -- a reactive circuit's response rolls off with f_in
  [5] point count  -- the sweep produces the expected number of points
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_qpsw"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


PUMP = ("I1 0 n SIN(0 0.1m 1.0G)\nI2 0 n SIN(0 0.1m 1.1G)\nR1 n 0 1k\nC1 n 0 2p\n"
        "Bnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\nIac 0 n AC 1\n")

def printed(out):
    """parse a `print frequency <vec>` table -> {freq: value}."""
    d = {}
    for m in re.finditer(r"^\s*\d+\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*$", out, re.M):
        d[float(m.group(1))] = float(m.group(2))
    return d

def qpac00(out, node="n"):
    blk = out.split("QPAC:")[-1] if "QPAC:" in out else ""   # skip the QPSS-HB spectrum
    m = re.search(rf"^\s+{node}\s+\(\s*0,\s*0\)\s+[-\d.eE+]+\s+([-\d.eE+]+)", blk, re.M)
    return float(m.group(1)) if m else None

def qpxf00(out):
    blk = out.split("QPXF:")[-1] if "QPXF:" in out else ""
    m = re.search(r"^\s+\(\s*0,\s*0\)\s+[-\d.eE+]+\s+([-\d.eE+]+)", blk, re.M)
    return float(m.group(1)) if m else None

def qpn_on(out):
    m = re.search(r"onoise density\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


print("Enhancement-142: two-tone small-signal frequency sweeps")

# [1] qpac: swept |(0,0) response| at 0.3 GHz == single-frequency qpac (0,0).
out = run("* qpac sweep\n" + PUMP +
          ".control\nqpss v(n) 1.0G 1.1G hb 3 3\nqpac 0.3G\n"
          "qpac lin 3 0.1G 0.5G\nprint frequency n\n.endc\n.end\n")
single = qpac00(out)
sw = printed(out)
sval = next((v for f, v in sw.items() if abs(f - 0.3e9) < 1e6), None)
check("qpac sweep value at 0.3G == single-frequency qpac (0,0)",
      single and sval and abs(single - sval) < 1e-6 * single, f"single={single} swept={sval}")

# [4] reactive roll-off: the response falls as f_in rises (RC low-pass).
lo = next((v for f, v in sw.items() if abs(f - 0.1e9) < 1e6), 0)
hi = next((v for f, v in sw.items() if abs(f - 0.5e9) < 1e6), 0)
check("reactive circuit: swept response rolls off with frequency", lo > hi > 0, f"0.1G={lo} 0.5G={hi}")

# [5] point count: lin 5 over a range -> 5 points.
out = run("* count\n" + PUMP + ".control\nqpss v(n) 1.0G 1.1G hb 3 3\n"
          "qpac lin 5 0.1G 0.5G\nprint frequency n\n.endc\n.end\n")
check("lin sweep produces the requested number of points", len(printed(out)) == 5, f"npts={len(printed(out))}")

# [2] qpxf: swept xf at 0.3G == single-frequency qpxf (0,0).
out = run("* qpxf sweep\n" + PUMP +
          ".control\nqpss v(n) 1.0G 1.1G hb 3 3\nqpxf n 0.3G\n"
          "qpxf n lin 3 0.1G 0.5G\nprint frequency xf\n.endc\n.end\n")
single = qpxf00(out)
sw = printed(out)
sval = next((v for f, v in sw.items() if abs(f - 0.3e9) < 1e6), None)
check("qpxf sweep xf at 0.3G == single-frequency qpxf (0,0)",
      single and sval and abs(single - sval) < 1e-6 * single, f"single={single} swept={sval}")

# [3] qpnoise: swept onoise at 0.3G == single-frequency qpnoise onoise.
out = run("* qpnoise sweep\n" + PUMP +
          ".control\nqpss v(n) 1.0G 1.1G hb 3 3\nqpnoise n 0.3G\n"
          "qpnoise n lin 3 0.1G 0.5G\nprint frequency onoise_spectrum\n.endc\n.end\n")
single = qpn_on(out)
sw = printed(out)
sval = next((v for f, v in sw.items() if abs(f - 0.3e9) < 1e6), None)
check("qpnoise sweep onoise at 0.3G == single-frequency qpnoise",
      single and sval and abs(single - sval) < 1e-6 * single, f"single={single} swept={sval}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
