#!/usr/bin/env python3
"""OSDI robustness + correctness campaign -- 83 checks, every one against an oracle.

DELIBERATELY NOT PART OF THE REGRESSION SUITE. `run_regression.py` discovers
`examples/*_examples/verify_*.py`; this driver is named `run_campaign.py` so the
routine sweep never picks it up. Run it by hand:

    python3 run_campaign.py            # everything
    python3 run_campaign.py A C        # only the named phases

Why it is separate: the regression suite answers "did anything change?" on every
fold. This answers "is the OSDI path CORRECT?", takes minutes, and is worth
running when the OSDI/analysis machinery is touched -- not on every commit.

WHAT MAKES A CHECK MEANINGFUL HERE
Every check computes its expected value independently, so a pass means the
number is right, not that a run finished. Five oracle kinds are used:

  A  closed form            -- the answer is derived on paper (36 checks, run
                              under BOTH Sparse and KLU, which must also agree)
  B  differential           -- the same circuit built from ngspice's own built-in
                              devices; OSDI must match it (11)
  C  analytic optimum /     -- an optimisation whose optimum is known exactly, and
     exact probability         a Monte Carlo whose yield has a closed-form value (14)
  D  cross-analysis         -- PSS/HB must reproduce the AC result on a linear
                              circuit; .sp against exact S-parameter algebra (6)
  E  robustness             -- corrupt input and lifecycle abuse must produce a
                              clean error, never a signal, hang or wrong answer (16)

RESULT WHEN LAST RUN (2026-07-27): 83/83, no ngspice or OSDI defect. Two
differences were chased down and explained rather than tolerated:

  * the Verilog-A diode differs from ngspice's built-in `d` by 7.35e-6, constant
    across reltol 1e-3..1e-12 -- it is a 0.24 ppm THERMAL-VOLTAGE CONSTANT
    difference. OpenVAF's `$vt` is 0.0258649231535, exactly the `constants.vams`
    kT/q; the built-in diode uses its own constant. Neither is wrong.
  * PSS sits ~0.1-0.8% off the AC oracle, and the error FALLS as the time grid is
    refined (7.6e-3 -> 3.6e-3 -> 8.9e-4). That is shooting-method discretisation,
    so the check asserts convergence rather than a fixed tolerance.

USAGE NOTES worth keeping (each of these cost a diagnostic cycle while writing
this, and each looks like a bug at first):
  * `(*type="instance"*)` parameters cannot be swept or tuned as MODEL parameters
  * multi-knob sweeps separate knobs with `-vs`; the family vectors are named
    `<output>_<knob>_<value>` and need a NAMED output (`-output vo=v(out)`) to be
    printable, since `v(out)_rb_1000` parses as a call to `v()`
  * `nsga`/`nsga2` require TWO OR MORE objectives and print a Pareto front table
  * `.noise` spectral density lands in plot `noise1`; the analysis leaves `noise2`
  * `.sp` wants the card form plus `run`; at one frequency S-params are SCALARS
  * ngspice echoes `print` tags LOWERCASED in `tag = value`
  * a swept analysis prints a TABLE, not `tag = value` -- index it or use `meas`
"""
import math
import os
import re
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

K_BOLTZ = 1.3806503e-23
VT_LRM = 1.3806488e-23 * 300.15 / 1.602176565e-19   # constants.vams kT/q at 27 C
MODELS = ("m_res", "m_resm", "m_cap", "m_ind", "m_diode", "m_vccs", "m_rnoise")
results = []


def rec(label, ok, detail=""):
    results.append((label, bool(ok)))
    print("  %-56s %s  %s" % (label, "PASS" if ok else "FAIL", detail))


def osdi(name):
    """path of a compiled model, as referenced from inside a deck"""
    return "_%s.osdi" % name


