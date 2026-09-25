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

    e712_checks()
    e714_checks()

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


# ------------------------------------------------- Enhancement-712 (campaign F9)
E712_OSDI = os.path.join(tempfile.gettempdir(), "filterforms_e712.osdi")


def e712_compile(name, src, timeout=600):
    """Compile `src`; returns (ok, seconds, peak RSS of the compiler in MB, log)."""
    import resource
    import time
    path = os.path.join(tempfile.gettempdir(), f"ff_{name}.va")
    with open(path, "w") as fh:
        fh.write(src)
    try:
        os.remove(E712_OSDI)
    except OSError:
        pass
    r0 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    t0 = time.time()
    try:
        r = subprocess.run([OPENVAF, path, "-o", E712_OSDI], capture_output=True, text=True,
                           timeout=timeout)
        log = r.stdout + r.stderr
        ok = r.returncode == 0 and os.path.exists(E712_OSDI)
    except subprocess.TimeoutExpired:
        log, ok = f"timeout after {timeout} s", False
    t = time.time() - t0
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # ru_maxrss is the largest of all children so far (bytes on macOS, kB on
    # Linux); it only says something when this compile raised it.
    unit = 1e6 if sys.platform == "darwin" else 1e3
    rss = (r1 / unit) if r1 > r0 else float("nan")
    return ok, t, rss, log


