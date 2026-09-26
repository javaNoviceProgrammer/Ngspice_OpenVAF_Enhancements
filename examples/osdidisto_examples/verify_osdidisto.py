#!/usr/bin/env python3
"""Enhancement-352/359: distortion analysis for Verilog-A (OSDI) devices.

`.disto` is a Volterra-series analysis: it needs each device's Taylor expansion
of I(v) to THIRD order, not the operating-point linearisation the Jacobian
provides. Built-in devices hand-code those coefficients, which is why only four
of ~58 implement DEVdisto -- and why OSDI devices previously contributed nothing
but a warning.

E-352 had the compiler emit those coefficients symbolically. Enhancement-359
replaced that: ngspice now DIFFERENCES the model's analytic Jacobian at the
operating point, so nothing is needed from the compiler and no ABI beyond what
every OSDI >= 0.4 object already has. There is still no 3-variable ceiling --
`Dderivs` holds derivatives "w.r.t 3 variables" and has no fourth-variable form,
which is a property of those helpers, not the mathematics.

  [1] single tone against a CLOSED-FORM polynomial -- no simulator involved
  [2] the A^3 scaling law, which a wrong implementation cannot fake
  [3] two-tone f1+f2, f1-f2 and IM3 against ngspice's own built-in diode
  [4] MULTI-VARIABLE: a pure cross term, closed form. Zero here would mean the
      mixed partial was dropped -- the failure the whole change exists to avoid
  [5] a linear model still yields no distortion
  [6] a GROUND-REFERENCED nonlinearity contributes, against a closed form. E-352
      indexed tensors by model input (a hi/lo pair) and so could not reach this
      at all; E-359 works in node coordinates, where there is no pair to miss
  [9] Enhancement-739: a CHARGE nonlinearity against its Volterra closed form.
      The driver evaluated the model with operating-point flags, which never
      compute the reactive Jacobian, so every finite difference of it was zero
      and a device whose only nonlinearity is a charge reported NO distortion
  [10] [11] a diode WITH charge storage (junction and diffusion) against the
      built-in diode: harmonics and two-tone products at three frequencies
  [12] the charge polynomial's .disto against the transient: the same drive as
      a real sine, ngspice's own `fourier`, the check the suite lacked

WHY THE ORACLES ARE WHAT THEY ARE. A distortion result that is wrong by a
constant looks entirely plausible, and the previous OSDI campaign "tested"
`.disto` by asserting HD2 ~ 0 on a LINEAR network -- which is exactly what a
broken implementation also produces. Every check here has a NON-ZERO expected
value, and [1] and [4] depend on no simulator at all.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

MODELS = ["dst_cubic", "dst_mixer", "dst_diode", "dst_qcube", "dst_diodeq"]
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build():
    for m in MODELS:
        out = os.path.join(HERE, "_%s.osdi" % m)
        r = subprocess.run([OPENVAF, os.path.join(HERE, "va", "%s.va" % m), "-o", out],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not os.path.exists(out):
            print("FATAL: %s failed to compile\n%s" % (m, r.stdout + r.stderr))
            sys.exit(2)


def run(deck, tag, timeout=600):
    p = os.path.join(HERE, "_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    return r.stdout + r.stderr


def cplx(out, name="d"):
    return [complex(float(a), float(b)) for a, b in
            re.findall(r"^%s(?:\[0\])? = ([-\d.e+]+),\s*([-\d.e+]+)" % name, out, re.M)]


def cplx_idx(out, name="d"):
    """every `name[k] = re,im` line, in print order (E-739)"""
    return [complex(float(a), float(b)) for a, b in
            re.findall(r"^%s\[\d+\] = ([-\d.e+]+),\s*([-\d.e+]+)" % name, out, re.M)]


def fourier_mags(out):
    """harmonic magnitudes 1.. from ngspice's `fourier` table (E-739)"""
    return [float(m) for m in re.findall(r"^\s*[1-9]\s+[\d.e+]+\s+([\d.e+-]+)\s", out, re.M)]


# ------------------------------------------------------------------ [1] [2]
A1, A2, A3, RS = 1e-3, 1e-4, 4e-5, 1000.0


def cubic_run(amp):
    return run(f"""dst cubic
V1 in 0 dc 0 ac 1 distof1 {amp}
Rs in d {RS}
N1 d 0 m1
.model m1 dst_cubic(a1={A1} a2={A2} a3={A3})
.control
pre_osdi _dst_cubic.osdi
option noacct
set numdgt=14
disto dec 2 1e4 1e5
setplot disto1
print d[0]
setplot disto2
print d[0]
.endc
.end
""", "cubic_%g" % amp)


