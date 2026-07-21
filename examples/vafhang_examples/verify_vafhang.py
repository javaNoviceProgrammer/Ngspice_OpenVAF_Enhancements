#!/usr/bin/env python3
"""verify_vafhang.py -- Enhancement-264: large instance arrays in openvaf-r.

Two independent robustness properties of the hierarchy elaboration + OSDI codegen
path, each with its own reproducer:

  CHECK A -- flatten scaling is O(N), not O(N^2)  [fast, always runs]
      `flatten_array.va` instantiates a 16001-element array. The module-flatten
      pass (E-5/E-49/E-86 text rewrite) was O(N^2) in the instance count:
      hierarchical-name resolution re-scanned every instance prefix per token,
      per port binding, per instance, and each per-instance scope deep-cloned the
      whole absolute-reference map. Elaboration time quadrupled when N doubled
      (2k~1.8s, 8k~30s, 16k~100s), so a large array looked like a hang. It is now
      O(N) (ancestor-set for O(1) prefix lookups, a dot-free early-out, and an
      Rc-shared absolute-reference map): 16001 instances compile in ~1s, and
      32001 in ~2s -- a re-introduced O(N^2) would blow the absolute time bounds
      below (it would be ~100s / ~400s).

  CHECK B -- deep per-node fan-in no longer overflows the codegen stack  [--slow]
      `deep_fanin.va` puts 8001 instances -- each with a distinct parameter, so
      the contributions do NOT collapse -- on ONE node pair, building an
      8001-deep contribution/derivative chain. OpenVAF's recursive OSDI codegen
      ran on a rayon worker whose default stack is a few MB and aborted with
      "thread has overflowed its stack" (SIGABRT). Codegen now runs on a pool
      with a generous worker stack, so this compiles. It is genuinely a lot of IR
      (~40s), so check B is gated behind `--slow` (or `NG_RUN_ALL=1`).

Passes iff every enabled check compiles cleanly (no hang, no crash) within its
time bound. Reported to the regression harness by exit code (0 = pass).
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

RUN_SLOW = "--slow" in sys.argv or os.environ.get("NG_RUN_ALL") == "1"

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(src_text, timeout):
    """Write src_text to a temp .va, compile it, return (returncode, seconds).

    returncode < 0 or == 134 is a crash (signal / SIGABRT stack overflow);
    124 marks our own timeout (a hang)."""
    path = os.path.join(tempfile.gettempdir(), "vafhang_in.va")
    out = os.path.join(tempfile.gettempdir(), "vafhang_out.osdi")
    with open(path, "w") as f:
        f.write(src_text)
    t0 = time.time()
    try:
        r = subprocess.run([OPENVAF, path, "-o", out],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.returncode, time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, time.time() - t0


def array_src(n, parameterized):
    """A `top` that instantiates an (n+1)-element array of `leaf` on one node pair."""
    if parameterized:
        leaf = ("module leaf(a, b); inout a, b; electrical a, b;\n"
                " parameter real R = 1.0; analog I(a, b) <+ V(a, b) / R; endmodule\n")
    else:
        leaf = ("module leaf(a, b); inout a, b; electrical a, b;\n"
                " analog I(a, b) <+ V(a, b); endmodule\n")
    return ('`include "disciplines.vams"\n' + leaf +
            f"module top(a, b); inout a, b; electrical a, b;\n"
            f" leaf u[0:{n}] (.a(a), .b(b)); endmodule\n")


print("Enhancement-264: openvaf-r large instance arrays -- O(N) flatten + codegen stack headroom")

# CHECK A: flatten O(N). A re-introduced O(N^2) makes 16k ~100s and 32k ~400s,
# so these generous absolute bounds (well above the ~1-2s reality) catch it.
rc16, t16 = compile_va(array_src(16000, parameterized=False), timeout=60)
check("[A] 16001-instance array elaborates + compiles (O(N), not a hang)",
      rc16 == 0 and t16 < 30.0, f"rc={rc16} {t16:.1f}s")

rc32, t32 = compile_va(array_src(32000, parameterized=False), timeout=90)
check("[A] 32001-instance array stays linear (2x size -> ~2x time, not ~4x)",
      rc32 == 0 and t32 < 45.0, f"rc={rc32} {t32:.1f}s")

# CHECK B: deep-fan-in stack overflow guard (slow -- thousands of live contributions).
if RUN_SLOW:
    rcB, tB = compile_va(array_src(8000, parameterized=True), timeout=300)
    check("[B] 8001 distinct contributions on one node compile (was a stack-overflow SIGABRT)",
          rcB == 0, f"rc={rcB} {tB:.1f}s")
else:
    print("  SKIP  [B] deep-fan-in stack-overflow guard (run with --slow or NG_RUN_ALL=1)")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
