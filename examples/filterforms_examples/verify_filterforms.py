#!/usr/bin/env python3
"""verify_filterforms.py -- Enhancement-405: all eight analog filter operators,
checked in dc, ac and tran against closed-form transfer functions.

`laplace_nd/np/zd/zp` and `zi_nd/np/zd/zp` differ only in whether the numerator
and denominator arrive as ascending-power COEFFICIENTS or as ROOTS (given as
(real, imaginary) PAIRS). Three filters -- a single real pole, a zero plus a
pole, and a complex conjugate pair -- are written in all four forms of each
family and must give one answer.

THREE INDEPENDENT ORACLES, because each covers what the others miss:

  1. ANALYTIC.  H(s) in closed form. For the `zi_*` family the reference is the
     BILINEAR (Tustin) equivalent, which is what the implementation documents
     itself as realizing: a z-domain filter is a sampled-data system, and
     lowering converts H(z) to a continuous H(s) via z^-1 = (1-sT/2)/(1+sT/2)
     rather than modelling zero-order hold. Comparing against an ideal sampled
     response would fail for reasons that are not defects.

  2. CROSS-FORM.  The four spellings must agree with each other. This needs no
     knowledge of the sign convention at all, and it is the check that caught
     Enhancement-405: `zi_np`/`zi_zp` had every pole and zero RECIPROCATED, so a
     pole written 0.5 landed at z=2 and the four forms disagreed 2.0 vs -1.0.

  3. FINAL VALUE.  A step response must settle to the dc gain.

TRAP, recorded because it cost a wrong conclusion once: the transient oracle may
only be applied AFTER the stimulus has settled. The pulse source has a finite
rise time, and a filter with a direct feedthrough term (every `zi_*` filter, once
bilinear-transformed) tracks its input INSTANTANEOUSLY -- so during the ramp the
output is d0*u(t), not d0. Comparing against an ideal step reports a 0.66 error
at t=1e-14 that is entirely the oracle's fault. The `laplace_*` filters here have
no feedthrough and hide it.

Passes iff every form matches its analytic response in all three analyses and
the four forms of each filter agree. Exit code 0 = pass.
"""
import cmath
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

T = 1e-6                       # zi sample period, matching filter_forms.va
WP, WZ = 1e6, 4e6              # rad/s
A, B = 0.5e6, 1.0e6            # laplace conjugate pair
ZA, ZB = 0.4, 0.3              # zi conjugate pair
AC_FREQS = [1e3, 1e5, 3e5, 1e6, 3e6]

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


# --------------------------------------------------------------- analytic refs
def bilinear_w(s):
    x = s * T / 2.0
    return (1 - x) / (1 + x)


PC = [complex(-A, B), complex(-A, -B)]
ZC = [complex(ZA, ZB), complex(ZA, -ZB)]

FILTERS = {
    "lap1": dict(H=lambda s: 1.0 / (1 + s / WP), forms="nd np zd zp".split()),
    "lap2": dict(H=lambda s: (1 + s / WZ) / (1 + s / WP), forms="nd np zd zp".split()),
    "lap3": dict(H=lambda s: 1.0 / ((1 - s / PC[0]) * (1 - s / PC[1])),
                 forms="nd np zd zp".split()),
    "zi1": dict(H=lambda s: 1.0 / (1 - 0.5 * bilinear_w(s)), forms="nd np zd zp".split()),
    "zi2": dict(H=lambda s: (1 - 0.25 * bilinear_w(s)) / (1 - 0.5 * bilinear_w(s)),
                forms="nd np zd zp".split()),
    "zi3": dict(H=lambda s: 1.0 / ((1 - ZC[0] * bilinear_w(s)) * (1 - ZC[1] * bilinear_w(s))),
                forms="nd np zd zp".split()),
}

OSDI = os.path.join(tempfile.gettempdir(), "filterforms.osdi")


def compile_models():
    src = os.path.join(HERE, "filter_forms.va")
    r = subprocess.run([OPENVAF, src, "-o", OSDI], capture_output=True, text=True, timeout=600)
    return r.returncode == 0 and os.path.exists(OSDI), (r.stdout + r.stderr)


