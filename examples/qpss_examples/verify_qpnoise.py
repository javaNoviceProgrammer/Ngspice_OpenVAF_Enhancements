#!/usr/bin/env python3
"""
verify_qpnoise.py -- Enhancement-138: two-tone small-signal QPnoise.

`qpnoise <output_node> <f_in>` folds every device's noise through the ADJOINT of the
2-D conversion matrix around the QPSS operating point retained by a prior
`qpss <expr> <f1> <f2> hb`, summing the contribution of every sideband
f_in + k1*f1 + k2*f2 into the output noise at f_in -- the two-tone analogue of pnoise.

The anchor: with the pump driven to ~0 the conversion matrix is block-diagonal, so only
sideband (0,0) contributes and QPnoise reduces EXACTLY to ordinary `.noise`.

Checks (numpy-free, parsed from stdout):

  [1] reduce-to-noise    -- pump->0: QPnoise onoise == plain .noise onoise (exact)
  [2] thermal law        -- pump->0: onoise density = 4kTR of the 1k resistor
  [3] conversion active  -- with pump, the folded onoise differs from the no-pump value
  [4] inoise consistency -- inoise = onoise / gain^2
  [5] no op-point        -- qpnoise with no prior `qpss ... hb` errors cleanly
  [6] KLU vs Sparse      -- solver-independent (bit-identical)
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


def run(deck, name="_qpn"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def qpn(out):
    """parse QPnoise output -> dict(onoise, onoise_sqrt, inoise, gain2)."""
    d = {}
    m = re.search(r"onoise density\s*=\s*([-\d.eE+]+)\s*V\^2/Hz\s*\(([-\d.eE+]+)", out)
    if m:
        d["onoise"] = float(m.group(1)); d["onoise_sqrt"] = float(m.group(2))
    m = re.search(r"inoise density\s*=\s*([-\d.eE+]+)\s*\(gain\^2 =\s*([-\d.eE+]+)", out)
    if m:
        d["inoise"] = float(m.group(1)); d["gain2"] = float(m.group(2))
    return d


def deck(Apump, f_in="0.3G", opt="", K="3 3"):
    return (f"* qpnoise\n"
            f"I1 0 n SIN(0 {Apump} 1.0G)\nI2 0 n SIN(0 {Apump} 1.1G)\n"
            f"R1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\nIac 0 n AC 1\n{opt}"
            f".control\nqpss v(n) 1.0G 1.1G hb {K}\nqpnoise n {f_in}\n.endc\n.end\n")


print("Enhancement-138: two-tone small-signal QPnoise (quasi-periodic noise)")

# [1] reduce-to-noise: pump ~ 0 -> QPnoise onoise == plain .noise onoise at f_in.
qp0 = qpn(run(deck("1e-9")))
nref = run("* noise ref\nIac 0 n AC 1\nR1 n 0 1k\n.control\n"
           "noise v(n) Iac lin 1 0.3G 0.3G 1\nsetplot noise1\nprint onoise_spectrum\n.endc\n.end\n")
m = re.search(r"onoise_spectrum\s*=\s*([-\d.eE+]+)", nref)
noise_ref = float(m.group(1)) if m else None
qp_sqrt = qp0.get("onoise_sqrt")
check("reduce-to-noise: QPnoise onoise == plain .noise onoise (pump->0)",
      noise_ref and qp_sqrt and abs(qp_sqrt - noise_ref) < 1e-4 * noise_ref,
      f"qpnoise={qp_sqrt} noise={noise_ref}")

# [2] thermal law: onoise density = 4kTR of R1 (k=1.380649e-23, T=300.15 K default).
thermal = 4 * 1.380649e-23 * 300.15 * 1000.0
check("thermal law: onoise density = 4kTR (1k resistor)",
      qp0.get("onoise") and abs(qp0["onoise"] - thermal) < 1e-3 * thermal,
      f"onoise={qp0.get('onoise')} 4kTR={thermal:.4e}")

# [3] conversion active: with a real pump the folded onoise differs from the no-pump value
# (the conversion matrix is no longer block-diagonal, so sidebands contribute + load).
qpP = qpn(run(deck("0.6m")))
check("conversion active: folded onoise differs under pump",
      qpP.get("onoise") and abs(qpP["onoise"] - qp0["onoise"]) > 1e-2 * qp0["onoise"],
      f"pump={qpP.get('onoise')} nopump={qp0.get('onoise')}")

# [4] input-referred consistency: inoise = onoise / gain^2.
check("inoise = onoise / gain^2",
      qpP.get("inoise") and qpP.get("gain2")
      and abs(qpP["inoise"] - qpP["onoise"] / qpP["gain2"]) < 1e-6 * qpP["inoise"])

# [5] qpnoise without a prior qpss ... hb must error cleanly.
out = run("* no op\nR1 n 0 1k\nIac 0 n AC 1\n.control\nqpnoise n 0.3G\n.endc\n.end\n")
check("qpnoise with no QPSS operating point errors cleanly",
      "no QPSS operating point" in out and "QPnoise:" not in out)

# [6] SOLVER PARITY: KLU and Sparse give identical onoise.
ok = qpn(run(deck("0.5m", opt=".options klu\n"))).get("onoise")
os_ = qpn(run(deck("0.5m", opt=".options sparse\n"))).get("onoise")
check("QPnoise solver-independent: KLU vs Sparse identical",
      ok and os_ and abs(ok - os_) < 1e-9 * os_, f"klu={ok} sparse={os_}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
