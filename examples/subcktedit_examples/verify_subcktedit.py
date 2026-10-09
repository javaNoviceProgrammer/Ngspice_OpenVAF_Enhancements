#!/usr/bin/env python3
"""Enhancements 817-819 (F1-F3 of the 2026-10-08 ngspice + OSDI hunt): editing
and naming inside subcircuits.

  [1] E-817 (F1): `alterparam cell rr=100` on a parameter of the `.subckt` LINE
      overrode every instance -- `xb ... rr=500` as well as the ones that took
      the default -- because inpcom had already rewritten each call to carry a
      value for every parameter. An instance that gave the parameter itself now
      keeps it, the default moves, and a Note names who kept theirs. An inner
      `.param` (the documented form) still changes everywhere.
  [2] E-818 (F2): `altermod gm g=7m` with `gm` only inside a subcircuit printed
      a Note claiming a top-level card had been changed; there was none, and
      nothing changed. The note now says what is there.
  [3] E-819 (F3): `.ic`, `.nodeset`, `.save @...` and an analysis command typed
      before the first setup refused the `x1.n1` spelling of a device inside a
      subcircuit (flattened `n.x1.n1`) that `print`, `alter` and `show` accept.
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

WORK = tempfile.mkdtemp(prefix="subcktedit_")
checks = passed = 0

MODELS = {
    "gres": """module gres(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3 from (0:inf);
analog I(a,b) <+ g*V(a,b);
endmodule
""",
    "rr2": """module rr2(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin
  I(a, mid) <+ V(a, mid)/1k;
  I(mid, b) <+ V(mid, b)/1k + ddt(1n*V(mid, b));
end
endmodule
""",
    "ov": """module ov(a, b);
inout a, b; electrical a, b;
(* desc="current", units="A" *) real iop;
(* desc="power" *) real pw;
analog begin
  iop = V(a,b)/1k;
  pw = iop*V(a,b);
  I(a,b) <+ iop;
end
endmodule
""",
    "kid": """module kidr(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin I(a,mid) <+ V(a,mid)/1k; I(mid,b) <+ V(mid,b)/1k + ddt(1n*V(mid,b)); end
endmodule
module par(a, b);
inout a, b; electrical a, b;
kidr c1(a, b);
endmodule
""",
}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


for name, src in MODELS.items():
    va = os.path.join(WORK, f"{name}.va")
    with open(va, "w") as f:
        f.write('`include "disciplines.vams"\n' + src)
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, f"{name}.osdi")],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(deck, tag, osdi=()):
    pre = "".join(f"pre_osdi {m}.osdi\n" for m in osdi)
    if pre:
        deck = deck.replace("\n", f"\n.control\n{pre}.endc\n", 1)
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(deck)
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, errors="replace")
    return p.stdout + p.stderr


def vals(out, name):
    return [float(v) for v in re.findall(r"^" + re.escape(name) + r" = (\S+)", out, re.M)]


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1e-30, abs(b))


def seq(out, name, want):
    got = vals(out, name)
    return len(got) == len(want) and all(near(g, w) for g, w in zip(got, want))


print("Enhancements 817-819: editing and naming inside subcircuits\n")

# ------------------------------------------------------------- [1] ---
print("[1] E-817: alterparam on a parameter of the .subckt line")
out = run("""* f1
.subckt cell a b rr=1k
r1 a b {rr}
.ends
v1 1 0 1
xa 1 0 cell rr=1k
xb 1 0 cell rr=500
xc 1 0 cell
.control
op
print i(v1)
alterparam cell rr=100
reset
op
print i(v1)
.endc
.end
""", "f1")
check("[1] xa rr=1k and xb rr=500 keep their own value, xc (the default) moves to 100: "
      "4 mA -> 13 mA (it was 30 mA, every instance at 100)",
      seq(out, "i(v1)", [-4e-3, -13e-3]), f"{vals(out, 'i(v1)')}")
check("[1] a Note says the default moved and names who kept theirs",
      "Note: alterparam cell rr=100 sets the default of .subckt cell; xa, xb give rr on the "
      "instance line and keep it." in out, out[-400:])
out = run("""* f1 inner
.subckt cell a b rr=1k
.param inner=2k
r1 a b {rr}
r2 a b {inner}
.ends
v1 1 0 1
xa 1 0 cell rr=1k
xb 1 0 cell rr=500
xc 1 0 cell
.control
op
print i(v1)
alterparam cell inner=500
reset
op
print i(v1)
alterparam cell rr=100
reset
op
print i(v1)
alterparam cell rr=200
reset
op
print i(v1)
.endc
.end
""", "f1inner")
check("[1] the documented inner `.param` still changes in every instance, and the line's "
      "parameter can be moved twice: 5.5, 10, 19, 14 mA",
      seq(out, "i(v1)", [-5.5e-3, -10e-3, -19e-3, -14e-3]) and "inner=500 sets" not in out,
      f"{vals(out, 'i(v1)')}")
out = run("""* f1 nested
.subckt cell a b rr=1k
r1 a b {rr}
.ends
.subckt pair a b
xin a b cell rr=250
xdf a b cell
.ends
v1 1 0 1
xp 1 0 pair
xt 1 0 cell
.control
op
print i(v1)
alterparam cell rr=100
reset
op
print i(v1)
.endc
.end
""", "f1nest")
check("[1] a call inside another subcircuit that gives its own value keeps it: 6 -> 24 mA",
      seq(out, "i(v1)", [-6e-3, -24e-3]) and "xin gives rr" in out, f"{vals(out, 'i(v1)')}")
out = run("""* f1 osdi
.subckt cell a b gg=1m
.model gm gres g={gg}
n1 a b gm
.ends
v1 1 0 1
xa 1 0 cell gg=1m
xb 1 0 cell gg=3m
xc 1 0 cell
.control
op
print i(v1)
alterparam cell gg=10m
reset
op
print i(v1)
.endc
.end
""", "f1osdi", ["gres"])
check("[1] an OSDI card inside the subcircuit reading the line's parameter: 5 -> 14 mA "
      "(it was 30 mA)", seq(out, "i(v1)", [-5e-3, -14e-3]), f"{vals(out, 'i(v1)')}")

# ------------------------------------------------------------- [2] ---
print("[2] E-818: altermod's note about subcircuit copies")


def layout(top, copies, tag):
    deck = "* f2\n.subckt cell a b\n.model gm gres g=1m\nn1 a b gm\n.ends\n"
    if top:
        deck += ".model gm gres g=1m\nnt 1 0 gm\n"
    deck += "v1 1 0 1\n" + "".join(f"x{i} 1 0 cell\n" for i in range(1, copies + 1))
    deck += ".control\nop\nprint i(v1)\naltermod gm g=7m\nop\nprint i(v1)\n.endc\n.end\n"
    return run(deck, tag, ["gres"])


out = layout(True, 2, "f2t2")
check("[2] a top-level card and two copies: the note is right, only the card changed (3 -> 9 mA)",
      "Note: 3 models are named 'gm' (the top-level card and 2 flattened subcircuit copies); "
      "only the top-level one was changed" in out and seq(out, "i(v1)", [-3e-3, -9e-3]),
      out[-400:])
out = layout(False, 3, "f2c3")
check("[2] three copies and no top-level card: no claim of a top-level card; the note says none "
      "was changed, and nothing did (3 mA)",
      "the top-level card" not in out
      and "Note: no top-level card is named 'gm'; the 3 models of that name are flattened "
          "subcircuit copies" in out and "none was changed" in out
      and seq(out, "i(v1)", [-3e-3, -3e-3]), out[-500:])
out = layout(False, 1, "f2c1")
check("[2] one copy: the note names it",
      "the only model of that name is the flattened subcircuit copy 'x1:gm'" in out
      and seq(out, "i(v1)", [-1e-3, -1e-3]), out[-400:])
out = layout(True, 0, "f2t0")
check("[2] a top-level card alone: no note, the card changed (1 -> 7 mA)",
      "Note: " not in out.replace("Note: Simulation", "") and seq(out, "i(v1)", [-1e-3, -7e-3]),
      out[-300:])

# ------------------------------------------------------------- [3] ---
print("[3] E-819: the x1.n1 spelling of a device inside a subcircuit")
SUB = ".subckt w a b\nn1 a b rrm\n.ends\n.model rrm rr2\nv1 1 0 2\nx1 1 0 w\n"
out = run("* f3 ic\n" + SUB + ".ic v(x1.n1#mid)=1.5\n.nodeset v(x1.n1#mid)=0.3\n"
          ".control\ntran 1n 10n uic\nprint v(x1.n1#mid)[0]\n.endc\n.end\n", "f3ic", ["rr2"])
check("[3] `.ic v(x1.n1#mid)=1.5` applies: the node starts at 1.5 V (it was ignored, 2 uV)",
      near((vals(out, "v(x1.n1#mid)[0]") or [None])[0], 1.5, 1e-5)
      and "non-existent" not in out, out[-400:])
check("[3] `.nodeset v(x1.n1#mid)` is accepted, as `.nodeset v(n.x1.n1#mid)` is",
      "Nodeset on non-existent node" not in out, out[-300:])
out = run("* f3 save\n.subckt w a b\nn1 a b ovm\n.ends\n.model ovm ov\nv1 1 0 2\nx1 1 0 w\n"
          ".save @x1.n1[pw] @x1.n1[iop] v(1)\n.control\ntran 10n 100n\n"
          "print @x1.n1[pw][5] @x1.n1[iop][5]\n.endc\n.end\n", "f3save", ["ov"])
check("[3] `.save @x1.n1[pw]` of an operating-point variable records it under that name: "
      "pw 4 mW, iop 2 mA (it was 'no such device', an empty vector)",
      "no such device" not in out and vals(out, "@x1.n1[pw][5]") == [4e-3]
      and vals(out, "@x1.n1[iop][5]") == [2e-3], out[-400:])
out = run("* f3 tf\n" + SUB + ".control\ntf v(x1.n1#mid) v1\nprint transfer_function\nop\n"
          "tf v(x1.n1#mid) v1\nprint transfer_function\n.endc\n.end\n", "f3tf", ["rr2"])
check("[3] `tf v(x1.n1#mid) v1` as the first command and after an op: 0.5 both times",
      seq(out, "transfer_function", [0.5, 0.5]), out[-400:])
out = run("* f3 child\n.subckt w a b\nn1 a b pm\n.ends\n.model pm par\nv1 1 0 2\nx1 1 0 w\n"
          ".ic v(x1.n1#c1.mid)=1.7\n.control\ntran 1n 10n uic\nprint v(x1.n1#c1.mid)[0]\n"
          ".endc\n.end\n", "f3child", ["kid"])
check("[3] with Enhancement-806's spelling of a Verilog-A child's node: "
      "`.ic v(x1.n1#c1.mid)=1.7` applies",
      near((vals(out, "v(x1.n1#c1.mid)[0]") or [None])[0], 1.7, 1e-5), out[-300:])
out = run("* f3 bjt\n.subckt amp c b e\nq1 c b e qm\n.ends\n"
          ".model qm npn bf=100 rb=100 rc=10 re=1\nvc c 0 5\nvb b 0 0.7\nx1 c b 0 amp\n"
          ".ic v(x1.q1#base)=0.33\n.control\ntran 1n 10n uic\n.endc\n.end\n", "f3bjt")
check("[3] a built-in BJT's internal node: `.ic v(x1.q1#base)` is accepted as the top-level "
      "`.ic v(q1#base)` is", "non-existent" not in out, out[-300:])
out = run("* f3 typo\n" + SUB + ".ic v(x1.nosuch#mid)=1\n.control\nop\n.endc\n.end\n", "f3typo",
          ["rr2"])
check("[3] a name that is no device under either spelling is still refused",
      "IC on non-existent node - x1.nosuch#mid" in out, out[-300:])

print(f"\n    {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
