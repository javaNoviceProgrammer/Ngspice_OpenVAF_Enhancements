#!/usr/bin/env python3
"""Enhancement-642: a literal or computed seed for the analog random functions.

LRM Syntax 9-8/9-9 let the seed of `$arandom` and of the `$dist_*`/`$rdist_*`
family be an integer variable, an integer parameter or `[sign] decimal_number`
-- the LRM's own 6.4.1 example seeds with literals -- but the compiler
accepted only the first two: `$rdist_normal(7, 0, 1)` was "expected integer
variable reference or integer parameter ref but found integer literal", and
so was the IHP corner modules' `seed + 3`. Under the E-10 design a draw is a
pure function of (seed value, call site) and the seed is never written back,
so any integer expression serves. That also gives a loop a fresh draw per
iteration (`seed + i`), which the E-395 draw-in-a-loop lint now recognises.
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
WORK = tempfile.mkdtemp(prefix="seedexpr_")
A = "@"
HDR = '`include "disciplines.vams"\n'
M = "module m(p,n); inout p,n; electrical p,n; parameter real r = 1k from (0:inf);\n"


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
        f.write(f"* seedexpr {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\npre_osdi {osdi}.osdi\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def values(out, name):
    return [float(v) for v in re.findall(rf"^{re.escape(name)} = (\S+)", out, re.M)]


print("Enhancement-642: a literal or computed seed for the analog random functions\n")

# ---------------------------------------------------------------- 1 ---
# every seed form the LRM spells, plus the computed one: the draw is (* desc *)
# so the value can be read back
src = (M + "(* type=\"instance\" *) parameter integer seed = 4; (* type=\"instance\" *) parameter integer k = 0;\n"
       "(* desc=\"literal seed\" *) real dl; (* desc=\"negative literal\" *) real dn;\n"
       "(* desc=\"seed + k\" *) real de; (* desc=\"arandom literal\" *) integer ia; (* desc=\"dist literal\" *) integer id;\n"
       "analog begin\n"
       "  dl = $rdist_normal(7, 0, 1); dn = $rdist_normal(-5, 0, 1); de = $rdist_normal(seed + k, 0, 1);\n"
       "  ia = $arandom(7); id = $dist_uniform(3, 1, 6);\n"
       "  I(p,n) <+ V(p,n)/r;\nend endmodule\n")
ok, msg = compile_src(src, "forms")
check("[1] `$rdist_normal(7,…)`, `(-5,…)`, `(seed + k,…)`, `$arandom(7)`, `$dist_uniform(3,…)` compile",
      ok and "error" not in msg, msg.strip().splitlines()[-1][:100] if msg.strip() else "")

# ---------------------------------------------------------------- 2 ---
# the same literal seed at the same call site is the same number in every
# instance (E-10: a draw is a function of seed and call site), and a seed
# that is computed to the same VALUE draws the same number as the plain one
# at that site; a different value draws a different number
if ok:
    out = run(".model mm m\nv1 1 0 1\n"
              "n1 1 0 mm\nn2 1 0 mm seed=5\nn3 1 0 mm seed=4 k=1\nn4 1 0 mm seed=4 k=2",
              f"op\nprint {A}n1[dl] {A}n2[dl] {A}n1[dn] {A}n1[de] {A}n2[de] {A}n3[de] {A}n4[de] {A}n1[ia] {A}n1[id]", "same", "forms")
    dl = values(out, f"{A}n1[dl]") + values(out, f"{A}n2[dl]")
    dn = values(out, f"{A}n1[dn]")
    de = [values(out, f"{A}n{i}[de]") for i in (1, 2, 3, 4)]
    de = [v[0] if v else None for v in de]
    ia = values(out, f"{A}n1[ia]")
    idv = values(out, f"{A}n1[id]")
    check("[2] the literal seed 7 draws one number for both instances, -5 another; `seed + k` at 4+1 equals `seed` at 5, differs at 4+2",
          len(dl) == 2 and dl[0] == dl[1] and dn and dn[0] != dl[0] and None not in de
          and de[2] == de[1] and de[0] != de[1] and de[3] != de[1] and de[3] != de[0],
          f"dl={dl} dn={dn} de={de}")
    check("...[2] `$arandom(7)` and `$dist_uniform(3, 1, 6)` are integers, the latter in [1, 6]",
          ia and idv and float(ia[0]).is_integer() and float(idv[0]).is_integer() and 1 <= idv[0] <= 6,
          f"ia={ia} id={idv}")
else:
    check("[2] (not run: [1] failed)", False)
    check("...[2] (not run)", False)

# ---------------------------------------------------------------- 3 ---
# a loop with `seed + i`: ten different draws, and no L019; the same loop with
# `seed + 1`: one number ten times, and L019 says so
LOOP = (M + "parameter integer seed = 1; integer i; real d, prev;\n"
        "(* desc=\"changes between iterations\" *) integer nd; (* desc=\"sum\" *) real s;\n"
        "analog begin\n  s = 0; nd = 0; prev = 0;\n  for (i = 0; i < 10; i = i + 1) begin\n"
        "    d = $rdist_normal(SEED, 0, 1);\n    if (i > 0 && d != prev) nd = nd + 1;\n    prev = d; s = s + d;\n  end\n"
        "  I(p,n) <+ V(p,n)/r;\nend endmodule\n")
okv, msgv = compile_src(LOOP.replace("SEED", "seed + i"), "loopvar")
okc, msgc = compile_src(LOOP.replace("SEED", "seed + 1"), "loopconst")
check("[3] `$rdist_normal(seed + i, …)` in a loop compiles without L019; `seed + 1` in the same loop is warned by L019 with the new help",
      okv and "L019" not in msgv and okc and "L019" in msgc and "seed that changes" in msgc,
      ("var:" + ("L019" if "L019" in msgv else "clean")) + " const:" + ("L019" if "L019" in msgc else "silent"))
if okv and okc:
    outv = run(".model mm m\nv1 1 0 1\nn1 1 0 mm", f"op\nprint {A}n1[nd] {A}n1[s]", "loopvar", "loopvar")
    outc = run(".model mm m\nv1 1 0 1\nn1 1 0 mm", f"op\nprint {A}n1[nd] {A}n1[s]", "loopconst", "loopconst")
    ndv = values(outv, f"{A}n1[nd]"); ndc = values(outc, f"{A}n1[nd]")
    sv = values(outv, f"{A}n1[s]"); sc = values(outc, f"{A}n1[s]")
    check("...[3] the varying seed changes the draw on all 9 transitions, the constant seed on none, and the sums differ",
          ndv and ndc and ndv[0] == 9 and ndc[0] == 0 and sv and sc and sv[0] != sc[0], f"nd={ndv}/{ndc} s={sv}/{sc}")
else:
    check("...[3] (not run)", False)

# ---------------------------------------------------------------- 4 ---
# a variable the loop advances is a changing seed too (no L019); one the
# loop leaves alone is not (L019)
okadv, msgadv = compile_src(M + "integer i, sd; real s; analog begin s = 0; sd = 1; for (i=0;i<10;i=i+1) begin s = s + $rdist_normal(sd, 0, 1); sd = sd + 1; end I(p,n) <+ V(p,n)/r*(1+0.01*s); end endmodule\n", "adv")
okinv, msginv = compile_src(M + "integer i, sd; real s; analog begin s = 0; sd = 1; for (i=0;i<10;i=i+1) begin s = s + $rdist_normal(sd, 0, 1); end I(p,n) <+ V(p,n)/r*(1+0.01*s); end endmodule\n", "inv")
check("[4] a seed variable the loop advances (`sd = sd + 1`) is not warned; one the loop never writes still is",
      okadv and "L019" not in msgadv and okinv and "L019" in msginv,
      ("adv:" + ("L019" if "L019" in msgadv else "clean")) + " inv:" + ("L019" if "L019" in msginv else "silent"))

# ---------------------------------------------------------------- 5 ---
# what stays refused: a real seed (an integer value is required), and
# `$random(7)` -- Syntax 9-8's random_seed is a variable only
okr, msgr = compile_src(M + "real g; analog begin g = 1 + 0.01*$rdist_normal(1.5, 0, 1); I(p,n) <+ V(p,n)/r*g; end endmodule\n", "realseed")
okq, msgq = compile_src(M + "integer k; analog begin k = $random(7); I(p,n) <+ V(p,n)/r*(k%2); end endmodule\n", "randomlit")
check("[5] a real seed is refused as an integer value would be; `$random(7)` keeps Verilog's variable-only seed",
      (not okr) and "expected integer value but found real literal" in msgr
      and (not okq) and "expected integer variable reference but found integer literal" in msgq,
      (msgr.splitlines()[0][:70] if msgr else "") + " | " + (msgq.splitlines()[0][:70] if msgq else ""))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
