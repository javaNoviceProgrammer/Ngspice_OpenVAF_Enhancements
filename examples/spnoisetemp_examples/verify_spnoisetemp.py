#!/usr/bin/env python3
"""verify_spnoisetemp.py -- Enhancement-901: `.sp`'s noise figure, NFmin and Rn
are normalised by the IEEE standard temperature T0 = 290 K. F7 of the analyses
correctness campaign of 2026-10-16.

span.c divided the noise correlation matrix by 4k*CKTtemp. The IEEE noise
figure is defined with the source at T0 = 290 K; a passive two-port at physical
temperature T has F = 1 + (T/T0)(1/Ga - 1). ngspice computed 1/Ga, which holds
only at T = T0. The reference here is the network itself: every resistor's
4kT/R, at its own temperature, folded to the ports' short-circuit currents,
transformed to the chain form and normalised by 4kT0.

  [1] a 100 ohm / 100 ohm attenuator between 50 ohm ports at 27 C: NF, NFmin
      and Rn as the IEEE definition gives them (E-899: NF 8.7506 dB against
      8.8804, Rn 3.4 % low)
  [2] the same at 16.85 C, T = T0: NF = 10*log10(1/Ga), as before
  [3] a series 100 ohm resistor at 27 C: Rn = R*T/T0 = 103.5 ohm (E-899: 100)
  [4] a resistive T network at 125 C and at -40 C: NF, NFmin and Rn (E-899:
      1.2 dB and 0.82 dB off)
  [5] an active stage (a VCCS with resistors and capacitors) at 60 C: NF,
      NFmin, Rn and SOpt at four frequencies (E-899: NF 0.34 dB off, Rn 13 %)
  [6] a series resistor at temp=-196 C in a circuit at 27 C: NF follows the
      resistor's own temperature, F = 1 + (T_R/T0) R/Z0 (E-899: T_R/300.15)
  [7] Cy itself is unchanged: 4kT Re(Y) at the circuit's temperature, here
      125 C (E-899 too)

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="spnoisetemp_")
K_B = 1.38064852e-23          # ngspice's CONSTboltz
T0 = 290.0
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def deck(els, tc, z0=(50.0, 50.0), fs=(1e6,)):
    """els: (kind, a, b, value[, temp]) on nodes 1..n; ports on nodes 1 and 2"""
    L = ["* sp noise reference temperature"]
    for i, e in enumerate(els):
        k, a, b, v = e[:4]
        if k == "G":
            c, d, g = v
            L.append("g%d %d %d %d %d %r" % (i, a, b, c, d, g))
        else:
            L.append("%s%d %d %d %r%s" % (k.lower(), i, a, b, v, " temp=%r" % e[4] if len(e) > 4 else ""))
    L += ["vp1 1 0 dc 0 ac 1 portnum 1 z0 %r" % z0[0], "vp2 2 0 dc 0 ac 0 portnum 2 z0 %r" % z0[1],
          ".temp %r" % tc, ".control", "set wr_singlescale", "set numdgt=15",
          "sp lin %d %r %r 1" % (len(fs), fs[0], fs[-1]) if len(fs) > 1 else "sp lin 1 %r %r 1" % (fs[0], fs[0]),
          "wrdata %s Y_1_1 Y_1_2 Y_2_1 Y_2_2 Cy_1_1 Cy_1_2 Cy_2_1 Cy_2_2 NF NFmin Rn SOpt",
          ".endc", ".end", ""]
    return "\n".join(L)


def run(name, els, tc, **kw):
    path = os.path.join(WORK, name + ".cir")
    out_txt = os.path.join(WORK, name + ".txt")
    with open(path, "w") as f:
        f.write(deck(els, tc, **kw).replace("wrdata %s", "wrdata " + out_txt))
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
        log = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return [], "TIMEOUT"
    rows = []
    try:
        for line in open(out_txt):
            x = [float(t) for t in line.split()]
            c = lambda q: complex(x[1 + 2 * q], x[2 + 2 * q])
            rows.append(dict(f=x[0], Y=np.array([[c(0), c(1)], [c(2), c(3)]]),
                             Cy=np.array([[c(4), c(5)], [c(6), c(7)]]),
                             NF=c(8).real, NFmin=c(9).real, Rn=c(10).real, Sopt=c(11)))
    except (OSError, ValueError, IndexError):
        pass
    return rows, log


def reference(els, tc, f, z0=(50.0, 50.0)):
    """the noise parameters by the IEEE definition, from the network's resistors"""
    n = max(max(e[1], e[2]) for e in els)
    w = 2 * math.pi * f
    Y = np.zeros((n + 1, n + 1), dtype=complex)
    CJ = np.zeros((n + 1, n + 1), dtype=complex)

    def stamp(M, a, b, y):
        M[a, a] += y; M[b, b] += y; M[a, b] -= y; M[b, a] -= y
    for e in els:
        k, a, b, v = e[:4]
        if k == "R":
            stamp(Y, a, b, 1 / v)
            stamp(CJ, a, b, 4 * K_B * ((e[4] if len(e) > 4 else tc) + 273.15) / v)
        elif k == "C":
            stamp(Y, a, b, 1j * w * v)
        elif k == "L":
            stamp(Y, a, b, 1 / (1j * w * v))
        else:
            c, d, g = v
            Y[a, c] += g; Y[a, d] -= g; Y[b, c] -= g; Y[b, d] += g
    Y, CJ = Y[1:, 1:], CJ[1:, 1:]
    P, I = [0, 1], list(range(2, n))
    T = np.zeros((2, n), dtype=complex); T[0, 0] = T[1, 1] = 1
    Yp = Y[np.ix_(P, P)]
    if I:
        Yii_inv = np.linalg.inv(Y[np.ix_(I, I)])
        Yp = Yp - Y[np.ix_(P, I)] @ Yii_inv @ Y[np.ix_(I, P)]
        T[:, I] = -Y[np.ix_(P, I)] @ Yii_inv
    Cy = T @ CJ @ T.conj().T
    y11, y21 = Yp[0, 0], Yp[1, 0]
    TA = np.array([[0, -1 / y21], [1, -y11 / y21]])
    CA = TA @ Cy @ TA.conj().T
    k4 = 4 * K_B * T0
    Rn = CA[0, 0].real / k4
    Ycor = CA[1, 0] / CA[0, 0]
    Gu = (CA[1, 1].real - abs(Ycor) ** 2 * CA[0, 0].real) / k4
    Ys = 1 / z0[0]
    F = 1 + (Gu + Rn * abs(Ys + Ycor) ** 2) / Ys
    Gopt = math.sqrt(max(Ycor.real ** 2 + Gu / Rn, 0.0))
    Yopt = complex(Gopt, -Ycor.imag)
    return dict(Y=Yp, Cy=Cy, NF=10 * math.log10(F), NFmin=10 * math.log10(1 + 2 * Rn * (Ycor.real + Gopt)),
                Rn=Rn, Sopt=(Ys - Yopt) / (Ys + Yopt))


