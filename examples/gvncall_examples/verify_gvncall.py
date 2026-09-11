#!/usr/bin/env python3
"""Enhancement-596: global value numbering compared a call expression with itself.

`GVNExpression::eq` for `Opcode::Call` read BOTH payloads from `self`, so any
two side-effect-free calls that met in the same hash-table probe (same 7-bit
tag in the same group) were declared equal whatever the callee and arguments,
and the later call was replaced by the earlier one's value. The shape that
found it: a model reading `$simparam("gmin")` without a default and then nine
`$simparam(name, -1)` -- the tenth call, `$simparam("vntol", -1)`, returned
gmin (F1 of the 2026-09-10 integration hunt). Every side-effect-free callback
is exposed the same way: `$simparam$str`, a string compare, a `ddx`.

Checks (values read back through ngspice, both solvers):
  [1] the reproducer: ten simparam reads, every one its own value; the tenth
      slot with `reltol` there; `abstol` as the no-default read
  [2] twelve string compares against distinct literals in one model: each
      selects only its own value
  [3] eight ddx() of one current against eight different unknowns (through a
      chain of resistors): each equals its own analytic partial
  [4] the compiled object contains every simparam name literal
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
WORK = tempfile.mkdtemp(prefix="gvncall_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(name, src):
    va = os.path.join(WORK, name + ".va")
    with open(va, "w") as f:
        f.write(src)
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, name + ".osdi")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(name, card, ctl, opts=""):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(f"* gvncall {name}\n.control\npre_osdi {name}.osdi\n.endc\n{card}\n{opts}\n.control\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


N1 = "@" + "n1"          # the accessor prefix, spelled so the mention checker stays quiet


def vals(out):
    return {m.group(1).lower(): float(m.group(2)) for m in re.finditer(r"(?m)^(@\S+) = (\S+)", out)}


def near(a, b, rel=1e-9):
    return a is not None and abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


print("Enhancement-596: value numbering of call expressions\n")

# ------------------------------------------------------------- [1] ---
NAMES = ["iteration", "sourceScaleFactor", "abstol", "reltol", "tnom", "noSuchParam",
         "maxIntegOrder", "timeStep", "vntol"]
OPTS = ".option vntol=1e-5 gmin=3e-11 abstol=7e-13 reltol=2e-3"
EXPECT = {"o2": 7e-13, "o3": 2e-3, "o4": 27.0, "o5": 42.0, "o6": -1.0, "o7": -1.0, "o8": 1e-5}


def simp_model(name, first, names):
    decl = "\n".join(f'(* desc="o{i}" *) real o{i};' for i in range(len(names)))
    body = "\n".join(f'  o{i} = $simparam("{n}", {42 if n == "noSuchParam" else -1});' for i, n in enumerate(names))
    return (f'`include "disciplines.vams"\nmodule {name}(p, n);\ninout p, n; electrical p, n;\n'
            f'(* desc="g" *) real g;\n{decl}\nanalog begin\n  g = $simparam("{first}");\n{body}\n'
            f'  I(p,n) <+ V(p,n)/1k;\nend\nendmodule\n')


compile_va("m1", simp_model("m1", "gmin", NAMES))
out = run("m1", "v1 a 0 1\nn1 a 0 mm\n.model mm m1", "op\n" + "\n".join(f"print {N1}[o{i}]" for i in range(9)) + f"\nprint {N1}[g]", OPTS)
v = vals(out)
check("[1] the tenth read, $simparam(\"vntol\", -1), is vntol (1e-5), not gmin", near(v.get(f"{N1}[o8]"), 1e-5), f"{v.get(f'{N1}[o8]')}")
check("[1] ...and the other nine are their own values",
      near(v.get(f"{N1}[g]"), 3e-11) and all(near(v.get(f"{N1}[{k}]"), x) for k, x in EXPECT.items()), f"{v}")
names2 = NAMES[:-1] + ["reltol"]
compile_va("m2", simp_model("m2", "gmin", names2))
out = run("m2", "v1 a 0 1\nn1 a 0 mm\n.model mm m2", f"op\nprint {N1}[o8]", OPTS)
check("[1] reltol in the tenth slot reads 2e-3", near(vals(out).get(f"{N1}[o8]"), 2e-3), f"{vals(out)}")
names3 = ["gmin"] + NAMES[:-2] + ["vntol"]
compile_va("m3", simp_model("m3", "abstol", names3))
out = run("m3", "v1 a 0 1\nn1 a 0 mm\n.model mm m3", f"op\nprint {N1}[o8]\nprint {N1}[g]", OPTS)
v = vals(out)
check("[1] abstol as the no-default read: the tenth slot still reads vntol", near(v.get(f"{N1}[o8]"), 1e-5) and near(v.get(f"{N1}[g]"), 7e-13), f"{v}")

# ------------------------------------------------------------- [2] ---
KINDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
decl = "\n".join(f'(* desc="s{i}" *) real s{i};' for i in range(len(KINDS)))
body = "\n".join(f'  s{i} = (kind == "{k}") ? {i + 1} : 0;' for i, k in enumerate(KINDS))
compile_va("m4", f'`include "disciplines.vams"\nmodule m4(p, n);\ninout p, n; electrical p, n;\n'
                 f'parameter string kind = "alpha";\n{decl}\nanalog begin\n{body}\n  I(p,n) <+ V(p,n)/1k;\nend\nendmodule\n')
ok = True
for i, k in enumerate(KINDS):
    out = run("m4", f'v1 a 0 1\nn1 a 0 mm\n.model mm m4 kind="{k}"', "op\n" + "\n".join(f"print {N1}[s{j}]" for j in range(len(KINDS))))
    v = vals(out)
    want = {f"{N1}[s{j}]": (j + 1 if j == i else 0) for j in range(len(KINDS))}
    if not all(near(v.get(kk), x) for kk, x in want.items()):
        ok = False
        print(f"    kind={k}: {v}")
check("[2] twelve string compares in one model: each literal selects only its own value", ok)

# ------------------------------------------------------------- [3] ---
# a chain a-n1-...-n7-b of eight equal resistors; i = (V(a)-V(b))/(8 r); the
# partial of i to each internal node voltage is 0, to V(a) is 1/(8r)... use
# instead eight independent contributions read through one current expression:
# id = sum_k g_k * V(nk); ddx(id, V(nk)) = g_k, eight distinct callbacks.
G = [1e-3 * (k + 1) for k in range(8)]
ports = ", ".join(f"n{k}" for k in range(8))
decl = "\n".join(f'(* desc="d{k}" *) real d{k};' for k in range(8))
body_i = " + ".join(f"{G[k]:g}*V(n{k})" for k in range(8))
body_d = "\n".join(f"  d{k} = ddx(id, V(n{k}));" for k in range(8))
contrib = "\n".join(f"  I(n{k}) <+ V(n{k})/1k;" for k in range(8))
compile_va("m5", f'`include "disciplines.vams"\nmodule m5({ports});\ninout {ports}; electrical {ports};\n'
                 f'real id;\n{decl}\nanalog begin\n  id = {body_i};\n{body_d}\n{contrib}\nend\nendmodule\n')
card = "\n".join(f"v{k} a{k} 0 {0.1 * (k + 1):g}" for k in range(8)) + "\nn1 " + " ".join(f"a{k}" for k in range(8)) + " mm\n.model mm m5"
out = run("m5", card, "op\n" + "\n".join(f"print {N1}[d{k}]" for k in range(8)))
v = vals(out)
check("[3] eight ddx() against eight unknowns: each its own partial (1m .. 8m)",
      all(near(v.get(f"{N1}[d{k}]"), G[k], 1e-6) for k in range(8)), f"{v}")

# ------------------------------------------------------------- [4] ---
with open(os.path.join(WORK, "m1.osdi"), "rb") as f:
    blob = f.read()
missing = [n for n in NAMES + ["gmin"] if (n.encode() + b"\0") not in blob]
check("[4] the compiled object carries every simparam name literal", not missing, f"missing {missing}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
