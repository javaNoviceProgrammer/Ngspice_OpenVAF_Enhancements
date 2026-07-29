#!/usr/bin/env python3
"""Enhancement-364: transient noise for OSDI (Verilog-A) devices.

`.noise` linearises about an operating point and reports spectral densities; it
cannot show jitter, noise-induced switching, or an oscillator's phase noise,
because those need the noise present IN THE TIME DOMAIN. ngspice has had
time-domain noise for independent sources (`trnoise` on V/I sources) for years,
but OSDI devices were silently noiseless in `.tran` -- a deck asking for
transient noise got noise from its sources and nothing from its transistors.

AUTOMATIC ACTIVATION. There is no option to set. Transient noise switches on
when the circuit already contains a `trnoise` source, i.e. when the deck is
demonstrably already running a noisy transient, and it adopts that source's own
noise timestep so every generator in the circuit shares one grid. It is
deliberately NOT keyed on "this device declares noise sources": practically
every real compact model declares thermal and flicker noise, so that test would
mean "always on", making every existing transient stochastic and changing
results nobody asked to change. A deck with no `trnoise` source is unaffected.

THE AMPLITUDE LAW (derived, not fitted). The generator is a unit-parameter
source filtered by Kasdin's fractional-integration FIR, H(z) = (1-z^-1)^(-a/2),
so |H|^2 -> (2*pi*f*ts)^-a below Nyquist. Discrete white noise of deviation Q on
a grid of period ts has one-sided density 2*Q^2*ts, hence

    S(f) = 2*Q^2*ts*(2*pi*f*ts)^-a  =>  Q = sqrt(|power| * (2*pi*ts)^a / (2*ts))

with a = 0 collapsing to the white case, so white and 1/f share one expression.
Getting this wrong is not subtle: applying the white law to a flicker source
overstates its amplitude by sqrt(1/(2*ts*pi)), which for ts = 1 us is 399x --
and that is exactly the error that was measured against `.noise` before the law
was derived.

WHY A FIXED NOISE GRID. The sample must NOT be scaled by the adaptive
simulation timestep. A white source of density S sampled at dt has deviation
sqrt(S/(2*dt)); if dt is the LTE-controlled step then the injected POWER moves
whenever the step controller changes its mind, and the spectrum becomes an
artefact of the integrator. Check [3] below is what fails in that case.

This suite is deliberately quick. The full statistical validation -- Welch PSD
of a 0.2 s transient against `.noise`, which is what pinned the flicker
normalisation to 0.994 +/- 0.009 with a fitted slope of -0.993 -- lives in
`validate/` next to this file and is NOT run by the regression.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

K = 1.3806488e-23
T = 300.15
R_VA = 1e3
R_EXT = 1e3
C = 1e-9
R_TOT = R_VA * R_EXT / (R_VA + R_EXT)
VAR_ANALYTIC = (4.0 * K * T / R_VA) * R_TOT / (4.0 * C)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


LIN_VA = """`include "disciplines.vams"
module valin(p, n);
  inout p, n;
  electrical p, n;
  parameter real r = 1e3 from (0:inf);
  parameter real c = 1e-9 from [0:inf);
  parameter real kf = 0.0 from [0:inf);
  analog begin
    I(p, n) <+ V(p, n) / r;
    I(p, n) <+ ddt(c * V(p, n));
    I(p, n) <+ white_noise(4.0 * 1.3806488e-23 * $temperature / r, "thermal");
    if (kf > 0.0)
      I(p, n) <+ flicker_noise(kf, 1.0, "fl");
  end
endmodule
"""


def compile_model():
    src = os.path.join(HERE, "_trnoise_dut.va")
    out = os.path.join(HERE, "_trnoise_dut.osdi")
    with open(src, "w") as f:
        f.write(LIN_VA)
    r = subprocess.run([OPENVAF, os.path.basename(src), "-o", os.path.basename(out)],
                       cwd=HERE, capture_output=True, text=True, timeout=600)
    return out if r.returncode == 0 else None


def deck(osdi, ts, tstop, tstep, kf=0.0, noisy=True):
    act = ("Vn nz 0 dc 0 trnoise(0 %g 0 0)\nRz nz 0 1k\n" % ts) if noisy else ""
    return """osdi transient noise
V1 in 0 dc 0
Rs in mid 1k
N1 mid 0 mylin
.model mylin valin(r=1k c=1n kf={kf})
{act}.options reltol=1e-6 abstol=1e-18 vntol=1e-15
.control
option noacct
pre_osdi {osdi}
tran {tstep} {tstop} 0 {tstep}
let ac_ = v(mid) - mean(v(mid))
let v2 = ac_*ac_
let mv = mean(v2)
echo VAR $&mv
.endc
.end
""".format(osdi=osdi, act=act, tstep=tstep, tstop=tstop, kf=kf)


def run(src, tag):
    p = os.path.join(HERE, "_t_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(src)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def var_of(out):
    m = re.search(r"^VAR\s+(\S+)", out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def main():
    osdi = compile_model()
    check("device with white + flicker noise compiles", osdi is not None)
    if not osdi:
        print("\nFAILURES: %d/%d passed" % (passed, checks))
        sys.exit(1)

    # [1] auto-activation, and the injected white noise has the right POWER.
    # Short run => a wide tolerance; this pins the amplitude law, which fails by
    # orders of magnitude when wrong, not by tens of percent.
    out = run(deck(osdi, 10e-9, "300u", "10n"), "a")
    v1 = var_of(out)
    check("activates automatically from a trnoise source",
          "transient noise active" in out)
    ok = v1 is not None and abs(v1 - VAR_ANALYTIC) / VAR_ANALYTIC < 0.45
    check("thermal noise power matches the analytic value", ok,
          ("%.3e vs %.3e" % (v1, VAR_ANALYTIC)) if v1 is not None else "no data")

    # [2] no trnoise source => untouched, deterministic, exactly zero
    out0 = run(deck(osdi, 0, "20u", "10n", noisy=False), "b")
    v0 = var_of(out0)
    check("inactive when the deck has no trnoise source",
          v0 == 0.0 and "transient noise active" not in out0, "variance %s" % v0)

    # [3] THE key property: the answer must not depend on the noise grid. A
    # naive implementation that scales by the adaptive simulation step fails
    # here while passing [1].
    v2 = var_of(run(deck(osdi, 5e-9, "300u", "5n"), "c"))
    ok = bool(v1) and v2 is not None and abs(v2 - v1) / v1 < 0.5
    check("noise power independent of the noise timestep", ok,
          ("%.3e vs %.3e" % (v1, v2)) if None not in (v1, v2) else "no data")

    # [4] flicker is injected too, and adds power on top of the thermal floor.
    vf = var_of(run(deck(osdi, 10e-9, "300u", "10n", kf=1e-18), "d"))
    check("flicker_noise contributes on top of the white floor",
          vf is not None and v1 is not None and vf > v1,
          ("with 1/f %.3e vs white-only %.3e" % (vf, v1)) if None not in (vf, v1) else "no data")

    for j in os.listdir(HERE):
        if j.startswith(("_t_", "_trnoise_")):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
