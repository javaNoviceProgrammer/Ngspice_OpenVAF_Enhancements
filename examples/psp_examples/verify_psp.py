#!/usr/bin/env python3
"""
verify_psp.py -- Enhancement-132: periodic S-parameters (.psp).

`.psp` runs a periodic steady state (PSS), then for each RF port injects a unit
excitation in the 0-th sideband through the harmonic conversion matrix (the E-121
engine that PAC/pnoise/PXF share) and reads the per-sideband port waves, forming
the periodic scattering matrix S^(k) = B^(k) * A^-1 at each swept input frequency.
It reuses the RFSPICE port framework (`portnum`/`z0` on voltage sources) and the
same power-wave convention as `.sp`.

The rigorous check: for a **time-invariant** circuit the conversion matrix is
block-diagonal, so the sideband-0 S-matrix must reduce **exactly** to the ordinary
`.sp` S-matrix, and every conversion sideband must be zero. Each check builds the
same network, runs `.sp` (reference) and `.psp`, and compares the complex
S-parameters:

  [1] resistive 2-port          -- real S, S = B*A^-1 exact
  [2] reactive 2-port (R+L+C)   -- complex S across several frequencies (phase too)
  [3] 1-port reflection         -- N-general machinery down to a single port
  [4] 3-port resistive star     -- N-general machinery for N > 2
  [5] conversion sidebands ~0   -- a time-invariant circuit has no mixing

Like the rest of the periodic small-signal suite, `.psp` runs correctly under both
linear solvers (the conversion matrix is a standalone dense LU independent of
KLU/Sparse; PSS runs under both since E-118). This script exercises the default
Sparse solver -- PSS shooting is slow under KLU, so the dual-solver run is left out
of the fast regression, matching the other rfpss examples.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE, VAF as OPENVAF

# a decoupled periodic reference so PSS has a period to shoot on; the measured
# network is time-invariant, so its sideband-0 S is independent of this.
PSS_DRIVE = "Vpss pssref 0 SIN(0 0.01 100meg)\nRpss pssref 0 1k"
PSS_HEAD = "100meg 1u pssref 256 4 20 5u"     # fguess stab osc points harm sc_iter steady

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_psp"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def sval(out, name):
    """parse `name = re,im` printed by ngspice -> complex, or None."""
    m = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)", out)
    return complex(float(m.group(1)), float(m.group(2))) if m else None


def sp_ref(body, names, freq, pre=""):
    ctrl = (pre + "\n") if pre else ""
    deck = (f"* sp ref\n{body}\n.control\n{ctrl}sp lin 1 {freq} {freq}\n"
            f"print {' '.join(names)}\n.endc\n.end\n")
    out = run(deck, "_spref")
    return {n: sval(out, n) for n in names}


def psp_run(body, names, freq, tail="", pre=""):
    ctrl = (pre + "\n") if pre else ""
    deck = (f"* psp\n{body}\n{PSS_DRIVE}\n.psp {PSS_HEAD} lin 1 {freq} {freq}{tail}\n"
            f".control\n{ctrl}run\nprint {' '.join(names)}\n.endc\n.end\n")
    out = run(deck, "_psprun")
    return {n: sval(out, n) for n in names}


def cmp_smatrix(label, body, names, freqs, tol=1e-6, pre=""):
    """PSP sideband-0 must equal .sp for every S-parameter at every frequency."""
    worst = 0.0
    ok = True
    for f in freqs:
        ref = sp_ref(body, names, f, pre=pre)
        psp = psp_run(body, names, f, pre=pre)
        for n in names:
            a, b = ref.get(n), psp.get(n)
            if a is None or b is None:
                ok = False
                check(f"{label}: {n} @ {f} parsed", False, f"ref={a} psp={b}")
                continue
            worst = max(worst, abs(a - b))
    check(f"{label}: PSP sideband-0 == .sp over {len(freqs)} freq(s), {len(names)} S-params "
          f"(max |ΔS| = {worst:.1e})", ok and worst < tol, f"maxdiff={worst:.3e}")


print("Enhancement-132: periodic S-parameters (.psp)")

# [1] resistive 2-port: series 50 with a 200 ohm load at port 2 (real S).
b1 = ("V1 in 0 DC 0 AC 1 portnum 1 z0 50\nV2 out 0 DC 0 AC 1 portnum 2 z0 50\n"
      "Rs in out 50\nRl out 0 200")
cmp_smatrix("resistive 2-port", b1, ["s_1_1", "s_2_1", "s_1_2", "s_2_2"], ["100meg"])

# [2] reactive 2-port (R + series L + shunt C): complex S with real frequency
# dependence -- exercised across a small sweep so magnitude AND phase must match.
b2 = ("V1 in 0 DC 0 AC 1 portnum 1 z0 50\nV2 out 0 DC 0 AC 1 portnum 2 z0 50\n"
      "Rs in out 30\nLs in out 50n\nCs out 0 100p")
cmp_smatrix("reactive 2-port", b2, ["s_1_1", "s_2_1", "s_1_2", "s_2_2"],
            ["100meg", "200meg", "300meg", "500meg"])

# [3] 1-port reflection: 75 ohm on a 50 ohm port -> Gamma = 25/125 = 0.2 exactly.
b3 = "V1 in 0 DC 0 AC 1 portnum 1 z0 50\nRs in 0 75"
cmp_smatrix("1-port reflection", b3, ["s_1_1"], ["100meg"])
g = psp_run(b3, ["s_1_1"], "100meg").get("s_1_1")
check(f"1-port: Γ = (75-50)/(75+50) = 0.2 (got {g})",
      g is not None and abs(g - 0.2) < 1e-6, str(g))

# [4] 3-port resistive star (20 ohm arms to a common node): N-general for N > 2.
b4 = ("V1 a 0 DC 0 AC 1 portnum 1 z0 50\nV2 b 0 DC 0 AC 1 portnum 2 z0 50\n"
      "V3 c 0 DC 0 AC 1 portnum 3 z0 50\nR1 a m 20\nR2 b m 20\nR3 c m 20")
cmp_smatrix("3-port star", b4, ["s_1_1", "s_2_1", "s_3_1", "s_2_3"], ["100meg"])

# [5] conversion sidebands of a time-invariant circuit are zero (no mixing). With
# maxsideband=1 the ±1 conversion terms must be ~0 while sideband 0 is not.
sb = psp_run(b2, ["s_2_1", "s_2_1_usb1", "s_2_1_lsb1"], "200meg", tail=" 1")
s0, su, sl = sb.get("s_2_1"), sb.get("s_2_1_usb1"), sb.get("s_2_1_lsb1")
check(f"conversion sidebands ~0 for a time-invariant circuit "
      f"(|sb0|={abs(s0):.3f}, |usb1|={abs(su):.1e}, |lsb1|={abs(sl):.1e})"
      if None not in (s0, su, sl) else "conversion sideband parse",
      None not in (s0, su, sl) and abs(s0) > 0.1 and abs(su) < 1e-6 and abs(sl) < 1e-6)

# [6] reciprocity of the reactive passive network: S21 == S12.
rec = psp_run(b2, ["s_2_1", "s_1_2"], "300meg")
s21, s12 = rec.get("s_2_1"), rec.get("s_1_2")
check(f"reciprocity S21 == S12 for a passive network (|ΔS| = "
      f"{abs(s21-s12):.1e})" if None not in (s21, s12) else "reciprocity parse",
      None not in (s21, s12) and abs(s21 - s12) < 1e-6)

# [7] OSDI / Verilog-A devices: a compiled VA resistor (G stamp) + VA capacitor
# (reactive ddt stamp) 2-port. Both are time-invariant, so PSP sideband-0 must
# still equal .sp -- confirming OSDI device Jacobian stamps are captured in the
# conversion matrix across frequency (magnitude and phase).
osdi = os.path.join(HERE, "psp_dev.osdi")
cr = subprocess.run([OPENVAF, os.path.join(HERE, "psp_dev.va"), "-o", osdi],
                    capture_output=True, text=True, timeout=120)
if os.path.exists(osdi):
    bo = ("V1 in 0 DC 0 AC 1 portnum 1 z0 50\nV2 out 0 DC 0 AC 1 portnum 2 z0 50\n"
          "N1 in out rmod\nNc out 0 cmod\n.model rmod vares r=30\n.model cmod vacap c=100p")
    cmp_smatrix("OSDI 2-port (VA R + VA C)", bo,
                ["s_1_1", "s_2_1", "s_1_2", "s_2_2"],
                ["100meg", "300meg", "500meg"], pre=f"pre_osdi {osdi}")
    os.remove(osdi)
else:
    check("OSDI 2-port: compiled psp_dev.va", False, cr.stderr.strip()[:80])

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
