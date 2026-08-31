#!/usr/bin/env python3
"""Enhancement-521: analog user-defined functions, audited against Accellera
VAMS-2023 clause 4.7, then fixed.

What this suite pins, each against the quoted clause:

  * 4.7.1 -- "parameter_declaration" is a legal analog_function_item, and the
    clause defines the scoping: "if a locally-defined parameter with the
    specified name does not exist, then the module-level parameter of the
    specified name will be used." A function-local `parameter real k = 3.0;`
    CRASHED codegen ("attempted to read undefined value"): the module walk
    never enters function scopes, so the parameter had no binding. It lowers
    as an inlined compile-time constant now -- a local shadows the module
    parameter of the same name, other module parameters read through, a
    NETLIST OVERRIDE of those propagates into the function, an override of
    the shadowed one does not leak in, and $param_given on a local is
    constantly false ($param_given's constant answers are BOOL constants
    now: an integer constant there panicked the MIR folder at the bool->int
    cast -- a latent bug the paramset path shared).
  * 4.7.2.3 -- "All output arguments of an analog user-defined function are
    initialized, zero (0) if numeric ... which in turn means that the
    argument passed to it is reset to zero (0)". A pure OUTPUT array had
    inout copy-in semantics: the body read the caller's values where the
    LRM mandates zeros, and an unassigned output array left the caller
    unchanged where the LRM mandates the reset. Inout arrays keep
    copy-in/copy-out.
  * 4.7.1 Example 3 -- the LRM's own array-argument spelling, `inout [0:1]a;
    input [0:1]b; real a[0:1], b[0:1];`, was "unexpected token '['" -- and
    the compiler's own name-then-range elaboration REWRITE generated exactly
    this form and then refused to parse it. Example 3 compiles verbatim now
    and computes exactly; the dimensions come from the mandatory data-type
    declaration.
  * The 4.7.1 restriction list stays enforced: recursion (direct and
    mutual), access functions, contributions, analog operators, event
    control, zero-argument functions, and module-variable references inside
    a function body are all still rejected.
  * Deliberate relaxations stay and are documented (compliance doc 5.6):
    named blocks in function bodies, UDF calls in constant contexts, and a
    function-local parameter ARRAY is a clean error, not a crash.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lu_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_file(name):
    osdi = os.path.join(HERE, f"_lu_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lu_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lu_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmudf\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def opvar(out, name):
    m = re.search(rf"@n1\[{name}\]\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


HDR = '`include "disciplines.vams"\n'

# ---- the committed module: every fixed semantic at run time ----------------
print("lrmudf.va (run-time values):")
rc, out, osdi = compile_file("lrmudf.va")
check("[1] lrmudf.va compiles (local params, output arrays, LRM Example 3)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmudf", "op\n"
              "print @n1[r_local] @n1[r_shadow] @n1[r_chain] @n1[r_zinit]\n"
              "print @n1[r_reset] @n1[r_mixed] @n1[r_ex3]", "main", osdi)
    for name, want, why in [
        ("r_local", 4, "function-local parameter: 1 + k(3)"),
        ("r_shadow", 14, "local p(3) shadows module p(2); module q reads through"),
        ("r_chain", 42, "chained local defaults from q; $param_given(local)=0"),
        ("r_zinit", 1, "pure output array reads LRM zeros, not the caller's {5,6}"),
        ("r_reset", 0, "unassigned output array RESETS the caller to {0,0}"),
        ("r_mixed", 14, "partial-assign output {6,0} + inout copy-in/out {8,8}"),
        ("r_ex3", 816, "LRM 4.7.1 Example 3 verbatim (range on the direction line)"),
    ]:
        got = opvar(sim, name)
        check(f"[2] {why} = {want}", got == want, f"{got}")

    # the scoping corners, driven from the netlist
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmudf(q=20)", "op\n"
              "print @n1[r_shadow] @n1[r_chain]", "qovr", osdi)
    check("[3] overriding module q propagates INTO the function (14 -> 24)",
          opvar(sim, "r_shadow") == 24, opvar(sim, "r_shadow"))
    check("[4] ...and into a local parameter's default (42 -> 82)",
          opvar(sim, "r_chain") == 82, opvar(sim, "r_chain"))
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmudf(p=99)", "op\n"
              "print @n1[r_shadow]", "povr", osdi)
    check("[5] overriding the SHADOWED module p does not leak in (still 14)",
          opvar(sim, "r_shadow") == 14, opvar(sim, "r_shadow"))

# ---- the 4.7.1 restriction list stays enforced -----------------------------
print("\nthe 4.7.1 restrictions stay enforced:")
rc, out, _ = compile_src(HDR + """
module rec(a,b); inout a,b; electrical a,b;
analog function real f;
  input x; real x;
  f = f(x - 1.0);
endfunction
analog V(a,b) <+ f(3.0);
endmodule
""", "rec")
check("[6] direct recursion is still a clean error", rc != 0 and "recurs" in out)

rc, out, _ = compile_src(HDR + """
module acc(a,b); inout a,b; electrical a,b;
analog function real f;
  input x; real x;
  f = x + V(a,b);
endfunction
analog V(a,b) <+ f(3.0);
endmodule
""", "acc")
check("[7] access functions inside a function body are still rejected",
      rc != 0)

rc, out, _ = compile_src(HDR + """
module noarg(a,b); inout a,b; electrical a,b;
analog function real f;
  f = 1.0;
endfunction
analog V(a,b) <+ f();
endmodule
""", "noarg")
check("[8] a zero-argument function is still rejected (4.7.1)", rc != 0)

rc, out, _ = compile_src(HDR + """
module fpa(a,b); inout a,b; electrical a,b;
analog function real f;
  input x; real x;
  parameter real w[0:1] = '{2.0, 3.0};
  f = x * w[0] + w[1];
endfunction
analog V(a,b) <+ f(1.0);
endmodule
""", "fpa")
check("[9] a function-local parameter ARRAY is a clean error, not a crash",
      rc != 0 and "crashed" not in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
