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

Enhancement-172 extends this: SMPcAddCol gained a KLU branch (with the union
sparsity pattern reserved in CKTpzSetup), so BALANCED / DIFFERENTIAL-output
pole-zero now runs under KLU (it was guarded off as unsupported), and the
out-of-range pivot-tolerance fallback became FULL partial pivoting (tol=1.0):
KLU's ordering is fixed at analyze time (pattern-only), so PZ's ~20-decade |s|
sweep needs the strongest within-block pivoting to keep the determinant accurate
(with the old 0.001 default, far-field factorizations went catastrophically
inaccurate -- wrong sign AND magnitude vs an exact rational determinant --
minting spurious roots at |s| ~ 1e19..1e21).  Checks [7]-[9] cover the balanced
output forms and the twin-T notch that previously stalled.

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

# [7] balanced (differential) output: RC bridge, out = v(a)-v(b)
#     poles -1/(R1C1) = -1e6 and -1/(R2C2) = -5e5, single zero at the origin.
#     Was "not supported with 'option KLU'" before E-172.
compare("[7] balanced output: differential RC bridge (was unsupported under KLU)",
        "r1 in a 1k\nc1 a 0 1n\nr2 in b 2k\nc2 b 0 1n",
        "pz in 0 a b vol pz",
        expect=[("pole", -1e6, 0.0), ("pole", -5e5, 0.0), ("zero", 0.0, 0.0)])

# [8] balanced output with a complex pole pair (RLC branch vs RC branch)
compare("[8] balanced output: complex poles across a floating pair",
        "rr in a 10\nll a c 1m\ncc c 0 1n\nrx in b 1k\ncx b 0 1n",
        "pz in 0 c b vol pol",
        expect=[("pole", -5000.0, 999987.5), ("pole", -1e6, 0.0)])

# [9] twin-T notch: 3 poles + real zero + conjugate notch pair at +-j1e6.
#     The conjugate pair used to stall under KLU (found 4 of 6 roots) until the
#     full-partial-pivoting fallback kept the far-field determinant accurate.
compare("[9] twin-T notch: deflated conjugate zero pair (was stalling under KLU)",
        "r1 in n1 1k\nr2 n1 out 1k\nc3 n1 0 2n\nc1 in n2 1n\nc2 n2 out 1n\nr3 n2 0 500\nrl out 0 100k",
        "pz in 0 out 0 vol pz",
        expect=[("zero", 0.0, 1e6)])

# ---------------------------------------------------------------------------
# Enhancement-737 -- F4 of the second solver-core hunt (2026-09-25): the same
# common-emitter stage gave 2, 3 or 5 poles depending on the solver, its knobs
# and the deck's line order.  The determinant near a far root is at its
# rounding floor, and the Muller driver (cktpzstr.c) lost its sign-change
# bracket there (an endpoint replaced by magnitude, which is noise at the
# floor), read the three same-sign points as a magnitude minimum, and went
# hunting a conjugate pair that is not there until its iteration limit.  Now
# a bracket keeps its crossing, Muller's two companions to a complex start sit
# at half and twice its imaginary part instead of j1e8 and j1e12, and the
# outward march stops once the deflated determinant is flat over 1e16 (every
# remaining root is then beyond 1e22, the search's own horizon), and a
# real-axis magnitude minimum whose three values agree to 2^-33 is taken at
# once instead of being refined until two trials coincide by chance.
# ---------------------------------------------------------------------------

def pz_run(deck_body, pzcard, solver, opts=""):
    """Full deck body (sources included).  Returns (sorted roots, output)."""
    opt = f".option {solver}" + (f" {opts}" if opts else "")
    deck = (f"* pz\n{opt}\n{deck_body}\n.control\n{pzcard}\nset numdgt=12\n"
            f"print all\n.endc\n.end\n")
    path = os.path.join(SCRATCH, "e737.cir")
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    out = r.stdout + r.stderr
    roots = []
    for m in re.finditer(r"(pole|zero)\(\d+\)\s*=\s*([-\d.eE+]+),([-\d.eE+]+)", out):
        roots.append((m.group(1), float(m.group(2)), float(m.group(3))))
    return sorted(roots), out


def poles_are(roots, expect, tol):
    """Every expected pole (a complex number) is matched by one found pole to
    tol relative, and there are no others."""
    pol = [complex(r, i) for k, r, i in roots if k == "pole"]
    if len(pol) != len(expect):
        return False
    left = pol[:]
    for e in expect:
        best = min(left, key=lambda z: abs(z - e))
        if abs(best - e) > tol * max(abs(e), 1e-300):
            return False
        left.remove(best)
    return True


def gave_up(out):
    return "giving up" in out


CE = """Vcc vcc 0 12
Vin in 0 dc 0.7 ac 1
Rs in b 1k
Rb1 vcc b 100k
Rb2 b 0 22k
Q1 c b e qm
.model qm npn(bf=150 is=1e-15 cje=2p cjc=1p tf=0.3n rb=50)
Rc vcc c 4.7k
Re e 0 1k
Ce e 0 100u
Cc c out 10u
Rl out 0 100k
Cs out 0 1p
Lp c c2 1n
Rp c2 0 1e9"""
# the three lines the hunt moved to the top (five poles under KLU either way now)
CE_MOVED = "Lp c c2 1n\nRp c2 0 1e9\nCs out 0 1p\n" + "\n".join(
    l for l in CE.splitlines() if not l.startswith(("Lp ", "Rp ", "Cs ")))
