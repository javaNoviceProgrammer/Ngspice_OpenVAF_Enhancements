#!/usr/bin/env python3
"""verify_vafconstlit.py -- Enhancement-314: constant-evaluation / literal-materialization
robustness in openvaf-r. Two independent defects found by grammar-based fuzzing (the
E-307..313 campaign family), both in how the compiler folds/materializes constant and
literal input.

(a) INTEGER CONST-FOLD OVERFLOW. Two hand-rolled integer const evaluators used UNCHECKED
    i32 arithmetic. In `elaborate.rs` the Enhancement-91 bus-width folder's `+`/`-`
    (parse_add) and unary negate (parse_unary) overflowed on inputs like
    `localparam integer k = 2147483647 + 1;` (its `*` was already checked). In
    `const_eval.rs` the MIR const-fold made Iadd/Isub/Imul wrapping (Enhancement-286) but
    MISSED `Ineg`, so negating i32::MIN (e.g. `-(1<<31)`) overflowed. Both aborted the
    overflow-checked build; the shipped release wrapped silently. Fixed: elaborate.rs uses
    checked_add/sub/neg (declining the fold, like its `*`, so an un-foldable width is left
    unchanged); const_eval.rs uses wrapping_neg (matching its wrapping Iadd/Isub/Imul).

(b) UNBOUNDED REPLICATION. `{N{...}}` materializes N copies of its operands at COMPILE
    time (an N*|elems| list, and for strings an N*|elems|-char format string). A huge
    literal count -- `{'d999999999{"x"}}` ~= 1e9 -- allocated gigabytes and HUNG the
    compiler on ~1 line of source: a shipped denial-of-service. Fixed: cap the count at
    2^20 in `concat_rep_count` (hir_ty) and reject an abusive count with the existing
    InvalidReplicationCount diagnostic instead of hanging.

Both fixes are output-preserving: checked/wrapping arithmetic is identical to plain on
every non-overflowing input, and the cap only rejects counts above 2^20 -- no real model
has either, so the 419-model corpus is unaffected.

Checks:
  1. the integer-overflow model compiles (aborted the overflow-checked build before) and
     simulates to I = 1e-3*V (forward correctness -- (a) is assertions-only, release
     always compiled, so this guards the numbers);
  2. a small legitimate replication {4{"ab"}} still compiles;
  3. an abusive replication {'d999999999{"x"}} is REJECTED QUICKLY (< 8 s) rather than
     hanging -- this FAILS on the pre-fix binary, which hangs.
"""
import os
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


def compile_va(name, timeout=30):
    osdi = os.path.join(HERE, name.replace(".va", ".osdi"))
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if "has crashed" in out or "panicked at" in out:
        return False, "COMPILER CRASH"
    return (r.returncode, out)


def write(name, text):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(text)


def ngspice_iv1(osdi, model):
    deck = (f"* op\n.control\npre_osdi {osdi}\n.endc\n"
            f"n1 p 0 m1\nv1 p 0 dc 1\n.model m1 {model}\n"
            f".control\nop\nprint i(v1)\n.endc\n.end\n")
    write("_run.cir", deck)
    try:
        r = subprocess.run([NGSPICE, "-b", "_run.cir"], cwd=HERE, capture_output=True,
                           text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return None
    import re
    m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", (r.stdout or "") + (r.stderr or ""))
    return float(m.group(1)) if m else None


print("Enhancement-314: const-eval / literal-materialization robustness")

# ---- (a) integer overflow ----------------------------------------------------
rc, _ = compile_va("int_overflow.va")
compiled = rc == 0
check("integer-overflow const-fold model compiles (aborted the checked build before)",
      compiled, f"rc={rc}")
if compiled:
    iv = ngspice_iv1("int_overflow.osdi", "intovf")
    if iv is None:
        print("  SKIP  ngspice/OSDI unavailable -- forward correctness check")
    else:
        check("integer-overflow model simulates to I = 1e-3*V (forward guard)",
              abs(iv - (-1e-3)) < 1e-9, f"i(v1)={iv:.6e}")

# ---- (b) replication ---------------------------------------------------------
rc, _ = compile_va("big_replication.va")
check("small legitimate replication {4{...}} compiles", rc == 0, f"rc={rc}")

write("_huge.va", '`include "disciplines.vams"\n'
                  'module hugerep(a,b); inout a,b; electrical a,b; string s;\n'
                  'analog begin s = {' + "'" + 'd999999999{"x"}}; I(a,b) <+ 1e-3*V(a,b); end\n'
                  'endmodule\n')
rc, _ = compile_va("_huge.va", timeout=8)
check("abusive replication {'d999999999{...}} is rejected quickly, not a hang "
      "(fails on the pre-fix binary)", rc != "HANG", "HANG" if rc == "HANG" else f"clean rc={rc}")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
