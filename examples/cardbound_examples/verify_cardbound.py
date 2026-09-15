#!/usr/bin/env python3
"""Enhancement-643: a netlist number is the double its text names, and a
paramset is selected by its own parameters (IHP hunt B1/B2).

B2. ngspice's number parsers computed mantissa * 10^exponent and rounded
    twice: INPevaluate("1.2") was 1.2000000000000002, "0.96u"
    9.600000000000001e-07, "10e-6" 9.999999999999999e-06. The compiler parses
    the same spelling correctly (and, since this enhancement, its scaled
    literals too: `1.1u` was 1.1 * 1e-6, an ulp off for a third of them), so
    a card value AT a declared bound was refused by the model's own range
    check -- `vmax=1.2` outside `from [0:1.2]` -- and the paramset selection,
    which re-reads a bound's text through the same parser, judged a member's
    own default outside its own range. Every parser now hands the digits and
    the whole power of ten to strtod as one number: INPevaluate (and its four
    copies), the frontend's ft_numparse (`alter`, `let`, `print`) and
    numparam's suffixed literals (`.param w=1.1u`).
B1. The selection read `exclude {0}` -- the compiler's spelling of every
    single-value constraint -- as one unparseable bound, i.e. as satisfied, so
    every exclude excluded everything; and it range-checked and counted the
    target module's pass-through parameters as if they were the paramset's
    own, where LRM 6.4.2 says only the paramset's own count. The compiler now
    exports which parameters are the paramset's own (OSDI_PARAMSET_OWN); the
    selection judges and counts only those; a tie names the ranges that would
    break it.
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
WORK = tempfile.mkdtemp(prefix="cardbound_")
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
    pre = f"pre_osdi {osdi}.osdi\n" if osdi else ""
    with open(path, "w") as f:
        f.write(f"* cardbound {tag}\n{deck}\n.control\nset noinit\nset numdgt=17\n{pre}{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def value(out, name):
    m = re.search(rf"^{re.escape(name)} = (\S+)", out, re.M)
    return float(m.group(1)) if m else None


print("Enhancement-643: a netlist number is the double its text names; a paramset is selected by its own parameters\n")

# ---------------------------------------------------------------- 1 ---
# card values AT the declared bounds, every spelling the model uses
src = ("module m(p,n); inout p,n; electrical p,n;\n"
       "parameter real vmax = 1.0 from [0:1.2];\n"
       "(* type=\"instance\" *) parameter real w = 1.0 from (0:3.3];\n"
       "parameter real l = 1e-6 from [0.96u:10e-6];\n"
       "parameter real t = 1e-6 from [1.1u:inf);\n"
       "parameter real r = 1k from (0:inf);\n"
       "analog I(p,n) <+ V(p,n)/r * vmax * w * (l / 0.96e-6) * (t / 1.1e-6);\nendmodule\n")
ok, msg = compile_src(src, "bounds")
check("[1] the model compiles (bounds 1.2, 3.3, 0.96u, 10e-6, 1.1u)", ok, msg.strip().splitlines()[-1][:80] if msg.strip() else "")
out = run(".model mm m vmax=1.2 l=0.96u t=1.1u\nv1 1 0 1\nn1 1 0 mm w=3.3",
          f"op\nprint i(v1) {A}mm[vmax] {A}n1[w]", "atbound", "bounds")
i1 = value(out, "i(v1)")
check("...[1] `vmax=1.2`, `w=3.3`, `l=0.96u`, `t=1.1u` on the cards are accepted at their bounds and read back exactly",
      "out of bounds" not in out and i1 is not None and abs(-i1 - 1e-3 * 1.2 * 3.3) < 1e-12
      and value(out, f"{A}mm[vmax]") == 1.2 and value(out, f"{A}n1[w]") == 3.3,
      (re.search(r"out of bounds.*", out) or [f"i(v1)={i1}"])[0] if "out of bounds" in out else f"i(v1)={i1}")
out = run(".model mm m l=10e-6\nv1 1 0 1\nn1 1 0 mm", f"op\nprint {A}mm[l]", "hibound", "bounds")
check("...[1] `l=10e-6` at the inclusive upper bound is accepted; the parsed value is exactly 1e-5",
      "out of bounds" not in out and value(out, f"{A}mm[l]") == 1e-5, f"l={value(out, A + 'mm[l]')}")

# ---------------------------------------------------------------- 2 ---
# the same numbers through the other parsers: alter (ft_numparse), .param (numparam)
out = run(".model mm m\nv1 1 0 1\nn1 1 0 mm", f"alter {A}n1[w] = 3.3\naltermod mm vmax = 1.2\nop\nprint {A}n1[w] {A}mm[vmax]", "alter", "bounds")
check("[2] `alter` / `altermod` to the bound (3.3, 1.2) is accepted and exact",
      "out of bounds" not in out and value(out, f"{A}n1[w]") == 3.3 and value(out, f"{A}mm[vmax]") == 1.2,
      f"w={value(out, A + 'n1[w]')} vmax={value(out, A + 'mm[vmax]')}")
out = run(".param wv=3.3 tv=1.1u\n.model mm m t={tv}\nv1 1 0 1\nn1 1 0 mm w={wv}", f"op\nprint {A}n1[w] {A}mm[t]", "param", "bounds")
check("...[2] `.param wv=3.3 tv=1.1u` substituted into the cards is accepted at the bounds",
      "out of bounds" not in out and value(out, f"{A}n1[w]") == 3.3 and value(out, f"{A}mm[t]") == 1.1e-6,
      f"w={value(out, A + 'n1[w]')} t={value(out, A + 'mm[t]')}")
out = run("v1 1 0 1.2\nr1 1 0 1k", "op\nprint v(1) - 12/10\nprint 0.96e-6 - 96/1e8", "plain", None)
check("...[2] a source value `1.2` and a control-language `0.96e-6` are the correctly rounded doubles (differences to the divisions are 0)",
      value(out, "v(1) - 12/10") == 0.0 and value(out, "0.96e-6 - 96/1e8") == 0.0, out.strip().splitlines()[-3:-1])

# ---------------------------------------------------------------- 3 ---
# selection: an exclude on a pass-through parameter, a discrete set on an own
# one, a default spelled 0.96e-6, a pass-through default outside its range
src = ("module res_va(p, n); inout p, n; electrical p, n;\n"
       "parameter integer type = -1 from [-1:1] exclude 0;\n"
       "parameter real q = 5 from [0:1];\n"
       "parameter real w = 1e-6 from [0.96e-6:10e-6);\n"
       "parameter real r = 1k from (0:inf);\n"
       "analog I(p,n) <+ V(p,n) / r * type * type * (q > 0 ? 1 : 1);\nendmodule\n"
       "paramset rs res_va;\n"
       "    parameter integer mm_ok = 0 from [0:0];\n"
       "    parameter integer bins = 1 from {1, 2, 4};\n"
       "    parameter real l = 0.96e-6 from [0.96e-6:10e-6);\n"
       "    .r = 1k * l / 0.96e-6; .w = l;\nendparamset\n"
       "paramset rs res_va;\n"
       "    parameter integer mm_ok = 1 from [1:1];\n"
       "    parameter integer bins = 1 from {1, 2, 4};\n"
       "    parameter real l = 0.96e-6 from [0.96e-6:10e-6);\n"
       "    .r = 2k * l / 0.96e-6; .w = l; .type = 1;\nendparamset\n")
ok, msg = compile_src(src, "sel")
check("[3] two `rs` members over a module with `type from [-1:1] exclude 0` and `q = 5 from [0:1]` compile", ok,
      msg.strip().splitlines()[-1][:80] if msg.strip() else "")
out = run(".model rs0 rs mm_ok=0\n.model rs1 rs mm_ok=1\nv1 1 0 1\nn1 1 0 rs0\nn2 1 0 rs1", "op\nprint i(v1)", "select", "sel")
check("...[3] `mm_ok=0` selects rs, `mm_ok=1` rs__2: neither the pass-through `type` (exclude {0}) nor `q` (default outside its range) nor the 0.96e-6 default disqualifies",
      "no paramset" not in out and "resolved to its member 'rs__2'" in out and value(out, "i(v1)")
      is not None and abs(-value(out, "i(v1)") - 1.5e-3) < 1e-9,
      (re.search(r"no paramset.*", out) or [f"i(v1)={value(out, 'i(v1)')}"])[0][:120] if "no paramset" in out else f"i(v1)={value(out, 'i(v1)')}")
out = run(".model rs2 rs mm_ok=0 bins=2\n.model rs3 rs mm_ok=0 bins=3\nv1 1 0 1\nn1 1 0 rs2\nn2 1 0 rs3", "op\nprint i(v1)", "set", "sel")
check("...[3] the discrete set `from {1, 2, 4}` on an own parameter is read: `bins=2` applies, `bins=3` is outside it",
      "rs3" in out and "bins = 3 is outside from {1, 2, 4}" in out and "rs2" not in (re.search(r"no paramset 'rs' applies to \.model rs2.*", out) or [""])[0],
      (re.search(r"no paramset.*", out) or ["no refusal"])[0][:110])

# ---------------------------------------------------------------- 4 ---
# nothing on the card: the tie is an error naming what selects
out = run(".model r0 rs\nv1 1 0 1\nn1 1 0 r0", "op", "tie", "sel")
check("[4] `.model r0 rs` with nothing given is the LRM's tie error, naming `mm_ok from [0:0]` / `[1:1]` -- rs__2's extra binding (`.type = 1`) no longer makes it win",
      "ambiguous" in out and "rs takes mm_ok from [0:0]" in out and "rs__2 takes mm_ok from [1:1]" in out
      and "bins" not in (re.search(r"ambiguous.*", out) or [""])[0],
      (re.search(r"ambiguous.*", out) or ["not ambiguous"])[0][-90:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
