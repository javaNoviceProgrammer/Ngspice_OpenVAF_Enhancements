#!/usr/bin/env python3
"""Enhancement-173: eigenvalue-based pole-zero root finder (.options pzeig).

The classic spice3 pole-zero driver hunts the roots of det(G + sC) with a
Muller iteration on determinant values -- famously fragile (iteration limits,
noise-floor stalls). `.options pzeig` switches `.pz` to a direct dense
eigenvalue method built on the same CKTpzSetup/CKTpzLoad machinery:

    A(s) = G + s*C  is extracted densely from two loads (s=0, s=1; a third
    load verifies affinity); the roots of det(G + sC) = 0 are the finite
    eigenvalues of the pencil, computed by SHIFT-INVERT linearization --
    factor (G + sigma*C) once at a non-root shift with the circuit's own
    sparse solver, form M = (G+sigma*C)^{-1} C by n sparse solves, and run a
    classical balance/Hessenberg/Francis-QR eigensolver (new maths/dense/eig.c):
    every finite root is s = sigma - 1/mu, and the pencil's infinite
    eigenvalues land harmlessly at mu = 0.

Checks (the eig method under BOTH solvers, anchored analytically and compared
with the Muller method where Muller works):
  [1] series RLC: complex-conjugate pole pair, exact under eig, both solvers.
  [2] 10-section RC ladder: ALL TEN poles match the analytic tridiagonal
      eigenvalue formula s_k = -(2 - 2cos((2k-1)pi/21))/(RC) -- and match
      Muller's roots, root for root.
  [3] RLC bandpass: Muller under Sparse hits its iteration limit ("giving up
      after N trials"); eig produces the identical correct roots with NO
      warning.
  [4] twin-T notch: all 6 roots (3 poles, real zero, conjugate notch pair at
      +-j1e6) under eig, both solvers.
  [5] RLC bandstop: purely imaginary zeros +-j1e6 -- exact under eig.
  [6] balanced (differential) output works under eig too, both solvers.
  [7] a purely resistive circuit (C = 0: every pencil eigenvalue infinite)
      yields no roots and no crash, either method.
  [8] the default remains the Muller method (without `.options pzeig` the
      bandpass still shows Muller's iteration-limit warning).

This is a front-end-of-analysis feature independent of the dual-solver
harness: the verify drives both solvers and both methods itself.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
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

SCRATCH = tempfile.mkdtemp(prefix="pzeig_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_pz(body, pzcard, solver, eig):
    opt = f".option {solver} pzeig" if eig else f".option {solver}"
    deck = (f"* pz\n{opt}\nv1 in 0 dc 0 ac 1\n{body}\n"
            f".control\n{pzcard}\nset numdgt=10\nprint all\n.endc\n.end\n")
    path = os.path.join(SCRATCH, "d.cir")
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    out = r.stdout + r.stderr
    roots = []
    for m in re.finditer(r"(pole|zero)\(\d+\)\s*=\s*([-\d.eE+]+),([-\d.eE+]+)", out):
        roots.append((m.group(1), float(m.group(2)), float(m.group(3))))
    if not roots:
        for m in re.finditer(r"all\s*=\s*([-\d.eE+]+),([-\d.eE+]+)", out):
            roots.append(("root", float(m.group(1)), float(m.group(2))))
    return sorted(roots), out


def same_roots(a, b, reltol=1e-6, abstol_frac=1e-6):
    if len(a) != len(b):
        return False
    scale = max([max(abs(r), abs(i)) for _, r, i in a + b] + [1.0])
    for (ka, ra, ia), (kb, rb, ib) in zip(a, b):
        if ka != kb:
            return False
        if abs(ra - rb) > reltol * scale + abstol_frac * scale:
            return False
        if abs(ia - ib) > reltol * scale + abstol_frac * scale:
            return False
    return True


RLC = "r1 in n1 10\nl1 n1 out 1m\nc1 out 0 1n"
BP = "l1 in n1 1m\nc1 n1 out 1n\nr1 out 0 100"
TT = ("r1 in n1 1k\nr2 n1 out 1k\nc3 n1 0 2n\nc1 in n2 1n\nc2 n2 out 1n\n"
      "r3 n2 0 500\nrl out 0 100k")
BS = "r1 in out 1k\nl1 out n1 1m\nc1 n1 0 1n\nrload out 0 10k"
BRIDGE = "r1 in a 1k\nc1 a 0 1n\nr2 in b 2k\nc2 b 0 1n"
LADDER = "\n".join(f"r{k} {'in' if k == 1 else 'n%d' % (k-1)} n{k} 1k\nc{k} n{k} 0 1n"
                   for k in range(1, 11))

# [1] series RLC under eig, both solvers, vs analytic
for sol in ("sparse", "klu"):
    roots, _ = run_pz(RLC, "pz in 0 out 0 vol pol", sol, eig=True)
    ok = (len(roots) == 2
          and all(abs(r + 5000.0) < 1.0 for _, r, _ in roots)
          and any(abs(i - 999987.5) < 1.0 for _, _, i in roots)
          and any(abs(i + 999987.5) < 1.0 for _, _, i in roots))
    check(f"[1] series RLC conjugate pole pair exact under eig ({sol})", ok,
          f"({roots})")

# [2] 10-pole ladder: eig vs analytic and vs muller
analytic = sorted(-(2.0 - 2.0 * math.cos((2 * k - 1) * math.pi / 21.0)) / 1e-6
                  for k in range(1, 11))
for sol in ("sparse", "klu"):
    eg, _ = run_pz(LADDER, "pz in 0 n10 0 vol pol", sol, eig=True)
    mu, _ = run_pz(LADDER, "pz in 0 n10 0 vol pol", sol, eig=False)
    got = sorted(r for _, r, _ in eg)
    ok = (len(got) == 10
          and all(abs(g - a) < 1e-3 * abs(a) for g, a in zip(got, analytic))
          and same_roots(eg, mu))
    check(f"[2] 10-pole RC ladder: eig == analytic == muller ({sol})", ok,
          f"({len(eg)} eig roots, {len(mu)} muller roots)")

# [3] bandpass: muller warns (iteration limit) under sparse; eig is clean + identical
mu, mu_out = run_pz(BP, "pz in 0 out 0 vol pz", "sparse", eig=False)
eg, eg_out = run_pz(BP, "pz in 0 out 0 vol pz", "sparse", eig=True)
check("[3] RLC bandpass: eig has NO iteration-limit warning and matches Muller's roots",
      "iteration limit" not in eg_out and same_roots(eg, mu),
      f"(muller warns: {'iteration limit' in mu_out}; roots {len(eg)}=={len(mu)})")

# [4] twin-T: all 6 roots under eig, both solvers
for sol in ("sparse", "klu"):
    eg, _ = run_pz(TT, "pz in 0 out 0 vol pz", sol, eig=True)
    pair = [x for x in eg if x[0] == "zero" and abs(abs(x[2]) - 1e6) < 1.0]
    ok = len(eg) == 6 and len(pair) == 2
    check(f"[4] twin-T: all 6 roots incl. conjugate notch pair under eig ({sol})",
          ok, f"({len(eg)} roots)")

# [5] bandstop: purely imaginary zeros exact
eg, _ = run_pz(BS, "pz in 0 out 0 vol pz", "sparse", eig=True)
zz = [x for x in eg if x[0] == "zero"]
ok = (len(zz) == 2 and all(abs(r) < 1.0 and abs(abs(i) - 1e6) < 1.0 for _, r, i in zz))
check("[5] RLC bandstop: purely imaginary zeros +-j1e6 exact under eig", ok, f"({zz})")

# [6] balanced output under eig, both solvers
for sol in ("sparse", "klu"):
    eg, _ = run_pz(BRIDGE, "pz in 0 a b vol pz", sol, eig=True)
    pol = sorted(r for k, r, _ in eg if k == "pole")
    ok = (len(pol) == 2 and abs(pol[0] + 1e6) < 1.0 and abs(pol[1] + 5e5) < 1.0)
    check(f"[6] balanced (differential) output works under eig ({sol})", ok, f"({eg})")

# [7] purely resistive: no roots, no crash, either method
for eig in (False, True):
    roots, out = run_pz("r1 in out 1k\nr2 out 0 1k", "pz in 0 out 0 vol pol",
                        "sparse", eig=eig)
    check(f"[7] resistive circuit: no poles, no crash ({'eig' if eig else 'muller'})",
          len(roots) == 0 and "Segm" not in out)

# [8] default stays Muller (bandpass without pzeig still shows the warning)
check("[8] default method remains Muller (no pzeig -> iteration-limit warning present)",
      "iteration limit" in mu_out)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