def build_models():
    print("Compiling %d Verilog-A models\n" % len(MODELS))
    for m in MODELS:
        src = os.path.join(HERE, "va", "%s.va" % m)
        out = os.path.join(HERE, osdi(m))
        r = subprocess.run([OPENVAF, src, "-o", out],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(out):
            print("  FATAL: %s failed to compile\n%s" % (m, r.stdout + r.stderr))
            sys.exit(2)


def run(name, deck, timeout=600):
    # check names become file names, so strip anything path-unsafe
    p = os.path.join(HERE, "_%s.cir" % re.sub(r"\W+", "_", name))
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", ""
    finally:
        if os.path.exists(p):
            os.remove(p)
    rc = r.returncode
    if rc < 0:
        try:
            rc = "SIG" + signal.Signals(-rc).name
        except ValueError:
            rc = "SIG%d" % -rc
    return rc, r.stdout + r.stderr


def vals(out, tag):
    """floats printed as `tag = value` (ngspice lowercases the echoed tag)"""
    return [float(x) for x in
            re.findall(re.escape(tag) + r"\s*=\s*([-\d.]+e?[-+]?\d*)", out, re.I)]


def table(out, ncol):
    """rows of a `print` table: an index followed by ncol floats"""
    got = []
    for line in out.splitlines():
        q = line.split()
        if len(q) == ncol + 1 and q[0].isdigit():
            try:
                got.extend(float(x) for x in q[1:])
            except ValueError:
                pass
    return got


PRE_ALL = "".join("pre_osdi %s\n" % osdi(m) for m in MODELS)
CTL = ".control\n%sset numdgt=12\noption noacct\n%s\n.endc\n.end\n"


# --------------------------------------------------------------------------
def phase_a():
    print("\nPHASE A -- analytic oracles, both solvers\n")

    def both(name, net, analysis, tag, want, rtol=1e-6, atol=0.0, pre=PRE_ALL):
        seen = {}
        for solver in ("sparse", "klu"):
            opt = ".option klu\n" if solver == "klu" else ""
            rc, out = run("a_%s_%s" % (name, solver),
                          "A %s\n%s%s%s" % (name, opt, net, CTL % (pre, analysis)))
            v = vals(out, tag)
            g = v[0] if v else None
            seen[solver] = g
            ok = g is not None and abs(g - want) <= max(atol, rtol * abs(want))
            rec("%-30s [%s]" % (name, solver), ok,
                "got %.10g want %.10g" % (g, want) if g is not None else "no value")
        a, b = seen["sparse"], seen["klu"]
        rec("%-30s [sparse == klu]" % name,
            a is not None and b is not None
            and abs(a - b) <= max(1e-12, 1e-6 * abs(a)), "")

    R, C, L, Cr = 1e3, 1e-9, 1e-6, 1e-9
    f0 = 1.0 / (2 * math.pi * R * C)
    RC = "N1 in out rmod r=%g\nN2 out 0 cmod c=%g\n.model rmod m_res\n.model cmod m_cap\n" % (R, C)

    both("op divider",
         "V1 in 0 dc 1\nN1 in out rmod r=1k\nN2 out 0 rmod r=3k\n.model rmod m_res\n",
         "op\nprint v(out)", "v(out)", 0.75)
    both("dc sweep endpoint",
         "V1 in 0 dc 1\nN1 in out rmod r=1k\nN2 out 0 rmod r=3k\n.model rmod m_res\n",
         "dc V1 0 2 0.5\nprint v(out)[4]", "v(out)[4]", 1.5)
    both("ac RC at -3dB", "V1 in 0 dc 0 ac 1\n" + RC,
         "ac lin 1 %.10g %.10g\nprint mag(v(out))" % (f0, f0),
         "mag(v(out))", 1.0 / math.sqrt(2.0), rtol=1e-5)
    both("ac RC phase", "V1 in 0 dc 0 ac 1\n" + RC,
         "ac lin 1 %.10g %.10g\nprint ph(v(out))*180/pi" % (f0, f0),
         "ph(v(out))*180/pi", -45.0, rtol=1e-4)
    fres = 1.0 / (2 * math.pi * math.sqrt(L * Cr))
    both("ac LC resonance -> short",
         "V1 in 0 dc 0 ac 1\nN1 in out rmod r=1\nN2 out m lmod l=%g\nN3 m 0 cmod c=%g\n"
         ".model rmod m_res\n.model lmod m_ind\n.model cmod m_cap\n" % (L, Cr),
         "ac lin 1 %.10g %.10g\nprint mag(v(out))" % (fres, fres),
         "mag(v(out))", 0.0, atol=1e-6)
    tau = R * C
    both("tran RC at one tau", "V1 in 0 pulse(0 1 0 1p 1p 1 2)\n" + RC,
         ".options reltol=1e-9 abstol=1e-15 vntol=1e-12\ntran %.12g %.12g\n"
         "meas tran vt FIND v(out) AT=%.12g" % (tau / 2000.0, tau, tau),
         "vt", 1.0 - math.exp(-1.0), rtol=2e-4)
    Is, vb = 1e-14, 0.6
    both("diode I(V) exact",
         "V1 a 0 dc %g\nN1 a 0 dmod is=%g n=1\n.model dmod m_diode\n" % (vb, Is),
         "op\nprint -i(v1)", "-i(v1)", Is * (math.exp(vb / VT_LRM) - 1.0))
    gm, RL = 2e-3, 4.7e3
    both("vccs gain",
         "V1 in 0 dc 0.1\nN1 out 0 in 0 gmod gm=%g\nNR out 0 rmod r=%g\n"
         ".model gmod m_vccs\n.model rmod m_res\n" % (gm, RL),
         "op\nprint v(out)", "v(out)", -gm * RL * 0.1)
    r1 = r2 = 1e3
    both("noise thermal density = sqrt(4kTR)",
         "V1 in 0 dc 0 ac 1\nN1 in out rmod r=%g\nN2 out 0 rmod r=%g\n"
         ".model rmod m_rnoise\n" % (r1, r2),
         "noise v(out) V1 lin 1 1k 1k\nsetplot noise1\nprint onoise_spectrum",
         "onoise_spectrum",
         math.sqrt(4.0 * K_BOLTZ * 300.15 * (r1 * r2 / (r1 + r2))), rtol=2e-3)
    both("pz pole at -1/RC", "V1 in 0 dc 0 ac 1\n" + RC,
         "pz in 0 out 0 vol pol\nprint pole(1)", "pole(1)", -1.0 / (R * C), rtol=1e-4)
    both("tf gain",
         "V1 in 0 dc 1\nN1 in out rmod r=1k\nN2 out 0 rmod r=3k\n.model rmod m_res\n",
         "tf v(out) V1\nprint transfer_function", "transfer_function", 0.75)
    both("tf input resistance",
         "V1 in 0 dc 1\nN1 in out rmod r=1k\nN2 out 0 rmod r=3k\n.model rmod m_res\n",
         "tf v(out) V1\nprint v1#input_impedance", "v1#input_impedance", 4000.0)


# --------------------------------------------------------------------------
def phase_b():
    print("\nPHASE B -- OSDI device vs the equivalent ngspice built-in\n")

    def pair(label, osdi_net, ref_net, analysis, tag, rtol=1e-9):
        _, a_out = run("b_%s_o" % label[:10].replace(" ", ""),
                       "B\n" + osdi_net + CTL % (PRE_ALL, analysis))
        _, b_out = run("b_%s_r" % label[:10].replace(" ", ""),
                       "B\n" + ref_net + CTL % ("", analysis))
        a, b = vals(a_out, tag), vals(b_out, tag)
        ok = (len(a) == len(b) and a
              and all(abs(x - y) <= rtol * max(1e-300, abs(y)) for x, y in zip(a, b)))
        worst = (max(abs(x - y) / max(1e-300, abs(y)) for x, y in zip(a, b))
                 if a and b else None)
        rec(label, ok, "max rel diff %.2e" % worst if worst is not None
            else "osdi=%d ref=%d values" % (len(a), len(b)))

    SRC = "V1 in 0 dc 1 ac 1\n"
    ACSW = ("ac dec 12 1 1e9\nprint mag(v(out))[0] mag(v(out))[54] mag(v(out))[108]")

    pair("resistor: op divider",
         SRC + "N1 in out rmod r=2.2k\nN2 out 0 rmod r=4.7k\n.model rmod m_res\n",
         SRC + "R1 in out 2.2k\nR2 out 0 4.7k\n", "op\nprint v(out)", "v(out)")
    pair("capacitor: AC 1Hz..1GHz",
         SRC + "N1 in out rmod r=1k\nN2 out 0 cmod c=1n\n.model rmod m_res\n"
               ".model cmod m_cap\n",
         SRC + "R1 in out 1k\nC1 out 0 1n\n", ACSW, "mag(v(out))[54]", rtol=1e-8)
    pair("inductor: AC sweep",
         SRC + "N1 in out rmod r=50\nN2 out 0 lmod l=10u\n.model rmod m_res\n"
               ".model lmod m_ind\n",
         SRC + "R1 in out 50\nL1 out 0 10u\n", ACSW, "mag(v(out))[54]", rtol=1e-8)
    pair("RC transient",
         "V1 in 0 pulse(0 1 0 1n 1n 1 2)\nN1 in out rmod r=1k\nN2 out 0 cmod c=1n\n"
         ".model rmod m_res\n.model cmod m_cap\n",
         "V1 in 0 pulse(0 1 0 1n 1n 1 2)\nR1 in out 1k\nC1 out 0 1n\n",
         "tran 1n 2u\nmeas tran a FIND v(out) AT=0.5u", "a", rtol=1e-6)
    pair("diode: DC sweep 0..0.8V",
         "V1 a 0 dc 0\nN1 a 0 dmod is=1e-14 n=1\n.model dmod m_diode\n",
         "V1 a 0 dc 0\nD1 a 0 dref\n.model dref d(is=1e-14 n=1 rs=0 cjo=0 tt=0)\n",
         "dc V1 0 0.8 0.02\nprint -i(v1)[40]", "-i(v1)[40]", rtol=2e-5)
    pair("vccs: op",
         "V1 in 0 dc 0.25\nN1 out 0 in 0 gmod gm=3.3m\nNR out 0 rmod r=2k\n"
         ".model gmod m_vccs\n.model rmod m_res\n",
         "V1 in 0 dc 0.25\nG1 out 0 in 0 3.3m\nR2 out 0 2k\n", "op\nprint v(out)",
         "v(out)")
    pair("noise: OSDI vs built-in R",
         "V1 in 0 dc 0 ac 1\nN1 in out rmod r=1k\nN2 out 0 rmod r=1k\n"
         ".model rmod m_rnoise\n",
         "V1 in 0 dc 0 ac 1\nR1 in out 1k\nR2 out 0 1k\n",
         "noise v(out) V1 dec 5 100 1e4\nsetplot noise1\nprint onoise_spectrum[5]",
         "onoise_spectrum[5]", rtol=2e-3)
    pair("tf: gain",
         SRC + "N1 in out rmod r=2.2k\nN2 out 0 rmod r=4.7k\n.model rmod m_res\n",
         SRC + "R1 in out 2.2k\nR2 out 0 4.7k\n",
         "tf v(out) V1\nprint transfer_function", "transfer_function")
    pair("pz: pole of the RC",
         SRC + "N1 in out rmod r=1k\nN2 out 0 cmod c=1n\n.model rmod m_res\n"
               ".model cmod m_cap\n",
         SRC + "R1 in out 1k\nC1 out 0 1n\n",
         "pz in 0 out 0 vol pol\nprint pole(1)", "pole(1)", rtol=1e-6)
    pair("sens: DC sensitivities",
         SRC + "N1 in out rmod r=2.2k\nN2 out 0 rmod r=4.7k\n.model rmod m_res\n",
         SRC + "R1 in out 2.2k\nR2 out 0 4.7k\n", "sens v(out)\nprint v1", "v1",
         rtol=1e-6)
    pair("diode rectifier transient",
         "V1 in 0 sin(0 1 1meg)\nN1 in out dmod is=1e-14 n=1\nNR out 0 rmod r=10k\n"
         "NC out 0 cmod c=100p\n.model dmod m_diode\n.model rmod m_res\n"
         ".model cmod m_cap\n",
         "V1 in 0 sin(0 1 1meg)\nD1 in out dref\nR1 out 0 10k\nC1 out 0 100p\n"
         ".model dref d(is=1e-14 n=1 rs=0 cjo=0 tt=0)\n",
         "tran 5n 5u\nmeas tran pk MAX v(out)", "pk", rtol=1e-4)


# --------------------------------------------------------------------------
def phase_c():
    print("\nPHASE C -- sweep / optimize / Monte Carlo over OSDI devices\n")
    NET = ("V1 in 0 dc 1\nN1 in out rmod r={rr}\nN2 out 0 rmod r=3k\n"
           ".model rmod m_res\n")
    want = [3000.0 / (r + 3000.0) for r in (1000, 2000, 3000, 4000, 5000)]

    rc, out = run("c_sweep_i", "C\n.param rr = 1k\n" + NET
                  + CTL % (PRE_ALL,
                           "sweep rr lin 5 1k 5k -analysis op -output v(out)\n"
                           "print v(out)"))
    got = table(out, 1)
    rec("sweep -> OSDI INSTANCE param, closed form",
        len(got) == 5 and all(abs(g - w) < 1e-9 * w for g, w in zip(got, want)),
        "max rel err %.1e" % max(abs(g - w) / w for g, w in zip(got, want))
        if len(got) == 5 else "%d pts" % len(got))

    rc, out = run("c_sweep_m", "C\n.param rr = 1k\nV1 in 0 dc 1\nN1 in out rmod\n"
                  "N2 out 0 rfix\n.model rmod m_resm r={rr}\n.model rfix m_resm r=3k\n"
                  + CTL % (PRE_ALL,
                           "sweep rr lin 5 1k 5k -analysis op -output v(out)\n"
                           "print v(out)"))
    got = table(out, 1)
    rec("sweep -> OSDI MODEL param, closed form",
        len(got) == 5 and all(abs(g - w) < 1e-9 * w for g, w in zip(got, want)),
        "max rel err %.1e" % max(abs(g - w) / w for g, w in zip(got, want))
        if len(got) == 5 else "%d pts" % len(got))

    rc, out = run("c_nested", "C\n.param ra = 1k\n.param rb = 1k\nV1 in 0 dc 1\n"
                  "N1 in out rmod r={ra}\nN2 out 0 rmod r={rb}\n.model rmod m_res\n"
                  + CTL % (PRE_ALL,
                           "sweep ra lin 3 1k 3k -vs rb lin 4 1k 4k -analysis op "
                           "-output vo=v(out)\n"
                           "print vo_rb_1000 vo_rb_2000 vo_rb_3000 vo_rb_4000"))
    got = table(out, 4)
    grid = sorted(round(rb / (ra + rb), 9)
                  for ra in (1000, 2000, 3000) for rb in (1000, 2000, 3000, 4000))
    rec("nested 3x4 sweep (4 curves x 3 points)",
        len(got) == 12 and sorted(round(g, 9) for g in got) == grid,
        "%d points, exact" % len(got))

    for meth in ("nm", "lm", "pso", "de", "sa"):
        rc, out = run("c_opt_" + meth, "C\n.param rr = 1k\n" + NET
                      + CTL % (PRE_ALL,
                               "optimize -dparam rr 1000 200 20000 -analysis op "
                               "-target v(out) 0.5 -method %s -maxiter 400 -seed 3\n"
                               "print rr" % meth))
        v = vals(out, "rr")
        rec("optimize -method %-4s -> analytic optimum r=3000" % meth,
            v and abs(v[0] - 3000.0) < 0.02 * 3000.0,
            "got %.6g" % v[0] if v else "no result")

    for meth in ("nsga", "nsga2"):
        rc, out = run("c_opt_" + meth,
                      "C\n.param rr = 1k\nV1 in 0 dc 1\nN1 in mid rmod r={rr}\n"
                      "N2 mid 0 rmod r=3k\n.model rmod m_res\n"
                      + CTL % (PRE_ALL,
                               "optimize -dparam rr 1000 200 20000 -analysis op "
                               "-minimize v(mid) -minimize 1-v(mid) -method %s "
                               "-maxiter 60 -seed 1" % meth))
        pts = bad = 0
        for line in out.splitlines():
            q = line.replace("|", " ").split()
            if len(q) != 3:
                continue
            try:
                f1, f2, rr = map(float, q)
            except ValueError:
                continue
            if not 200.0 <= rr <= 20000.0:
                continue
            pts += 1
            if abs(f1 - 3000.0 / (rr + 3000.0)) > 2e-6 or abs(f1 + f2 - 1.0) > 2e-6:
                bad += 1
        rec("optimize -method %-5s: front on the analytic curve" % meth,
            pts >= 5 and bad == 0, "%d front points, %d off-curve" % (pts, bad))

    rc, out = run("c_mparam", "C\nV1 in 0 dc 1\nN1 in out rmod\nN2 out 0 rfix\n"
                  ".model rmod m_resm r=1k\n.model rfix m_resm r=3k\n"
                  + CTL % (PRE_ALL,
                           "optimize -mparam @rmod[r] 1000 200 20000 -analysis op "
                           "-target v(out) 0.5 -maxiter 300 -seed 3\nprint @rmod[r]"))
    v = vals(out, "@rmod[r]")
    rec("optimize -mparam on an OSDI model param",
        v and abs(v[0] - 3000.0) < 0.02 * 3000.0, "got %.6g" % v[0] if v else "none")

    mc = (".param rr = agauss(3000, 300, 3)\nV1 in 0 dc 1\n"
          "N1 in out rmod r={rr}\nN2 out 0 rmod r=3k\n.model rmod m_res\n")
    LO, HI = 0.48, 0.52
    rc, out = run("c_mc", "C\n" + mc + CTL % (PRE_ALL,
                  "montecarlo 400 -analysis op -spec v(out) -max %g -min %g -seed 5"
                  % (HI, LO)))
    m = re.search(r"\((\d+) / (\d+) pass", out)
    got_mc = int(m.group(1)) if m else None
    rc, out2 = run("c_mc_oracle", "C\n" + mc + CTL % (PRE_ALL,
                   "setseed 5\nlet np = 0\nlet i = 0\nwhile i < 400\n  reset\n  op\n"
                   "  if (v(out) < %g) & (v(out) > %g)\n    let np = np + 1\n  end\n"
                   "  let i = i + 1\nend\necho ORACLE $&np" % (HI, LO)))
    mo = re.search(r"^ORACLE\s+(\d+)", out2, re.M)
    rec("montecarlo == hand-rolled reset-loop oracle",
        got_mc is not None and mo is not None and got_mc == int(mo.group(1)),
        "mc %s vs oracle %s" % (got_mc, mo.group(1) if mo else None))

    def phi(z):
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    rlo, rhi = 3000.0 / HI - 3000.0, 3000.0 / LO - 3000.0
    exact = phi((rhi - 3000.0) / 100.0) - phi((rlo - 3000.0) / 100.0)
    N = 20000
    for tag, flag in (("MC", ""), ("LHS", "-lhs ")):
        rc, out = run("c_stat_" + tag, "C\n" + mc + CTL % (PRE_ALL,
                      "montecarlo %d %s-analysis op -spec v(out) -max %g -min %g "
                      "-seed 11" % (N, flag, HI, LO)))
        m = re.search(r"\((\d+) / (\d+) pass", out)
        if not m:
            rec("%s yield vs the EXACT Gaussian probability" % tag, False, "no yield")
            continue
        p = int(m.group(1)) / N
        se = math.sqrt(exact * (1 - exact) / N)
        rec("%s yield vs the EXACT Gaussian probability" % tag,
            abs(p - exact) / se < 3.5,
            "got %.4f exact %.4f z=%.2f" % (p, exact, abs(p - exact) / se))


# --------------------------------------------------------------------------
def phase_d():
    print("\nPHASE D -- RF / periodic analyses\n")
    Z0, Zr = 50.0, 30.0
    rc, out = run("d_sp", "D\nV1 in 0 dc 0 ac 1 portnum 1 z0 %g\n"
                  "N1 in out rmod r=%g\n.model rmod m_res\n"
                  "V2 out 0 dc 0 ac 0 portnum 2 z0 %g\n.sp lin 1 1e9 1e9 1\n"
                  ".control\n%srun\nset numdgt=12\noption noacct\n"
                  "print mag(S_1_1) mag(S_2_1)\n.endc\n.end\n" % (Z0, Zr, Z0, PRE_ALL))
    s11, s21 = vals(out, "mag(S_1_1)"), vals(out, "mag(S_2_1)")
    rec("S11 of a series OSDI resistor = Z/(Z+2Z0)",
        s11 and abs(s11[0] - Zr / (Zr + 2 * Z0)) < 1e-6,
        "got %.9g" % s11[0] if s11 else "no S11")
    rec("S21 of a series OSDI resistor = 2Z0/(2Z0+Z)",
        s21 and abs(s21[0] - 2 * Z0 / (2 * Z0 + Zr)) < 1e-6,
        "got %.9g" % s21[0] if s21 else "no S21")

    rc, out = run("d_sp_m", "D\nV1 in 0 dc 0 ac 1 portnum 1 z0 50\n"
                  "N1 in 0 rmod r=50\n.model rmod m_res\n.sp lin 1 1e9 1e9 1\n"
                  ".control\n%srun\nset numdgt=12\noption noacct\n"
                  "print mag(S_1_1)\n.endc\n.end\n" % PRE_ALL)
    v = vals(out, "mag(S_1_1)")
    rec("matched 50ohm OSDI load -> |S11| = 0", v and v[0] < 1e-9,
        "got %.3e" % v[0] if v else "no S11")

    R, C, f0 = 1e3, 1e-9, 1e5
    acmag = 1.0 / math.sqrt(1.0 + (2 * math.pi * f0 * R * C) ** 2)
    base = ("V1 in 0 dc 0 ac 1 sin(0 1 %g)\nN1 in out rmod r=%g\nN2 out 0 cmod c=%g\n"
            ".model rmod m_res\n.model cmod m_cap\n" % (f0, R, C))
    errs = []
    for npts, harm, iters, tol in ((1024, 5, 10, "1e-9"), (2048, 9, 30, "1e-12"),
                                   (4096, 15, 50, "1e-14")):
        rc, out = run("d_pss%d" % npts, "D\n" + base + CTL % (PRE_ALL,
                      "pss %g 5e-4 %d %d %d %s\nprint mag(v(out))[1]"
                      % (f0, npts, harm, iters, tol)))
        v = vals(out, "mag(v(out))[1]")
        errs.append(abs(v[0] - acmag) / acmag if v else None)
    rec("PSS -> AC magnitude, error CONVERGES under refinement",
        all(e is not None for e in errs) and errs[0] > errs[1] > errs[2]
        and errs[-1] < 2e-3,
        "rel err " + " -> ".join("%.1e" % e for e in errs if e is not None))

    rc, out = run("d_hb", "D\n" + base + CTL % (PRE_ALL,
                  "hb %g 5\nprint mag(v(out))[1]" % f0))
    v = vals(out, "mag(v(out))[1]")
    rec("HB fundamental == AC magnitude", v and abs(v[0] - acmag) < 2e-3 * acmag,
        "got %.6g want %.6g" % (v[0], acmag) if v else "no HB output")

    rc, out = run("d_disto", "D\n" + base + CTL % (PRE_ALL,
                  "disto dec 3 1e4 1e6 0.9\nprint mag(hd2)[0]"))
    v = vals(out, "mag(hd2)[0]")
    rec("disto of a LINEAR OSDI network -> HD2 ~ 0", (not v) or v[0] < 1e-12,
        "got %.3e" % v[0] if v else "no hd2 (acceptable)")


# --------------------------------------------------------------------------
def phase_e():
    print("\nPHASE E -- robustness: corrupt input and lifecycle abuse\n")
    GOOD = ("V1 in 0 dc 1\nN1 in out rmod r=1k\nN2 out 0 rmod r=3k\n"
            ".model rmod m_res\n")
    raw = open(os.path.join(HERE, osdi("m_res")), "rb").read()
    for nm, blob in (("truncated_half", raw[:len(raw) // 2]),
                     ("truncated_tiny", raw[:64]),
                     ("header_zeroed", b"\x00" * 256 + raw[256:]),
                     ("all_garbage",
                      bytes((i * 7 + 13) & 0xFF for i in range(len(raw) // 4))),
                     ("empty", b"")):
        f = os.path.join(HERE, "_bad_%s.osdi" % nm)
        with open(f, "wb") as fh:
            fh.write(blob)
        rc, out = run("e_bad_" + nm, "E\n" + GOOD
                      + ".control\npre_osdi %s\nop\necho SURVIVED\n.endc\n.end\n"
                      % os.path.basename(f))
        os.remove(f)
        rec("corrupt .osdi (%s) -> clean error" % nm, isinstance(rc, int), "rc=%s" % rc)

    for nm, net, ctl in (
        ("pre_osdi of a nonexistent file", GOOD,
         "pre_osdi _does_not_exist.osdi\nop\necho SURVIVED"),
        ("pre_osdi the same file twice", GOOD,
         "pre_osdi %s\npre_osdi %s\nop\necho SURVIVED" % (osdi("m_res"), osdi("m_res"))),
        ("model names a module not in the .osdi",
         "V1 in 0 dc 1\nN1 in 0 nomod r=1k\n.model nomod not_a_module\n",
         "pre_osdi %s\nop\necho SURVIVED" % osdi("m_res")),
        ("instance sets an unknown parameter",
         "V1 in 0 dc 1\nN1 in 0 rmod r=1k bogus=42\n.model rmod m_res\n",
         "pre_osdi %s\nop\necho SURVIVED" % osdi("m_res")),
        ("parameter below its declared range (r<0)",
         "V1 in 0 dc 1\nN1 in 0 rmod r=-5\n.model rmod m_res\n",
         "pre_osdi %s\nop\necho SURVIVED" % osdi("m_res")),
        ("parameter = 0 on a `from (0:inf)` range",
         "V1 in 0 dc 1\nN1 in 0 rmod r=0\n.model rmod m_res\n",
         "pre_osdi %s\nop\necho SURVIVED" % osdi("m_res")),
        ("absurdly large parameter (1e300)",
         "V1 in 0 dc 1\nN1 in out rmod r=1e300\nN2 out 0 rmod r=1k\n"
         ".model rmod m_res\n", "pre_osdi %s\nop\necho SURVIVED" % osdi("m_res")),
        ("absurdly small parameter (1e-300)",
         "V1 in 0 dc 1\nN1 in out rmod r=1e-300\nN2 out 0 rmod r=1k\n"
         ".model rmod m_res\n", "pre_osdi %s\nop\necho SURVIVED" % osdi("m_res")),
    ):
        rc, out = run("e_" + re.sub(r"\W+", "_", nm)[:18],
                      "E\n" + net + ".control\n" + ctl + "\n.endc\n.end\n")
        rec(nm, isinstance(rc, int), "rc=%s" % rc)

    rc, out = run("e_life", "E\nV1 in 0 dc 1 ac 1\nN1 in out rmod r=1k\n"
                  "N2 out 0 cmod c=1n\n.model rmod m_res\n.model cmod m_cap\n"
                  ".control\n%soption noacct\nop\nac dec 3 1 1e6\ntran 1u 10u\n"
                  "reset\nop\ndestroy all\nop\ntran 1u 10u\nreset\n"
                  "ac dec 3 1 1e6\nremcirc\necho SURVIVED\n.endc\n.end\n" % PRE_ALL)
    rec("lifecycle: op/ac/tran x reset/destroy/remcirc interleaved",
        isinstance(rc, int) and "SURVIVED" in out, "rc=%s" % rc)

    rc, out = run("e_resrc", "E\n" + GOOD + CTL % (PRE_ALL,
                  "let i = 0\nwhile i < 40\n  reset\n  op\n  let i = i + 1\nend\n"
                  "print v(out)\necho SURVIVED"))
    v = vals(out, "v(out)")
    rec("40x reset+op with OSDI loaded, value still exact",
        isinstance(rc, int) and v and abs(v[0] - 0.75) < 1e-12,
        "v(out)=%s" % (v[0] if v else None))

    net = ["E stress", "V1 x0 0 dc 1", ".model rmod m_res"]
    for i in range(2000):
        net.append("N%d x%d x%d rmod r=100" % (i + 1, i, i + 1))
    net.append("NT x2000 0 rmod r=1k")
    rc, out = run("e_stress", "\n".join(net) + "\n"
                  + CTL % (PRE_ALL, "op\nprint v(x2000)\necho SURVIVED"))
    v = vals(out, "v(x2000)")
    want = 1000.0 / (2000 * 100.0 + 1000.0)
    rec("2000 OSDI instances in one circuit, exact divider",
        isinstance(rc, int) and v and abs(v[0] - want) < 1e-9,
        "got %s want %.9g" % (v[0] if v else None, want))


PHASES = {"A": phase_a, "B": phase_b, "C": phase_c, "D": phase_d, "E": phase_e}


def main(argv):
    want = [a.upper() for a in argv[1:] if a.upper() in PHASES] or list(PHASES)
    build_models()
    for p in want:
        PHASES[p]()
    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))
    n = len(results)
    ok = sum(1 for _, k in results if k)
    print("\n%s: %d/%d checks passed" % ("ALL PASS" if ok == n else "FAILURES", ok, n))
    return 0 if ok == n else 1


sys.exit(main(sys.argv))
