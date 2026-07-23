#!/usr/bin/env python3
"""verify_fftexpr.py -- Enhancement-306: the E-241 twin in the fft EXPRESSION function.

Enhancement-241 fixed an amplitude normalization that divided by the ZERO-PADDED
transform size instead of the input length, in the `fft` COMMAND
(frontend/com_fft.c). The identical mistake survived in `maths/cmaths/cmath4.c`, the
vector-expression function reached by `let F = fft(v)` -- a separate implementation of
the same computation.

`cx_fft` holds two complete implementations (complex-input and real-input), each with
an FFTW branch and a Green's radix-2 branch. In BOTH, the FFTW branch already used the
input length while Green's used the padded size:

    real branch     FFTW: scale = ((double)length)/2.0     Green: ((double)N)/2   <- bug
    complex branch  FFTW: scale = (double) fpts            Green: (double) N      <- bug

so the two halves of one function disagreed -- an internal contradiction, not a
question of convention. This build has HAVE_LIBFFTW3 undefined, so Green's is live.

Oracles, all closed form:
  * bin 0 with a DC offset D must read D. E-241's own discriminator: bin 0 is
    unambiguous (no window or scalloping) and "a DC value cannot depend on how many
    samples were taken". X[0] = D*length, so dividing by N read back D*length/N.
  * ifft(fft(x)) must return x. Nothing here touches ifft, so the round trip closing
    to machine precision is an INDEPENDENT confirmation of the forward normalization.
  * for a complex input, bin 0 is the mean of the samples -- checked against the
    analytic mean of an RC response.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def close(got, want, tol, label):
    if got is None:
        check(label, False, "no value"); return
    rel = abs(got - want) / (abs(want) if want else 1.0)
    check(label, rel <= tol, f"got {got:.8g} want {want:.8g} rel {rel:.1e}")


def run(deck, name):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=300, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


def num(out, vec):
    m = re.search(rf"^{re.escape(vec)}\s*=\s*([-\d.eE+]+)", out, re.M | re.I)
    return float(m.group(1)) if m else None


print("Enhancement-306: fft expression-function amplitude normalization")

# ---- real input: bin 0 must equal the DC offset, and must match the COMMAND ----
# 4001 samples pad to 4096; the old code read back 2.0*4001/4096 = 1.953613.
DC = 2.0
out = run(f"""* E-241's discriminator on both paths
v1 a 0 dc 0 sin({DC} 1.0 1000)
r1 a 0 1k
.control
tran 1u 4m
linearize
let s = v(a)
fft s
print mag(s)[0]
setplot previous
let F = fft(s)
print mag(F)[0]
.endc
.end
""", "_dc.cir")
print("\n[306] bin 0 of a DC offset, padded record (4001 -> 4096)")
close(num(out, "mag(s)[0]"), DC, 1e-6, "fft COMMAND bin 0 = DC (E-241, unchanged)")
close(num(out, "mag(f)[0]"), DC, 1e-6, "fft EXPRESSION bin 0 = DC (was DC*4001/4096)")
a, b = num(out, "mag(s)[0]"), num(out, "mag(f)[0]")
check("the two paths agree with each other",
      a is not None and b is not None and abs(a - b) <= 1e-9 * max(abs(a), 1.0),
      f"command {a} vs expression {b}")

# ---- ifft(fft(x)) round trip: independent of the DC argument -------------------
print("\n[306] ifft(fft(x)) round trip (independent confirmation -- ifft untouched)")
for tag, tstop, note in (("padded", "4m", "4001 samples -> 4096"),
                         ("exact ", "4.095m", "4096 samples, no padding")):
    run(f"""* round trip, {note}
v1 a 0 dc 0 sin(0 2 1k)
r1 a 0 1k
.control
tran 1u {tstop}
linearize
let s  = v(a)
let rt = ifft(fft(s))
let e  = rt - s
wrdata _rt_{tag.strip()}.dat e
.endc
.end
""", f"_rt{tag.strip()}.cir")
    p = os.path.join(HERE, f"_rt_{tag.strip()}.dat")
    err = None
    if os.path.exists(p):
        vals = []
        for line in open(p):
            f_ = line.split()
            if len(f_) >= 2:
                try:
                    vals.append(abs(float(f_[1])))
                except ValueError:
                    pass
        err = max(vals) if vals else None
    check(f"round trip exact ({note})",
          err is not None and err < 1e-9, f"max|ifft(fft(s))-s| = {err}")

# ---- complex input: bin 0 is the mean of the samples --------------------------
# AC of an RC low-pass, f = 1..4001 Hz: bin 0 = |mean(1/(1+j2 pi f R C))|
print("\n[306] complex-input branch: bin 0 = mean of the samples")
Rr, Cc, N = 1e3, 1e-9, 4001
mean = sum(1.0 / complex(1.0, 2 * math.pi * f * Rr * Cc)
           for f in range(1, N + 1)) / N
out = run(f"""* complex-input fft: bin 0 must be the mean
v1 in 0 dc 0 ac 1
r1 in out {Rr}
c1 out 0 {Cc}
.control
ac lin {N} 1 {N}
let cv = v(out)
let Fc = fft(cv)
print mag(Fc)[0]
.endc
.end
""", "_cx.cir")
close(num(out, "mag(fc)[0]"), abs(mean), 1e-5,
      "complex bin 0 = |mean(H)| (was |mean|*4001/4096)")

for f_ in os.listdir(HERE):
    if f_.startswith("_"):
        os.remove(os.path.join(HERE, f_))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
