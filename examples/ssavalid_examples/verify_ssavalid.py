#!/usr/bin/env python3
"""Enhancement-347: the SSA re-builder no longer mints an Invalid phi operand.

Enhancement-329 fixed the CRASH that a GRAVESTONE phi operand caused in the
small-signal network builder, and said plainly that a deeper defect was left
open: the MIR carrying that operand is SSA-INVALID, so the assertions build
trips `debug_assert!(cx.func.validate())`. This is that fix.

WHERE IT ACTUALLY CAME FROM (E-329 named the right file but the wrong path, which
is why the obvious fix location did not work). A backtrace at phi creation:

    mir_build::ssa::SSABuilder::finish_predecessors_lookup
    mir_build::SSAVariableBuilder::use_var          <- a SECOND SSA builder
    mir_build::SSAVariableBuilder::define_at_exit
    sim_back::topology::lineralize::builid_analog_operators

The gravestone is NOT minted while `mir_build` constructs the function. It comes
from `SSAVariableBuilder` -- the "add values to an already finished MIR function"
builder -- called during topology linearisation. That explains every symptom:
`FunctionBuilder::finalize()` never sees these phis (measured: exactly one phi
exists there, carrying no `v0`), and `validate()` passes at sim_back/src/lib.rs
line 175 but fails at 179, on either side of `Topology::new`.

THE FIX. In `finish_predecessors_lookup`, a GRAVESTONE operand now takes a LIVE
SIBLING operand of the same phi. Such an operand sits on an edge out of a block
unreachable from the entry, so the edge cannot execute and the value is never
read -- any sibling is equally correct. A sibling rather than a synthesised zero
because that builder is TYPE-AGNOSTIC: it has no `Type` for the place, so a
sibling is the only type-correct value available.

WHAT THIS SCRIPT CAN AND CANNOT CHECK. `validate()` is `debug_assert`-only, so
the definitive check needs an assertions build and is not runnable from the
shipped release binary:

    cd OpenVAF-master-20260610
    CARGO_TARGET_DIR=target-assert RUSTFLAGS="-C debug-assertions=on" \
        cargo build --release --bin openvaf-r --features openvaf-driver/llvm18

Each model in `va/` was verified to TRIP `assertion failed: cx.func.validate()`
on a PRE-fix assertions build and to be clean after -- they are proven triggers,
not decoration. (A `for`-loop variant was tried, did NOT trip, and was dropped
rather than shipped as filler.)

What the release binary can still prove, and what this checks:

  [1] every gravestone shape compiles
  [2] every one simulates to a finite operating point
  [3] the dead code contributes EXACTLY zero -- each model matches a reference
      circuit with the gravestone ingredients removed, bit for bit
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

# module name -> (series conductance used by the model, in S)
SHAPES = {"gs_basic": 1.0e-3, "gs_nested": 2.0e-3, "gs_two_dead_loops": 1.0e-3}
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def op_of(name, deck_body, pre):
    """run one op and return (i(v1), v(mid)) or None"""
    p = os.path.join(HERE, "_%s.cir" % name)
    with open(p, "w") as f:
        f.write("ssa valid %s\n%s.control\n%sset numdgt=12\noption noacct\n"
                "op\nprint i(v1) v(mid)\n.endc\n.end\n" % (name, deck_body, pre))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=300,
                           errors="replace")
    finally:
        if os.path.exists(p):
            os.remove(p)
    t = r.stdout + r.stderr
    i = re.search(r"i\(v1\)\s*=\s*([-\d.]+e?[-+]?\d*)", t, re.I)
    v = re.search(r"v\(mid\)\s*=\s*([-\d.]+e?[-+]?\d*)", t, re.I)
    if r.returncode < 0 or not i or not v:
        return None
    return float(i.group(1)), float(v.group(1))


def main():
    compiled, results = {}, {}
    for mod in SHAPES:
        src = os.path.join(HERE, "va", "%s.va" % mod)
        out = os.path.join(HERE, "_%s.osdi" % mod)
        r = subprocess.run([OPENVAF, src, "-o", out], capture_output=True,
                           text=True, timeout=600)
        compiled[mod] = r.returncode == 0 and os.path.exists(out)
    check("every gravestone shape compiles", all(compiled.values()),
          ", ".join("%s=%s" % (m, "ok" if v else "FAIL") for m, v in compiled.items()))

    # a reference model with the gravestone ingredients removed: the same two
    # conductances and nothing else. `r0*r1` must contribute exactly zero, so the
    # shape and the reference have to agree bit for bit.
    ref_src = os.path.join(HERE, "_ref.va")
    with open(ref_src, "w") as f:
        f.write('`include "disciplines.vams"\n'
                "module gs_ref(a,b,c); inout a,b,c; electrical a,b,c;\n"
                "  parameter real g = 1.0e-3;\n"
                "  analog begin\n"
                "    I(a,b) <+ g*V(a,b);\n"
                "    I(b,c) <+ g*V(b,c);\n"
                "  end\nendmodule\n")
    r = subprocess.run([OPENVAF, ref_src, "-o", os.path.join(HERE, "_ref.osdi")],
                       capture_output=True, text=True, timeout=600)
    ref_ok = r.returncode == 0

    finite, exact = [], []
    for mod, g in SHAPES.items():
        if not compiled[mod]:
            finite.append("%s: not compiled" % mod)
            continue
        # c1 MUST be terminated -- left floating, no current flows and every
        # shape trivially reads 1 V, which would make the comparison vacuous
        body = ("V1 a 0 dc 1\nN1 a mid c1 m\nRL c1 0 1k\n"
                ".model m %s\n" % mod)
        got = op_of(mod, body, "pre_osdi _%s.osdi\n" % mod)
        if got is None:
            finite.append("%s: no operating point" % mod)
            continue
        results[mod] = got
        rbody = ("V1 a 0 dc 1\nN1 a mid c1 m\nRL c1 0 1k\n"
                 ".model m gs_ref g=%g\n" % g)
        want = op_of("ref_%s" % mod, rbody, "pre_osdi _ref.osdi\n") if ref_ok else None
        if want is None or got != want:
            exact.append("%s: %s vs ref %s" % (mod, got, want))

    check("every shape simulates to a finite operating point", not finite,
          "; ".join(finite) if finite else
          ", ".join("%s=%.6g V" % (m, v[1]) for m, v in results.items()))
    check("the dead code contributes EXACTLY zero (matches the reference)",
          ref_ok and not exact,
          "; ".join(exact) if exact else "%d shapes bit-identical to reference"
          % len(results))

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
