#!/usr/bin/env python3
"""Enhancement-363: two openvaf-r compiler crashes found by cross-feature fuzzing.

Both were found by a generator that composes features which had each been
developed and tested in ISOLATION (the ~100 enhancements in this repo). Neither
is reachable by mutating the corpus -- mutants die at the parser -- and neither
involves malformed input: every file here is legal Verilog-A that the shipped
compiler answered with "OpenVAF encountered a problem and has crashed!".

The campaign harness that found them lives in `fuzz/` next to this file
(generators, driver, and a structural reducer). It is committed so the search is
repeatable, but it is NOT run by the regression -- the runner globs
`examples/*_examples/verify_*.py`, so `fuzz/` is excluded by name, and a fuzz run
takes minutes rather than the second this file takes. What THIS file does is pin
the specific reproducers so they cannot come back.

  [1] BLOCK MERGED INTO ITSELF  (mir_opt/src/simplify_cfg.rs)
      `simplify_unconditional_jmp_term(src, dst)` merges `src` into `dst`: it
      retargets every predecessor of `src` to `dst`, then removes `src` from the
      layout. It had no guard for `src == dst`. A block whose terminator jumps to
      ITSELF (`block2: jmp block2`) is a self-loop -- which is what a `case`
      inside a `do-while` folds to -- so the retarget was a no-op and the block
      was then deleted while terminators still named it. `mir_llvm::Builder::new`
      allocates LLVM blocks only for blocks IN the layout, so codegen unwrapped
      `None` (builder.rs:655/656/690). The CFG layer already considered this
      invalid input: `ControlFlowGraph::replace` opens with
      `debug_assert_ne!(old, new)`, which is exactly what fires on a
      debug-assertions build. Fixed by declining the self-merge; a self-loop is a
      legitimate CFG shape and must survive to codegen.

  [2] ARRAY PARAMETERS WERE NEVER INSTANCE-RENAMED  (hir/src/elaborate.rs)
      A module has THREE array collections -- `buses` (vectored nets/ports),
      `var_arrays` (array variables, E-4) and `param_arrays` (array-valued
      parameters, E-14). Flattening renamed the first two per instance but not
      the third, so every instance re-declared `cf[0]`, `cf[1]`, ... under the
      same names and name resolution rejected the second one. A module with an
      array parameter could therefore not be instantiated twice -- and two
      DIFFERENT modules that merely shared an array-parameter name collided too.
      Legal Verilog-A, refused. Fixed by chaining `param_arrays` into the rename.

KNOWN AND DELIBERATELY NOT PAPERED OVER: a provably NON-TERMINATING analog loop
(`while (1)`, or a loop whose index is never advanced) still fails to compile.
After fix [1] its MIR is well-formed -- the loop is a self-loop, as it should be
-- but the contributions that follow the loop are then unreachable, so OSDI
codegen reads values no reachable block defines. There is no correct object code
for such a model: it can never finish one evaluation. The right answer is a
diagnostic rejecting it, not a substituted value, and that is left as follow-up
work rather than trading a loud crash for a silently meaningless model.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    """Returns (rc, combined output). rc 101 is the compiler PANIC we are pinning."""
    out = os.path.join(HERE, "_" + name.replace(".va", ".osdi"))
    r = subprocess.run([OPENVAF, name, "-o", out], cwd=HERE, capture_output=True,
                       text=True, timeout=180, errors="replace")
    return r.returncode, r.stdout + r.stderr


# [1] a `case` inside a `do-while`. The loop terminates; if/else, while, for and
#     repeat in the same position always compiled -- only `case` folded the body
#     to a self-loop and tripped the merge.
CASE_IN_DOWHILE = """`include "disciplines.vams"
module case_in_dowhile(a, b);
  inout a, b;
  electrical a, b;
  integer i;
  analog begin
    i = 0;
    do begin
      case (1)
        default: i = i;
      endcase
      i = i + 1;
    end while (i < 2);
    I(a, b) <+ V(a, b);
  end
endmodule
"""

# [2] one module with an array parameter, instantiated twice.
ARRAY_PARAM_TWICE = """`include "disciplines.vams"
module apleaf(p, n);
  inout p, n;
  electrical p, n;
  parameter real cf[0:2] = '{1.0, 2.0, 3.0};
  analog I(p, n) <+ cf[0] * V(p, n);
endmodule
module array_param_twice(a, b);
  inout a, b;
  electrical a, b;
  electrical t;
  apleaf x0(a, t);
  apleaf x1(a, t);
  analog I(t, b) <+ V(t, b);
endmodule
"""

# [2b] two DIFFERENT modules that merely share an array-parameter name. This one
#      shows the bug was never about instantiating the same module twice.
ARRAY_PARAM_SHARED_NAME = """`include "disciplines.vams"
module apa(p, n);
  inout p, n;
  electrical p, n;
  parameter real cf[0:1] = '{1.0, 2.0};
  analog I(p, n) <+ cf[0] * V(p, n);
endmodule
module apb(p, n);
  inout p, n;
  electrical p, n;
  parameter real cf[0:1] = '{3.0, 4.0};
  analog I(p, n) <+ cf[1] * V(p, n);
endmodule
module array_param_shared_name(a, b);
  inout a, b;
  electrical a, b;
  electrical t;
  apa x0(a, t);
  apb x1(a, t);
  analog I(t, b) <+ V(t, b);
endmodule
"""

# Constructs that were ALWAYS fine in a do-while. Pinned so a future fix to the
# merge logic cannot quietly start rejecting them.
DOWHILE_NEIGHBOURS = """`include "disciplines.vams"
module dowhile_neighbours(a, b);
  inout a, b;
  electrical a, b;
  integer i, j;
  analog begin
    i = 0;
    do begin
      if (i > 0) j = 1; else j = 2;
      i = i + 1;
    end while (i < 2);
    i = 0;
    do begin
      while (i > 99) i = i + 1;
      i = i + 1;
    end while (i < 2);
    i = 0;
    do begin
      j = 0;
      do begin j = j + 1; end while (j < 2);
      i = i + 1;
    end while (i < 2);
    I(a, b) <+ V(a, b);
  end
endmodule
"""

CASES = [
    ("case inside a do-while compiles", "case_in_dowhile.va", CASE_IN_DOWHILE),
    ("array param, module instantiated twice", "array_param_twice.va", ARRAY_PARAM_TWICE),
    ("array param name shared by two modules", "array_param_shared_name.va",
     ARRAY_PARAM_SHARED_NAME),
    ("if/while/do-while inside a do-while still compile", "dowhile_neighbours.va",
     DOWHILE_NEIGHBOURS),
]


def main():
    for label, fname, src in CASES:
        with open(os.path.join(HERE, fname), "w") as f:
            f.write(src)
        rc, out = compile_va(fname)
        # rc 101 is the panic these fixes remove; any other non-zero would be a
        # diagnostic, which for this legal input would equally be a failure.
        if rc == 101:
            check(label, False, "COMPILER PANIC (exit 101)")
        elif rc != 0:
            first = next((l for l in out.splitlines() if l.startswith("error")), "rc=%d" % rc)
            check(label, False, first[:70])
        else:
            check(label, True, "compiles")

    for junk in os.listdir(HERE):
        if junk.startswith("_") and junk.endswith(".osdi"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
