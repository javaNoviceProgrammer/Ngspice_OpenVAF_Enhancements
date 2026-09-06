#!/usr/bin/env python3
"""Enhancement-546: a parameter that reads an instance parameter is one.

Compiler hunt F2 (2026-09-04). The model/instance split -- `(* type="instance" *)`
-- is an OpenVAF convention, not a language one: in Verilog-A every parameter
belongs to the instance, and a "model" parameter is one the compiler may resolve
ONCE per model card because nothing in it varies between that card's instances.

    (* type="instance" *) parameter real w = 1e-6 from (0:inf);
    parameter real l = 1e-6 from (0:w];

broke that premise and nobody noticed. `l` was resolved in the MODEL setup with
the card-level `w` -- the declared default, unless the card gave one -- stored in
the model, and every instance read that value:

    .model mm m(l=1e-6)   n2 ... w=0.5e-6   ->  RAN, l/w = 2.0 (the range says l <= w)
    .model mm m(l=3e-6)   n1 ... w=5e-6     ->  REFUSED, against the DEFAULT w = 1e-6
    parameter real l = 2*w;   n1 ... w=3e-6 ->  l = 2e-6

Since E-546 the two dependences get the two treatments they mean
(`sim_back::module_info::promote_instance_dependent`):

  * a DEFAULT that reads an instance parameter gives the parameter a value per
    instance, so it is PROMOTED to instance level: the instance setup resolves
    it with that instance's values. The dependency is transitive and
    `$param_given(p)` counts as reading `p`. The `instance_dependent_parameter`
    lint (L028, warn) names every promotion except that of an untyped
    `localparam`. A promoted parameter stays settable on the `.model` card, like
    any instance parameter, as the default for the card's instances.
  * a RANGE that reads an instance parameter does not change what the parameter
    is (the stock CMC models are full of this shape -- BSIM6's `XGL from
    (-inf:L*LMLT+XL)`, HiSIM2's `LP from [0:L]`). The parameter keeps its level;
    the model setup skips its given-value check and the instance setup judges it
    with the instance's values. Nothing is said.

Checks (both solvers):
  [1]-[5]   the hunt's range shape: judged per instance, in both directions,
            the parameter staying on the model
  [6]-[7]   the default shape, parameter and localparam: promoted
  [8]-[10]  the lint: wording, explicit `type="model"`, the allow attribute
  [11]-[12] transitivity and $param_given: two instances of one card differ
  [13]-[14] settable where an instance parameter is; no over-promotion
  [15]-[16] a DECLARED instance parameter with instance-dependent bounds
  [17]-[18] a model parameter whose range reads a PROMOTED parameter
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.gettempdir()
H = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(text, tag):
    src = os.path.join(WORK, f"_id_{tag}.va")
    osdi = os.path.join(WORK, f"_id_{tag}.osdi")
    with open(src, "w") as f:
        f.write(text)
    r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr), (osdi if r.returncode == 0 else None)


def sim(osdi, deck, ctl, tag, timeout=300):
    path = os.path.join(WORK, f"_id_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* instdep {tag}\n{deck}\n.control\npre_osdi {osdi}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=timeout, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr)


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


def refused(out):
    return "out of bounds" in out.lower()


LINT = "instance_dependent_parameter"

print("Enhancement-546: a parameter that reads an instance parameter is one\n")

# --------------------------------------------- [1]-[5] the hunt's range shape ---
print("the range shape: judged per instance, in both directions")
RANGE = H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6 from (0:inf);
parameter real l = 1e-6 from (0:w];
(* desc="l over w" *) real r;
analog begin r = l/w; I(p,n) <+ (w/l)*1e-3*V(p,n); end
endmodule
"""
rc, out, osdi = compile_va(RANGE, "range")
check("[1] compiles, and nothing is said: a range alone does not move the parameter",
      rc == 0 and "L028" not in out, f"rc={rc}")
