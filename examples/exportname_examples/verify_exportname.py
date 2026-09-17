#!/usr/bin/env python3
"""Enhancement-652: an exported name ngspice cannot reach is reported where
the author is (2026-09-16 hunt, F8).

Verilog-A is case-sensitive; ngspice folds every name to lower case and keeps
two flat tables per device -- the instance's parameters, aliases and
operating-point variables (with the simulator's own m/temp/dtemp/dt and the
terminal currents E-394 synthesizes), and the model's parameters and aliases.
Two entries that fold to one name are one name to `@inst[name]`, `show` and
`alter`: the first in the table wins and the other is unreachable, with two
rows of that name in `show`. ngspice warns at load time (E-335/E-396); the
author compiling the model never saw it, and L029 (reserved_parameter_name)
covered parameters only. A `$` in an exported name (legal Verilog-A) is read
by ngspice's expression parser as a shell variable, so `@inst[a$b]` never
works and the name is write-only.

Now `exported_name_collision` (L035) and `dollar_in_exported_name` (L036)
report both at compile time, naming which declaration wins and why.
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
WORK = tempfile.mkdtemp(prefix="exportname_")
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


def run(tag, ctl, mcard=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* exportname {tag}\nv1 1 0 1\n.model m m {mcard}\nna1 1 0 m\n.control\nset noinit\npre_osdi {tag}.osdi\nop\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL, errors="replace")
    return p.stdout + p.stderr


def val(o, name):
    m = re.search(re.escape(name) + r"\s*=\s*([-+0-9.eE]+)", o)
    return float(m.group(1)) if m else None


MOD = lambda body: "module m(p,n); inout p,n; electrical p,n;\n" + body + "\nendmodule\n"
D = '(* desc="x" *) '
L035 = "warning[L035]"
L036 = "warning[L036]"
A = "@"  # the instance/model accessor, spelt apart so the source carries no bare mention


def first_warn(out):
    return next((l[:100] for l in out.splitlines() if l.startswith("warning[")), (out.strip().splitlines() or [""])[0][:80])


# ---------------------------------------------------------------- collisions in the instance table
ok, out = compile_src(MOD(f'(* type="instance" *) parameter real w = 2; {D}real W;\nanalog begin W = 5; I(p,n) <+ w*V(p,n); end'), "c1")
o = run("c1", f"print {A}na1[W]") if ok else ""
check("[1] instance parameter 'w' beside operating-point variable 'W': L035 names both and says the parameter wins; it compiles",
      ok and L035 in out and "operating-point variable 'W' and instance parameter 'w' differ only by case" in out
      and "instance parameter 'w' comes first in the simulator's table and wins the lookup" in out, first_warn(out))
check(f"[2] ... and on ngspice `{A}na1[W]` is indeed the parameter (2), not the variable (5)", val(o, A + "na1[w]") == 2.0, f"{val(o, A + 'na1[w]')}")
ok, out = compile_src(MOD(f"{D}real g; {D}real G;\nanalog begin g = 1; G = 3; I(p,n) <+ V(p,n); end"), "c3")
o = run("c3", f"print {A}na1[G]") if ok else ""
check("[3] two operating-point variables 'g' and 'G': L035, the earlier declaration wins",
      ok and "operating-point variable 'G' and operating-point variable 'g' differ only by case" in out
      and "operating-point variable 'g' comes first" in out and val(o, A + "na1[g]") == 1.0, first_warn(out))
ok, out = compile_src(MOD(f'(* type="instance" *) parameter real r = 1; aliasparam res = r; {D}real Res;\nanalog begin Res = 7; I(p,n) <+ V(p,n)/r; end'), "c4")
check("[4] an instance alias 'res' beside variable 'Res': L035 names the alias", ok and "operating-point variable 'Res' and alias 'res' differ only by case" in out, first_warn(out))
ok, out = compile_src(MOD("parameter real g = 2; parameter real G = 3;\nanalog I(p,n) <+ g*G*V(p,n);"), "c5")
check("[5] two model parameters 'g' and 'G': L035 with the model-level spelling (`@<model>[g]`, showmod, altermod)",
      ok and "model parameter 'G' and model parameter 'g' differ only by case" in out and "@<model>[g]" in out and "showmod" in out and "altermod" in out, first_warn(out))
ok, out = compile_src(MOD("parameter real a = 1, b = 2; aliasparam x = a; aliasparam X = b;\nanalog I(p,n) <+ a*b*V(p,n);"), "c6")
check("[6] two aliases of different parameters, 'x' and 'X': L035", ok and "alias 'X' and alias 'x' differ only by case" in out, first_warn(out))

# ---------------------------------------------------------------- ngspice's own names
ok, out = compile_src(MOD(f"{D}real m; {D}real temp; {D}real dt;\nanalog begin m = 9; temp = 8; dt = 7; I(p,n) <+ V(p,n); end"), "r1")
check("[7] operating-point variables 'm', 'temp' and 'dt': three L035, ngspice's own instance parameter wins the lookup",
      ok and out.count(L035) == 3 and "has the name of ngspice's own instance parameter 'm', which wins the lookup" in out
      and "'temp', which wins" in out and "'dt', which wins" in out, first_warn(out))
ok, out = compile_src(MOD(f"{D}real i_p; {D}real i;\nanalog begin i_p = 4; i = 5; I(p,n) <+ V(p,n); end"), "r2")
check("[8] operating-point variables 'i_p' and 'i' on a two-terminal device shadow the synthesized terminal currents (E-394): two L035",
      ok and out.count(L035) == 2 and "shadows 'i_p', the terminal current ngspice synthesizes" in out and "shadows 'i', the terminal current" in out, first_warn(out))
ok, out = compile_src("module m(p,n,q); inout p,n,q; electrical p,n,q;\n" + D + "real i; parameter real i_p = 1;\nanalog begin i = 1; I(p,n) <+ V(p,n); I(q,n) <+ V(q,n)*i_p; end\nendmodule\n", "r3")
check("[9] a three-terminal device synthesizes no bare 'i', and a MODEL parameter 'i_p' lives in the other table: no word", ok and L035 not in out, first_warn(out))
ok, out = compile_src(MOD('(* type="instance" *) parameter real i = 1;\nanalog I(p,n) <+ i*V(p,n);'), "r4")
check("[10] an instance parameter named 'i' is routed by ngspice (E-644), not shadowed: no word", ok and L035 not in out, first_warn(out))

# ---------------------------------------------------------------- $ in a name
ok, out = compile_src(MOD("parameter real a$b = 1;\nanalog I(p,n) <+ a$b*V(p,n);"), "d1")
check("[11] model parameter 'a$b': L036, write-only from ngspice",
      ok and L036 in out and "model parameter 'a$b' has a `$` in its name" in out and "write-only from ngspice" in out, first_warn(out))
ok, out = compile_src(MOD(f"{D}real a$b;\nanalog begin a$b = 4; I(p,n) <+ V(p,n); end"), "d2")
check("[12] operating-point variable 'a$b': L036, not exported to the simulator",
      ok and "operating-point variable 'a$b' has a `$` in its name" in out and "not exported to the simulator" in out, first_warn(out))
ok, out = compile_src(MOD('(* type="instance" *) parameter real c$d = 1; parameter real e = 2; aliasparam x$y = e;\nanalog I(p,n) <+ c$d*e*V(p,n);'), "d3")
check("[13] an instance parameter 'c$d' and an alias 'x$y': two L036", ok and out.count(L036) == 2 and "instance parameter 'c$d'" in out and "alias 'x$y'" in out, first_warn(out))
ok, out = compile_src(MOD('parameter real r = 1;\n' + D + 'real x;\nanalog begin x = r; I(p,n) <+ V(p,n)/r; end') + "paramset ps m;\nparameter real rr = 2;\n(* desc=\"b\" *) real x;\n.r = rr;\nendparamset\n", "d4")
check("[14] the `x$ps` twin a paramset's redeclared variable creates (LRM 6.4.3) is not the author's `$`: no word", ok and L036 not in out, first_warn(out))

# ---------------------------------------------------------------- not collisions
ok, out = compile_src(MOD(f"parameter real g = 2; {D}real G;\nanalog begin G = 3; I(p,n) <+ g*V(p,n); end"), "n1")
o = run("n1", f"print {A}na1[G] {A}m[g]") if ok else ""
check(f"[15] a MODEL parameter 'g' beside variable 'G' live in different tables, both reachable (`{A}na1[G]` = 3, `{A}m[g]` = 2): no word",
      ok and L035 not in out and val(o, A + "na1[g]") == 3.0 and val(o, A + "m[g]") == 2.0, first_warn(out) if L035 in out else f"{val(o, A + 'na1[g]')} {val(o, A + 'm[g]')}")
ok, out = compile_src(MOD("parameter real R = 1; aliasparam r = R;\nanalog I(p,n) <+ V(p,n)/R;"), "n2")
check("[16] a parameter and its own alias differing by case are one entry ngspice routes: no word", ok and L035 not in out, first_warn(out))
ok, out = compile_src(MOD("parameter real dtemp = 0;\nanalog I(p,n) <+ V(p,n)*(1 + dtemp);"), "n3")
check("[17] a parameter named 'dtemp' is L029's (routed to ngspice's own): L029, no L035", ok and "L029" in out and L035 not in out, first_warn(out))
ok, out = compile_src(MOD('(* type="instance" *) parameter real w = 2; real W;\nanalog begin W = 5; I(p,n) <+ w*V(p,n); end'), "n4")
check("[18] a variable without desc/units is not exported, so its case twin is no collision: no word", ok and L035 not in out, first_warn(out))
ok, out = compile_src(MOD(f'(* type="instance" *) parameter real w = 2; (* desc="x", openvaf_allow="exported_name_collision" *) real W;\nanalog begin W = 5; I(p,n) <+ w*V(p,n); end'), "n5")
check("[19] `(* openvaf_allow=\"exported_name_collision\" *)` on the declaration silences it", ok and L035 not in out, first_warn(out))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
