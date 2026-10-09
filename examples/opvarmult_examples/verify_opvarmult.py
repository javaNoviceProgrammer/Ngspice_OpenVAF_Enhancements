#!/usr/bin/env python3
"""Enhancement-814 (F23 of the 2026-10-08 ngspice + OSDI hunt): an output
variable's `multiplicity` attribute scales its report by $mfactor.

LRM 3.2.1: an output variable declared `(* multiplicity="multiply" *)` is
multiplied by $mfactor "in any report of operating-point values", one declared
"divide" is divided by it, and "none" (the default) is left alone. openvaf-r read
the attribute nowhere, so `n1 ... m=4` reported every current, conductance and
capacitance per device and every resistance four times too large. About ninety
declarations in the bundled corpus carry it (BSIM-CMG/IMG/BULK/SOI, PSP, HiSIM,
HICUM L0, EKV). The compiled model now stores the scaled value in the
operating-point slot -- the variable itself, which the model reads, is untouched
-- so `print`, `show` and a saved vector all report it.

  [1] m=4: "multiply" times 4 and "divide" over 4, from a computed value, a
      constant and a parameter; no attribute and "none" unscaled; `show`; a
      variable carrying a hidden state is not fed its own scaled report
  [2] no m: unchanged; `alter n1 m=2` rescales; a saved vector in a transient
  [3] the multiplicity composes: a subcircuit's m=, a paramset's .$mfactor, and
      a Verilog-A child's #(.$mfactor(...)) at two levels
  [4] m=0: a multiplied report is 0, a divided one infinite
  [5] an attribute that cannot take effect is named at compile time
  [6] a corpus model: HICUM L0's transconductance, capacitance and input
      resistance at m=3 against m=1
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="opvarmult_")
checks = passed = 0

MODELS = """`include "disciplines.vams"
module mu(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
(* desc="current", units="A", multiplicity="multiply" *) real itot;
(* desc="constant resistance", units="Ohm", multiplicity="divide" *) real reff;
(* desc="parameter resistance", units="Ohm", multiplicity="divide" *) real rr;
(* desc="plain" *) real pl;
(* desc="none", multiplicity="none" *) real nn;
(* desc="peak voltage", units="V", multiplicity="multiply" *) real vpk;
analog begin
  itot = V(a,b)/r; reff = 1k; rr = r; pl = 7; nn = 5;
  if (V(a,b) > vpk) vpk = V(a,b);
  I(a,b) <+ V(a,b)/r;
end
endmodule
paramset mup mu;
  .$mfactor = 8;
endparamset
module leaf(a, b);
inout a, b; electrical a, b;
(* desc="leaf current", units="A", multiplicity="multiply" *) real il;
analog begin il = V(a,b)/1k; I(a,b) <+ V(a,b)/1k; end
endmodule
module mid(a, b);
inout a, b; electrical a, b;
(* desc="mid current", units="A", multiplicity="multiply" *) real im;
(* desc="mid resistance", units="Ohm", multiplicity="divide" *) real rm;
leaf #(.$mfactor(2)) c2(a, b);
analog begin im = V(a,b)/1k; rm = 1k; I(a,b) <+ V(a,b)/1k; end
endmodule
module top(a, b);
inout a, b; electrical a, b;
(* desc="top current", units="A", multiplicity="multiply" *) real it;
mid #(.$mfactor(4)) c1(a, b);
analog begin it = V(a,b)/1k; I(a,b) <+ V(a,b)/1k; end
endmodule
"""

DIAG = """`include "disciplines.vams"
module dg(a, b);
inout a, b; electrical a, b;
(* desc="bad value", multiplicity="times" *) real x1;
(* desc="count", multiplicity="multiply" *) integer cnt;
(* multiplicity="multiply" *) real x2;
(* desc="not a string", multiplicity=1 *) real x3;
(* desc="good", multiplicity = "divide" *) real x4;
analog begin : blk
  (* desc="in a block", multiplicity="divide" *) real x5;
  x5 = 1; x1 = 1; cnt = 3; x2 = 2; x3 = 3; x4 = 4*x5;
  I(a,b) <+ V(a,b)/1k;
end
endmodule
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


