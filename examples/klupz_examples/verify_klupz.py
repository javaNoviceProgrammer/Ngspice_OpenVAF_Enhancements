#!/usr/bin/env python3
"""Enhancement-171: KLU pole-zero -- complex determinant + pivot tolerance.

A deep audit of the KLU<->SMP solver bridge (maths/KLU/klusmp.c) found that
pole-zero analysis under `.option klu` silently produced GARBAGE for any circuit
with complex poles or zeros, through two independent defects:

  1. spDeterminant_KLU built each pivot as the mixed quantity
     (1/(Ux*Rs), Uz*Rs) and took its complex reciprocal.  That is correct ONLY
     when the pivot is real (Uz == 0) -- so real-axis poles/zeros came out right
     (and passed the existing regression) while every complex-plane determinant
     evaluation was garbage: a series RLC reported four bogus real poles instead
     of its conjugate pair.  (The real branch was worse still: its product loop
     never even ran -- the loop index was left at N by the preceding permutation
     scan -- it divided instead of multiplying, never wrote the imaginary part,
     and both branches computed the permutation sign as #non-fixed-points/2,
     which is wrong for any cycle longer than 2.)

  2. Pole-zero calls SMPcReorder with PivRel = 0.0.  Sparse's spOrderAndFactor
     SANITIZES a non-positive threshold to its default; the KLU branch passed it
     straight to Common->tol, making KLU accept an EXACTLY-ZERO diagonal as a
     pivot.  At the s = 0 trial an inductor branch has a 0.0 diagonal, so the
     factorization came back KLU_SINGULAR and PZ recorded a spurious root at the
     origin (and the poisoned Muller search never expanded past |s| ~ 10).

With both fixed, the determinant under KLU matches Sparse to ~14 digits at every
trial point and the E-113-era "finite-zero computation is not supported with
KLU" guard is removed (its root cause was defect 2).

Checks -- each circuit's FULL pole/zero root set under KLU vs Sparse:
  [1] series RLC: the complex-conjugate pole pair (was 4 bogus real poles)
  [2] RC lowpass: single real pole (the case that always worked -- no regression)
  [3] lead network: real pole + real finite zero
  [4] RC highpass: pole + zero at the origin
  [5] RLC bandstop: complex poles + PURELY IMAGINARY zeros (the hardest case)
  [6] RLC bandpass: complex poles + origin zero (finite-zero search under KLU,
      previously guarded off as unsupported)

The dual-solver harness is NOT used here: this verify drives both solvers itself
(the comparison across solvers is the check).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

SCRATCH = tempfile.mkdtemp(prefix="klupz_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def pz_roots(body, pzcard, solver):
    """Run a .pz and return sorted (kind, re, im) root tuples."""
    deck = f"* pz\n.option {solver}\nv1 in 0 dc 0 ac 1\n{body}\n.control\n{pzcard}\nset numdgt=10\nprint all\n.endc\n.end\n"
    path = os.path.join(SCRATCH, "d.cir")
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=60, cwd=SCRATCH)
    roots = []
    for m in re.finditer(r"(pole|zero)\(\d+\)\s*=\s*([-\d.eE+]+),([-\d.eE+]+)",
                         r.stdout + r.stderr):
        roots.append((m.group(1), float(m.group(2)), float(m.group(3))))
    # single-root prints come out as "all = re,im" with no pole()/zero() label
    if not roots:
        for m in re.finditer(r"all\s*=\s*([-\d.eE+]+),([-\d.eE+]+)",
                             r.stdout + r.stderr):
            roots.append(("root", float(m.group(1)), float(m.group(2))))
    return sorted(roots)


def same_roots(a, b, reltol=1e-6):
    if len(a) != len(b):
        return False
    for (ka, ra, ia), (kb, rb, ib) in zip(a, b):
        if ka != kb:
            return False
        scale = max(abs(ra), abs(ia), abs(rb), abs(ib), 1.0)
        if abs(ra - rb) > reltol * scale or abs(ia - ib) > reltol * scale:
            return False
    return True


def compare(name, body, pzcard, expect=None):
    sp = pz_roots(body, pzcard, "sparse")
    kl = pz_roots(body, pzcard, "klu")
    ok = len(sp) > 0 and same_roots(sp, kl)
    detail = f"(sparse {len(sp)} roots == klu {len(kl)} roots)"
    if not ok:
        detail = f"(sparse={sp} klu={kl})"
    if ok and expect:
        # anchor the shared answer against the analytic expectation
        for kind, ere, eim in expect:
            hit = any(k == kind and abs(r - ere) <= 1e-3 * max(abs(ere), 1.0)
                      and abs(abs(i) - abs(eim)) <= 1e-3 * max(abs(eim), 1.0)
                      for k, r, i in sp)
            if not hit:
                ok = False
                detail = f"(analytic anchor {kind} {ere}+-j{eim} missing: {sp})"
                break
    check(name, ok, detail)


# [1] series RLC: sigma = R/2L = 5000, w = sqrt(1/LC - sigma^2) ~ 999987.5
compare("[1] series RLC: complex-conjugate pole pair identical across solvers",
        "r1 in n1 10\nl1 n1 out 1m\nc1 out 0 1n",
        "pz in 0 out 0 vol pol",
        expect=[("pole", -5000.0, 999987.5)])

# [2] RC lowpass: pole at -1/RC = -1e6 rad/s
compare("[2] RC lowpass: single real pole (no regression on the old-good case)",
        "r1 in out 1k\nc1 out 0 1n",
        "pz in 0 out 0 vol pol",
        expect=[("root", -1e6, 0.0)])

# [3] lead network: zero -1/(R1 C1) = -1e6, pole -1/((R1||R2) C1) = -2e6
compare("[3] lead network: real pole + real finite zero",
        "r1 in out 1k\nc1 in out 1n\nr2 out 0 1k",
        "pz in 0 out 0 vol pz",
        expect=[("pole", -2e6, 0.0), ("zero", -1e6, 0.0)])

# [4] RC highpass: zero at the origin, pole at -1e6
compare("[4] RC highpass: origin zero + real pole",
        "c1 in out 1n\nr1 out 0 1k",
        "pz in 0 out 0 vol pz",
        expect=[("pole", -1e6, 0.0), ("zero", 0.0, 0.0)])

# [5] bandstop: notch zeros at +-j/sqrt(LC) = +-j1e6 (purely imaginary!)
compare("[5] RLC bandstop: complex poles + purely imaginary zeros",
        "r1 in out 1k\nl1 out n1 1m\nc1 n1 0 1n\nrload out 0 10k",
        "pz in 0 out 0 vol pz",
        expect=[("zero", 0.0, 1e6)])

# [6] bandpass: origin zero + complex poles (the finite-zero search KLU used to
#     guard off as unsupported)
compare("[6] RLC bandpass: finite-zero search under KLU (was 'not supported')",
        "l1 in n1 1m\nc1 n1 out 1n\nr1 out 0 100",
        "pz in 0 out 0 vol pz",
        expect=[("pole", -5e4, 998749.2), ("zero", 0.0, 0.0)])

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