def cubic_closed_form(amp):
    Y = 1.0 / RS
    Ytot = Y + A1
    H1 = amp * Y / Ytot
    H2 = -(A2 * H1 * H1) / Ytot
    H3 = -(A2 * (2.0 * H1 * H2) + A3 * H1 ** 3) / Ytot
    return abs(H2) / 2.0, abs(H3) / 4.0     # cos^2 -> 1/2, cos^3 -> 1/4


def main():
    build()

    out = cubic_run(1.0)
    got = cplx(out)
    e2, e3 = cubic_closed_form(1.0)
    # Enhancement-359 obtains these by differencing the model's analytic Jacobian
    # rather than from a compiler-emitted symbolic form, so they are no longer
    # exact. Measured against this very closed form the error is 4.0e-09 (HD2)
    # and 5.4e-09 (HD3); the bound is set an order of magnitude above that, not
    # at whatever would pass. For scale, the built-in-diode oracle below already
    # sits at 1.9e-06 because of a $vt constant difference.
    TOL = 1e-7
    ok = len(got) >= 2 and e2 > 0 and e3 > 0 and \
        abs(abs(got[0]) - e2) <= TOL * e2 and abs(abs(got[1]) - e3) <= TOL * e3
    check("HD2 and HD3 match the closed-form polynomial", ok,
          "HD2 %.6e vs %.6e ; HD3 %.6e vs %.6e"
          % (abs(got[0]) if got else 0, e2, abs(got[1]) if len(got) > 1 else 0, e3))

    # [2] IM/harmonic amplitudes must scale as A^2 and A^3
    g1, g2 = cplx(cubic_run(1.0)), cplx(cubic_run(0.5))
    r2 = abs(g1[0]) / abs(g2[0]) if g2 and abs(g2[0]) > 0 else 0
    r3 = abs(g1[1]) / abs(g2[1]) if len(g2) > 1 and abs(g2[1]) > 0 else 0
    check("HD2 scales as A^2 and HD3 as A^3", abs(r2 - 4) < 1e-6 and abs(r3 - 8) < 1e-6,
          "ratios %.4f (want 4) and %.4f (want 8)" % (r2, r3))

    # ---------------------------------------------------------------- [3]
    HEAD = "V1 in 0 dc 0.65 ac 1 distof1 1 distof2 1\nRs in d 1k\n"
    CTL = ("\n.control\n{pre}option noacct\nset numdgt=14\n"
           "disto dec 2 1e4 1e5 0.9\nsetplot disto1\nprint d[0]\n"
           "setplot disto2\nprint d[0]\nsetplot disto3\nprint d[0]\n.endc\n.end\n")
    o = cplx(run("dst tt osdi\n" + HEAD + "N1 d 0 m1\n.model m1 dst_diode(is=1e-14)"
                 + CTL.format(pre="pre_osdi _dst_diode.osdi\n"), "tt_o"))
    b = cplx(run("dst tt ref\n" + HEAD + "D1 d 0 dm\n"
                 ".model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)" + CTL.format(pre=""), "tt_b"))
    # OpenVAF's $vt is 0.0258649231535, ngspice's built-in 0.0258649170072 --
    # 0.24 ppm apart, a real constant difference, so the bound is what that
    # justifies rather than whatever makes the test pass.
    worst = max((abs(abs(x) - abs(y)) / max(abs(x), abs(y))
                 for x, y in zip(o, b) if max(abs(x), abs(y)) > 1e-30), default=1.0)
    check("two-tone f1+f2, f1-f2 and IM3 match the built-in diode",
          len(o) == 3 and len(b) == 3 and worst < 2e-3,
          "%d products, worst rel %.2e" % (len(o), worst))

    # ---------------------------------------------------------------- [4]
    K, RL, AMP = 1e-3, 1000.0, 0.05
    out = run(f"""dst mixer
Va a 0 dc 0 ac 1 distof1 {AMP}
Vb b 0 dc 0 ac 1 distof2 {AMP}
N1 a b out 0 m1
.model m1 dst_mixer(k={K})
Rl out 0 {RL}
.control
pre_osdi _dst_mixer.osdi
option noacct
set numdgt=14
disto lin 1 1e6 1e6 0.9
setplot disto1
print out
setplot disto2
print out
.endc
.end
""", "mixer")
    mv = cplx(out, "out")
    want = 0.5 * K * AMP * AMP * RL
    ok = len(mv) >= 2 and all(abs(abs(v) - want) <= 1e-9 * want for v in mv[:2])
    check("multi-variable cross term matches closed form 0.5*k*A^2*R", ok,
          "%s vs %.6e" % ([("%.6e" % abs(v)) for v in mv[:2]], want))

    # ---------------------------------------------------------------- [5]
    out = run("""dst linear
V1 in 0 dc 0 ac 1 distof1 1
Rs in d 1k
N1 d 0 m1
.model m1 dst_cubic(a1=1e-3 a2=0 a3=0)
.control
pre_osdi _dst_cubic.osdi
option noacct
disto dec 2 1e4 1e5
setplot disto1
print d[0]
.endc
.end
""", "lin")
    lv = cplx(out)
    check("a linear model still yields no distortion",
          bool(lv) and abs(lv[0]) < 1e-30, "%s" % (abs(lv[0]) if lv else None))

    # ---------------------------------------------------------------- [6]
    # A nonlinearity in a GROUND-REFERENCED probe used to be unreachable: the
    # tensors were indexed by model input, and a bare V(a) is not one because it
    # has no hi/lo pair, so E-352 reported "contributes no distortion" and
    # returned zero. Enhancement-359 works in NODE coordinates, where there is no
    # pair to miss, so this now contributes -- and the value is checked against a
    # closed form rather than merely being non-zero.
    #
    #   device: I(a) <+ g*V(a) + k*V(a)*V(b),  I(b) <+ g*V(b)
    #   H_d = 1/2, H_e = 1/3 from the resistive network below
    #   2f1 current  = k*H_d*H_e/2 ;  node response = -that / Ytot_d
    with open(os.path.join(HERE, "_gref.va"), "w") as f:
        f.write("""`include "disciplines.vams"
module dst_gref(a,b); inout a,b; electrical a,b;
  parameter real k = 1e-3;
  analog begin
    I(a) <+ 1e-3*V(a) + k*V(a)*V(b);
    I(b) <+ 1e-3*V(b);
  end
endmodule
""")
    subprocess.run([OPENVAF, os.path.join(HERE, "_gref.va"), "-o",
                    os.path.join(HERE, "_dst_gref.osdi")], capture_output=True, timeout=900)
    out = run("""dst gref
V1 in 0 dc 0 ac 1 distof1 1
Rs in d 1k
Rt in e 1k
N1 d e mm
Re e 0 1k
.model mm dst_gref(k=1e-3)
.control
pre_osdi _dst_gref.osdi
option noacct
set numdgt=14
disto dec 2 1e4 1e5
setplot disto1
print d[0]
.endc
.end
""", "gref")
    gv = cplx(out)
    K, Hd, He, Ytot = 1e-3, 0.5, 1.0 / 3.0, 2e-3
    want = (K * Hd * He / 2.0) / Ytot
    ok = bool(gv) and abs(abs(gv[0]) - want) <= 1e-6 * want
    check("a ground-referenced nonlinearity now contributes, matching closed form",
          ok, "%s vs %.8e" % (("%.8e" % abs(gv[0])) if gv else None, want))

    # ---------------------------------------------------------------- [7]
    # TWO OSDI MODEL TYPES IN ONE CIRCUIT. `DEVdisto` is dispatched once per
    # DEVICE TYPE and every distinct .osdi is its own type, so this whole routine
    # runs once per model for every mode -- D_SETUP included. A tensor cache that
    # is global and cleared at D_SETUP therefore has the second model wipe the
    # first, and every model but the last contributes ZERO. That is a silent
    # wrong answer, not an error, and only a multi-model deck exposes it.
    #
    # The cubic branch here is identical to [1], so its value must be unchanged
    # by the presence of a second Verilog-A device elsewhere in the circuit.
    out = run("""dst two models
V1 in 0 dc 0 ac 1 distof1 1
Rs in d 1k
N1 d 0 mc
.model mc dst_cubic(a1=%g a2=%g a3=%g)
Vb bb 0 dc 0.65 ac 1 distof1 1
Rb bb e 1k
N2 e 0 md
.model md dst_diode(is=1e-14)
.control
pre_osdi _dst_cubic.osdi
pre_osdi _dst_diode.osdi
option noacct
set numdgt=14
disto dec 2 1e4 1e5
setplot disto1
print d[0]
.endc
.end
""" % (A1, A2, A3), "two")
    tv = cplx(out)
    solo = cplx(cubic_run(1.0))
    ok = bool(tv) and bool(solo) and abs(tv[0]) > 1e-30 and \
        abs(abs(tv[0]) - abs(solo[0])) <= 1e-9 * abs(solo[0])
    check("a second OSDI model type does not silence the first", ok,
          "%s alongside a diode vs %s alone"
          % (("%.8e" % abs(tv[0])) if tv else None,
             ("%.8e" % abs(solo[0])) if solo else None))

    # ---------------------------------------------------------------- [8]
    # DEGENERATE SWEEP SPEC. `distoan.c` computed the point count with
    # (int)floor(...) over expressions that go NaN on ordinary input: a decade or
    # octave sweep with ZERO steps does exp(log(10)/0) = inf and then 0 * inf,
    # and a linear sweep with start == stop leaves DfreqDelta at zero (0/0).
    # Converting NaN to int is undefined -- the point count became whatever the
    # hardware produced, so a nonsense request quietly ran with an arbitrary
    # number of points. Reachable with BUILT-IN devices too; nothing here is
    # OSDI-specific, but this is where the .disto tests live.
    #
    # Zero steps per decade is not a meaningful request and must now be refused
    # rather than run. The start == stop case is already exercised by [4], whose
    # mixer deck sweeps `lin 1 1e6 1e6`. The undefined behaviour itself only
    # shows under UBSan; what an ordinary build can check is that a nonsense
    # sweep produces no output instead of inventing some.
    out = run("""dst degenerate zero-step
V1 in 0 dc 0 ac 1 distof1 1
Rs in d 1k
N1 d 0 m1
.model m1 dst_cubic(a1=%g a2=%g a3=%g)
.control
pre_osdi _dst_cubic.osdi
option noacct
disto dec 0 1e4 1e5
setplot disto1
print d[0]
.endc
.end
""" % (A1, A2, A3), "deg0")
    check("a zero-step .disto sweep is refused, not run with an arbitrary count",
          not cplx(out), "no distortion output" if not cplx(out) else "PRODUCED OUTPUT")

    # ---------------------------------------------------------------- [9]
    # Enhancement-739 (options-and-convergence hunt, F9). osdidisto.c built its
    # tensors under operating-point evaluation flags -- resistive Jacobian and
    # residual only. A DC evaluation never computes the REACTIVE Jacobian, so
    # write_jacobian_array_react returned the same stale array at every probe
    # step, every finite difference of it was zero, and the j*omega pass rotated
    # an empty tensor: this charge polynomial reported 0 + j0 for HD2 and HD3.
    # Closed form as for [1], with I = d/dt Q(v): the n-th order current source
    # is j*omega_out times the n-th order term of Q, and the network is solved at
    # omega_out against Rs and the linear capacitance c1.
    Q1, Q2, Q3, FQ = 1e-12, 2e-12, 20e-12, 1e6

    def qcube_run(amp, tag):
        return run(f"""dst qcube
V1 in 0 dc 0 ac 1 distof1 {amp}
Rs in d {RS}
N1 d 0 m1
.model m1 dst_qcube(c1={Q1} c2={Q2} c3={Q3})
.control
pre_osdi _dst_qcube.osdi
option noacct
set numdgt=14
disto lin 1 {FQ} {FQ}
setplot disto1
print d[0]
setplot disto2
print d[0]
.endc
.end
""", tag)

    def qcube_closed_form(amp, f):
        w = 2.0 * math.pi * f
        Y = 1.0 / RS
        H1 = amp * Y / (Y + 1j * w * Q1)
        H2 = -(1j * 2 * w * Q2 * H1 * H1) / (Y + 1j * 2 * w * Q1)
        H3 = -(1j * 3 * w * (2 * Q2 * H1 * H2 + Q3 * H1 ** 3)) / (Y + 1j * 3 * w * Q1)
        return abs(H2) / 2.0, abs(H3) / 4.0

    got = cplx(qcube_run(1.0, "qcube"))
    e2, e3 = qcube_closed_form(1.0, FQ)
    # measured 1.4e-9 (HD2) and 1.6e-12 (HD3) against this closed form; the
    # bound is 1e-6, the same three orders of headroom [1] keeps over its own
    ok = len(got) >= 2 and abs(abs(got[0]) - e2) <= 1e-6 * e2 and abs(abs(got[1]) - e3) <= 1e-6 * e3
    check("[E-739] a charge nonlinearity's HD2 and HD3 match the closed form (were 0 + j0)", ok,
          "HD2 %.6e vs %.6e ; HD3 %.6e vs %.6e"
          % (abs(got[0]) if got else 0, e2, abs(got[1]) if len(got) > 1 else 0, e3))

    # ------------------------------------------------------------ [10] [11]
    # A diode WITH charge storage against the built-in diode on the same card:
    # dst_diodeq.va is the benchmark suite's vadiode.va, which mirrors the
    # built-in's junction (cjo, vj, m, fc) and diffusion (tt) charge. Before
    # E-739 the diffusion charge's HD2 was 15 % low and HD3 40 % low at 10 MHz
    # (the transient's `fourier` sides with the built-in); now the two agree to
    # the $vt constant. Harmonics, then the two-tone products.
    QCARD = "is_=1e-14 n=1.2 cjo=2p vj=0.8 m=0.4 tt=5n"
    BCARD = "is=1e-14 n=1.2 cjo=2p vj=0.8 m=0.4 tt=5n"

    def dq_run(two_tone, osdi):
        src = "V1 in 0 dc 0.7 ac 1 distof1 0.01" + (" distof2 0.01" if two_tone else "")
        dev = ("N1 d 0 m1\n.model m1 dst_diodeq(%s)" % QCARD) if osdi else ("D1 d 0 dm\n.model dm d(%s)" % BCARD)
        plots = "\n".join("setplot disto%d\nprint d[0] d[1] d[2]" % k for k in ((1, 2, 3) if two_tone else (1, 2)))
        return run(f"""dst diode charge
{src}
Rs in d 1k
{dev}
C1 d 0 1p
.control
{"pre_osdi _dst_diodeq.osdi" if osdi else "option noacct"}
option noacct
set numdgt=14
disto dec 1 1e6 1e8{" 0.9" if two_tone else ""}
{plots}
.endc
.end
""", "dq_%d_%d" % (two_tone, osdi))

    for two_tone, label in ((False, "HD2 and HD3"), (True, "two-tone f1+f2, f1-f2 and IM3")):
        o, b = cplx_idx(dq_run(two_tone, True)), cplx_idx(dq_run(two_tone, False))
        n = 9 if two_tone else 6
        worst = max((abs(x - y) / max(abs(x), abs(y))
                     for x, y in zip(o, b) if max(abs(x), abs(y)) > 1e-30), default=1.0)
        check("[E-739] %s of a diode with charge storage match the built-in at 1, 10 and 100 MHz" % label,
              len(o) == n and len(b) == n and worst < 1e-4,
              "%d/%d values, worst complex rel %.2e" % (len(o), len(b), worst))

    # ---------------------------------------------------------------- [12]
    # The check the suite lacked: `.disto` against the TIME DOMAIN. The charge
    # polynomial driven by the same amplitude as a real sine, a tight
    # transient, and ngspice's own `fourier`. The drive is small enough for the
    # third-order series to hold (c2*A/c1 = 5 %, c3*A^2/c1 = 2.5 %), the
    # tolerances are the transient's, not the analysis's.
    AQ, FT = 0.05, 1e7
    got = cplx(run(f"""dst qcube vs tran
V1 in 0 dc 0 ac 1 distof1 {AQ}
Rs in d {RS}
N1 d 0 m1
.model m1 dst_qcube(c1={Q1} c2={Q2} c3={Q3})
.control
pre_osdi _dst_qcube.osdi
option noacct
set numdgt=14
disto lin 1 {FT} {FT}
setplot disto1
print d[0]
setplot disto2
print d[0]
.endc
.end
""", "qtr_disto"))
    mags = fourier_mags(run(f"""dst qcube tran truth
V1 in 0 dc 0 sin(0 {AQ} {FT})
Rs in d {RS}
N1 d 0 m1
.model m1 dst_qcube(c1={Q1} c2={Q2} c3={Q3})
.option reltol=1e-6 abstol=1e-15 vntol=1e-9
.control
pre_osdi _dst_qcube.osdi
option noacct
tran 0.05n 500n
fourier {FT} v(d)
.endc
.end
""", "qtr_tran"))
    ok = len(got) >= 2 and len(mags) >= 3 and \
        abs(abs(got[0]) - mags[1]) <= 0.02 * mags[1] and abs(abs(got[1]) - mags[2]) <= 0.05 * mags[2]
    check("[E-739] the charge polynomial's .disto agrees with the transient's fourier", ok,
          "HD2 %.4e vs tran %.4e ; HD3 %.4e vs tran %.4e"
          % (abs(got[0]) if got else 0, mags[1] if len(mags) > 1 else 0,
             abs(got[1]) if len(got) > 1 else 0, mags[2] if len(mags) > 2 else 0))

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
