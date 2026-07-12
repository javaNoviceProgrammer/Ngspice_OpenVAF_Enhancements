#!/usr/bin/env python3
"""
verify_qpss.py -- Enhancement-133: quasi-periodic (two-tone) steady state.

`qpss <expr> <f1> <f2> [periods] [maxorder]` computes the two-tone steady-state
spectrum -- every mixing product k1*f1 + k2*f2, including the third-order
intermodulation (IM3) that a single-tone analysis cannot show. For two
commensurate tones (a rational ratio, common beat fb = gcd(f1,f2)) the circuit is
periodic at fb; qpss runs a transient over a few beat periods to reach steady
state, then evaluates the Fourier coefficient DIRECTLY at each exact intermod
frequency k1*f1 + k2*f2 (a direct DFT, exact -- no FFT-bin rounding), labelling
each product by its 2-D harmonic index (k1, k2).

The reference is a memoryless weak nonlinearity i = g1*v + g3*v^3 driven by two
tones v = A(sin w1 t + sin w2 t). The cubic term produces analytically-known
products: fundamentals, IM3 at 2f1-f2 / 2f2-f1, IM5 sums, 3f, and NO even-order
terms. Each check runs qpss and compares.

Independent of the linear solver (qpss drives an ordinary transient).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_qpss"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


_ROW = re.compile(r"\(\s*(-?\d+),\s*(-?\d+)\)\s+([-\d.eE+]+)\s+([-\d.eE+]+)")

def qpss(deck):
    """run a deck and return {(k1,k2): (freq, mag)} plus the beat frequency."""
    out = run(deck)
    spec = {}
    for m in _ROW.finditer(out):
        k1, k2 = int(m.group(1)), int(m.group(2))
        spec[(k1, k2)] = (float(m.group(3)), float(m.group(4)))
    mb = re.search(r"beat fb\s*=\s*([-\d.eE+]+)", out)
    fb = float(mb.group(1)) if mb else None
    return spec, fb


def deck(nl, tones="100meg 110meg", per=4, order=3, pre=""):
    ctrl = (pre + "\n") if pre else ""
    return (f"* qpss test\n{nl}\n.control\n{ctrl}qpss v(out) {tones} {per} {order}\n.endc\n.end\n")


# a two-tone source pair (v(n2) = tone1 + tone2) into a memoryless nonlinearity
def src(A):
    return (f"V1 n1 0 SIN(0 {A} 100meg)\nV2 n2 n1 SIN(0 {A} 110meg)\nRhi n2 0 1meg")

CUBIC = "Bout out 0 V = 0.5*V(n2)*V(n2)*V(n2)\nRout out 0 1k"          # pure g3=0.5
LINCUB = "Bout out 0 V = V(n2) + 0.5*V(n2)*V(n2)*V(n2)\nRout out 0 1k"  # g1=1, g3=0.5

print("Enhancement-133: quasi-periodic (two-tone) steady state")

# [1] pure cubic, A=0.1: analytic two-tone products of 0.5*(A(s1+s2))^3.
A = 0.1
sp, fb = qpss(deck(f"{src(A)}\n{CUBIC}"))
fund = 0.5 * A**3 * (3.0/4.0 + 3.0/2.0)   # 1.125e-3
im3  = 0.5 * A**3 * (3.0/4.0)             # 3.75e-4
h3   = 0.5 * A**3 * (1.0/4.0)             # 1.25e-4
def mag(k1, k2):
    return sp.get((k1, k2), (0, None))[1]
def close(got, exp, tol=2e-2):
    return got is not None and abs(got - exp) <= tol * exp

check(f"beat frequency fb = gcd(100,110) = 10 MHz (got {fb})",
      fb is not None and abs(fb - 10e6) < 1e3, str(fb))
check(f"fundamentals at f1,f2 = {fund:.3e} (got {mag(1,0)}, {mag(0,1)})",
      close(mag(1, 0), fund) and close(mag(0, 1), fund))
check(f"IM3 at 2f1-f2 / 2f2-f1 = {im3:.3e} (got {mag(2,-1)}, {mag(-1,2)})",
      close(mag(2, -1), im3) and close(mag(-1, 2), im3))
check(f"3rd harmonics 3f1,3f2 = {h3:.3e} (got {mag(3,0)}, {mag(0,3)})",
      close(mag(3, 0), h3) and close(mag(0, 3), h3))
check(f"even-order products ~0 for an odd nonlinearity (got {mag(-1,1)}, {mag(2,0)})",
      (mag(-1, 1) or 0) < 1e-6 and (mag(2, 0) or 0) < 1e-6)

# [2] IM3 obeys the 3:1 IP3 slope law (linear + cubic): halve the drive ->
# fundamental halves (slope 1), IM3 drops 8x (slope 3).
s1, _ = qpss(deck(f"{src(0.1)}\n{LINCUB}"))
s2, _ = qpss(deck(f"{src(0.05)}\n{LINCUB}"))
f_ratio = s1[(1, 0)][1] / s2[(1, 0)][1]
i_ratio = s1[(2, -1)][1] / s2[(2, -1)][1]
check(f"fundamental scales ~2x with 2x drive (slope 1; ratio {f_ratio:.2f})",
      abs(f_ratio - 2.0) < 0.15, f"{f_ratio:.3f}")
check(f"IM3 scales ~8x with 2x drive (slope 3; ratio {i_ratio:.2f})",
      abs(i_ratio - 8.0) < 1.0, f"{i_ratio:.3f}")

# [3] a different commensurate tone pair -> beat correctly derived, IM3 present.
sp3, fb3 = qpss(deck(f"{src(0.1)}\n{CUBIC}", tones="30meg 33meg"))
check(f"other tones 30/33 MHz -> beat fb = 3 MHz (got {fb3})",
      fb3 is not None and abs(fb3 - 3e6) < 1e3, str(fb3))
check("IM3 present for the 30/33 MHz pair",
      (sp3.get((2, -1), (0, 0))[1] or 0) > 1e-5)

# [4] OSDI / Verilog-A: a compiled controlled cubic must match the built-in.
osdi = os.path.join(HERE, "vacube.osdi")
cr = subprocess.run([OPENVAF, os.path.join(HERE, "vacube.va"), "-o", osdi],
                    capture_output=True, text=True, timeout=120)
if os.path.exists(osdi):
    nl = (f"{src(0.1)}\nN1 out 0 n2 0 cubemod\n.model cubemod vacube g1=0 g3=0.5\n"
          "Rout out 0 1k")
    spo, _ = qpss(deck(nl, pre=f"pre_osdi {osdi}"))
    os.remove(osdi)
    check(f"OSDI cubic: fundamentals match built-in {fund:.3e} "
          f"(got {spo.get((1,0),(0,None))[1]})",
          close(spo.get((1, 0), (0, None))[1], fund))
    check(f"OSDI cubic: IM3 matches built-in {im3:.3e} "
          f"(got {spo.get((2,-1),(0,None))[1]})",
          close(spo.get((2, -1), (0, None))[1], im3))
else:
    check("OSDI cubic: compiled vacube.va", False, cr.stderr.strip()[:80])

# [.] DOT-CARD PARITY (Enhancement-163): a top-level `.qpss ...` netlist card must
# run the same engine as the `qpss` command in a .control block, straight from the
# deck. Compare the two-tone spectrum from the dot-card against the command form --
# they must be bit-for-bit identical.
_cmd_sp, _ = qpss(deck(f"{src(0.1)}\n{CUBIC}"))
_dot_sp, _dfb = qpss(f"* qpss dotcard\n{src(0.1)}\n{CUBIC}\n"
                     ".qpss v(out) 100meg 110meg 4 3\n.end\n")
_common = set(_cmd_sp) & set(_dot_sp)
_ident = bool(_common) and all(_cmd_sp[k] == _dot_sp[k] for k in _common)
check("`.qpss` dot-card runs in batch and matches the `qpss` command bit-for-bit",
      _ident and _dfb is not None, f"common={len(_common)} fb={_dfb}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