if osdi:
    # the hunt's deck: l on the card, one instance above the range, one below
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=2e-6\nn2 1 0 mm w=0.5e-6\n.model mm m(l=1e-6)",
                 "op\nprint @n1[r]", "hunt")
    check("[2] the instance whose w is below the card's l is refused (was: ran with l/w = 2.0)",
          refused(o) and re.search(r"n2", o) is not None, f"rc={rc2}")
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=2e-6\n.model mm m(l=1e-6)",
                 "op\nprint @n1[r]", "ok")
    check("[3] the instance whose w admits the card's l runs, l/w = 0.5",
          rc2 == 0 and not refused(o) and close(val(o, "@n1[r]"), 0.5), f"r={val(o, '@n1[r]')}")
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=5e-6\n.model mm m(l=3e-6)",
                 "op\nprint @n1[r]", "cardabove")
    check("[4] a card l above the DEFAULT w runs for an instance whose w admits it (was: refused at the card)",
          rc2 == 0 and not refused(o) and close(val(o, "@n1[r]"), 0.6), f"r={val(o, '@n1[r]')}")
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm\n.model mm m(l=3e-6)",
                 "op\nprint @n1[r]", "carddefault")
    check("[5] ...and is refused for an instance that inherits the default w",
          refused(o), f"rc={rc2}")
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm l=1e-6\n.model mm m", "op\nprint @n1[r]", "stillmodel")
    check("...[5] 'l' is still a model parameter: refused on the instance line",
          rc2 != 0, f"rc={rc2}")
else:
    for i in range(2, 6):
        check(f"[{i}] (skipped: the model did not compile)", False)

# ------------------------------------------------------ [6]-[7] the default shape ---
print("\nthe default shape: resolved with the instance's value")
DEFAULT = H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
parameter real l = 2*w;
localparam real l2 = 2*w;
(* desc="l over w" *) real r; (* desc="l2 over w" *) real r2;
analog begin r = l/w; r2 = l2/w; I(p,n) <+ V(p,n); end
endmodule
"""
rc, out, osdi = compile_va(DEFAULT, "default")
check("[6] the parameter's promotion is named; the untyped localparam's is not",
      rc == 0 and "'l' depends on instance parameter 'w'" in out
      and "'l2'" not in out and out.count("L028") == 1, f"rc={rc}, L028 x{out.count('L028')}")
if osdi:
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=3e-6\n.model mm m",
                 "op\nprint @n1[l] @n1[r] @n1[r2]", "default")
    check("[7] l = 2*w reads the instance's w: l = 6e-6, l/w = 2 for both (was: l = 2e-6)",
          rc2 == 0 and close(val(o, "@n1[l]"), 6e-6) and close(val(o, "@n1[r]"), 2.0)
          and close(val(o, "@n1[r2]"), 2.0),
          f"l={val(o, '@n1[l]')} r={val(o, '@n1[r]')} r2={val(o, '@n1[r2]')}")
else:
    check("[7] (skipped: the model did not compile)", False)

# ------------------------------------------------------------ [8]-[10] the lint ---
print("\nthe lint")
rc, out, _ = compile_va(H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
(* type="model" *) parameter real l = w + 1e-6;
analog I(p,n) <+ V(p,n)*l/w;
endmodule
""", "explicit")
check("[8] an explicit (* type=\"model\" *) that reads an instance parameter is named as such",
      rc == 0 and 'declared (* type="model" *) but depends on instance parameter' in out, f"rc={rc}")
rc, out, _ = compile_va(H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
(* openvaf_allow="instance_dependent_parameter" *) parameter real l = 2*w;
analog I(p,n) <+ V(p,n)*l/w;
endmodule
""", "allow")
check("[9] (* openvaf_allow=\"instance_dependent_parameter\" *) on the declaration silences it",
      rc == 0 and "L028" not in out and LINT not in out, f"rc={rc}")
rc, out, _ = compile_va(H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
(* type="model" *) localparam real l = 2*w;
analog I(p,n) <+ V(p,n)*l/w;
endmodule
""", "explicitlocal")
check("[10] a localparam the author typed \"model\" is named too (it was a choice); the help fits a localparam",
      rc == 0 and "localparam 'l' is declared" in out and "nothing settable changes for a localparam" in out,
      f"rc={rc}")

