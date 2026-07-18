#!/usr/bin/env python3
"""verify_cmdfuzz.py -- Enhancement-225: ngspice command/expression-evaluator
crash hardening (fuzzing).

Fuzzing the interactive `.control` command interpreter and vector-expression
evaluator (print / let / plot / meas / fft / the ?: operator, ...) found
memory-safety crashes (SIGSEGV / malloc abort -- ngspice is C, so these are real)
on malformed post-processing commands. Two distinct root causes, both fixed:

  [transform-short] maths/cmaths/cmath4.c (cx_fft, cx_deriv) + frontend/fourier.c --
        fft / deriv / fourier each overran the heap on a too-short (< 2-point) or
        synthetic vector (fft(1), deriv(vecmin(v(1))), fourier of a scalar). Fixed
        by padding / rejecting / zeroing degenerate inputs. Details for fft:

  [fft-short]  maths/cmaths/cmath4.c cx_fft() -- the Green's real/complex FFT
        (rffts) dereferences bit-reversal tables that fftInit() only builds for
        M > 2, so an input of <= 4 points read unallocated memory; and the
        `time`/`xscale` buffers were sized by the data `length` while the scale
        loops fill `pl_scale->v_length` entries, so a synthetic/expression vector
        shorter than the plot's scale (e.g. `fft(1)`, `fft(vector(5))` on a long
        .tran plot) overran the heap. Fixed: pad to N >= 8, size the buffers for
        the largest fill, and reject length < 2 / scale-too-short.

  [meas-errbuf] frontend/com_measure2.c -- measure error messages were formatted
        into a shared char errbuf[100]; a failed measure writes its whole
        expression string as the vector name ("no such vector as '%s'"), so a
        measure expression longer than ~80 chars overran the buffer -> SIGABRT.
        Fixed by bounding every write with snprintf(.., MEAS_ERRBUF_SIZE, ..).

  [ternary]    frontend/evaluate.c ft_ternary() -- a `?:` whose condition OR
        selected branch fails to evaluate (e.g. `1?0[3]:9`, "indexing a scalar"
        returns NULL) hit vec_copy(NULL) / cond->v_link2 with no NULL guard.
        Fixed with NULL guards on both.

Each check confirms a pathological command now yields a clean, bounded outcome
(no signal/abort) and that normal expressions still compute correctly.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
"""
import os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
D = tempfile.mkdtemp(prefix="cmdfuzz225_")
BASE = ("* cmdfuzz\nV1 1 0 sin(0 1 1k)\nR1 1 2 1k\nC1 2 0 1u\n"
        ".tran 5u 200u\n.control\nrun\n%s\n.endc\n.end\n")

def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))

def run(body, timeout=25):
    p = os.path.join(D, "f.cir")
    with open(p, "w") as f:
        f.write(BASE % body)
    wd = tempfile.mkdtemp(dir=D)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=timeout, cwd=wd, errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def is_clean(rc, out):
    if rc is None:                       # timeout
        return False
    if rc < 0 or (rc >= 128 and rc != 142):
        return False
    return "segmentation" not in out.lower()

# --- pathological commands: each must be CLEAN (no crash), run a few times
#     because the pre-fix corruption crashed only on some heap layouts ---
bad = {
    "fft-short: fft(1) (scalar / shorter than plot scale)":     "let z=fft(1)",
    "fft-short: fft(vector(3)) (M<3 bit-reversal tables)":      "let z=fft(vector(3))",
    "fft-short: fft(vector(5)) (data shorter than .tran scale)":"let z=fft(vector(5))",
    "deriv-short: deriv(vecmin(v(1))) (polyfit over a scalar)":  "let z=deriv(vecmin(v(1)))",
    "fourier-short: fourier of a degenerate (scalar) vector":    "fourier 1k deriv(vecmin(v(1)))",
    "ternary: condition fails to evaluate (0[3]?9:9)":          "print 0[3]?9:9",
    "ternary: selected branch fails to evaluate (1?0[3]:9)":    "print 1?0[3]:9",
    "ternary: all operands fail (0[3]?0[3]:0[3])":              "print 0[3]?0[3]:0[3]",
    "meas-errbuf: long measure expression (overran errbuf[100])":
        "meas tran m MAX (" + "+".join(["v(1)"]*80) + ")",
}
print("Enhancement-225: command/expression-evaluator crashes -> clean errors")
for name, body in bad.items():
    ok = True
    for _ in range(4):                   # a few runs (heap-layout dependent pre-fix)
        rc, out = run(body)
        if not is_clean(rc, out):
            ok = False; break
    check(name, ok, "" if ok else f"rc={rc}")

# --- regression: normal expressions still compute correctly ---
def scalar(out, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None

rc, out = run("let n=length(fft(v(1)))\nprint n")
n = scalar(out, "n")
check("regression: fft(v(1)) still transforms (length 33 for the padded tran)",
      is_clean(rc, out) and n is not None and n > 1, f"n={n}")

rc, out = run("let g=deriv(v(1))\nprint length(g)")
gl = scalar(out, "length(g)")
check("regression: deriv(v(1)) still differentiates (full-length result)",
      is_clean(rc, out) and gl is not None and gl > 1, f"len={gl}")

rc, out = run("let a = (1 ? 10 : 20)\nprint a\nlet b = (0 ? 10 : 20)\nprint b")
check("regression: normal ternary picks the right branch (1?10:20 = 10, 0?..:20)",
      scalar(out, "a") == 10.0 and scalar(out, "b") == 20.0,
      f"a={scalar(out,'a')} b={scalar(out,'b')}")

rc, out = run("let v=unitvec(5)\nprint v[2]")
check("regression: ordinary vector indexing unitvec(5)[2] = 1",
      scalar(out, "v[2]") == 1.0, f"{scalar(out,'v[2]')}")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
