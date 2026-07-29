#!/usr/bin/env python3
"""Bias-dependent transient noise: shot noise on a Verilog-A diode.

This is the harder case. Thermal noise 4kT/R is a constant, so getting it right
only proves the amplitude scaling. Shot noise is 2qI -- it TRACKS the operating
point, so it also proves that `load_noise_params` is re-read at the current bias
each timepoint rather than latched once.

For each bias the oracle is computed from the diode's OWN operating point as
reported by ngspice:

    I  = diode current             (read from the .op)
    rd = nf * Vt / I               small-signal diode resistance
    R  = rd || Rext                node resistance
    S  = 2 q I                     shot-noise density
    var = S * R / (4 C)            same integral as the thermal case

Sweeping the bias over a decade of current changes I, rd and hence var by a
large factor; matching at every bias is what demonstrates bias tracking.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from _setup import NG, VAF  # noqa: E402
Q = 1.602176565e-19
K = 1.3806488e-23
T = 300.15
VT = K * T / Q
C = 1e-9
REXT = 1e3


def deck(vbias, ts, tstop, tstep):
    return """shot noise transient verification
V1 in 0 dc {vb}
Rs in mid {rext}
N1 mid 0 mydio
Cx mid 0 {c}
.model mydio vadio(is=1e-14 nf=1)
Vn nz 0 dc 0 trnoise(0 {ts} 0 0)
Rz nz 0 1k
.options reltol=1e-6 abstol=1e-18 vntol=1e-15
.control
option noacct
pre_osdi {here}/nlin.osdi
op
let vd = v(mid)
let id = (({vb})-v(mid))/{rext}
echo VD $&vd
echo ID $&id
tran {tstep} {tstop} 0 {tstep}
let ac_ = v(mid) - mean(v(mid))
let v2 = ac_*ac_
let mv = mean(v2)
echo VAR $&mv
.endc
.end
""".format(vb=vbias, ts=ts, tstop=tstop, tstep=tstep, here=HERE, c=C, rext=REXT)


def build():
    """Compile the diode model. This step was MISSING: the deck referenced an
    `nlin.osdi` that lived only in a scratch directory, so the script could not
    run from a clean checkout -- it reported `FAILED to extract` for every bias,
    which reads like a simulator failure rather than a missing file."""
    r = subprocess.run([VAF, "nlin.va", "-o", "nlin.osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print("  model failed to compile:\n%s" % (r.stdout + r.stderr)[:400])
    return r.returncode == 0


def run(src, tag):
    p = os.path.join(HERE, "_s_%s.cir" % tag)
    open(p, "w").write(src)
    r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=1800, errors="replace")
    return r.stdout + r.stderr


def val(out, key):
    m = re.search(r"^%s\s+(\S+)" % key, out, re.M)
    return float(m.group(1)) if m else None


def main():
    if not build():
        sys.exit(1)
    print("  %-7s %-11s %-11s %-11s %-11s %s"
          % ("Vbias", "I (A)", "rd (ohm)", "var meas", "var calc", "dev"))
    ok = True
    for vb in (0.50, 0.60, 0.65, 0.70):
        out = run(deck(vb, 10e-9, "2m", "10n"), "%d" % int(vb * 100))
        i = val(out, "ID")
        var = val(out, "VAR")
        if i is None or var is None or i <= 0:
            print("  %-7s FAILED to extract (I=%s var=%s)" % (vb, i, var))
            ok = False
            continue
        rd = VT / i                      # nf = 1
        rtot = rd * REXT / (rd + REXT)
        calc = (2.0 * Q * i) * rtot / (4.0 * C)
        dev = abs(var - calc) / calc
        print("  %-7s %-11.4e %-11.4e %-11.4e %-11.4e %.1f%%"
              % (vb, i, rd, var, calc, 100 * dev))
        if dev > 0.20:
            ok = False
    for j in os.listdir(HERE):
        if j.startswith("_s_"):
            os.remove(os.path.join(HERE, j))
    print("\n  %s" % ("ALL BIASES MATCH" if ok else "MISMATCH"))
    sys.exit(0 if ok else 1)


main()