def compile_va(name, src=None, path=None):
    if path is None:
        path = os.path.join(WORK, f"{name}.va")
        with open(path, "w") as f:
            f.write(src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{name}.osdi")],
                       capture_output=True, text=True, errors="replace")
    return r.returncode, r.stdout + r.stderr


def run(lib, body, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* opvarmult {tag}\n.control\npre_osdi {lib}.osdi\n.endc\n{body}\n"
                f".control\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, errors="replace")
    return p.stdout + p.stderr


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r" = (\S+)", out, re.M)
    if not m:
        return None
    t = m.group(1).rstrip(",")
    return float("inf") if t == "inf" else float(t)


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1e-30, abs(b))


rc, out = compile_va("mm", MODELS)
if rc != 0:
    print(out)
    sys.exit(1)

print("Enhancement-814: the multiplicity attribute scales an output variable's report\n")

# ------------------------------------------------------------- [1] ---
print("[1] m=4 at 2 V")
out = run("mm", "v1 1 0 2\nn1 1 0 mum m=4\n.model mum mu",
          "op\nprint @n1[itot] @n1[reff] @n1[rr] @n1[pl] @n1[nn] @n1[vpk] i(v1)\nshow n1\n"
          "op\nprint @n1[vpk]", "flat")
check("[1] multiply: @n1[itot] = 8e-3 (4 x 2e-3), the current itself -8 mA",
      near(val(out, "@n1[itot]"), 8e-3) and near(val(out, "i(v1)"), -8e-3),
      f"{val(out, '@n1[itot]')} {val(out, 'i(v1)')}")
check("[1] divide: a constant @n1[reff] and the parameter @n1[rr] = 250 (1k / 4)",
      near(val(out, "@n1[reff]"), 250) and near(val(out, "@n1[rr]"), 250),
      f"{val(out, '@n1[reff]')} {val(out, '@n1[rr]')}")
check("[1] no attribute and \"none\": @n1[pl] = 7 and @n1[nn] = 5, unscaled",
      val(out, "@n1[pl]") == 7 and val(out, "@n1[nn]") == 5, f"{val(out, '@n1[pl]')} {val(out, '@n1[nn]')}")
check("[1] `show n1` reports the same: itot 0.008, reff 250",
      re.search(r"^\s+itot\s+0\.008\s*$", out, re.M) and re.search(r"^\s+reff\s+250\s*$", out, re.M),
      out[-600:])
pk = re.findall(r"^@n1\[vpk\] = (\S+)", out, re.M)
check("[1] a variable carrying a hidden state (a running peak): 8 after one op and after a "
      "second -- the model keeps its own 2 V, not the report",
      len(pk) == 2 and all(near(float(p), 8.0) for p in pk), f"{pk}")

# ------------------------------------------------------------- [2] ---
print("[2] no m, alter, a saved vector")
out = run("mm", "v1 1 0 2\nn1 1 0 mum\n.model mum mu",
          "op\nprint @n1[itot] @n1[reff]\nalter n1 m=2\nop\nprint @n1[itot] @n1[reff]", "alter")
it = re.findall(r"^@n1\[itot\] = (\S+)", out, re.M)
rf = re.findall(r"^@n1\[reff\] = (\S+)", out, re.M)
check("[2] no m: itot 2e-3 and reff 1000; after `alter n1 m=2`: 4e-3 and 500",
      [float(x) for x in it] == [2e-3, 4e-3] and [float(x) for x in rf] == [1000, 500], f"{it} {rf}")
out = run("mm", "v1 1 0 2\nn1 1 0 mum m=4\n.model mum mu\n.save @n1[itot] @n1[reff]",
          "tran 1n 10n\nprint @n1[itot][5] @n1[reff][5]", "tran")
check("[2] a saved vector in a transient: @n1[itot] = 8e-3, @n1[reff] = 250",
      near(val(out, "@n1[itot][5]"), 8e-3) and near(val(out, "@n1[reff][5]"), 250), out[-400:])

# ------------------------------------------------------------- [3] ---
print("[3] the multiplicity composes")
out = run("mm", "v2 2 0 2\nx1 2 0 sub m=3\n.subckt sub a b\nn1 a b mum\n.model mum mu\n.ends",
          "op\nprint @n.x1.n1[itot] @n.x1.n1[reff] i(v2)", "subckt")
