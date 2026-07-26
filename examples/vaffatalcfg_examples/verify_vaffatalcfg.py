#!/usr/bin/env python3
"""Enhancement-324: `$fatal` must not strand code in an unreachable block.

`$fatal` used to emit `exit()` and then continue lowering into a freshly created
block with NO incoming edges. That is unsound for a compiled device: every
ret-flag ($fatal/$finish/$stop) is only a flag the simulator inspects AFTER the
eval function returns, and the OSDI eval function has a mandatory epilogue
(store residual/jacobian) that the ABI requires to run. Terminating the MIR
function early stranded both user statements and that epilogue in dead code, and
crashed the SHIPPED compiler two different ways.

Checks (1) and (2) FAIL on the pre-fix binary (compiler panic, no .osdi);
(3) and (4) are forward guards that the run-time meaning of `$fatal` is intact.

  [1] a statement AFTER an unconditional `$fatal` compiles
      (was: panic in mir_opt dead_code_aggressive -- inst belongs to no block)
  [2] a contribution BEFORE an unconditional `$fatal` compiles
      (was: panic in mir_llvm builder -- read of an undefined residual)
  [3] both models load and the guarded model still ABORTS the run, printing the
      `$fatal` message -- i.e. the flag mechanism is untouched
  [4] `$finish`/`$stop`, which always used the flag-and-continue lowering that
      `$fatal` now shares, are unaffected
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    """Compile <name>.va -> <name>.osdi. Returns (ok, detail)."""
    src = os.path.join(HERE, name + ".va")
    osdi = os.path.join(HERE, name + ".osdi")
    if os.path.exists(osdi):
        os.remove(osdi)
    try:
        r = subprocess.run([OPENVAF, src, "-o", osdi],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "compiler HUNG"
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()
        sig = next((l for l in tail if "panicked at" in l), "")
        return False, f"rc={r.returncode} {sig[:70]}"
    return os.path.exists(osdi), f"rc={r.returncode}"


def run_deck(deck_text, name):
    path = os.path.join(HERE, name + ".cir")
    with open(path, "w") as f:
        f.write(deck_text)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(path)], cwd=HERE,
                           capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(path):
            os.remove(path)
    return r.stdout + r.stderr


def main():
    # --- [1] / [2]: the two crash shapes now compile ---
    ok1, d1 = compile_va("fatal_after")
    check("statement AFTER an unconditional $fatal compiles", ok1, d1)
    ok2, d2 = compile_va("fatal_before")
    check("contribution BEFORE an unconditional $fatal compiles", ok2, d2)

    # --- [3]: run-time meaning of $fatal preserved (guard still aborts) ---
    ok3, d3 = compile_va("fatal_guard")
    check("the $fatal parameter-guard model compiles", ok3, d3)
    if ok3:
        out = run_deck(
            "fatal guard\n"
            "V1 n1 0 dc 1\n"
            "N1 n1 0 gmod\n"
            ".model gmod fatal_guard r=0\n"
            ".control\n"
            "pre_osdi fatal_guard.osdi\n"
            "op\n"
            ".endc\n.end\n", "_fg")
        msg_ok = "must be positive" in out
        check("$fatal still prints its message at run time", msg_ok,
              "" if msg_ok else "message absent")
        abort_ok = ("abort" in out.lower() or "rejected its configuration" in out)
        check("$fatal still aborts the run", abort_ok,
              "" if abort_ok else "no abort reported")

    # --- [4]: $finish/$stop (same lowering shape) unaffected ---
    fin = os.path.join(HERE, "_fin.va")
    with open(fin, "w") as f:
        f.write('`include "disciplines.vams"\n'
                "module _fin(a,c); inout a,c; electrical a,c;\n"
                "  analog begin I(a,c) <+ V(a,c)/1.0e3; $finish; end\n"
                "endmodule\n")
    try:
        r = subprocess.run([OPENVAF, fin, "-o", os.path.join(HERE, "_fin.osdi")],
                           capture_output=True, text=True, timeout=120)
        check("$finish alongside a contribution still compiles", r.returncode == 0,
              f"rc={r.returncode}")
    finally:
        for p in (fin, os.path.join(HERE, "_fin.osdi")):
            if os.path.exists(p):
                os.remove(p)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