# ----------------------------------------- [11]-[12] transitivity and $param_given ---
print("\ntransitivity and $param_given: two instances of one card differ")
TRANS = H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
parameter real l = 2*w;
parameter real a = l + 1e-6;
parameter integer g = $param_given(w) ? 1 : 0;
(* desc="a" *) real ra; (* desc="g" *) integer rg;
analog begin ra = a; rg = g; I(p,n) <+ V(p,n); end
endmodule
"""
rc, out, osdi = compile_va(TRANS, "trans")
check("[11] 'a' is promoted through 'l' (named via 'l'), 'g' through $param_given(w)",
      rc == 0 and "'a' depends on instance parameter 'l'" in out
      and "'g' depends on instance parameter 'w'" in out, f"rc={rc}")
if osdi:
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=3e-6\nn2 1 0 mm\n.model mm m",
                 "op\nprint @n1[ra] @n2[ra] @n1[rg] @n2[rg]", "trans")
    check("[12] one card, two instances: a = 7e-6 / 3e-6 and $param_given(w) = 1 / 0",
          rc2 == 0 and close(val(o, "@n1[ra]"), 7e-6) and close(val(o, "@n2[ra]"), 3e-6)
          and val(o, "@n1[rg]") == 1 and val(o, "@n2[rg]") == 0,
          f"a={val(o, '@n1[ra]')}/{val(o, '@n2[ra]')} g={val(o, '@n1[rg]')}/{val(o, '@n2[rg]')}")
else:
    check("[12] (skipped: the model did not compile)", False)

# ------------------------------------------------- [13]-[14] settable, not over-promoted ---
print("\nsettable where an instance parameter is; nothing else moves")
SET = H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
parameter real l = 2*w;
parameter real k = 2.0;
parameter real q = k*2;
(* desc="l" *) real rl; (* desc="q" *) real rq;
analog begin rl = l; rq = q; I(p,n) <+ V(p,n); end
endmodule
"""
rc, out, osdi = compile_va(SET, "set")
if osdi:
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=8e-6\nn2 1 0 mm w=8e-6 l=2e-6\n.model mm m(l=4e-6 q=5)",
                 "op\nprint @n1[rl] @n2[rl] @n1[rq]", "set")
    check("[13] a promoted parameter is given on the card as the instances' default, and per instance",
          rc2 == 0 and close(val(o, "@n1[rl]"), 4e-6) and close(val(o, "@n2[rl]"), 2e-6)
          and close(val(o, "@n1[rq]"), 5.0),
          f"l={val(o, '@n1[rl]')}/{val(o, '@n2[rl]')} q={val(o, '@n1[rq]')}")
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm q=3\n.model mm m", "op\nprint @n1[rq]", "overpromote")
    check("[14] a parameter that reads only model parameters stays a model parameter (refused on the instance line)",
          rc2 != 0 or "unknown" in o.lower() or "not" in o.lower(), f"rc={rc2}")
    check("...[14] and no L028 was raised for it",
          "'q'" not in out and "'k'" not in out, "")
else:
    for i in (13, 14):
        check(f"[{i}] (skipped: the model did not compile)", False)

