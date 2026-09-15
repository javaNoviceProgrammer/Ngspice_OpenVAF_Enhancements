#!/usr/bin/env python3
"""Enhancement-641: macro text survives the paramset fold's re-rendering.

The E-563 fold (a paramset's `module.localparam` references) re-renders the
expanded token stream as a virtual file and re-parses it. Three things the
preprocessor did to macro text broke that rendering, and every paramset over
r3_cmc or PSP103 with an out-of-module reference died on them:
  [1]  a `//` comment at the end of a `define body was kept as macro text
       (IEEE 1364-2005 19.3.1 says it is not) and, laid out inline, commented
       out the rest of the line: `tk = 273.15 // 0C in K+ 27.0;`
  [2]  the white space after an argument reference in a body, and after a
       macro call, was dropped: `begin : blkAreal t;`, `endI(p,n)`
  [3]  the line break after an `include directive was dropped, so a file
       ending without a newline ran into the next line: `endEPSOX = ...`
The model here has all three; the two paramsets read `consts.rsh` and
`consts.scale`, so the fold re-renders the whole file.
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
WORK = tempfile.mkdtemp(prefix="macrofold_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* macrofold {tag}\n{deck}\n.control\nset noinit\npre_osdi macrofold.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def value(out, name):
    m = re.search(rf"^{re.escape(name)} = (\S+)", out, re.M)
    return float(m.group(1)) if m else None


print("Enhancement-641: macro text survives the paramset fold's re-rendering\n")

# ---------------------------------------------------------------- 1 ---
r = subprocess.run([VAF, os.path.join(HERE, "macrofold.va"), "-o", os.path.join(WORK, "macrofold.osdi")],
                   capture_output=True, text=True)
msg = r.stdout + r.stderr
check("[1] a paramset with out-of-module references over a macro-built module compiles",
      r.returncode == 0 and "error" not in msg, msg.strip().splitlines()[-1][:120] if msg.strip() else "")

# ---------------------------------------------------------------- 2 ---
# rs: r = rsh / w * 1e-6 = 7 ohm; rs2: twice that. tk/(`K + 27) is exactly 1,
# the `else` of the included file lands on `g = g * 1.0`, both `twice blocks
# add 0 -- so the current is exactly V / r.
out = run(".model r1 rs\n.model r2 rs2\nv1 1 0 1\nn1 1 0 r1\nn2 1 0 r2", "set numdgt=12\nop\nprint i(v1) v(1)\nquit", "op")
i1 = value(out, "i(v1)")
check("[2] r = consts.rsh / w * 1e-6 folds to 7 ohm and consts.rsh * consts.scale to 14: I = 1/7 + 1/14 A",
      i1 is not None and abs(-i1 - (1 / 7 + 1 / 14)) < 1e-9, f"i(v1)={i1}")

# ---------------------------------------------------------------- 3 ---
r = subprocess.run([VAF, "--print-expansion", os.path.join(HERE, "macrofold.va")], capture_output=True, text=True)
exp = r.stdout + r.stderr
# the expansion printer separates tokens with spaces; the module's text starts
# at its header (the file's own comments come before it)
body = exp[exp.index("res_va"):] if "res_va" in exp else exp
lines = [l.strip() for l in body.splitlines()]
check("[3] the expansion keeps the separators: `blkA` then `real` on the next line, `else` then `g = g * 1.0` on the next, `end` then `I(p,n)`",
      any(l.startswith("begin") and l.endswith("blkA  \\") for l in lines)
      and any(l.endswith("else") for l in lines) and any(l.startswith("g   =   g   *   1.0") for l in lines)
      and any(l.startswith("I ( p , n )") for l in lines) and "blkAreal" not in body and "elseg" not in body
      and "endI" not in body,
      "blkAreal" if "blkAreal" in body else ("elseg" if "elseg" in body else ("endI" if "endI" in body else "ok")))

# ---------------------------------------------------------------- 4 ---
check("[4] the body's trailing `//` comment is not macro text (19.3.1): `tk = 273.15 + 27.0 ;` with no `0C in K` after the use",
      any(l.startswith("tk   =   273.15") and "+   27.0" in l and "0C in K" not in l for l in lines),
      next((l for l in lines if l.startswith("tk")), "no tk line"))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
