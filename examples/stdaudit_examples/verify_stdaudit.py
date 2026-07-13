#!/usr/bin/env python3
"""Enhancement-179: standard-analyses audit -- .tf/.sens/.disto/.noise/.pz/.meas
referee battery + three fixes.

THE AUDIT. The gap-analysis doc marks the "Standard analyses (analog)" table all
on-par, but several of those rows are 1990s SPICE3 code whose VALUES had never
been checked against independent physics (the E-171/175/177/178
accidental-correctness lesson). This suite embeds the referees; the audit found
and fixed:

  1. `.tf` with a CURRENT output (`.tf i(vm) vin`) always reported output
     impedance 1e20: tfanal.c clamped `1/MAX(1e-20, rhs)` where the branch
     current of the unit forcing is NEGATIVE for every passive network (the
     input-impedance path right above divides by -rhs). Inherited verbatim
     from Berkeley SPICE3 -- a 35-year-old bug.
  2. KLU AC sensitivity silently truncated to ONE frequency point: the E-114
     KLU complex-conversion block inside the frequency loop reused `i` -- the
     outer loop variable -- so after the first point i = DEVmaxnum ended the
     sweep. Values at the surviving point were correct, which is why the
     single-point E-62 check passed.
  3. `.meas DERIV{ATIVE}` was parsed but NEVER evaluated (an explicit
     'currently not supported' stub with an empty `#if 0 measure_deriv()`
     placeholder) -- now implemented: 3-point Lagrange-quadratic derivative on
     the nonuniform time grid, AT= and WHEN forms; the INTEGRAL and DERIVATIVE
     long spellings are now accepted (only INTEG/DERIV matched before).

MEASURED-CORRECT (the rest of the table, referee'd here):
  - `.disto` (Volterra, 1990 code): HD2/HD3 against an analytic diode Volterra
    referee INCLUDING a frequency-dependent load (harmonic loads evaluated at
    Z(2w)/Z(3w) -- the E-177-style frequency-bug probe comes back clean), the
    SIM2 two-tone path (f1+f2, f1-f2, 2f1-f2), exact Volterra amplitude
    scaling, and nonlinear-junction-capacitance harmonics that agree with the
    E-134 Harmonic Balance engine to ~6 digits -- two independent engines.
  - `.noise` integrals: onoise_total^2 equals the band-limited analytic
    (-> kT/C wide-band) and the flicker log-integral KF*I^2*ln(f2/f1)*Zt^2 to
    6 digits (Nintegrate's power-law integration is exact for 1/f).
  - `.sens`: DC sensitivities at a NONLINEAR operating point (dv/dRs, dv/dIS)
    match central finite differences to 5-6 digits; AC dV/dC matches the
    analytic derivative -jwR/(1+jwRC)^2 to 6 digits below/at/above the pole.
  - `.pz` at a nonlinear OP works -- the E-62 'nonlinear pz quirk' was the
    input CONVENTION (a bias source on the injection node shorts it; ngspice's
    refusal is correct): the driving-point form `.pz a 0 a 0 cur pol` returns
    the linearized pole -(1/Rs + gd)/C exactly.
  - `.meas` RMS/AVG/PP/INTEG/WHEN on an analytic sine to ~1e-6.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_deck(name, deck):
    path = os.path.join(HERE, name)
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return r.stdout + r.stderr


def cxvals(out):
    """complex values from both indexed-table and scalar print forms"""
    vals = [complex(float(m.group(1)), float(m.group(2)))
            for m in re.finditer(r"^\d+\s+[\d.eE+-]+\s+([-\d.eE+]+),\s*([-\d.eE+]+)",
                                 out, re.M)]
    vals += [complex(float(m.group(2)), float(m.group(3)))
             for m in re.finditer(r"^(v\([a-z0-9]+\)|all) = ([-\d.eE+]+),([-\d.eE+]+)",
                                  out, re.M)]
    return vals


def scalars(out):
    return dict((m.group(1).lower(), float(m.group(2)))
                for m in re.finditer(r"^(\S+)\s*=\s*([-\d.eE+]+)", out, re.M))


IS, VT = 1e-14, 0.025864                       # 300.15 K, N=1
KB, T = 1.380649e-23, 300.15


def dc_op(vb, rs):
    v = 0.5
    for _ in range(300):
        e = math.exp(v / VT)
        f = (vb - v) / rs - IS * (e - 1)
        df = -1 / rs - IS * e / VT
        dv = -f / df
        if abs(dv) > 2 * VT:
            dv = math.copysign(2 * VT, dv)
        v += dv
        if abs(dv) < 1e-16:
            break
    return v, IS * (math.exp(v / VT) - 1)


# ---------------- [1] .disto HD vs Volterra, frequency-dependent load ----------------
VB, R, C = 0.55, 1000.0, 100e-9
A = 1e-3
v0, I0 = dc_op(VB, R)
g1, g2, g3 = I0 / VT, I0 / (2 * VT * VT), I0 / (6 * VT ** 3)
Z = lambda w: 1 / (1 / R + g1 + 1j * w * C)
out = run_deck("_hd.cir", f"""* disto hd
V1 in 0 DC {VB} DISTOF1 {A}
R1 in a {R}
D1 a 0 DMOD
C1 a 0 {C}
.model DMOD D(IS=1e-14 N=1)
.disto dec 2 1k 10k
.control
run
setplot disto1
print v(a)
setplot disto2
print v(a)
.endc
.end
""")
vals = cxvals(out)
freqs = [1e3, 10 ** 3.5, 1e4]
ok = len(vals) >= 6
worst = 0.0
for i, f in enumerate(freqs):
    w = 2 * math.pi * f
    v1 = A * Z(w) / R
    r2 = -g2 * v1 * v1 / 2 * Z(2 * w)
    r3 = -(g3 * v1 ** 3 / 4 + g2 * v1 * r2) * Z(3 * w)
    if ok:
        worst = max(worst, abs(abs(vals[i]) - abs(r2)) / abs(r2),
                    abs(abs(vals[3 + i]) - abs(r3)) / abs(r3))
check("[1] .disto HD2/HD3 == Volterra referee w/ frequency-dependent load (<=1%)",
      ok and worst < 0.01, f"(worst rel err {worst:.2e}, 130:1 dynamic range)")

# ---------------- [2] .disto SIM2 intermods + scaling ----------------
VB2, R2, A1, A2 = 0.55, 10.0, 1e-3, 0.5e-3
v0, I0 = dc_op(VB2, R2)
g1, g2, g3 = I0 / VT, I0 / (2 * VT * VT), I0 / (6 * VT ** 3)
rd = 1 / g1
Zr = R2 * rd / (R2 + rd)
v1a, v1b = A1 * rd / (R2 + rd), A2 * rd / (R2 + rd)
im2 = g2 * v1a * v1b * Zr
dim3 = 0.75 * g3 * v1a * v1a * v1b * Zr
SIM = f"""V1 in 0 DC {VB2} DISTOF1 {A1} DISTOF2 {{a2}}
R1 in a {R2}
D1 a 0 DMOD
.model DMOD D(IS=1e-14 N=1)
.disto dec 1 10k 10k 0.09
.control
run
setplot disto1
print v(a)
setplot disto2
print v(a)
setplot disto3
print v(a)
.endc
.end
"""
va = cxvals(run_deck("_s2a.cir", "* sim2 a\n" + SIM.format(a2=A2)))
vb = cxvals(run_deck("_s2b.cir", "* sim2 b\n" + SIM.format(a2=2 * A2)))
ok = (len(va) >= 3 and len(vb) >= 3 and
      abs(abs(va[0]) - im2) < 0.01 * im2 and          # f1+f2
      abs(abs(va[1]) - im2) < 0.01 * im2 and          # f1-f2
      abs(abs(va[2]) - dim3) < 0.03 * dim3 and        # 2f1-f2 (cascade ~2%)
      abs(abs(vb[0]) / abs(va[0]) - 2) < 1e-3 and     # DISTOF2 honored, linear
      abs(abs(vb[2]) / abs(va[2]) - 2) < 1e-3)
check("[2] .disto SIM2: f1+-f2 and 2f1-f2 == Volterra referee; DISTOF2 scaling exact",
      ok, f"(IM2 {abs(va[0]):.4e} ref {im2:.4e})" if va else "(no data)")

# ---------------- [3] .disto nonlinear junction cap == Harmonic Balance ----------------
CJ = """V1 in 0 DC 0.55 {stim}
R1 in a 1000
D1 a 0 DMOD
.model DMOD D(IS=1e-14 N=1 CJO=10n VJ=0.7 M=0.5)
{card}
.control
{ctrl}
.endc
.end
"""
dv = cxvals(run_deck("_cjd.cir", "* cj disto\n" + CJ.format(
    stim="DISTOF1 0.001", card=".disto dec 1 100k 100k",
    ctrl="run\nsetplot disto1\nprint v(a)\nsetplot disto2\nprint v(a)")))
hout = run_deck("_cjh.cir", "* cj hb\n" + CJ.format(
    stim="SIN(0.55 0.001 100k)", card="", ctrl="hb 100k 6"))
hrows = dict((int(m.group(1)), float(m.group(2))) for m in re.finditer(
    r"^\s+a\s+(\d+)\s+[\d.eE+-]+\s+([\d.eE+-]+)\s+[-\d.]+", hout, re.M))
ok = (len(dv) >= 2 and 2 in hrows and 3 in hrows and
      abs(abs(dv[0]) - hrows[2]) < 0.01 * hrows[2] and
      abs(abs(dv[1]) - hrows[3]) < 0.01 * hrows[3])
check("[3] .disto junction-cap harmonics == Harmonic Balance (independent engine, <=1%)",
      ok, f"(v2: disto {abs(dv[0]):.5e} hb {hrows.get(2, 0):.5e})" if dv else "(no data)")

# ---------------- [4] .noise integrals: kT/C band limit + flicker log-integral ----------------
Rn, Cn = 1e3, 1e-9
f1n, f2n = 1e-2, 1e12
xf = lambda f: 2 * math.pi * Rn * Cn * f
band = (2 * KB * T / (math.pi * Cn)) * (math.atan(xf(f2n)) - math.atan(xf(f1n)))
out = run_deck("_ni.cir", f"""* noise integral
V1 in 0 DC 0 AC 1
R1 in a {Rn}
C1 a 0 {Cn}
.noise v(a) v1 dec 20 {f1n} {f2n}
.control
run
setplot noise2
print onoise_total
.endc
.end
""")
tot = scalars(out).get("onoise_total", 0.0)
ok1 = abs(tot * tot - band) < 5e-3 * band
KFr, Ra, Rb = 1e-9, 1e3, 1e3
Ifl = 1.0 / (Ra + Rb)
Zt = Ra * Rb / (Ra + Rb)
flick = KFr * Ifl * Ifl * math.log(1e6 / 1.0) * Zt * Zt
therm = 4 * KB * T * (1 / Ra + 1 / Rb) * Zt * Zt * (1e6 - 1.0)
out = run_deck("_nf.cir", f"""* flicker integral
VDC a 0 DC 1
R1 a b rmod {Ra}
RL b 0 {Rb}
Iac 0 b AC 1
.model rmod R(kf={KFr} af=2 ef=1)
.noise v(b) iac dec 10 1 1e6
.control
run
setplot noise2
print onoise_total
.endc
.end
""")
tf_ = scalars(out).get("onoise_total", 0.0)
ok2 = abs(tf_ * tf_ - (flick + therm)) < 1e-3 * (flick + therm)
check("[4] .noise integrals: onoise_total^2 == kT/C band analytic + flicker KF*I^2*ln(f2/f1)",
      ok1 and ok2, f"(kT/C ratio {tot*tot/band:.5f}, flicker ratio {tf_*tf_/(flick+therm):.5f})")

# ---------------- [5] .tf: exact feedback amp + the current-output Rout fix ----------------
TFB = """Vin in 0 DC 0
E1 x 0 in fb 1000
Ro x out 100
Rf out fb 9k
Rg fb 0 1k
RL out {rl}
"""
gain = 1000 / 101.11
out = run_deck("_tfv.cir", "* tf v\n" + TFB.format(rl="0 1k") +
               ".tf v(out) vin\n.control\nrun\nprint all\n.endc\n.end\n")
s = scalars(out)
ok1 = (abs(s.get("transfer_function", 0) - gain) < 1e-6 * gain and
       abs(s.get("output_impedance_at_v(out)", 0) - gain / 10) < 1e-6 * gain / 10)
out = run_deck("_tfi.cir", "* tf i\n" + TFB.format(rl="m 1k") + "Vm m 0 DC 0\n" +
               ".tf i(vm) vin\n.control\nrun\nprint all\n.endc\n.end\n")
s = scalars(out)
# exact: current gain = gain/1000; Rout(vm branch) = RL + node Thevenin 0.98991
rout_i = 1000.0 + 1 / 1.01010
ok2 = (abs(s.get("transfer_function", 0) - gain / 1000) < 1e-6 * gain / 1000 and
       abs(s.get("vm#output_impedance", 0) - rout_i) < 1e-4 * rout_i)
ok3 = s.get("vm#output_impedance", 0) < 1e19          # pre-fix signature absent
check("[5] .tf exact (gain/Rout); CURRENT-output impedance fixed (was pinned to 1e20)",
      ok1 and ok2 and ok3,
      f"(vm Rout {s.get('vm#output_impedance', 0):.6g}, exact {rout_i:.6f})")

# ---------------- [6] .sens: nonlinear DC vs FD; AC dv/dC full sweep (KLU fix) ----------------
VBs, RSs = 0.75, 200.0
out = run_deck("_sd.cir", f"""* sens dc
Vb in 0 DC {VBs}
Rs in a {RSs}
D1 a 0 DMOD
.model DMOD D(IS=1e-14 N=1)
.sens v(a)
.control
run
print rs d1:is
.endc
.end
""")
s = scalars(out)
h = 1e-6
fd_rs = (dc_op(VBs, RSs * (1 + h))[0] - dc_op(VBs, RSs * (1 - h))[0]) / (2 * RSs * h)


def dc_op_is(is_, vb, rs):
    global IS
    sav = IS
    IS = is_
    v = dc_op(vb, rs)[0]
    IS = sav
    return v


fd_is = (dc_op_is(IS * (1 + h), VBs, RSs) - dc_op_is(IS * (1 - h), VBs, RSs)) / (2 * IS * h)
ok1 = (abs(s.get("rs", 0) - fd_rs) < 1e-4 * abs(fd_rs) and
       abs(s.get("d1:is", 0) - fd_is) < 1e-4 * abs(fd_is))
Rc, Cc = 1e3, 1e-9
out = run_deck("_sa.cir", f"""* sens ac
V1 in 0 DC 0 AC 1
R1 in a {Rc}
C1 a 0 {Cc}
.sens v(a) ac dec 1 15915.494 1591549.4
.control
run
print c1
.endc
.end
""")
vals = cxvals(out)
ok2 = len(vals) == 3            # pre-fix KLU: exactly 1 row survived
worst = 1.0
if ok2:
    worst = 0.0
    for f, v in zip([15915.494, 159154.94, 1591549.4], vals):
        w = 2 * math.pi * f
        ref = -1j * w * Rc / (1 + 1j * w * Rc * Cc) ** 2
        worst = max(worst, abs(v - ref) / abs(ref))
check("[6] .sens: nonlinear-OP DC == finite difference; AC dv/dC sweep COMPLETE == analytic "
      "(KLU used to truncate to 1 point)", ok1 and ok2 and worst < 1e-4,
      f"({len(vals)} AC rows, worst rel err {worst:.2e})")

# ---------------- [7] .pz at a nonlinear operating point (driving-point form) ----------------
v0, I0 = dc_op(0.75, 200.0)
gd = IS * math.exp(v0 / VT) / VT
pole = -(1 / 200.0 + gd) / 1e-9                      # ngspice prints pz roots in rad/s
out = run_deck("_pz.cir", """* pz nonlinear
Vb in 0 DC 0.75
Rs in a 200
D1 a 0 DMOD
C1 a 0 1n
.model DMOD D(IS=1e-14 N=1)
.pz a 0 a 0 cur pol
.control
run
print all
.endc
.end
""")
vals = cxvals(out)
ok = len(vals) == 1 and abs(vals[0].real - pole) < 2e-3 * abs(pole) and vals[0].imag == 0
check("[7] .pz at nonlinear OP: driving-point pole == analytic -(1/Rs+gd)/C (<=0.2%)",
      ok, f"(got {vals[0].real if vals else 0:.6e} rad/s, ref {pole:.6e} rad/s -- the E-62 "
          f"'quirk' was the input convention, not a pz defect)")

# ---------------- [8] .meas battery incl. the new DERIV + long aliases ----------------
out = run_deck("_ms.cir", """* meas battery
V1 a 0 SIN(0 2 1k)
R1 a 0 1k
.tran 1u 3m
.meas tran vrms RMS v(a) from=0 to=2m
.meas tran vpp PP v(a) from=0 to=3m
.meas tran tcross WHEN v(a)=0 CROSS=2
.meas tran vint INTEG v(a) from=0 to=0.5m
.meas tran vint2 INTEGRAL v(a) from=0 to=0.5m
.meas tran dpeak DERIV v(a) AT=0.25m
.meas tran dwhen DERIVATIVE v(a) WHEN v(a)=1 CROSS=1
.control
run
.endc
.end
""")
m = scalars(out)
Aa, fs = 2.0, 1e3
w = 2 * math.pi * fs
refs_ok = (abs(m.get("vrms", 9) - Aa / math.sqrt(2)) < 1e-4 and
           abs(m.get("vpp", 9) - 2 * Aa) < 1e-3 and
           abs(m.get("tcross", 9) - 1e-3) < 1e-8 and
           abs(m.get("vint", 9) - Aa / w * (1 - math.cos(w * 0.5e-3))) < 1e-8 and
           m.get("vint2", 9) == m.get("vint", 8))
dref = Aa * w * math.cos(math.asin(0.5))              # slope where v=1 rising
deriv_ok = (abs(m.get("dpeak", 9e9)) < 1e-2 * Aa * w and       # ~0 at the crest
            abs(m.get("dwhen", 0) - dref) < 1e-3 * dref)
check("[8] .meas battery exact; DERIV AT/WHEN implemented (was 'currently not supported')",
      refs_ok and deriv_ok,
      f"(dwhen {m.get('dwhen', 0):.6g} ref {dref:.6g}; INTEGRAL alias == INTEG)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
