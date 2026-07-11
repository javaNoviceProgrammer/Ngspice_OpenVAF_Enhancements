#!/usr/bin/env python3
"""
verify_trustregion.py -- verifies Enhancement-153: `.option trustregion`, a
Levenberg-Marquardt (trust-region) globalized Newton for the DC operating point.

The method adds an adaptive Jacobian-diagonal damping mu = lambda*||diag(J)|| (and
the matching mu*x_k RHS coupling) so a rejected step is retried with a re-aimed,
shorter step -- x_{k+1} = x_k - (J + mu*I)^-1 F(x_k). Because the fixed point is
F = 0 for *any* mu, and lambda returns to 0 once steps succeed, it is
**result-neutral**: it converges to the same operating point as plain Newton.

IMPORTANT / honest scope: on ordinary circuits ngspice already prevents the
residual-increasing overshoot a trust-region would catch, one layer lower -- via
per-device junction limiting (limexp / pnjlim / fetlim ...). So `lambda` stays 0
and the trust-region is INERT (a no-op) on the circuits below; the point of this
verifier is therefore to confirm it is **exactly result-neutral and safe** (never
changes a result or breaks convergence), under both linear solvers.

Checks:
  [1] result-neutrality -- `.option trustregion` gives the BIT-IDENTICAL DC
      solution as plain Newton on a diode circuit, a BJT amplifier, and a
      resistor divider.
  [2] correctness -- the trust-region solution matches the analytic value.
  [3] transient neutrality -- a diode-RC transient is unchanged (the trust-region
      touches only the DC/tran operating point, not the timesteps).

Runs under BOTH the Sparse and KLU solvers (the method lives in the solver-
independent Newton loop). Every SPICE deck starts with a title line.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

SCRATCH = tempfile.mkdtemp(prefix="tr_verify_")
_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run(deck):
    with open(os.path.join(SCRATCH, "_t.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_t.cir"], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log)
    return float(m.group(1)) if m else float("nan")


def op_value(circuit, probe, trustregion):
    opt = "  option trustregion\n" if trustregion else ""
    return grab(run(f"""* trust-region op probe
{circuit}
.control
  set numdgt=16
{opt}  op
  print {probe}
.endc
.end
"""), probe)


CIRCUITS = {
    "diode divider": ("V1 in 0 dc 2\nR1 in a 1k\nD1 a 0 dmod\nR2 a 0 10k\n"
                      ".model dmod d(is=1e-14 n=1.0)", "v(a)"),
    "BJT amplifier": ("Vcc c1 0 dc 5\nVb b1 0 dc 0.7\nRc c1 c 1k\nRb b1 b 10k\n"
                      "Q1 c b 0 qmod\n.model qmod npn(is=1e-15 bf=100)", "v(c)"),
    "resistor divider": ("V1 in 0 dc 1\nR1 in out 2k\nR2 out 0 3k", "v(out)"),
}

# --- [1] result-neutrality ------------------------------------------------
print("Enhancement-153: trust-region (Levenberg-Marquardt) Newton\n")
print("[1] result-neutrality: .option trustregion == plain Newton, bit-for-bit")
vals = {}
for name, (ckt, probe) in CIRCUITS.items():
    a = op_value(ckt, probe, False)
    b = op_value(ckt, probe, True)
    vals[name] = a
    check(f"{name}: identical", a == b and not math.isnan(a),
          f"{a!r} vs {b!r}")

# --- [2] correctness ------------------------------------------------------
print("[2] correctness: solution matches analytic")
check("resistor divider = 0.6 V (3k/(2k+3k))",
      abs(vals["resistor divider"] - 0.6) < 1e-9,
      f"got {vals['resistor divider']:.6f}")

# --- [3] transient neutrality --------------------------------------------
print("[3] transient neutrality: a diode-RC transient is unchanged")
tran = """* diode-RC transient
V1 in 0 dc 0 pulse(0 2 1n 1n 1n 50n 100n)
R1 in a 1k
D1 a b dmod
C1 b 0 10p
R2 b 0 10k
.model dmod d(is=1e-14)"""
def tran_last(trustregion):
    opt = "  option trustregion\n" if trustregion else ""
    log = run(f"""* tran
{tran}
.control
  set numdgt=14
{opt}  tran 1n 100n
  let vb = v(b)
  print vb[length(vb)-1]
.endc
.end
""")
    m = re.search(r"=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log.split("vb[")[-1]) if "vb[" in log else None
    # fall back: grab the final printed number
    nums = re.findall(r"(-?[0-9]+\.[0-9]+e[-+][0-9]+)", log)
    return float(nums[-1]) if nums else float("nan")
ta, tb = tran_last(False), tran_last(True)
check("transient final v(b) identical", ta == tb and not math.isnan(ta),
      f"{ta!r} vs {tb!r}")

import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)

print()
if _fail:
    print(f"RESULT: {_fail} check(s) FAILED")
    sys.exit(1)
print("RESULT: all checks passed")
