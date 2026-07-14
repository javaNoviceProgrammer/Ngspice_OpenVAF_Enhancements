#!/usr/bin/env python3
"""Enhancement-193: `.pnoise` honors the `sqrnoise` control variable.

The ngspice manual (sec. `.noise`) defines `onoise_spectrum` / `inoise_spectrum`
as the noise spectral density in **V/sqrt(Hz)** (or A/sqrt(Hz)) by default, and
says the `sqrnoise` control variable switches them to the **squared** V^2/Hz form.
`.noise` obeys this. But `.pnoise` (periodic noise) always emitted the SQUARED
V^2/Hz density and ignored `sqrnoise` -- so the same-named vectors carried
different units across the two analyses, and `sqrnoise` silently did nothing for
pnoise. Found while auditing the RF/PSS suite.

E-193 makes `.pnoise` (and QPnoise) read `sqrnoise` exactly like `.noise`:
default -> V/sqrt(Hz); `set sqrnoise` -> V^2/Hz.

The testbed is the driven RC low-pass from the E-124 pnoise example (linear, so
pnoise reduces to ordinary noise and only R1's thermal noise contributes):

    S_out(f) = 4kT*R1 / (1 + (2*pi*f*R1*C1)^2)      [V^2/Hz]
    a_out(f) = sqrt(S_out(f))                        [V/sqrt(Hz)]

Checks: default pnoise == a_out (V/sqrt(Hz)); `set sqrnoise` pnoise == S_out
(V^2/Hz); default^2 == squared (the sqrt relation); and default pnoise == default
`.noise` (the two analyses now agree by default).

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

BOLTZ, TEMP, R, C = 1.380649e-23, 300.15, 1e3, 1e-9   # TEMP = 27 C default
SCRATCH = tempfile.mkdtemp(prefix="pnoiseunits_")
passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def S_pow(f):
    """analytic output thermal-noise power density [V^2/Hz]."""
    return 4.0 * BOLTZ * TEMP * R / (1.0 + (2 * math.pi * f * R * C) ** 2)


def run(deck):
    open(os.path.join(SCRATCH, "d.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True,
                       cwd=SCRATCH, timeout=120)
    return r.stdout + r.stderr


def spectrum(log, col="onoise_spectrum"):
    """parse a `print <col>` table -> [(freq, value), ...]."""
    out, on = [], False
    for line in log.splitlines():
        if re.search(r"Index\s+frequency\s+" + re.escape(col), line):
            on = True
            continue
        if on:
            p = line.split()
            if len(p) == 3:
                try:
                    out.append((float(p[1]), float(p[2])))
                except ValueError:
                    if out:
                        break
    return out


# small, fast linear-RC pnoise (few harmonics / points): Sparse (pnoise = PSS)
PN = ("* pnoise units\n.option sparse\n"
      "V1 a 0 dc 0 ac 1 SIN(0 1 1meg)\n"
      "R1 a b 1k\nC1 b 0 1n\n"
      ".pnoise 1meg 1u b 512 6 40 5u b V1 dec 3 10k 300k\n")

# ---- 1. default pnoise -> V/sqrt(Hz) == sqrt(analytic) ----
dflt = spectrum(run(PN + ".control\nrun\nprint onoise_spectrum\n.endc\n.end\n"))
ok1 = len(dflt) >= 3 and all(
    abs(v - math.sqrt(S_pow(f))) / math.sqrt(S_pow(f)) < 0.03 for f, v in dflt)
worst1 = max((abs(v - math.sqrt(S_pow(f))) / math.sqrt(S_pow(f))
              for f, v in dflt), default=1)
check("[default] pnoise onoise == sqrt(4kTR/(1+(wRC)^2)) [V/sqrt(Hz)]", ok1,
      f"(worst rel {worst1:.2e})")

# ---- 2. `set sqrnoise` pnoise -> V^2/Hz == analytic ----
sqr = spectrum(run(PN + ".control\nset sqrnoise\nrun\nprint onoise_spectrum\n.endc\n.end\n"))
ok2 = len(sqr) >= 3 and all(abs(v - S_pow(f)) / S_pow(f) < 0.03 for f, v in sqr)
worst2 = max((abs(v - S_pow(f)) / S_pow(f) for f, v in sqr), default=1)
check("[sqrnoise] pnoise onoise == 4kTR/(1+(wRC)^2) [V^2/Hz]", ok2,
      f"(worst rel {worst2:.2e})")

# ---- 3. default^2 == sqrnoise form (the sqrt relation, exact) ----
if len(dflt) == len(sqr) and dflt:
    ok3 = all(abs(d[1] ** 2 - s[1]) / s[1] < 1e-6 for d, s in zip(dflt, sqr))
    check("[relation] default(V/sqrt(Hz))^2 == sqrnoise(V^2/Hz)", ok3)
else:
    check("[relation] default^2 == sqrnoise", False, "length mismatch")

# ---- 4. default pnoise == default .noise (analyses now agree by default) ----
nz = spectrum(run(
    "* noise ref\nV1 a 0 dc 0 ac 1\nR1 a b 1k\nC1 b 0 1n\n"
    ".noise v(b) V1 dec 3 10k 300k\n"
    ".control\nrun\nsetplot noise1\nprint onoise_spectrum\n.endc\n.end\n"))
if len(nz) == len(dflt) and dflt:
    ok4 = all(abs(a[1] - b[1]) / b[1] < 0.03 for a, b in zip(dflt, nz))
    worst4 = max(abs(a[1] - b[1]) / b[1] for a, b in zip(dflt, nz))
    check("[consistency] default pnoise == default .noise (both V/sqrt(Hz))", ok4,
          f"(worst rel {worst4:.2e})")
else:
    check("[consistency] default pnoise == default .noise", False,
          f"pnoise {len(dflt)} pts vs noise {len(nz)} pts")

# tidy
import glob
for g in glob.glob(os.path.join(SCRATCH, "*")):
    try:
        os.remove(g)
    except OSError:
        pass
try:
    os.rmdir(SCRATCH)
except OSError:
    pass

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
