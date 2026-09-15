#!/usr/bin/env python3
"""Enhancement-644: a paramset's own parameters are instance parameters, and
an instance selects its member (IHP hunt C1); a bound parameter's case-twin
and a model's own `i` no longer draw the collision warning (C2).

C1. A paramset's own parameters were model-card-only, so `n1 a b rsil l=0.5u
    w=0.5u mm_ok=0` -- what every SPICE device library writes -- was refused
    ("it is a model parameter of this device"). In the LRM's world they are
    what an INSTANCE of the paramset sets (`rsil #(.l(0.5u)) r1(...)`), so
    they are instance parameters now, the card giving the instances'
    defaults; `(* type="model" *)` keeps one on the card. And LRM 6.4.2
    selects the member PER INSTANCE: the first `n` line binds the card to its
    member, an instance that needs another member gets a clone of the card,
    `<card>.<member>`, made once.
C2. The E-335 case-collision warning fired for a parameter a paramset BOUND
    (PSP's `SWSOA` under the paramset's `swsoa`; `sp_resistor`'s `r` alias
    under the paramset's `R`), which cannot be set at all, and for the
    loader's own bare `i` alias against a model's `(* desc *) real i`.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="paramsetinst_")
A = "@"
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run(deck, ctl, tag, osdi):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* paramsetinst {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\npre_osdi {osdi}.osdi\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def value(out, name):
    m = re.search(rf"^{re.escape(name)} = (\S+)", out, re.M)
    return float(m.group(1)) if m else None


print("Enhancement-644: a paramset's own parameters are instance parameters, and an instance selects its member\n")

# a small r3_cmc-shaped resistor: sheet resistance, w and l, an alias `r`
# on a parameter every paramset binds, an operating-point variable `i`
MOD = ("module res_va(p, n); inout p, n; electrical p, n;\n"
       "(* type=\"instance\" *) parameter real resistance = 1k from (0:inf);\n"
       "aliasparam r = resistance;\n"
       "parameter real rsh = 7.0 from (0:inf);\n"
       "parameter real mm = 1.0 from (0:inf);\n"
       "(* desc=\"current\" *) real i;\n"
       "analog begin i = V(p,n) / resistance * mm; I(p,n) <+ i; end\nendmodule\n")
PS = (MOD +
      "paramset rs res_va;\n"
      "    parameter real w = 0.5e-6 from [0.5e-6:10e-6);\n"
      "    parameter real l = 0.5e-6 from [0.5e-6:10e-6);\n"
      "    parameter integer mm_ok = 0 from [0:0];\n"
      "    (* type=\"model\" *) parameter real tc = 0.0;\n"
      "    .resistance = 7.0 * l / w * (1 + tc);\n"
      "    .mm = 1.0;\n"
      "endparamset\n"
      "paramset rs res_va;\n"
      "    parameter real w = 0.5e-6 from [0.5e-6:10e-6);\n"
      "    parameter real l = 0.5e-6 from [0.5e-6:10e-6);\n"
      "    parameter integer mm_ok = 1 from [1:1];\n"
      "    (* type=\"model\" *) parameter real tc = 0.0;\n"
      "    .resistance = 7.0 * l / w * (1 + tc);\n"
      "    .mm = 2.0;\n"
      "endparamset\n")

# ---------------------------------------------------------------- 1 ---
ok, msg = compile_src(PS, "ps")
check("[1] two `rs` members over a module with a bound aliased parameter and an opvar `i` compile",
      ok, msg.strip().splitlines()[-1][:90] if msg.strip() else "")
out = run(".model r0 rs w=0.5u\nv1 1 0 1\nn1 1 0 r0 l=1u w=0.5u mm_ok=0",
          f"op\nprint i(v1) {A}n1[l] {A}n1[w] {A}n1[mm_ok]\nshowmod r0", "inst", "ps")
check("...[1] `n1 1 0 r0 l=1u w=0.5u mm_ok=0` -- the paramset's own parameters on the instance line -- is accepted and read back; I = 1 V / 14 ohm",
      "model parameter of this device" not in out and value(out, f"{A}n1[l]") == 1e-6
      and value(out, f"{A}n1[mm_ok]") == 0 and value(out, "i(v1)") is not None and abs(-value(out, "i(v1)") - 1 / 14) < 1e-9,
      f"i(v1)={value(out, 'i(v1)')} l={value(out, A + 'n1[l]')}")
check("...[1] `showmod r0` lists the card's `w` under its instance defaults, and the `(* type=\"model\" *)` one (tc) among the model parameters",
      "instance defaults on this card" in out and re.search(r"^\s+tc\s", out, re.M) is not None
      and re.search(r"^\s+w\s", out, re.M) is not None
      and out.index("\n         tc") < out.index("instance defaults on this card") < out.index("\n          w"), "")
out = run(".model r0 rs l=2u\nv1 1 0 1\nn1 1 0 r0 mm_ok=0 tc=0.1", "op\nprint i(v1)", "modelonly", "ps")
check("...[1] `tc` on the instance line is refused as the model parameter it was declared to be; the card's `l=2u` is the instances' default",
      "model parameter of this device" in out and "tc" in out, (re.search(r"unknown parameter.*", out) or ["no refusal"])[0][:80])
out = run(".model r0 rs l=2u\nv1 1 0 1\nn1 1 0 r0 mm_ok=0", f"op\nprint i(v1) {A}n1[l]", "carddefault", "ps")
check("...[1] the card's `l=2u` reaches an instance that does not set l: I = 1 V / 28 ohm",
      value(out, f"{A}n1[l]") == 2e-6 and abs(-value(out, "i(v1)") - 1 / 28) < 1e-9, f"i(v1)={value(out, 'i(v1)')}")

# ---------------------------------------------------------------- 2 ---
# per-instance selection: one card, two members
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0 l=0.5u w=0.5u mm_ok=0\nn2 2 0 r0 l=0.5u w=0.5u mm_ok=1\nv2 2 0 1",
          f"op\nprint i(v1) i(v2)\nshow n1 n2", "twomembers", "ps")
check("[2] `.model r0 rs` with `mm_ok=0` on n1 and `mm_ok=1` on n2: n1 is rs (7 ohm), n2 is rs__2 (mm = 2, 3.5 ohm)",
      "ambiguous" not in out and value(out, "i(v1)") is not None and abs(-value(out, "i(v1)") - 1 / 7) < 1e-9
      and abs(-value(out, "i(v2)") - 2 / 7) < 1e-9, f"i(v1)={value(out, 'i(v1)')} i(v2)={value(out, 'i(v2)')}")
check("...[2] n2 got a clone of the card, `r0.rs__2`, and the note says so",
      "a second card, r0.rs__2, is made for it" in out and re.search(r"model\s+r0\.rs__2", out) is not None,
      (re.search(r"Note: n2.*", out) or ["no note"])[0][:100])
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0 l=0.5u w=0.5u mm_ok=1\nn2 2 0 r0 l=0.5u w=0.5u mm_ok=0\nn3 3 0 r0 mm_ok=0\nv2 2 0 1\nv3 3 0 1",
          f"op\nprint i(v1) i(v2) i(v3)\nshow n2 n3", "firstbinds", "ps")
check("...[2] the first instance binds the card (n1 -> rs__2, noted); n2 and n3 (mm_ok=0) share the clone `r0.rs`",
      "by the parameters of its first instance, n1" in out and abs(-value(out, "i(v1)") - 2 / 7) < 1e-9
      and abs(-value(out, "i(v2)") - 1 / 7) < 1e-9 and abs(-value(out, "i(v3)") - 1 / 7) < 1e-9
      and re.search(r"model\s+r0\.rs\s+r0\.rs\s*$", out, re.M) is not None and out.count("a second card, r0.rs,") == 1,
      f"clones={out.count('a second card')}")

# ---------------------------------------------------------------- 3 ---
out = run(".model r0 rs mm_ok=0\nv1 1 0 1\nn1 1 0 r0 mm_ok=1", "op\nprint i(v1)\nshow n1", "instwins", "ps")
check("[3] the instance's `mm_ok=1` overrides the card's `mm_ok=0` for the selection: rs__2 (the first instance, so the card itself is bound to it)",
      abs(-value(out, "i(v1)") - 2 / 7) < 1e-9 and "by the parameters of its first instance, n1" in out
      and re.search(r"^ rs__2: A simulator", out, re.M) is not None, f"i(v1)={value(out, 'i(v1)')}")
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0 mm_ok=2", "op\nprint i(v1)", "noneapplies", "ps")
check("...[3] `mm_ok=2` on the instance is refused with each member's reason",
      "no paramset 'rs' applies" in out and "mm_ok = 2 is outside from [0:0]" in out and "mm_ok = 2 is outside from [1:1]" in out,
      (re.search(r"no paramset.*", out) or ["accepted"])[0][:110])
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0 mm_ok=1 m=2 temp=30", f"op\nprint i(v1) {A}n1[m]", "builtins", "ps")
check("...[3] the simulator's own `m=` and `temp=` on the instance line take no part in the selection",
      "not one of its parameters" not in out and abs(-value(out, "i(v1)") - 4 / 7) < 1e-9, f"i(v1)={value(out, 'i(v1)')}")
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0", "op", "tie", "ps")
check("...[3] an instance that gives nothing on a card that gives nothing is still the tie error",
      "ambiguous" in out and "rs takes mm_ok from [0:0]; rs__2 takes mm_ok from [1:1]" in out,
      (re.search(r"ambiguous.*", out) or ["no tie"])[0][-70:])

# ---------------------------------------------------------------- 4 ---
# C2: no collision warning for a bound case-twin or the model's own `i`;
# a genuine collision still warns
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0 mm_ok=0", f"op\nprint {A}n1[i] i(v1)", "case", "ps")
check("[4] the module's bound `resistance`/`r` under the paramset and its opvar `i` under the loader's alias draw no case-collision warning; `@n1[i]` is the model's own current",
      "differing only in case" not in out and value(out, f"{A}n1[i]") is not None
      and abs(value(out, f"{A}n1[i]") - 1 / 7) < 1e-9, (re.search(r"differing only in case.*", out) or ["clean"])[0][:80])
okg, msgg = compile_src("module g(p,n); inout p,n; electrical p,n;\n(* type=\"instance\" *) parameter real gain = 1.0;\n"
                        "(* type=\"instance\" *) parameter real GAIN = 2.0;\nanalog I(p,n) <+ V(p,n)/1k*gain*GAIN;\nendmodule\n", "gain")
out = run(".model gg g\nv1 1 0 1\nn1 1 0 gg", "op\nprint i(v1)", "gaincase", "gain") if okg else ""
check("...[4] two settable parameters `gain` and `GAIN` still draw the warning",
      okg and "instance parameter 'gain' is declared more than once differing only in case" in out,
      (re.search(r"differing only in case.*", out) or ["silent"])[0][:60])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
