#!/usr/bin/env python3
"""
verify_generate.py -- verifies the generate machinery end-to-end through
the committed openvaf-r + ngspice: the original Enhancement-5 ladder
(pinned against its hand-written twin) plus the Enhancement-67 audit set.

Enhancement-67 findings and fixes:
  * DEFECT: a genvar used in any ordinary expression position -- most
    visibly a parameter override like `#(.r(1e3*(i+1)))` -- was substituted
    through the identifier-renaming path, which re-escaped the numeral into
    a broken escaped identifier (`1e3*(\\0 +1)` -> "error: '0' was not
    found"). Genvars are now replaced by literal-value holes in every
    expression position (bit-select indices keep their whole-index
    constant fold, which the bus machinery requires).
  * nested generate-for loops did not parse; the grammar now accepts
    nested `for`/`if`/`case` inside a generate block (no repeated
    `generate`/`endgenerate`), and elaboration unrolls recursively with an
    environment of all in-scope genvars and cumulative `_i_j` name
    suffixes.
  * `begin : label` was mandatory; anonymous blocks are now accepted.
  * `generate if` / `generate case` mis-parsed into a broken GENERATE_FOR
    with misleading errors. Both are now supported with elaboration-time
    constant selection (conditions on integer literals and genvars --
    e.g. triangle structures `if (j <= i)`); conditions on module
    PARAMETERS are a clear, honest error: parameters bind at simulation
    time under OSDI (model cards!) and cannot shape generated structure.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def op_ma(osdi, model):
    deck = (f"* gen {model}\nV1 a 0 DC 1\nN1 a 0 mm\n.model mm {model}\n"
            f".save i(V1)\n.op\n.control\npre_osdi {osdi}\nrun\nset numdgt=12\n"
            f"print i(V1)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_g.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_g.cir"],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    m = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", r.stdout + r.stderr)
    return float(m.group(1)) * 1e3 if m else float("nan")


print("[1] E-5 regression: generated ladder == hand-written ladder")
out, ok1 = compile_va("resistor_ladder_generate.va")
out2, ok2 = compile_va("resistor_ladder_manual.va")
if not (ok1 and ok2):
    check("ladders compile", False)
else:
    deck = """* ladder twin compare
.control
pre_osdi resistor_ladder_generate.osdi
pre_osdi resistor_ladder_manual.osdi
.endc
V1 in 0 DC 1
N1 in 0 mmg
.model mmg ladder_generate
V2 in2 0 DC 1
N2 in2 0 mmm
.model mmm ladder_manual
.save i(V1) i(V2)
.op
.control
run
set numdgt=12
print i(V1) i(V2)
.endc
.end
"""
    with open(os.path.join(HERE, "_lad.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_lad.cir"],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    log = r.stdout + r.stderr
    i1 = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", log)
    i2 = re.search(r"v2#branch\s+(-?[0-9.eE+-]+)", log)
    check("6-stage ladder exact (1/6 mA) and twin-identical",
          i1 and i2 and abs(float(i1.group(1)) + 1.0/6e3) < 1e-12
          and i1.group(1) == i2.group(1))

print("[2] Enhancement-67 feature set (exact conductances)")
out, ok = compile_va("gen2_features.va")
if not ok:
    check("gen2 compiles", False, out.splitlines()[0] if out else "")
else:
    for mod, want, what in [
        ("gnest", -6.0, "nested loops (2x3 parallel)"),
        ("gpexpr", -(1 + 0.5 + 1.0/3), "genvar in param-override expr (was \\\\0 defect)"),
        ("gtri", -6.0, "generate if on genvars (triangle j<=i)"),
        ("gelse", -1.5, "generate if/else"),
        ("gcase", -2.75, "generate case (multi-value arm + default)"),
        ("ganon", -1.0, "anonymous block + per-iteration net"),
        ("gbounds", -3.0, "start!=0, step 2, <= bound"),
    ]:
        got = op_ma("gen2_features.osdi", mod)
        check(what, abs(got - want) < 1e-9, f"({got:.9g} mA)")

print("[3] honest error for parameter-shaped generate structure")
out, made = compile_va("_gen_param_if.va")
check("generate if on a parameter names the OSDI reason",
      not made and "simulation time" in out and "generate if" in out)

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
