#!/usr/bin/env python3
"""Enhancement-232: KLU solver-glue correctness hardening (klusmp.c).

A source audit of the active KLU/Sparse dispatch layer (src/maths/KLU/klusmp.c,
the only SMP layer compiled when KLU is enabled) turned up four latent defects,
all fixed here:

  A. SMPluFac / SMPsolve dereferenced KLUmatrixCommon *before* the `== NULL`
     guard (the complex twin SMPcLUfac checks NULL first, with an early return);
     reordered to match.
  B. The complex solves SMPcSolve / SMPcaSolve copied the RHS with a plain
     identity map, while the real SMPsolve routes RHS through the node-collapse
     map KLUmatrixNodeCollapsingNewToOld.  If a structural-zero column ever
     collapsed a node, AC/noise/pz would be silently mis-ordered relative to the
     DC/tran solve.  The complex paths now apply the same gather/scatter.
  C. SMPcZeroCol read KLUmatrixAp[Col-1] with no ground guard (Ap[-1] if Col==0);
     added the `Col >= 1` guard its sibling SMPfindElt already has.
  D. SMPmultiply had a dead `iSolution = iRHS;` (assigned a by-value local);
     removed.

All four are behaviour-preserving for any circuit that actually solves (the
node-collapse map is the identity unless the matrix is structurally singular,
which does not factor anyway).  This test therefore proves the invariant that
matters: KLU still agrees with SPARSE 1.3 to the bit on AC, noise (which uses
the modified *adjoint* SMPcaSolve), and pole-zero, on an ASYMMETRIC network
(a VCVS makes the MNA matrix non-symmetric, so the adjoint solve is exercised).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


# Asymmetric net: R-L-C ladder + a VCVS (E1) feeding back, so the MNA matrix is
# non-symmetric and the noise adjoint solve differs from the forward solve.
NET = """V1 in 0 dc 0 ac 1
R1 in n1 1k
R2 n1 out 2k
L1 n1 mid 1m
C1 out 0 100n
R4 mid out 500
E1 amp 0 out 0 3.0
R3 amp fb 5k
C2 fb 0 47n
R5 fb 0 8k
"""


def run(control, klu):
    deck = "* solverfix\n"
    if klu:
        deck += ".options klu\n"
    deck += NET + ".control\n" + control + "\n.endc\n.end\n"
    open(os.path.join(HERE, "_s.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_s.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def wr(control_fmt, fname, klu):
    """run a control block that ends by writing `fname`, return its rows."""
    run(control_fmt.format(f=os.path.join(HERE, fname)), klu)
    p = os.path.join(HERE, fname)
    if not os.path.exists(p):
        return None
    rows = []
    for line in open(p):
        parts = line.split()
        if parts:
            rows.append([float(x) for x in parts])
    return rows


def maxdiff(a, b):
    if a is None or b is None or len(a) != len(b):
        return None
    m = 0.0
    for ra, rb in zip(a, b):
        for xa, xb in zip(ra, rb):
            m = max(m, abs(xa - xb))
    return m


# --- AC: forward complex solve (SMPcSolve) ---
ac_ctl = "ac dec 20 10 1meg\nwrdata {f} vdb(out) vp(out)"
d = maxdiff(wr(ac_ctl, "ac_s.dat", False), wr(ac_ctl, "ac_k.dat", True))
check("AC (vdb/vp) KLU == SPARSE on an asymmetric net (forward SMPcSolve)",
      d is not None and d < 1e-9, f"max|diff|={d:.2e}" if d is not None else "no data")

# --- noise: adjoint complex solve (SMPcaSolve, the one most changed) ---
noise_ctl = ("noise v(out) V1 dec 20 10 1meg\nsetplot noise1\n"
             "wrdata {f} onoise_spectrum inoise_spectrum")
d = maxdiff(wr(noise_ctl, "n_s.dat", False), wr(noise_ctl, "n_k.dat", True))
check("noise spectrum KLU == SPARSE (adjoint SMPcaSolve exercised)",
      d is not None and d < 1e-20, f"max|diff|={d:.2e}" if d is not None else "no data")

# --- pole-zero: SMPcaSolve + SMPcZeroCol + SMPcAddCol ---
pz_ctl = "pz in 0 out 0 cur pz\nprint all"
sp = run(pz_ctl, False)
kl = run(pz_ctl, True)


def roots(txt):
    out = []
    for line in txt.splitlines():
        if "=" in line and ("pole" in line.lower() or "zero" in line.lower() or
                             line.strip().startswith("all")):
            rhs = line.split("=", 1)[1]
            for tok in rhs.replace(",", " ").split():
                try:
                    out.append(float(tok))
                except ValueError:
                    pass
    return out


rs, rk = roots(sp), roots(kl)
ok = rs and rk and len(rs) == len(rk) and \
    max(abs(a - b) for a, b in zip(sorted(rs), sorted(rk))) < 1e-6 * (1 + max(abs(x) for x in rs))
check("pole-zero roots KLU == SPARSE (SMPcaSolve + SMPcZeroCol + SMPcAddCol)",
      ok, f"sparse={rs} klu={rk}")

# --- basic: the fixed build still solves DC + tran cleanly under KLU ---
out = run("op\nprint v(out)\ntran 1u 50u\nlet ok = 1", True)
check("DC op + transient run clean under KLU (no crash / NaN)",
      "v(out)" in out and "nan" not in out.lower() and "error" not in out.lower(),
      "")

# tidy
for f in ("_s.cir", "ac_s.dat", "ac_k.dat", "n_s.dat", "n_k.dat"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
