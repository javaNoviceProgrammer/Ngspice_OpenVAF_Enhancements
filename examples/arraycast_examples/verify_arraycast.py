#!/usr/bin/env python3
"""
verify_arraycast.py -- Enhancement-214: whole-array type coercion.

A defect class that kept coming back: an integer Value reaches a float MIR op
(feq/fmul/fsub/fdiv), which mir_opt::const_eval::eval_binary has no (Int, Float)
case for, so the compiler PANICS -- "invalid operation fdiv Int(1) Float(..)",
exit 101, "please open an issue". (When const-prop does not fold it, the same
defect instead reaches LLVM as `i32 = fadd .., ConstantFP:f64` and aborts with
"LLVM ERROR: Cannot select" -- one bug, two faces.)

Four instances, each patched at its own call site as it was found:

  [case-discr]  E-33      `case` over an integer array (element type hardcoded
                          real -> feq on i32).
  [coeff-lit]   b77266ec  laplace_*/zi_* integer-LITERAL coefficients: `{1}`.
  [coeff-var]   c55812d6  laplace_*/zi_* integer ARRAY-VARIABLE coefficients.
                          The fix before it had reasoned that "a whole-array
                          variable reference is already real by its declaration",
                          which is false for an `integer` array.
  [case-item]   8d0ab057  an integer `case` item vs a REAL array discriminant:
                          the opcode is chosen from the discriminant (Feq) but
                          the item's elements lower to i32.

E-214 fixed the last two, then removed the trap itself: inference DOES record the
coercion, but it records it on the array EXPRESSION, and hir_lower's
lower_array_elems_impl decomposes the array and lowers each element on its own --
so lower_expr's needs_cast() never saw it and the cast was silently DEAD. Every
new array-consuming context therefore re-inherited the bug. It is now honoured at
that one chokepoint. See Enhancement-214.md.

Checks:
  [1] all four historical spellings compile instead of panicking (the class);
  [2] no miscompile -- the integer spelling of a laplace filter is bit-identical
      to the '{1.0} spelling AND matches the analytic response. Coercion that
      silently changed a coefficient would pass a compiles-only test;
  [3] an integer case item still MATCHES semantically (the arm is taken);
  [4] valid code is unchanged (real coeffs, real items, scalar/string cases);
  [5] arraycast_demo.va: mode-selected gain + unity integer numerator.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

HDR = '`include "disciplines.vams"\n'

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def compile_va(name, src):
    """(ok, verdict, first-line-of-diagnostic).

    openvaf-r installs its own panic hook: it prints "OpenVAF encountered a
    problem and has crashed!" and exits 101 rather than dying on a signal or
    printing the usual "panicked at" (the lesson of Enhancement-213). A crash
    check that looks only for a signal would score these panics as clean errors.
    """
    with open(os.path.join(HERE, name), "w") as f:
        f.write(src)
    r = subprocess.run([OPENVAF, name, "-o", name.replace(".va", ".osdi")],
                       cwd=HERE, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    if r.returncode == 101 or r.returncode < 0 or "has crashed" in out:
        return False, "CRASH", out.strip().splitlines()[0] if out.strip() else ""
    if r.returncode != 0:
        return False, "ERROR", out.strip().splitlines()[0] if out.strip() else ""
    return True, "OK", ""


def ac_sweep(osdi, model, card="ac dec 3 1e3 1e7", params="", node="out"):
    """[(f, dB, phase)] for a 1 V AC drive through `model`."""
    deck = (f"* arraycast {model}\n"
            "vin in 0 dc 0 ac 1\n"
            f"n1 in {node} dm\n"
            f".model dm {model}({params})\n"
            f"rl {node} 0 1e9\n"
            ".control\n"
            f"pre_osdi {osdi}\n"
            f"{card}\n"
            f"wrdata _ac.txt vdb({node}) vp({node})\n"
            ".endc\n.end\n")
    with open(os.path.join(HERE, "_ac.cir"), "w") as f:
        f.write(deck)
    p = os.path.join(HERE, "_ac.txt")
    if os.path.exists(p):
        os.remove(p)
    subprocess.run([NGSPICE, "-b", "_ac.cir"], cwd=HERE,
                   capture_output=True, text=True, timeout=120)
    if not os.path.exists(p):
        return []
    return [[float(x) for x in l.split()] for l in open(p) if l.strip()]


def dc_current(osdi, model, v=1.0):
    """I through a 1 V-biased two-terminal `model`, or None."""
    deck = (f"* arraycast {model} dc\n"
            f"vb a 0 dc {v!r}\n"
            f"n1 a 0 dm\n.model dm {model}\n"
            ".control\n"
            f"pre_osdi {osdi}\n"
            f"dc vb {v!r} {v!r} 1\nwrdata _dc.txt i(vb)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_dc.cir"), "w") as f:
        f.write(deck)
    p = os.path.join(HERE, "_dc.txt")
    if os.path.exists(p):
        os.remove(p)
    subprocess.run([NGSPICE, "-b", "_dc.cir"], cwd=HERE,
                   capture_output=True, text=True, timeout=120)
    if not os.path.exists(p):
        return None
    row = open(p).read().split("\n")[0].split()
    return -float(row[1]) if len(row) >= 2 else None      # i(vb) = -I(a,0)


# --- the four historical spellings of the class ----------------------------
FILT = "module {n}(in,out); input in; output out; electrical in,out;\n{b}endmodule\n"


def case_mod(name, decl, init, item):
    return (HDR + f"module {name}(a,b); inout a,b; electrical a,b;\n"
            f" {decl} real g;\n analog begin\n  {init}\n"
            f"  case (arr) {item}: g = 7.0; default: g = 1.0; endcase\n"
            "  I(a,b) <+ g*V(a,b);\n end\nendmodule\n")


CLASS = [
    ("[coeff-lit]  laplace_nd(V(in), {1}, ...)          integer literal",
     "_lit.va", HDR + FILT.format(n="cast_lit",
                                  b=" analog V(out) <+ laplace_nd(V(in), {1}, '{1.0, 1e-6});\n")),
    ("[coeff-var]  integer c[0:0]; laplace_nd(.., c, ..) integer array variable",
     "_var.va", HDR + FILT.format(n="cast_var",
                                  b=" integer c[0:0];\n analog begin c[0] = 1;\n"
                                    "  V(out) <+ laplace_nd(V(in), c, '{1.0, 1e-6}); end\n")),
    ("[coeff-zi]   zi_nd(.., {1}, ..)                   integer literal, zi",
     "_zi.va", HDR + FILT.format(n="cast_zi",
                                 b=" analog V(out) <+ zi_nd(V(in), {1}, '{1.0, 0.5}, 1e-6, 0.0);\n")),
    ("[case-item]  real arr[0:0]; case (arr) {1}:       integer item, real discriminant",
     "_item.va", case_mod("cast_item", "real arr[0:0];", "arr[0] = 1.0;", "{1}")),
    ("[case-discr] integer arr[0:0]; case (arr) '{1}:   integer discriminant (E-33)",
     "_discr.va", case_mod("cast_discr", "integer arr[0:0];", "arr[0] = 1;", "'{1}")),
]

print("[1] every spelling of the class compiles instead of panicking")
for label, fname, src in CLASS:
    ok, verdict, detail = compile_va(fname, src)
    check(label, ok, "" if ok else f"{verdict}: {detail}")

print("[2] no miscompile: the integer spelling is identical to '{1.0}, and analytic")
real_src = HDR + FILT.format(n="cast_real",
                             b=" analog V(out) <+ laplace_nd(V(in), '{1.0}, '{1.0, 1e-6});\n")
ok, _, detail = compile_va("_real.va", real_src)
check("reference filter with real coefficients compiles", ok, detail)
a_int = ac_sweep("_lit.osdi", "cast_lit")
a_var = ac_sweep("_var.osdi", "cast_var")
a_real = ac_sweep("_real.osdi", "cast_real")
check("all three filters produce an AC sweep", bool(a_int and a_var and a_real),
      f"{len(a_int)}/{len(a_var)}/{len(a_real)} points")
if a_int and a_var and a_real:
    w_lit = max(abs(x[1] - y[1]) for x, y in zip(a_int, a_real))
    w_var = max(abs(x[1] - y[1]) for x, y in zip(a_var, a_real))
    # Coercion must be exact: these are the SAME coefficients, so the compiled
    # response must agree to the last bit, not merely to a tolerance.
    check("integer LITERAL {1} == real '{1.0}, bit for bit", w_lit == 0.0,
          f"worst dB diff {w_lit:g}")
    check("integer array VARIABLE == real '{1.0}, bit for bit", w_var == 0.0,
          f"worst dB diff {w_var:g}")
    worst = max(abs(f[1] - (-20 * math.log10(math.hypot(1, 2 * math.pi * f[0] * 1e-6))))
                for f in a_int)
    check("integer-coefficient filter matches analytic 1/(1+j.w.tau)", worst < 1e-6,
          f"worst dB err {worst:.2e}")

print("[3] the coerced integer case item still MATCHES (the arm is taken)")
i_item = dc_current("_item.osdi", "cast_item")
ok, _, detail = compile_va("_itemr.va",
                           case_mod("cast_itemr", "real arr[0:0];", "arr[0] = 1.0;", "'{1.0}"))
check("real-item reference compiles", ok, detail)
i_ref = dc_current("_itemr.osdi", "cast_itemr")
check("integer item {1} selects the matching arm (g = 7, not the default 1)",
      i_item is not None and abs(i_item - 7.0) < 1e-9, f"I = {i_item}")
check("integer item == real item '{1.0}, exactly",
      i_item is not None and i_ref is not None and i_item == i_ref,
      f"{i_item} vs {i_ref}")

print("[4] valid code is unchanged")
VALID = [
    ("real scalar case",
     HDR + "module v1(a,b); inout a,b; electrical a,b; real g;\n analog begin\n"
           "  case (1.0) 1.0: g = 7.0; default: g = 1.0; endcase\n"
           "  I(a,b) <+ g*V(a,b);\n end\nendmodule\n"),
    ("integer scalar case",
     HDR + "module v2(a,b); inout a,b; electrical a,b; real g;\n analog begin\n"
           "  case (1) 1: g = 7.0; default: g = 1.0; endcase\n"
           "  I(a,b) <+ g*V(a,b);\n end\nendmodule\n"),
    ("string case",
     HDR + 'module v3(a,b); inout a,b; electrical a,b; real g; string s;\n analog begin\n'
           '  s = "hi";\n  case (s) "hi": g = 7.0; default: g = 1.0; endcase\n'
           "  I(a,b) <+ g*V(a,b);\n end\nendmodule\n"),
    ("real array variable as a coefficient vector",
     HDR + FILT.format(n="v4", b=" real c[0:0];\n analog begin c[0] = 1.0;\n"
                                 "  V(out) <+ laplace_nd(V(in), c, '{1.0, 1e-6}); end\n")),
    ("real array case, element-wise (E-33)",
     HDR + "module v5(a,b); inout a,b; electrical a,b; real g; real arr[0:1];\n analog begin\n"
           "  arr[0] = 1.0; arr[1] = 2.0;\n"
           "  case (arr) '{1.0, 2.0}: g = 7.0; default: g = 1.0; endcase\n"
           "  I(a,b) <+ g*V(a,b);\n end\nendmodule\n"),
]
for i, (label, src) in enumerate(VALID):
    ok, verdict, detail = compile_va(f"_v{i}.va", src)
    check(label, ok, "" if ok else f"{verdict}: {detail}")
i_v5 = dc_current("_v4.osdi", "v5")
check("real array case still selects its arm (E-33 stays correct)",
      i_v5 is not None and abs(i_v5 - 7.0) < 1e-9, f"I = {i_v5}")

print("[5] arraycast_demo.va -- integer numerator + integer case items")
ok, verdict, detail = compile_va("arraycast_demo.va", open(
    os.path.join(HERE, "arraycast_demo.va")).read())
check("arraycast_demo.va compiles", ok, "" if ok else f"{verdict}: {detail}")
for mode, want, arm in ((1, 1.0, "the {1} arm"), (2, 2.0, "the {2} arm"),
                        (3, 0.5, "no arm matches -> default")):
    rows = ac_sweep("arraycast_demo.osdi", "arraycast_demo", card="ac lin 1 1e3 1e3",
                    params=f"tau=1e-6 mode={mode}")
    got = 10 ** (rows[0][1] / 20.0) if rows else None
    # gain * 1/(1+j.w.tau) at 1 kHz -- the rolloff is 2e-5 dB, hence the tolerance
    check(f"mode {mode}: {arm} sets gain = {want}",
          got is not None and abs(got - want) < 1e-3 * want, f"gain = {got}")

for f in os.listdir(HERE):
    if f.startswith("_") and f.split(".")[-1] in ("va", "osdi", "cir", "txt"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "SOME FAILED")
sys.exit(0 if passed == checks else 1)
