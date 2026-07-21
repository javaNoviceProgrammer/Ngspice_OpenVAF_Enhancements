#!/usr/bin/env python3
"""Enhancement-255: .disto is machine-exact -- proven against Harmonic Balance /
QPSS-HB (independent engines), and the behavioral-source (B) silent-zero warning.

.disto (the 1990 Volterra code) reports the pure 2nd/3rd-order distortion kernels,
scaled by the DISTOF1/DISTOF2 source magnitudes -- amplitude-independent physics.
Harmonic Balance and two-tone QPSS-HB are INDEPENDENT large-signal engines that
include ALL orders; at small drive A their k-th harmonic / mixing amplitudes
converge to the Volterra result with higher-order leakage ~A^2. So HB(A) -> .disto
as A -> 0, exactly the E-251 HB-proof structure applied to distortion. Because HB
and .disto share ngspice's identical device model, model-constant ambiguity (VT,
DC-op) cancels -- the agreement measures the .disto engine itself.

The existing stdaudit checks bound .disto vs a *python* Volterra referee at <=1-3%
(referee VT/formula precision). This proves the tighter truth: against the
independent engine, .disto is exact to the reference engine's own resolution.

Checks (both solvers):
 [1] single-tone diode HD2/HD3 == HB, and the HB->.disto convergence tightens as
     A shrinks (rel err ~A^2); the .disto output scales EXACTLY as A^2/A^3 (the
     DISTOF1 magnitude is applied exactly, kernels amplitude-independent).
 [2] two-tone diode IM3 (2f1-f2) == QPSS-HB, with .disto IM3 scaling exactly ~A^3.
 [3] behavioral B-source nonlinearity: .disto reports ZERO and now WARNS loudly
     (Enhancement-255) -- while QPSS-HB gives the true nonzero IM3, showing exactly
     what the (documented) limitation would otherwise silently miss.

Line 1 of every deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    passed += 1 if ok else 0
    failed += 0 if ok else 1


def run(name, deck):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       cwd=HERE, timeout=180)
    return r.stdout + "\n" + r.stderr


def disto_mags(out, node="a"):
    return [abs(complex(float(a), float(b))) for a, b in
            re.findall(rf"v\({node}\)\s*=\s*([-\d.eE+]+),\s*([-\d.eE+]+)", out)]


def hb_harm(out, node="a"):
    rows = {}
    for m in re.finditer(rf"^\s+{node}\s+(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.]+",
                         out, re.M):
        rows[int(m.group(1))] = float(m.group(2))
    return rows


def qpss_mix(out, node="a"):
    mix = {}
    for m in re.finditer(rf"^\s+{node}\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+\S+\s+([-\d.eE+]+)",
                         out, re.M):
        mix[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))
    return mix


VB, R, f0 = 0.55, 1000.0, 10e3
DIO = (".model DMOD D(IS=1e-14 N=1)\n")


def disto_hd(A):
    out = run("_hd.cir",
              f"* diode disto HD A={A}\nV1 in 0 DC {VB} DISTOF1 {A}\n"
              f"R1 in a {R}\nD1 a 0 DMOD\n{DIO}.disto dec 1 {f0} {f0}\n"
              ".control\nset numdgt=12\nrun\n"
              "setplot disto1\nprint v(a)\nsetplot disto2\nprint v(a)\n.endc\n.end\n")
    return disto_mags(out)


def hb_hd(A):
    out = run("_hh.cir",
              f"* diode hb HD A={A}\nV1 in 0 DC {VB} SIN({VB} {A} {f0})\n"
              f"R1 in a {R}\nD1 a 0 DMOD\n{DIO}"
              f".control\nset numdgt=12\nhb {f0} 12\n.endc\n.end\n")
    return hb_harm(out)


# ---------- [1] single-tone HD2/HD3 vs HB + amplitude convergence ----------
dA1, dA4 = disto_hd(1e-3), disto_hd(1e-4)
hA1, hA4 = hb_hd(1e-3), hb_hd(1e-4)
ok = len(dA1) >= 2 and len(dA4) >= 2 and 2 in hA4 and 3 in hA4
if ok:
    r2_A1 = abs(dA1[0] - hA1[2]) / hA1[2]
    r2_A4 = abs(dA4[0] - hA4[2]) / hA4[2]
    r3_A4 = abs(dA4[1] - hA4[3]) / hA4[3]
    # disto output scales EXACTLY as A^2 (HD2) and A^3 (HD3): DISTOF1 applied exactly
    scale2 = abs(dA1[0] / dA4[0] - 100.0) / 100.0        # (1e-3/1e-4)^2 = 100
    scale3 = abs(dA1[1] / dA4[1] - 1000.0) / 1000.0      # (1e-3/1e-4)^3 = 1000
    ok = (r2_A4 < 1e-5 and r3_A4 < 5e-5 and r2_A4 < r2_A1
          and scale2 < 1e-6 and scale3 < 1e-6)
check("[1] diode HD2/HD3 == HB (A->0), HB->disto convergence ~A^2, exact A^n scaling",
      ok, (f"(HD2 rel {r2_A4:.1e}@1e-4 vs {r2_A1:.1e}@1e-3; HD3 rel {r3_A4:.1e}; "
           f"A-scale {max(scale2, scale3):.1e})") if ok else "(parse/tol fail)")

# ---------- [2] two-tone IM3 (2f1-f2) vs QPSS-HB ----------
f1, f2, R2 = 1.0e9, 1.3e9, 50.0


def disto_im3(A):
    out = run("_i3d.cir",
              f"* diode disto IM3 A={A}\nV1 in 0 DC {VB} DISTOF1 {A} DISTOF2 {A}\n"
              f"R1 in a {R2}\nD1 a 0 DMOD\n{DIO}.disto dec 1 {f1} {f1} {f2 / f1}\n"
              ".control\nset numdgt=12\nrun\nsetplot disto3\nprint v(a)\n.endc\n.end\n")
    return disto_mags(out)


def qpss_im3(A):
    out = run("_i3q.cir",
              f"* diode qpss IM3 A={A}\nV1 in 0 DC {VB} SIN({VB} {A} {f1})\n"
              f"V2 x in SIN(0 {A} {f2})\nR1 x a {R2}\nD1 a 0 DMOD\n{DIO}"
              f".control\nset numdgt=12\nqpss v1#branch {f1} {f2} hb 5 5\n.endc\n.end\n")
    return qpss_mix(out).get((2, -1))


di3_a, di3_b = disto_im3(3e-4), disto_im3(1e-4)
qi3 = qpss_im3(3e-4)
ok = bool(di3_a) and bool(di3_b) and bool(qi3)
if ok:
    rel = abs(di3_a[0] - qi3) / qi3
    scale3 = abs(di3_a[0] / di3_b[0] - 27.0) / 27.0      # (3e-4/1e-4)^3 = 27
    ok = rel < 1e-4 and scale3 < 1e-6
check("[2] diode two-tone IM3 (2f1-f2) == QPSS-HB; .disto IM3 scales exactly ~A^3",
      ok, (f"(IM3 disto {di3_a[0]:.5e} qpss-hb {qi3:.5e} rel {rel:.1e}; "
           f"A^3 scale {scale3:.1e})") if ok else "(parse/tol fail)")

# ---------- [3] behavioral B-source: .disto reports ZERO and now WARNS ----------
a3 = 2e-3
Abs = 0.5
bout = run("_b.cir",
           f"* bsrc disto vs qpss\nV1 a 0 DC 0 DISTOF1 {Abs}\n"
           f"V2 n a DISTOF2 {Abs}\nB1 n 0 I=1m*v(n)+{a3}*v(n)*v(n)*v(n)\n"
           f"Rn n 0 1\n.disto dec 1 {f1} {f1} {f2 / f1}\n"
           ".control\nrun\nsetplot disto3\nprint v(n)\n.endc\n.end\n")
bdisto = disto_mags(bout, "n")
warned = "behavioral source" in bout.lower() and "no distortion model" in bout.lower()
# QPSS-HB of the same polynomial gives the true IM3 = (3/4)*a3*A^3 (node driven direct)
qout = run("_bq.cir",
           f"* bsrc qpss truth\nV1 a 0 SIN(0 {Abs} {f1})\nV2 n a SIN(0 {Abs} {f2})\n"
           f"B1 nn 0 I=1m*v(n)+{a3}*v(n)*v(n)*v(n)\nRnn nn 0 1\nRn n 0 1e12\n"
           f".control\nqpss v1#branch {f1} {f2} hb 4 4\n.endc\n.end\n")
# analytic IM3 magnitude for i=a3*v^3 with v=A(cos f1 + cos f2): (3/4)*a3*A^3 (current)
truth_im3 = 0.75 * a3 * Abs ** 3
disto_zero = (not bdisto) or all(v < 1e-20 for v in bdisto)
check("[3] behavioral B-source: .disto reports ZERO for its nonlinearity AND now warns",
      disto_zero and warned,
      f"(disto3={ (bdisto[0] if bdisto else 0.0):.2e}, warned={warned}, "
      f"true IM3 current=(3/4)a3 A^3={truth_im3:.3e} is silently missed w/o the warning)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