check("[3] a subcircuit called with m=3: itot 6e-3, reff 333.3",
      near(val(out, "@n.x1.n1[itot]"), 6e-3) and near(val(out, "@n.x1.n1[reff]"), 1000 / 3)
      and near(val(out, "i(v2)"), -6e-3), out[-400:])
out = run("mm", "v3 3 0 2\nn3 3 0 mpp m=3\n.model mpp mup", "op\nprint @n3[itot] @n3[reff] i(v3)",
          "paramset")
check("[3] a paramset with .$mfactor = 8, instance m=3: the effective 24 -- itot 48e-3, reff 41.67",
      near(val(out, "@n3[itot]"), 48e-3) and near(val(out, "@n3[reff]"), 1000 / 24)
      and near(val(out, "i(v3)"), -48e-3), out[-400:])
out = run("mm", "v4 4 0 2\nn4 4 0 tm m=2\n.model tm top",
          "op\nprint @n4[it] @n4[c1__im] @n4[c1__rm] @n4[c1__c2__il] i(v4)", "children")
check("[3] Verilog-A children under m=2: the top's own 4e-3, c1 #(.$mfactor(4)) 16e-3 and 125 Ohm, "
      "its c2 #(.$mfactor(2)) 32e-3",
      near(val(out, "@n4[it]"), 4e-3) and near(val(out, "@n4[c1__im]"), 16e-3)
      and near(val(out, "@n4[c1__rm]"), 125) and near(val(out, "@n4[c1__c2__il]"), 32e-3)
      and near(val(out, "i(v4)"), -52e-3), out[-500:])

# ------------------------------------------------------------- [4] ---
print("[4] m=0")
out = run("mm", "v5 5 0 2\nn5 5 0 mum m=0\n.model mum mu", "op\nprint @n5[itot] @n5[reff]", "mzero")
check("[4] m=0 disables the instance: itot reports 0, reff infinite",
      val(out, "@n5[itot]") == 0 and val(out, "@n5[reff]") == float("inf"), out[-300:])

# ------------------------------------------------------------- [5] ---
print("[5] an attribute that cannot take effect")
rc, cout = compile_va("dg", DIAG)
check("[5] five warnings, each naming why: the value, an integer, no desc/units, a named block",
      rc == 0 and cout.count("'multiplicity' attribute is ignored") == 5
      and cout.count('its value must be "multiply", "divide" or "none"') == 2
      and "only a real scalar output variable" in cout and "no 'units' or 'desc'" in cout
      and "declared in a named block" in cout, cout[-800:])
out = run("dg", "v1 1 0 2\nn1 1 0 dgm m=2\n.model dgm dg", "op\nprint @n1[cnt] @n1[x1] @n1[x4]", "diag")
check("[5] at m=2 the ignored ones report unscaled (cnt 3, x1 1), the good one is divided (x4 2)",
      val(out, "@n1[cnt]") == 3 and val(out, "@n1[x1]") == 1 and near(val(out, "@n1[x4]"), 2),
      out[-300:])

# ------------------------------------------------------------- [6] ---
print("[6] a corpus model: HICUM L0")
hic = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code", "hicum0", "vacode", "hicumL0_v2p1p0.va")
rc, cout = compile_va("hic", path=hic)
res = {}
for m in (1, 3):
    out = run("hic", f"vc c 0 2\nvb b 0 0.8\nn1 c b 0 0 t hicm m={m}\n.model hicm hicumL0va",
              "op\nprint i(vc) @n1[g_mi] @n1[c_jeop] @n1[r_pii]", f"hic{m}")
    res[m] = {k: val(out, k) for k in ("i(vc)", "@n1[g_mi]", "@n1[c_jeop]", "@n1[r_pii]")}
ok = rc == 0 and all(v is not None for r in res.values() for v in r.values())
check("[6] m=3 against m=1: the collector current, G_Mi and C_JEop x3 (\"multiply\"), "
      "R_PIi / 3 (\"divide\")",
      ok and all(near(res[3][k] / res[1][k], 3, 1e-4) for k in ("i(vc)", "@n1[g_mi]", "@n1[c_jeop]"))
      and near(res[3]["@n1[r_pii]"] / res[1]["@n1[r_pii]"], 1 / 3, 1e-4), f"{res}")

print(f"\n    {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
