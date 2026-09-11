#!/usr/bin/env python3
"""Enhancement-606: `showmod` finds a subcircuit's model by its hierarchical
name, dotted or with its colons, as `altermod` does.

N1 of the 2026-09-10 integration hunt. Subcircuit expansion renames a model
card inside `x1` to `x1:rm` (nested: `x1.x2:rm`). `altermod x1.rm r=3k` and
`altermod x1:rm ...` both reach it, and `showmod x1.r1` shows it through the
instance -- but `showmod x1.rm` and `showmod x1:rm` answered "No matching
instances or models". The device generator's grammar could express neither:
`#x1.rm` was compared whole against `x1:rm`, and in `#x1:rm` the ':' is the
subcircuit delimiter, leaving a device named `rm` in subcircuit `#x1`. As
E-410 did for instances, a whole-word match is consulted alongside that
grammar: the query, with or without the model marker `#`, equal to the
model's name with '.' standing for ':'.

Checks (built-in resistor and capacitor models, then OSDI):
  [1] showmod x1.rm and showmod x1:rm: the model, its r
  [2] nested: x1.x2.rm, x1:x2:rm, and the mixed x1.x2:rm spelling
  [3] showmod x1.rm : r (one parameter)
  [4] after altermod x1.rm r=3k, showmod shows 3000
  [5] stays: show x1.rm (an instance query) finds nothing; showmod rm
      (top-level only) finds nothing; showmod x1.r1 still shows the model
  [6] an OSDI model inside a subcircuit
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
WORK = tempfile.mkdtemp(prefix="showmodhier_")


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

CKT = (".subckt inner a b\nr1 a b rm\n.model rm r r=2k\n.ends\n"
       ".subckt outer a b\nx2 a b inner\nc1 a b cm\n.model cm c c=1p\n.ends\n"
       "v1 in 0 dc 1\nx1 in out outer\nr2 out 0 1k\n")


def run(ctl, tag, ckt=CKT, pre=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* showmodhier {tag}\n{pre}{ckt}.control\nop\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def section(out, tag):
    """the text between `echo --- tag` and the next `echo ---`"""
    m = re.search(rf"^--- {re.escape(tag)}\n(.*?)(?=^--- |\Z)", out, re.S | re.M)
    return m.group(1) if m else ""


NONE = "No matching instances or models"
print("Enhancement-606: showmod by hierarchical model name\n")

# ------------------------------------------------------------- [1] ---
out = run("echo --- a\nshowmod x1.x2.rm\necho --- b\nshowmod x1:x2:rm\necho --- c\nshowmod x1.x2:rm\necho --- end", "t1")
for tag, q in (("a", "x1.x2.rm"), ("b", "x1:x2:rm"), ("c", "x1.x2:rm")):
    sec = section(out, tag)
    check(f"[1/2] showmod {q}: the model x1.x2:rm with r = 2000",
          NONE not in sec and "x1.x2:rm" in sec and re.search(r"^\s+r\s+2000\s*$", sec, re.M), sec[:200])

# ------------------------------------------------------------- [2] ---
out = run("echo --- a\nshowmod x1.cm\necho --- b\nshowmod x1:cm\necho --- end", "t2")
check("[2] one level: showmod x1.cm and x1:cm show the capacitor model x1:cm",
      all(NONE not in section(out, t) and "x1:cm" in section(out, t) for t in "ab"), out[-300:])

# ------------------------------------------------------------- [3] ---
out = run("echo --- a\nshowmod x1.x2.rm : r\necho --- end", "t3")
sec = section(out, "a")
check("[3] showmod x1.x2.rm : r -- the one parameter",
      "x1.x2:rm" in sec and re.search(r"^\s+r\s+2000\s*$", sec, re.M) and "rsh" not in sec, sec[:200])

# ------------------------------------------------------------- [4] ---
out = run("altermod x1.x2.rm r=3k\necho --- a\nshowmod x1:x2:rm : r\necho --- b\nop\nprint v(out)\necho --- end", "t4")
sec = section(out, "a")
check("[4] after altermod x1.x2.rm r=3k: showmod shows 3000 and v(out) follows (0.25)",
      re.search(r"^\s+r\s+3000\s*$", sec, re.M) and "v(out) = 2.500000e-01" in out, out[-300:])

# ------------------------------------------------------------- [5] ---
out = run("echo --- a\nshow x1.x2.rm\necho --- b\nshowmod rm\necho --- c\nshowmod x1.x2.r1\necho --- end", "t5")
check("[5] stays: show x1.x2.rm (an instance query) and showmod rm (top level) find nothing; showmod x1.x2.r1 shows the model",
      NONE in section(out, "a") and NONE in section(out, "b")
      and "x1.x2:rm" in section(out, "c") and NONE not in section(out, "c"), out[-400:])

# ------------------------------------------------------------- [6] ---
OCKT = ".subckt sub a b\nn1 a b om\n.model om rr r=2k\n.ends\nv1 in 0 dc 1\nx1 in out sub\nr2 out 0 1k\n"
out = run("echo --- a\nshowmod x1.om\necho --- b\nshowmod x1:om : r\necho --- end", "t6", ckt=OCKT,
          pre=".control\npre_osdi rr.osdi\n.endc\n")
check("[6] an OSDI model inside a subcircuit: showmod x1.om and x1:om : r",
      all(NONE not in section(out, t) and "x1:om" in section(out, t) for t in "ab")
      and re.search(r"^\s+r\s+2000\s*$", section(out, "b"), re.M), out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