# ------------------------------ [15]-[16] a declared instance parameter, dependent bounds ---
print("\na declared instance parameter whose bounds read another instance parameter")
DECL = H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6 from (0:inf);
(* type="instance" *) parameter real w2 = 1e-6 from (0:w];
(* desc="w2 over w" *) real r;
analog begin r = w2/w; I(p,n) <+ V(p,n); end
endmodule
"""
rc, out, osdi = compile_va(DECL, "decl")
check("[15] nothing to promote, nothing said", rc == 0 and "L028" not in out, f"rc={rc}")
if osdi:
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=5e-6\n.model mm m(w2=3e-6)",
                 "op\nprint @n1[r]", "declok")
    ok_a = rc2 == 0 and not refused(o) and close(val(o, "@n1[r]"), 0.6)
    rc3, o3 = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm\n.model mm m(w2=3e-6)",
                  "op\nprint @n1[r]", "declbad")
    check("[16] a card w2 above the default w runs where the instance's w admits it, and is refused where it does not",
          ok_a and refused(o3), f"r={val(o, '@n1[r]')}, second rc={rc3}")
else:
    check("[16] (skipped: the model did not compile)", False)

# ------------------------------ [17]-[18] a range that reads a PROMOTED parameter ---
print("\na model parameter whose range reads a promoted parameter")
PROM = H + """
module m(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter real w = 1e-6;
parameter real l = 2*w;
parameter real k = 1e-6 from (0:l];
(* desc="k over l" *) real r;
analog begin r = k/l; I(p,n) <+ V(p,n); end
endmodule
"""
rc, out, osdi = compile_va(PROM, "prom")
check("[17] only the promotion of 'l' is named; 'k' keeps its level",
      rc == 0 and out.count("L028") == 1 and "'l' depends" in out and "'k'" not in out,
      f"rc={rc}, L028 x{out.count('L028')}")
if osdi:
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=2e-6\n.model mm m(k=3e-6)",
                 "op\nprint @n1[r]", "promok")
    ok_a = rc2 == 0 and not refused(o) and close(val(o, "@n1[r]"), 0.75)
    rc3, o3 = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=1e-6\n.model mm m(k=3e-6)",
                  "op\nprint @n1[r]", "prombad")
    check("[18] a card k = 3e-6 runs where the instance's l = 2w admits it and is refused where it does not",
          ok_a and refused(o3) and "n1" in o3, f"r={val(o, '@n1[r]')}, second rc={rc3}")
else:
    check("[18] (skipped: the model did not compile)", False)

# ------------------------------------------ [19]-[21] hunt F15: the runtime forms through the model name ---
# `altermod mm l=10` was refused as "model 'mm' has no parameter l" (and, because
# the model's name starts with `m`, the MOS bin probe first complained about a
# width) while `.model mm m(l=...)` set every instance and `alter n1 l=...`
# worked: a promoted parameter is instance-level, and the message says so now.
print("\nhunt F15: altermod / print / dc of a promoted parameter through the model name")
rc, out, osdi = compile_va(SET, "set")
if osdi:
    rc2, o = sim(osdi, "v1 1 0 dc 1\nn1 1 0 mm w=8e-6\nn2 1 0 mm w=8e-6 l=2e-6\n.model mm m",
                 "op\naltermod mm l=4e-6\nprint @mm[l]\ndc @mm[l] 4e-6 8e-6 2e-6\n"
                 "alter @n1[l]=4e-6\nop\nprint @n1[rl] @n2[rl]", "f15")
    check("[19] altermod of a promoted parameter says it is INSTANCE-level and points at alter and the card (was: 'has no parameter l' after a MOS width probe)",
          "'l' is an INSTANCE parameter of model 'mm'" in o and "`altermod` sets model parameters" in o
          and "alter @<instance>[l]=" in o and "has no parameter l" not in o
          and "no such parameter w" not in o and "width instance parameter" not in o, o.strip()[-300:])
    check("[20] print @mm[l] and dc @mm[l] say the same and point at the instance",
          "a model has no value of its own to read" in o and "sweep @<instance>[l] instead" in o, o.strip()[-300:])
    check("[21] the instance route works: alter @n1[l] moves n1 only",
          close(val(o, "@n1[rl]"), 4e-6) and close(val(o, "@n2[rl]"), 2e-6),
          f"rl={val(o, '@n1[rl]')}/{val(o, '@n2[rl]')}")
else:
    for i in (19, 20, 21):
        check(f"[{i}] (skipped: the model did not compile)", False)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
