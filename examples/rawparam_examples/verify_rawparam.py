#!/usr/bin/env python3
"""Enhancement-607: a `@dev[param]` vector keeps its own name in a raw file,
and loads back addressable.

N4 of the 2026-09-10 integration hunt. The raw-file writers spell a node
voltage `v(x)` and a branch current `i(x)` (with `#branch` stripped), and a
loaded file's `v(out)` and `i(v1)` resolve again. But `@r1[i]` is
current-typed, so it was written `i(`@r1[i]`)` -- a name nothing reads back:
after `load`, `@r1[i]` asks the (absent) device and `i(`@r1[i]`)` is the
parser's i() of a name that is not a source. Every OSDI terminal current
`.option savecurrents` records (`@n1[i_p]`) was affected, in `write` and in
batch `-r` alike. A `@` name is a device parameter, never a node or a branch:
both writers keep it, and the reader puts an old file's `i(@...)`/`v(@...)`
back, so files an earlier writer produced load addressable too.

Checks (built-in resistors, then an OSDI device):
  [1] write, then load in a session with no circuit: `@r1[i]`, `@r1[p]`, `@r2[i]`
      print their values; v(out) and i(v1) still do
  [2] batch -r with .option savecurrents: the file names `@r1[i]`, `@r2[i]`
      verbatim; a fresh session loads and prints them
  [3] an old-format file (i(`@r1[i]`) written by hand): loads as `@r1[i]`
  [4] an OSDI device's `@n1[i_p]` under savecurrents, round-tripped
  [5] stays: a node voltage and a branch current keep v()/i() in the file
"""
import os
import re
import subprocess
import sys
import tempfile

A = "@"     # the accessor prefix, spelled apart so no line reads as a GitHub mention

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="rawparam_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "rr.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule rr(p, n);\ninout p, n; electrical p, n;\n'
            'parameter real r = 1k from (0:inf);\nanalog I(p,n) <+ V(p,n)/r;\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "rr.va"), "-o", os.path.join(WORK, "rr.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(body, tag, args=()):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* rawparam {tag}\n{body}\n.end\n")
    p = subprocess.run([NGSPICE, "-b", *args, path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def names(rawfile):
    """the variable names of a raw file (ascii or binary header)"""
    with open(os.path.join(WORK, rawfile), "rb") as f:
        txt = f.read().decode("latin-1")
    return re.findall(r"^\t\d+\t(\S+)\t", txt, re.M)


def val(out, name):
    m = re.findall(rf"^{re.escape(name)} = ([-+.\deE]+)", out, re.M)
    return [float(x) for x in m]


DIV = "v1 in 0 dc 1\nr1 in out 1k\nr2 out 0 1k\n"
print(f"Enhancement-607: {A}dev[param] vectors in raw files\n")

# ------------------------------------------------------------- [1] ---
out = run(DIV + f".control\nsave all {A}r1[i] {A}r1[p] {A}r2[i]\nop\nwrite t1.raw\nremcirc\nload t1.raw\n"
          f"print {A}r1[i] {A}r1[p] {A}r2[i] v(out) i(v1)\n.endc", "t1")
check(f"[1] write, remcirc, load: {A}r1[i], {A}r1[p], {A}r2[i] read back (were i({A}r1[i]), unreachable)",
      val(out, f"{A}r1[i]") == [0.0005] and val(out, f"{A}r1[p]") == [0.00025] and val(out, f"{A}r2[i]") == [0.0005]
      and "no such device" not in out and "not available" not in out, out[-400:])
check("[1] ...the node and the branch current still read back",
      val(out, "v(out)") == [0.5] and val(out, "i(v1)") == [-0.0005], out[-300:])
check("[1] ...the file names them verbatim",
      {f"{A}r1[i]", f"{A}r1[p]", f"{A}r2[i]"} <= set(names("t1.raw")) and f"i({A}r1[i])" not in names("t1.raw"),
      str(names("t1.raw")))

# ------------------------------------------------------------- [2] ---
run(DIV + ".option savecurrents\n.op", "t2", args=("-r", "t2.raw"))
out = run(f".control\nload t2.raw\nprint {A}r1[i] {A}r2[i] v(out)\n.endc", "t2b")
check(f"[2] batch -r with savecurrents: {A}r1[i], {A}r2[i] verbatim in the file; a fresh session prints them",
      {f"{A}r1[i]", f"{A}r2[i]"} <= set(names("t2.raw")) and val(out, f"{A}r1[i]") == [0.0005]
      and val(out, f"{A}r2[i]") == [0.0005] and val(out, "v(out)") == [0.5], out[-300:])

# ------------------------------------------------------------- [3] ---
with open(os.path.join(WORK, "old.raw"), "w") as f:
    f.write("Title: old\nDate: today\nPlotname: Operating Point\nFlags: real\nNo. Variables: 3\nNo. Points: 1\n"
            f"Variables:\n\t0\tv(in)\tvoltage\n\t1\ti({A}r1[i])\tcurrent\n\t2\tv({A}r1[v])\tvoltage\nValues:\n"
            "0\t1.0\n\t0.0005\n\t0.5\n")
out = run(f".control\nload old.raw\ndisplay\nprint {A}r1[i] {A}r1[v]\n.endc", "t3")
check(f"[3] an old file's i({A}r1[i]) and v({A}r1[v]) load as {A}r1[i] and {A}r1[v]",
      val(out, f"{A}r1[i]") == [0.0005] and val(out, f"{A}r1[v]") == [0.5] and f"i({A}r1[i])" not in out, out[-300:])

# ------------------------------------------------------------- [4] ---
run(".control\npre_osdi rr.osdi\n.endc\nv1 in 0 dc 1\nn1 in out om\nr2 out 0 1k\n.model om rr r=1k\n"
    ".option savecurrents\n.op", "t4", args=("-r", "t4.raw"))
out = run(f".control\nload t4.raw\nprint {A}n1[i_p] {A}n1[i_n]\n.endc", "t4b")
check(f"[4] an OSDI device's {A}n1[i_p]/{A}n1[i_n] under savecurrents: verbatim, and read back",
      {f"{A}n1[i_p]", f"{A}n1[i_n]"} <= set(names("t4.raw")) and val(out, f"{A}n1[i_p]") == [0.0005]
      and val(out, f"{A}n1[i_n]") == [-0.0005], f"{names('t4.raw')} {out[-300:]}")

# ------------------------------------------------------------- [5] ---
check("[5] stays: the node voltage and the branch current keep their v()/i() spelling",
      "v(out)" in names("t1.raw") and "i(v1)" in names("t1.raw"), str(names("t1.raw")))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
