#!/usr/bin/env python3
"""verify_vafcrash4.py -- Enhancement-263: three openvaf-r compiler PANICs found by a
robustness-fuzzing campaign, now clean.

Each input below made the shipped `openvaf-r` PANIC (exit 101, "OpenVAF encountered a
problem and has crashed!") instead of either compiling or emitting a diagnostic. The
three were surfaced by three fuzzing strategies (byte/token mutation of the whole .va
corpus, grammar-aware structured adversarial inputs, and valid-but-pathological modules
that compile through to the backend); all three are now fixed:

 [1] nested_ddt.va      -- deeply nested analog operators (ddt/idt/absdelay) produced a
                           cached value with no init-time definition (ValueDef::Invalid),
                           crashing the instance-setup cache builder (sim_back/init.rs)
                           and the OSDI backend. Now compiles to a valid .osdi.
 [2] ddx_badunknown.va  -- ddx() whose 2nd argument is not a probe access function
                           (ddx(V,5)) crashed hir_lower (unwrap_param); the type checker
                           had a dead-code diagnostic (it tested the ddx call itself, not
                           the unknown). Now a clean "invalid ddx unknown" diagnostic.
 [3] malformed_module.va -- a malformed module whose item TREE recorded an instantiation
                           but whose parsed AST item list was empty crashed the
                           hierarchy-flattening pass (hir/elaborate.rs, items.first()
                           .unwrap()). Now the module is returned verbatim (a no-op).

The test passes iff none of the three CRASH or HANG (each compiles OK or emits a clean
diagnostic ERROR). Reported to the regression harness via exit code (0 = pass).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


OUT = os.path.join(tempfile.gettempdir(), "vafcrash4_out.osdi")


def run(va_name, timeout=30):
    """Compile examples/vafcrash4_examples/<va_name>; return OK / ERROR / CRASH / HANG."""
    path = os.path.join(HERE, va_name)
    try:
        r = subprocess.run([OPENVAF, path, "-o", OUT],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode is not None and r.returncode < 0:
        return "CRASH"
    if "panicked at" in out or "has crashed" in out or r.returncode == 101:
        return "CRASH"
    return "OK" if r.returncode == 0 else "ERROR"


print("Enhancement-263: openvaf-r robustness -- 3 fuzz-found panics -> clean errors")

# [1] nested analog operators: previously CRASH (Invalid init-cache value); now compiles.
r1 = run("nested_ddt.va")
check("[1] nested ddt/idt/absdelay compiles cleanly (was a sim_back/OSDI crash)",
      r1 == "OK", r1)

# [2] ddx(V,5): previously CRASH (unwrap_param); now a clean diagnostic.
r2 = run("ddx_badunknown.va")
check("[2] ddx() with a non-probe unknown gives a clean error (was a hir_lower crash)",
      r2 == "ERROR", r2)

# [3] malformed module (empty AST item list + recorded instantiation): previously CRASH
# (elaborate.rs items.first().unwrap()); now a clean error / no-op.
r3name = "malformed_module.va"
if os.path.exists(os.path.join(HERE, r3name)):
    r3 = run(r3name)
    check("[3] malformed module (empty item list) does not crash the flatten pass",
          r3 in ("ERROR", "OK"), r3)
else:
    check("[3] malformed_module.va present", False, "missing reproducer")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