def compare(rows, els, tc, z0=(50.0, 50.0), what=("NF", "NFmin", "Rn")):
    """the largest deviation of each quantity: dB for NF/NFmin, relative for Rn, absolute for SOpt"""
    if not rows:
        return None
    e = dict.fromkeys(what, 0.0)
    for r in rows:
        R = reference(els, tc, r["f"], z0)
        for q in what:
            d = abs(r[q] / R[q] - 1) if q == "Rn" else abs(r[q] - R[q])
            e[q] = max(e[q], d)
    return e


def fmt(e):
    return "no result" if e is None else ", ".join(
        "%s %.2g%s" % (q, v, " dB" if q.startswith("NF") else "") for q, v in e.items())


def good(e, tol_db=1e-6, tol_rel=1e-9):
    return e is not None and all(v < (tol_db if q.startswith("NF") else tol_rel) for q, v in e.items())


print("Enhancement-901: .sp noise parameters at the IEEE T0 = 290 K")

ATT = [("R", 1, 2, 100.0), ("R", 2, 0, 100.0)]
rows, log = run("att27", ATT, 27.0)
e = compare(rows, ATT, 27.0)
nf = rows[0]["NF"] if rows else None
check("[1] 100/100 ohm attenuator at 27 C: NF, NFmin, Rn as the IEEE definition gives them",
      good(e), "NF %s dB; %s" % ("%.4f" % nf if nf is not None else "?", fmt(e)))

rows, log = run("att290", ATT, 16.85)
nf = rows[0]["NF"] if rows else None
check("[2] the same at 16.85 C (T = T0): NF = 10*log10(1/Ga) = 8.7506 dB, as before",
      nf is not None and abs(nf - 10 * math.log10(7.5)) < 1e-6, "NF %s dB" % nf)

SER = [("R", 1, 2, 100.0)]
rows, log = run("ser", SER, 27.0)
rn = rows[0]["Rn"] if rows else None
check("[3] a series 100 ohm resistor at 27 C: Rn = R*T/T0 = 103.5 ohm",
      rn is not None and abs(rn / (100.0 * 300.15 / T0) - 1) < 1e-9, "Rn %s" % rn)

TEE = [("R", 1, 3, 33.0), ("R", 3, 0, 68.0), ("R", 3, 2, 47.0)]
res = []
for tc in (125.0, -40.0):
    rows, log = run("tee%d" % (tc + 100), TEE, tc)
    res.append((tc, compare(rows, TEE, tc)))
check("[4] a resistive T network at 125 C and at -40 C: NF, NFmin and Rn",
      all(good(e) for _, e in res), "; ".join("%g C: %s" % (tc, fmt(e)) for tc, e in res))

AMP = [("R", 1, 0, 1000.0), ("C", 1, 3, 2e-12), ("R", 3, 0, 200.0), ("G", 2, 0, (3, 0, 0.04)),
       ("R", 2, 0, 500.0), ("C", 3, 2, 0.2e-12), ("R", 1, 3, 25.0)]
rows, log = run("amp", AMP, 60.0, z0=(50.0, 75.0), fs=(1e7, 1e8, 1e9, 1e10))
e = compare(rows, AMP, 60.0, z0=(50.0, 75.0), what=("NF", "NFmin", "Rn", "Sopt"))
check("[5] an active stage at 60 C: NF, NFmin, Rn and SOpt at four frequencies",
      good(e) and len(rows) == 4, fmt(e))

COLD = [("R", 1, 2, 100.0, -196.0)]
rows, log = run("cold", COLD, 27.0)
nf = rows[0]["NF"] if rows else None
want = 10 * math.log10(1 + (77.15 / T0) * 100.0 / 50.0)
check("[6] a series resistor at temp=-196 C, circuit at 27 C: F = 1 + (T_R/T0) R/Z0",
      nf is not None and abs(nf - want) < 1e-6, "NF %s dB, want %.6f" % (nf, want))

rows, log = run("cy125", ATT, 125.0)
cy = None
if rows:
    Y = rows[0]["Y"]
    want = 2 * K_B * 398.15 * (Y + Y.conj().T)
    cy = float(np.max(np.abs(rows[0]["Cy"] - want)) / np.max(np.abs(want)))
check("[7] Cy itself is unchanged: 4kT Re(Y) at the circuit's 125 C",
      cy is not None and cy < 1e-9, "relative %s" % ("%.1e" % cy if cy is not None else "?"))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
