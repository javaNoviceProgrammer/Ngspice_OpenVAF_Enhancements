#!/usr/bin/env python3
"""verify_vafargcoerce.py -- Enhancement-313: two builtin argument type-coercion gaps in
openvaf-r's hir_ty inference, each producing broken code that the shipped (release)
compiler emitted silently. Found by grammar-based middle/back-end fuzzing (the same
campaign family as E-307..310).

(a) FILE/STRING FORMAT TASKS were never type-checked. `infere_display` -- which parses a
    format string and inserts the int->real cast a `%g`/`%e`/`%f`/`%r` conversion needs --
    was reached only by the CONSOLE tasks ($display/$strobe/$write/$monitor/$debug plus
    $fatal/$warning/$error/$info). The file ($fdisplay/$fwrite/$fstrobe/$fmonitor/$fdebug)
    and string ($swrite/$sformat) tasks were missing from that dispatch, so a `%g` fed an
    integer kept its integer value while the formatting callback typed its parameter as
    `double`. Lowering passed a raw i32 to a double parameter: INVALID LLVM IR. The verifier
    (a debug_assert, off in release) caught it in the assertions build; release emitted a
    malformed .osdi, and the callback read the integer's bit pattern as a double -- garbage.
    fmt_roundtrip.va makes it observable: format 5 with "%g", read it back with $sscanf, use
    it as a conductance. Correct -> I = 5*V. Pre-fix -> the recovered value is the denormal
    ~2.47e-323 (bits of the integer 5), so the current collapses to ~0.

(b) ddx WITH AN INTEGER ARGUMENT crashed the compiler. `infere_ddx` recorded the "must be
    real" requirement + cast on the ddx CALL expression instead of on the differentiated
    argument. The ddx call already has type Real, so an integer argument inserted a Real cast
    onto a Real-typed expression; `needs_cast` then saw src == dst == Real and tripped its
    debug_assert -- and the release build aborted downstream with no .osdi.

The fix routes the file/string format tasks through infere_display, and records the ddx
requirement on the argument. Both are output-preserving: the whole 419-model corpus produces
BYTE-IDENTICAL MIR before and after (the fixes only touch the previously-crashing / invalid
paths), and the fuzz corpus is clean.

Checks (this suite FAILS on the pre-fix binary):
  1. ddx(integer, probe) compiles           -- crashed the compiler before (b);
  2. its model simulates to I = 1e-3*V       -- ddx of a probe-independent value is 0;
  3. $sformat("%g", integer) compiles        -- invalid IR before (a);
  4. the round-tripped value is exactly 5    -- pre-fix reads garbage (~2.47e-323).

The XSPICE/OSDI models load from the prebuilt bundle via SPICE_LIB_DIR (set by _setup); if
unavailable in this checkout the ngspice checks self-skip while the compile checks still run.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    osdi = os.path.join(HERE, name.replace(".va", ".osdi"))
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi],
                           capture_output=True, text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if "has crashed" in out or "panicked at" in out or "please open an issue" in out:
        return False, "COMPILER CRASH"
    if r.returncode != 0:
        return False, f"exit {r.returncode}"
    return os.path.exists(osdi), "compiled"


def ngspice_iv1(model_file, model_name):
    """pre_osdi the model, run .op, return i(v1) or None (skip if models unavailable)."""
    deck = (f"* osdi op\nn1 p 0 mdl\nv1 p 0 dc 1\n.model mdl {model_name}\n"
            f".control\npre_osdi {model_file}\nop\nprint i(v1)\n.endc\n.end\n")
    path = os.path.join(HERE, "_run.cir")
    with open(path, "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return None
    out = (r.stdout or "") + (r.stderr or "")
    if "unable to" in out.lower() or "could not" in out.lower() and "pre_osdi" in out.lower():
        return None
    m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


print("Enhancement-313: builtin argument type-coercion gaps (format tasks + ddx)")

# ---- (b) ddx integer ---------------------------------------------------------
okc, verdict = compile_va("ddx_integer.va")
check("ddx(integer, probe) compiles (crashed the compiler before)", okc, verdict)
if okc:
    iv = ngspice_iv1("ddx_integer.osdi", "ddxint")
    if iv is None:
        print("  SKIP  ngspice/OSDI unavailable -- ddx runtime check")
    else:
        # I(p,n) = 1e-3*V + ddx(int,probe)=0  ->  i(v1) = -1e-3
        check("ddx model simulates to I = 1e-3*V (ddx term is 0)",
              abs(iv - (-1e-3)) < 1e-9, f"i(v1)={iv:.6e}")

# ---- (a) $sformat %g + integer ----------------------------------------------
okc, verdict = compile_va("fmt_roundtrip.va")
check("$sformat(\"%g\", integer) compiles (invalid IR before)", okc, verdict)
if okc:
    iv = ngspice_iv1("fmt_roundtrip.osdi", "fmtrt")
    if iv is None:
        print("  SKIP  ngspice/OSDI unavailable -- format round-trip check")
    else:
        # correct: I = 5*V -> i(v1) = -5.0 ; pre-fix: garbage denormal ~ -2.47e-323
        check("round-tripped %g value is exactly 5 (pre-fix read garbage bits)",
              abs(iv - (-5.0)) < 1e-9, f"i(v1)={iv:.6e}")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
