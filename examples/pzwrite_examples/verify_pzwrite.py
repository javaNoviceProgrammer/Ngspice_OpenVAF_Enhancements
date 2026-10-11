#!/usr/bin/env python3
"""verify_pzwrite.py -- Enhancement-866: a pz plot's vectors keep their names in
`write` and `print all`.

F11 of the third robustness campaign of 2026-10-10.

`write` wraps a voltage-typed vector's name in v(...) unless it is already a
node voltage; a pz plot's roots are voltage-typed, so `zero(1)` and `pole(2)`
were written v(zero(1)) and v(pole(2)), and did not load back under their own
names. `all` names a list of vectors; on a plot with one, the evaluator renamed
that one to `all`: `print all` printed `all = ...`, and `write` wrote the pole
twice, the second time as v(all).

  [1] write of a plot with a pole and a zero: pole(1) and zero(1)
  [2] write of a plot with one pole: one variable, pole(1), no v(all)
  [3] print all on that plot prints pole(1) = ... (all = ... on E-863)
  [4] the written file loads back under its own names
  [5] (control) an op plot still writes v(...) and i(...) names
  [6] (control) print all on a plot with several vectors is unchanged

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="pzwrite_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, control):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset filetype=ascii\n%s\n.endc\n.end\n" % (name, body, control))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=60,
                       errors="replace")
    return p.stdout + p.stderr


def raw_names(path):
    if not os.path.exists(path):
        return None
    txt = open(path).read()
    head = txt.split("Values:")[0].split("Variables:")[-1]
    return re.findall(r"^\s*\d+\s+(\S+)\s+\S+", head, re.M)


TWO = "r1 1 2 1k\nr2 2 0 2k\nc1 2 0 1n\nc2 1 2 1n"
ONE = "r1 1 2 1k\nr2 2 0 2k\nc1 2 0 1n"

# [1]
raw2 = os.path.join(WORK, "two.raw")
run("two", TWO, "pz 1 0 2 0 vol pz\nwrite %s" % raw2)
names = raw_names(raw2)
check("[1] write of a plot with a pole and a zero: pole(1) and zero(1)", names == ["pole(1)", "zero(1)"],
      "%r" % names)

# [2], [3]
raw1 = os.path.join(WORK, "one.raw")
out = run("one", ONE, "pz 1 0 2 0 vol pz\nwrite %s\nprint all" % raw1)
names = raw_names(raw1)
check("[2] write of a plot with one pole: one variable, pole(1)", names == ["pole(1)"], "%r" % names)
m = re.search(r"^(\S+) = (\S+)", out, re.M)
check("[3] print all on that plot prints pole(1) = ...", m is not None and m.group(1) == "pole(1)",
      m.group(0) if m else "nothing printed")

# [4]
out = run("load", ONE, "load %s\ndisplay" % raw2)
listed = re.findall(r"^\s+(\S+)\s+:\s", out, re.M)
check("[4] the written file loads back under its own names: display lists pole(1) and zero(1)",
      set(listed) == {"pole(1)", "zero(1)"}, "%r" % sorted(set(listed)))

# [5]
rawop = os.path.join(WORK, "op.raw")
run("op", "v1 1 0 1\nr1 1 2 1k\nr2 2 0 1k", "op\nwrite %s" % rawop)
names = raw_names(rawop)
check("[5] (control) an op plot still writes v(...) and i(...) names",
      names is not None and "v(1)" in names and "v(2)" in names and "i(v1)" in names, "%r" % names)

# [6]
out = run("multi", "v1 1 0 1\nr1 1 2 1k\nr2 2 0 1k", "op\nprint all")
got = sorted(re.findall(r"^(\S+) = ", out, re.M))
check("[6] (control) print all on a plot with several vectors names each", got == sorted(["v(1)", "v(2)", "v1#branch"]),
      "%r" % got)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