def e712_run(name, source, control, osdi=None):
    path = os.path.join(tempfile.gettempdir(), f"ff_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* filterforms {name}
{source}
.control
pre_osdi {osdi or E712_OSDI}
{control}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def e712_filters(n, poles):
    body = "\n".join(
        "I(p,n) <+ laplace_zp(V(p,n), '{}, '{%s});"
        % ",".join("-%d.0e6,0.0" % (k + 1) for k in range(poles)) for _ in range(n))
    return ('`include "disciplines.vams"\nmodule many(p, n);\ninout p, n; electrical p, n;\n'
            'analog begin\n%s\nend\nendmodule\n' % body)


def e712_checks():
    """Enhancement-712 (robustness campaign F9 of 2026-09-23): compile time and
    memory of a module with many Laplace filters, and of a module with many
    Jacobian entries, and the answers such modules give.

    A 100-filter module of twenty poles each (2 000 filter states) took 113 s and
    48 GB: the zero-root choice of the root-to-polynomial expansion was four
    branch diamonds per (root, coefficient) pair, 54 000 blocks for 20 filters,
    and the OSDI descriptor module's straight-line helper functions -- one
    memory operation per Jacobian entry -- hit two quadratic LLVM backend
    passes. The expansion decides the choice at compile time for constant
    roots (a `select` otherwise) and the descriptor module is built at -O0
    above 256 entries. The budgets below are loose (a loaded sweep machine);
    before the fix the 100-filter compile was two orders of magnitude outside
    both.
    """
    print("\nEnhancement-712: many filters and many Jacobian entries (campaign F9)")

    # 100 filters of 20 poles, 2 000 states, 6 200 Jacobian entries: 113 s and
    # 48 GB before, 1.6 s and 0.55 GB now.
    ok, t, rss, log = e712_compile("many100", e712_filters(100, 20))
    check("100 twenty-pole filters compile", ok, "" if ok else log.strip()[:80])
    check(f"  ... in under 60 s ({t:.1f} s)", ok and t < 60.0)
    check(f"  ... in under 4 GB ({rss:.0f} MB peak)", ok and (rss != rss or rss < 4000.0))
    if ok:
        # every filter has unit dc gain (prod(1 - 0/r) = 1), so I = 100 V
        out = e712_run("many100", "v1 a 0 dc 0.01\nn1 a 0 mm\n.model mm many()", "op\nprint i(v1)")
        m = re.findall(r"i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out)
        got = float(m[0]) if m else None
        check(f"  dc current of 100 unit-gain filters at 10 mV: {got}",
              got is not None and abs(got + 1.0) < 1e-6)
        # 20 states per filter: the transient response of one is 1/100 of all
        out = e712_run("many100t", "v1 a 0 pulse(0 0.01 0 1p 1p 1 2)\nn1 a 0 mm\n.model mm many()",
                       "tran 5e-8 5e-5 uic\nprint i(v1)")
        rows = [float(v) for v in re.findall(r"^\s*\d+\s+[\d.eE+-]+\s+(-?[\d.eE+-]+)\s*$", out, re.M)]
        # the time constants of poles at 1..20 Mrad/s add up to 3.6 us; at 50 us
        # the step response has settled to the dc gain
        check(f"  transient settles to the dc current ({rows[-1] if rows else None})",
              bool(rows) and abs(rows[-1] + 1.0) < 1e-3)

    # a root that is a parameter is decided at run time (a select, not a
    # branch); a zero root makes the factor a bare s (LRM 4.5.11): the same
    # differentiator written with a literal 0 and with a parameter set to 0
    src = ('`include "disciplines.vams"\n'
           'module zlit(p, n); inout p, n; electrical p, n;\n'
           "analog I(p,n) <+ 1.0e-6 * laplace_zp(V(p,n), '{0.0, 0.0}, '{-1.0e6, 0.0});\nendmodule\n"
           'module zpar(p, n); inout p, n; electrical p, n; parameter real z0 = 0.0;\n'
           "analog I(p,n) <+ 1.0e-6 * laplace_zp(V(p,n), '{z0, 0.0}, '{-1.0e6, 0.0});\nendmodule\n")
    ok, t, rss, log = e712_compile("zeroroot", src)
    check("a zero root as a literal and as a parameter compiles", ok, "" if ok else log.strip()[:80])
    if ok:
        # an admittance of H(s) = 1e-6 s / (1 + s/1e6): |I| = w*1e-6 / |1 + jw/1e6| per volt
        for mod in ("zlit", "zpar"):
            f = 1e5
            w = 2 * math.pi * f
            want = w * 1e-6 / abs(1 + 1j * w / 1e6)
            out = e712_run(mod, f"v1 a 0 dc 0 ac 1\nn1 a 0 m{mod}\n.model m{mod} {mod}()",
                           f"ac lin 1 {f:g} {f:g}\nprint mag(i(v1))")
            mg = re.findall(r"mag\(i\(v1\)\)\s*=\s*([\d.eE+-]+)", out)
            got = float(mg[0]) if mg else None
            check(f"  {mod}: |H| at 100 kHz {got} vs {want:.6g}",
                  got is not None and abs(got - want) <= 1e-4 * want)

    # no filter at all: a 300-node resistor ladder has 904 Jacobian entries, so
    # its descriptor module is the -O0 path; 5.8 s at 400 nodes before
    nodes = 300
    src = ('`include "disciplines.vams"\nmodule ladder(p, n);\ninout p, n; electrical p, n;\n'
           + " ".join("electrical x%d;" % i for i in range(nodes))
           + "\nanalog begin\nI(p, x0) <+ V(p, x0)*1e-3;\n"
           + "\n".join("I(x%d, x%d) <+ V(x%d, x%d)*1e-3;" % (i, i + 1, i, i + 1) for i in range(nodes - 1))
           + "\nI(x%d, n) <+ V(x%d, n)*1e-3;\nend\nendmodule\n" % (nodes - 1, nodes - 1))
    ok, t, rss, log = e712_compile("ladder300", src)
    check(f"a 300-node ladder (904 Jacobian entries) compiles in under 20 s ({t:.1f} s)",
          ok and t < 20.0, "" if ok else log.strip()[:80])
    if ok:
        out = e712_run("ladder300", "v1 a 0 dc 3.01\nn1 a 0 mm\n.model mm ladder()", "op\nprint i(v1)")
        m = re.findall(r"i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out)
        got = float(m[0]) if m else None
        # 301 resistors of 1 kOhm in series: 3.01 V / 301 kOhm = 10 uA
        check(f"  its dc current is 3.01 V over 301 kOhm: {got}",
              got is not None and abs(got + 1e-5) < 1e-11)


# ------------------------------------------------- Enhancement-714
def e714_compile(name, src, env=None, args=()):
    """Compile `src` with extra environment and arguments; returns (ok, log)."""
    path = os.path.join(tempfile.gettempdir(), f"ff_{name}.va")
    with open(path, "w") as fh:
        fh.write(src)
    try:
        os.remove(E712_OSDI)
    except OSError:
        pass
    r = subprocess.run([OPENVAF, path, "-o", E712_OSDI, *args], capture_output=True, text=True,
                       timeout=600, env={**os.environ, **(env or {})})
    return r.returncode == 0 and os.path.exists(E712_OSDI), r.stdout + r.stderr


def e714_ladder(nodes):
    return ('`include "disciplines.vams"\nmodule ladder(p, n);\ninout p, n; electrical p, n;\n'
            + " ".join("electrical x%d;" % i for i in range(nodes))
            + "\nanalog begin\nI(p, x0) <+ V(p, x0)*1e-3;\n"
            + "\n".join("I(x%d, x%d) <+ V(x%d, x%d)*1e-3;" % (i, i + 1, i, i + 1) for i in range(nodes - 1))
            + "\nI(x%d, n) <+ V(x%d, n)*1e-3;\nend\nendmodule\n" % (nodes - 1, nodes - 1))


def e714_geps(log, func):
    """getelementptr count of `func` in the dumped descriptor module, or None."""
    m = re.search(r"^Optimized LLVM IR for osdi_descriptors in .*?\n(.*?)(?=^Optimized LLVM IR for |\Z)",
                  log, re.M | re.S)
    if not m:
        return None
    f = re.search(r"^define [^\n]*@%s\([^\n]*\{\n(.*?)^\}" % func, m.group(1), re.M | re.S)
    return len(re.findall(r"getelementptr", f.group(1))) if f else None


def e714_checks():
    """Enhancement-714: the descriptor module of a file above 256 Jacobian
    entries runs LLVM's -O1 middle end and is emitted through the fast
    instruction selector; E-712 had built it at -O0 outright, and a 2 mm
    transmission line's transient (511 entries) ran 2 % slower on it than on
    the -O3 descriptor. Below the threshold the module keeps the requested
    level end to end.
    """
    print("\nEnhancement-714: the descriptor's middle end above 256 entries")
    # the 300-node ladder of E-712 (904 entries): the fast path
    ok, log = e714_compile("ladder300b", e714_ladder(300), env={"PHASE_PROF": "1"}, args=("--dump-ir",))
    line = next((l for l in log.splitlines() if l.startswith("PHASE llvm main")), "")
    check("904 entries: the descriptor's object is emitted through the fast instruction selector",
          ok and "(fast isel)" in line, line.split("main ", 1)[-1])
    g = e714_geps(log, "load_jacobian_resist_0")
    # 904 entries: one address computation per entry after -O1 (904), two and a
    # half without a middle end (2 260 on the E-713 binaries)
    check(f"  ... after the -O1 middle end: {g} address computations in load_jacobian_resist for 904 entries",
          g is not None and g <= 1.5 * 904)
    # the same module with the middle end switched off through the hook
    ok2, log2 = e714_compile("ladder300c", e714_ladder(300), env={"OPENVAF_MAIN_PIPELINE": "default<O0>"},
                             args=("--dump-ir",))
    g2 = e714_geps(log2, "load_jacobian_resist_0")
    check(f"  ... OPENVAF_MAIN_PIPELINE=default<O0> leaves them unfolded ({g2})",
          ok2 and g2 is not None and g is not None and g2 > 2 * g)
    # a 60-node ladder (184 entries) stays below the threshold: the requested
    # level end to end, and the right current
    ok, log = e714_compile("ladder60", e714_ladder(60), env={"PHASE_PROF": "1"})
    line = next((l for l in log.splitlines() if l.startswith("PHASE llvm main")), "")
    check("184 entries: the descriptor keeps the requested level (no fast isel)",
          ok and "jacobian=184" in line and "(fast isel)" not in line, line.split("main ", 1)[-1])
    if ok:
        out = e712_run("ladder60", "v1 a 0 dc 0.61\nn1 a 0 mm\n.model mm ladder()", "op\nprint i(v1)")
        m = re.findall(r"i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out)
        got = float(m[0]) if m else None
        check(f"  its dc current is 0.61 V over 61 kOhm: {got}",
              got is not None and abs(got + 1e-5) < 1e-11)


if __name__ == "__main__":
    sys.exit(main())