# the five poles both solvers agree on (E-736 Sparse; -Rp/Lp = -1e18 is real)
CE_POLES = [-1e18, -5.9265028e8, -5.7692869e7, -53.963296, -0.95510995]

# [10] the hunt's failure: KLU default gave -53.963 and -0.95511 and
#      "iteration limit reached; giving up after 218 trials"
kl, out = pz_run(CE, "pz in 0 out 0 vol pol", "klu")
check("[10] CE stage under KLU (default): five poles, no 'giving up' (was 2 and a warning)",
      poles_are(kl, CE_POLES, 1e-4) and not gave_up(out),
      f"({len([1 for k, _, _ in kl if k == 'pole'])} poles)")

# [11] the knobs that gave 3 (btf off, scale none) or 5 (scale sum, colamd):
#      five under every one, identical to the default's to 1e-6
for opts in ("klu_btf=off", "klu_scale=none", "klu_scale=sum", "klu_ordering=colamd"):
    r, o = pz_run(CE, "pz in 0 out 0 vol pol", "klu", opts)
    check(f"[11] CE stage under KLU {opts}: the same five poles, no warning",
          poles_are(r, CE_POLES, 1e-4) and same_roots(r, kl) and not gave_up(o),
          f"({len([1 for k, _, _ in r if k == 'pole'])} poles)")

# [12] Sparse found the five before; it still does, and they are KLU's
sp, o = pz_run(CE, "pz in 0 out 0 vol pol", "sparse")
check("[12] CE stage under Sparse: the same five poles as KLU (1e-6), no warning",
      poles_are(sp, CE_POLES, 1e-4) and same_roots(sp, kl) and not gave_up(o))

# [13] the deck's line order changes the matrix order, not the answer
r, o = pz_run(CE_MOVED, "pz in 0 out 0 vol pol", "klu")
check("[13] CE stage with Lp, Rp, Cs moved to the top (KLU): the same five poles",
      poles_are(r, CE_POLES, 1e-4) and same_roots(r, kl) and not gave_up(o))

# [14] the hunt's six-element RLC ladder over twelve decades: both solvers gave
#      up after 236 trials with three poles.  The exact roots of det(G + sC)
#      (characteristic polynomial over the rationals, degree 6): three real,
#      a conjugate pair at -5e11 +- j3.16e13 and one at -1e15.
RLC = """V1 in 0 dc 0 ac 1
R1 in a 1
L1 a b 1e-12
C1 b 0 1e-15
R2 b c 1e6
L2 c d 1e-3
C2 d 0 1e-18
R3 d e 1e3
C3 e 0 1e-6
R4 e out 1e9
C4 out 0 1e-12
Rl out 0 1e12"""
RLC_POLES = [-0.999000002995, -1001.001, -1001000999.0,
             complex(-499999999500.0, 3.16188235233e13),
             complex(-499999999500.0, -3.16188235233e13), -9.99999999001e14]
for sol in ("sparse", "klu"):
    r, o = pz_run(RLC, "pz in 0 out 0 vol pol", sol)
    check(f"[14] six-element RLC ladder ({sol}): all six exact roots incl. the pair "
          f"at +-j3.16e13 and -1e15, no warning (was 3 and 'giving up after 236')",
          poles_are(r, RLC_POLES, 1e-6) and not gave_up(o),
          f"({len([1 for k, _, _ in r if k == 'pole'])} poles)")

# [15] the RLC bandpass of [6]: Sparse used to give up after 231 trials once
#      the pair was found -- the outward march reached the rounding zone at
#      +-1e21 and trapped on a chance minimum there
r, o = pz_run("v1 in 0 dc 0 ac 1\nl1 in n1 1m\nc1 n1 out 1n\nr1 out 0 100",
              "pz in 0 out 0 vol pz", "sparse")
check("[15] RLC bandpass under Sparse: the pair and the origin zero, no 'giving up' "
      "(was a warning after 231 trials)",
      poles_are(r, [complex(-5e4, 998749.217772), complex(-5e4, -998749.217772)], 1e-6)
      and any(k == "zero" and abs(re) < 1.0 for k, re, _ in r) and not gave_up(o))

# [16] the CE stage's linear twin (the hunt's: Sparse gave up with 3 of 5):
#      exact roots of its characteristic polynomial
LIN = """Vcc vcc 0 12
Vin in 0 dc 0.7 ac 1
Rs in b 1k
Rb1 vcc b 100k
Rb2 b 0 22k
Rbb b bi 50
Rpi bi e 3.9k
Cpi bi e 20p
Cmu bi c 1p
G1 c e bi e 0.038
Ro c e 100k
Rc vcc c 4.7k
Re e 0 1k
Ce e 0 100u
Cc c out 10u
Rl out 0 100k
Cs out 0 1p
Lp c c2 1n
Rp c2 0 1e9"""
LIN_POLES = [-0.955181035262, -301.757666387, -6491633.69063, -1100972078.43, -1e18]
for sol in ("sparse", "klu"):
    r, o = pz_run(LIN, "pz in 0 out 0 vol pol", sol)
    check(f"[16] linear CE twin ({sol}): the five exact poles, no warning",
          poles_are(r, LIN_POLES, 1e-6) and not gave_up(o),
          f"({len([1 for k, _, _ in r if k == 'pole'])} poles)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
