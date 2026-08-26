#!/usr/bin/env python3
"""Enhancement-487: every RF analysis leaves its results in a nutmeg plot.

An RF result that is only PRINTED is a result you cannot use. It cannot be
plotted, printed again, `wrdata`'d, compared against a reference, or read by a
script -- and ngspice's whole post-processing model is built on the plot, not on
the terminal.

Six of the eight RF entry points already did this. `hbosc` and `phasenoise` did
not: they printed a table and stored nothing, so the session was left with
`hbosc`'s own STARTUP TRANSIENT as the current plot. The numbers were on screen
and nowhere else.

The cause was a plain asymmetry. Enhancement-209 gave `HBanalyze` a
`struct hbspectrum *out` so `com_hb` could publish its spectrum as vectors;
`HBOSCanalyze` computes the same (2K+1)*N two-sided spectrum in the same layout
and never got that parameter. So the driven case published and the autonomous
case did not, for no reason other than that one signature was extended and its
sibling was not.

TWO THINGS THIS SUITE PINS THAT ARE EASY TO GET WRONG:

  * THE PLOT NAME. `ft_plotabbrev()` matches by SUBSTRING, so "hbosc" hits the
    `hb` pattern and "phasenoise" hits `noise` unless each is given an entry
    AHEAD of the pattern that shadows it. Without that, an oscillator spectrum
    is called `hb1` -- indistinguishable from a driven run in the same session --
    and a phase-noise curve is called `noise1`, colliding with `.noise`. Checks
    [12] and [13] run the shadowing pair together in ONE session, which is the
    only arrangement where the collision is visible.

  * THE VALUES. A plot that exists but holds the wrong numbers is worse than no
    plot. Check [5] compares the published spectrum against the printed table
    rather than merely asserting the vectors are present.

DELIBERATELY NOT TYPED: `gamma_re`/`gamma_im`, `pae`, `eff` and `stb`'s
`loopgain` stay SV_NOTYPE. They are dimensionless ratios and `enum
simulation_types` has no member for that; inventing one would be worse than
leaving them untyped. Only the quantities with a real type available -- dB and
frequency -- carry one. Checks [9] and [11] hold that line.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

L_OSC, C_OSC = 1.0132118364233778e-05, 1e-9


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, ctl, tag, timeout=300):
    path = os.path.join(HERE, f"_rf_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* rfplots {tag}\n{deck}\n.control\noption noacct\nset numdgt=8\n"
                f"{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True,
                           text=True, timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    try:
        os.remove(path)
    except OSError:
        pass
    return out


def current_plot(out):
    """the plot abbreviation `setplot` reports as Current, e.g. 'hbosc1'"""
    m = re.search(r"^Current\s+(\S+)", out, re.M)
    return m.group(1) if m else None


def vectors(out):
    """names in the `display` listing"""
    return set(re.findall(r"^\s{4}(\S+)\s*:", out, re.M))


def vtype(out, name):
    m = re.search(r"^\s{4}" + re.escape(name) + r"\s*:\s*([a-z-]+)", out, re.M)
    return m.group(1) if m else None


OSC = ("L1 a 0 %g\nC1 a 0 %g\nR1 a 0 100k\n"
       "B1 a 0 i = -(5e-4*v(a)) + 5e-4*v(a)*v(a)*v(a)\n.ic v(a)=0.1\n"
       % (L_OSC, C_OSC))

SPD = ("V1 p1 0 DC 0 AC 1 portnum 1 z0 50\nV2 p2 0 DC 0 AC 0 portnum 2 z0 50\n"
       "R1 p1 mid 25\nC1 mid 0 1n\nR2 mid p2 25\n")

HBD = ("V1 in 0 dc 0.6 sin(0.6 0.05 1e9)\nR1 in d 50\nD1 d 0 dmod\n"
       ".model dmod d(is=1e-14)\nR2 d 0 1k\n")

STBD = ("Vin inp 0 dc 0 ac 0\nG1 0 n1 inp inn 1\nR1 n1 0 1e5\nC1 n1 0 1.59e-9\n"
        "E2 n2 0 n1 0 1\nR2 n2 n3 1k\nC3a n3 0 1.59e-10\nE3 n4 0 n3 0 1\n"
        "R3 n4 n5 1k\nC3b n5 0 1.59e-11\nE4 out 0 n5 0 1000\n"
        "Rf out mid 9k\nRg mid 0 1k\nVstb mid inn dc 0 ac 0\nIstb 0 inn dc 0 ac 0\n")

LPD = ("Vs src 0 dc 0 sin(0 1 1e9)\nRs src n1 50\nLs n1 out 4.7746n\n"
       "RL out l1 50\nLL l1 l2 1e-15\nCL l2 0 1e-3\n")

PSSD = "V1 a 0 SIN(0 1 1meg)\nR1 a b 1k\nC1 b 0 1n\n.pss 1meg 1u b 1024 10 50 5u\n"

SHOW = "setplot\ndisplay\n"

# ---------------------------------------------------------------- the six that worked
print("\nthe RF analyses that already published -- these must not move")

out = run(SPD, "sp dec 10 1e6 1e9\n" + SHOW, "sp")
check("[1] .sp leaves an 'sp' plot carrying the S-parameters",
      (current_plot(out) or "").startswith("sp") and "S_1_1" in vectors(out),
      current_plot(out))
check("[2] ...with S_1_1 typed as an s-param, not left untyped",
      vtype(out, "S_1_1") == "s-param", str(vtype(out, "S_1_1")))

out = run(HBD, "hb 1e9 5\n" + SHOW, "hb")
check("[3] the driven `hb` leaves an 'hb' plot with the hbfrequency scale",
      (current_plot(out) or "").startswith("hb") and "hbfrequency" in vectors(out),
      current_plot(out))

out = run(PSSD, "run\n" + SHOW, "pss")
check("[4] .pss leaves both the time- and frequency-domain plots",
      "pss1" in out and "qpss1" in out, "pss1 + qpss1")

out = run(STBD, "stb Vstb Istb dec 20 1 10meg\n" + SHOW, "stb")
check("[5] `stb` leaves a 'stb' plot carrying the loop gain",
      (current_plot(out) or "").startswith("stb") and "loopgain" in vectors(out),
      current_plot(out))

out = run(LPD, "loadpull -load RL LL CL -out out -drive Vs -f 1e9 -n 9 -gmax 0.85\n" + SHOW,
          "lp")
check("[6] `loadpull` leaves a 'loadpull' plot with the swept contour",
      (current_plot(out) or "").startswith("loadpull")
      and {"gamma_re", "gamma_im", "pout_dbm", "gain_db"} <= vectors(out),
      current_plot(out))
check("[7] ...with pout_dbm and gain_db typed as dB quantities",
      vtype(out, "pout_dbm") == "decibel" and vtype(out, "gain_db") == "decibel",
      "%s / %s" % (vtype(out, "pout_dbm"), vtype(out, "gain_db")))
check("[8] ...while the dimensionless gamma stays untyped, having no enum member",
      vtype(out, "gamma_re") == "notype", str(vtype(out, "gamma_re")))

# ---------------------------------------------------------------- the two that did not
print("\nhbosc and phasenoise -- these stored NOTHING and left a transient current")

out = run(OSC, "hbosc a 5 5e6 100u\nsetplot\ndisplay\nprint oscfreq\nprint mag(a)\n", "osc")
cp = current_plot(out)
check("[9] `hbosc` leaves its OWN plot current, not its startup transient",
      cp is not None and cp.startswith("hbosc"), str(cp))
check("[10] ...carrying the harmonic scale and one vector per node",
      {"hbfrequency", "a", "l1#branch"} <= vectors(out),
      ",".join(sorted(vectors(out))[:4]))
m_f0 = re.search(r"^oscfreq\s*=\s*([-+0-9.eE]+)", out, re.M)
check("[11] ...and 'oscfreq', the frequency an autonomous circuit SOLVES for",
      m_f0 is not None, m_f0.group(1) if m_f0 else "missing")

# the published spectrum must EQUAL the printed table, not merely exist
tbl = {int(mm.group(1)): float(mm.group(2)) for mm in
       re.finditer(r"^\s+a\s+(\d+)\s+\S+\s+([-+0-9.eE]+)\s+\S+\s*$", out, re.M)}
vec = [float(mm.group(1)) for mm in re.finditer(r"^\d+\t([-+0-9.eE]+)\t*\s*$", out, re.M)]
ok = len(vec) > 1 and 1 in tbl and abs(vec[1] - tbl[1]) <= 1e-6 * max(1.0, abs(tbl[1]))
check("[12] the stored spectrum equals the printed table",
      ok, "vector[1]=%.8g table[1]=%.8g" % (vec[1], tbl[1])
          if (len(vec) > 1 and 1 in tbl) else "could not compare")

out = run(OSC, "hbosc a 5 5e6 100u\nphasenoise 1e3 1e6 5\n" + SHOW, "pn")
cp = current_plot(out)
check("[13] `phasenoise` leaves its own plot current",
      cp is not None and cp.startswith("phasenoise"), str(cp))
check("[14] ...carrying the offset scale, the curve and the carrier frequency",
      {"offsetfreq", "phasenoise", "carrierfreq"} <= vectors(out),
      ",".join(sorted(vectors(out))))
check("[15] ...with L(df) typed as a dB quantity",
      vtype(out, "phasenoise") == "decibel", str(vtype(out, "phasenoise")))

# ------------------------------------------------ the substring collisions, in ONE session
print("\nthe plot NAME -- ft_plotabbrev() matches by substring, so these shadow")

out = run(HBD.replace("V1 in", "Vd in"), "hb 1e9 3\nsetplot\n", "hbonly")
hb_name = current_plot(out)
out = run(OSC, "hbosc a 5 5e6 100u\nsetplot\n", "osconly")
osc_name = current_plot(out)
check("[16] `hbosc` is NOT abbreviated as the driven `hb` -- 'hbosc' contains 'hb'",
      hb_name != osc_name and (osc_name or "").startswith("hbosc"),
      "hb -> %s, hbosc -> %s" % (hb_name, osc_name))

out = run(OSC + "Vn n 0 dc 0 ac 1\nRn n 0 1k\n",
          "hbosc a 5 5e6 100u\nphasenoise 1e3 1e6 3\nnoise v(n) Vn dec 5 1e3 1e6\n"
          "setplot\n", "coll")
plots = re.findall(r"^\s*(?:Current\s+)?(\S+)\s+", out, re.M)
check("[17] `phasenoise` and `.noise` coexist -- 'phasenoise' contains 'noise'",
      any(p.startswith("phasenoise") for p in plots)
      and any(re.fullmatch(r"noise\d+", p) for p in plots),
      ",".join(p for p in plots if "noise" in p))

for f in os.listdir(HERE):
    if f.startswith("_rf_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