def run_deck(name, source, control):
    """One ngspice batch run; returns stdout+stderr."""
    path = os.path.join(tempfile.gettempdir(), f"ff_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* filterforms {name}
{source}
nd1 a 0 o m{name}
.model m{name} {name}()
.control
pre_osdi {OSDI}
{control}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def dc_gain(mod):
    out = run_deck(mod, "v1 a 0 dc 1", "op\nprint v(o)")
    m = re.findall(r"v\(o\)\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


def ac_point(mod, f):
    out = run_deck(mod, "v1 a 0 dc 0 ac 1",
                   f"ac lin 1 {f:g} {f:g}\nprint mag(v(o))\nprint ph(v(o))")
    mg = re.findall(r"mag\(v\(o\)\)\s*=\s*([\d.eE+-]+)", out)
    ph = re.findall(r"ph\(v\(o\)\)\s*=\s*(-?[\d.eE+-]+)", out)
    return (float(mg[0]) if mg else None,
            math.degrees(float(ph[0])) if ph else None)


def tran_wave(mod):
    out = run_deck(mod, "v1 a 0 pulse(0 1 0 1p 1p 1 2)", "tran 2e-8 2e-5 uic\nprint v(o)")
    return [(float(t), float(v)) for t, v in
            re.findall(r"^\s*\d+\s+([\d.eE+-]+)\s+(-?[\d.eE+-]+)\s*$", out, re.M)]


def main():
    print("Enhancement-405: laplace_nd/np/zd/zp and zi_nd/np/zd/zp in dc, ac and tran\n")
    ok, log = compile_models()
    if not check("filter_forms.va compiles (24 modules)", ok,
                 "" if ok else log.strip().splitlines()[0][:70] if log.strip() else ""):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    for fam, spec in FILTERS.items():
        H = spec["H"]
        want_dc = H(0j).real
        print(f"\n{fam}: dc gain {want_dc:.6g}")
        dcs, waves = {}, {}

        for form in spec["forms"]:
            mod = f"{fam}_{form}"

            # ---- dc
            got = dc_gain(mod)
            ok = got is not None and abs(got - want_dc) <= 1e-6 * max(1.0, abs(want_dc))
            dcs[form] = got
            check(f"{mod:10s} dc   {got}", ok, "" if ok else f"want {want_dc:.9g}")

            # ---- ac over the sweep
            bad = ""
            for f in AC_FREQS:
                mg, ph = ac_point(mod, f)
                Hv = H(1j * 2 * math.pi * f)
                wm, wp = abs(Hv), math.degrees(cmath.phase(Hv))
                okm = mg is not None and abs(mg - wm) <= 2e-4 * max(1e-12, wm)
                d = None if ph is None else ((ph - wp + 180) % 360 - 180)
                if not (okm and d is not None and abs(d) < 0.3):
                    bad = f"f={f:g}: |H|={mg} want {wm:.6g}, ph={ph} want {wp:.3f}"
                    break
            check(f"{mod:10s} ac   {len(AC_FREQS)} points vs analytic", not bad, bad)

            # ---- tran: settles to the dc gain
            rows = tran_wave(mod)
            waves[form] = rows
            fin = rows[-1][1] if rows else None
            okt = fin is not None and abs(fin - want_dc) <= 2e-3 * max(1.0, abs(want_dc))
            check(f"{mod:10s} tran settles to {fin}", okt, "" if okt else f"want {want_dc:.6g}")

        # ---- the convention-free check
        vals = [v for v in dcs.values() if v is not None]
        agree = len(vals) == 4 and (max(vals) - min(vals)) <= 1e-9 * max(1.0, abs(max(vals)))
        check(f"{fam}: four forms agree in dc", agree,
              "" if agree else f"spread {max(vals) - min(vals):.3e}" if vals else "missing")

        base = None
        same = True
        for rows in waves.values():
            v = [r[1] for r in rows]
            if base is None:
                base = v
            elif len(v) != len(base) or any(
                    abs(x - y) > 1e-9 * max(1.0, abs(y)) for x, y in zip(v, base)):
                same = False
        check(f"{fam}: four transient waveforms identical", same and base is not None)

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
