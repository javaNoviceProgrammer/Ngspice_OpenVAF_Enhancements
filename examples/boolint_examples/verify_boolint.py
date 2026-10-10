#!/usr/bin/env python3
"""verify_boolint.py -- Enhancement-845: a relational or logical result meeting an
integer is the integer 1 or 0, not a Bool the integer is cast to.

F1 of the second robustness campaign of 2026-10-10. openvaf-r types `a < b`,
`a && b`, `!a` and `$param_given(p)` as Bool. Integer and Bool are semantically
equivalent to its overload resolution, so where both met:
  - `c ? n : (a < b)` and `n == (a < b)` kept a Bool and an Integer signature,
    neither exact, and took the first in the table -- Bool. The integer was cast
    to 0 or 1: for n = 5 the ternary gave 1 and `n == (n > 0)` was true;
  - `case (n > 0) 5:` cast the item 5 to Bool and matched.
The value was silently wrong, folded or at run time alike. The overload
resolution now prefers a signature that does not narrow an integer to Bool, and
a Bool case expression with an integer item is compared as an integer.

  [1] the ternary: an integer and a logical branch, either order (and controls)
  [2] == and != against a logical result, $param_given among them
  [3] case with a comparison as its expression (and the case (1) idiom)
  [4] into an integer variable
  [5] at run time, from a node voltage
  [6] boolparam.va: a parameter without a type whose default is a comparison,
      a logical operator or $param_given is an integer (element-wise for an
      array); it was typed Bool, and the parameter lowering panicked on it

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="boolint_")
checks = passed = 0

EXPECT = [
    ("[1]", "t1", 5.0, "(n > 0) ? n : (n < 0)"),
    ("[1]", "t2", 5.0, "(n < 0) ? (n > 0) : n -- the logical branch first"),
    ("[1]", "t3", 2.5, "(n > 0) ? 2.5 : (n < 0) (control: a real branch)"),
    ("[1]", "t4", 1.0, "(n > 0) ? (n > 1) : (n > 9) (control: both logical)"),
    ("[1]", "t5", 1.0, "(n > 0) ? (n && 7) : 300 -- the logical result is 1"),
    ("[2]", "e1", 0.0, "n == (n > 0): 5 == 1"),
    ("[2]", "e2", 1.0, "n != (n > 0)"),
    ("[2]", "e3", 1.0, "(n > 0) == 1 (control)"),
    ("[2]", "e4", 1.0, "(m || n) != (10 | -7): 1 != -5"),
    ("[2]", "g1", 0.0, "$param_given(n) == 2: 1 == 2"),
    ("[2]", "g2", 1.0, "$param_given(n) == 1 (control)"),
    ("[3]", "c1", 2.0, "case (n > 0) 5: -- 1 != 5, so the default"),
    ("[3]", "c2", 1.0, "case (n > 0) 1: (control)"),
    ("[3]", "c3", 2.0, "case (1) (n > 0): (control: the priority idiom)"),
    ("[4]", "k1", 5.0, "k = (n > 0) ? n : (n < 0)"),
    ("[5]", "v1", 5.0, "(V(x) > 0) ? n : (V(x) < 0)"),
    ("[5]", "v2", 0.0, "n == (V(x) > 0)"),
    ("[5]", "v3", 5.0, "a nested ternary with a logical else, times V(x) = 1"),
]


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


PEXPECT = [
    ("p1", 5.0, "parameter pt = (n > 0) ? n : (n < 0)"),
    ("p2", 1.5, "parameter pb = (n > 0): pb + 0.5"),
    ("p3", 0.0, "pb/2 is integer division, so pb is an integer"),
    ("p4", 1.0, "parameter pc = (n > 0) && (n < 9)"),
    ("p5", 0.0, "parameter pd = !n"),
    ("p6", 1.0, "parameter pg = $param_given(n)"),
    ("p7", 1.0, "localparam pl = (n > 0)"),
    ("p8", 1.0, "parameter pa[0:1] = '{(n > 0), (n < 0)}: pa[0] + 2*pa[1]"),
]


def compile_and_run(stem, ports, card, extra=""):
    osdi = os.path.join(WORK, stem + ".osdi")
    cp = subprocess.run([OPENVAF, os.path.join(HERE, stem + ".va"), "-o", osdi], cwd=WORK,
                        capture_output=True, text=True, env=dict(os.environ, RAYON_NUM_THREADS="1"))
    msg = "exit %d %s" % (cp.returncode, "(compiler panic)" if cp.returncode == 101 else
                          (cp.stdout + cp.stderr).strip()[-120:])
    check("%s.va compiles" % stem, cp.returncode == 0, "" if cp.returncode == 0 else msg)
    if cp.returncode != 0:
        return {}
    deck = os.path.join(WORK, stem + ".cir")
    with open(deck, "w") as f:
        f.write("* %s\n.control\npre_osdi %s\n.endc\n%s" % (stem, osdi, extra)
                + "n1 %s mm\n.model mm %s %s\n" % (" ".join(ports), stem, card)
                + ".control\nop\n"
                + "".join("print v(%s)\n" % o for o in ports if o != "x") + ".endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", deck], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    return {k: float(v) for k, v in re.findall(r"^v\((\w+)\) = (\S+)", p.stdout + p.stderr, re.M)}


vals = compile_and_run("boolint", ["x"] + [o for _, o, _, _ in EXPECT], "n=5", "vx x 0 1\n")
if vals:
    for sec, o, want, text in EXPECT:
        got = vals.get(o)
        check("%s %s = %g" % (sec, text, want), got is not None and abs(got - want) < 1e-12, "got %s" % got)

pports = [o for o, _, _ in PEXPECT]
vals = compile_and_run("boolparam", pports, "n=5")
if vals:
    for o, want, text in PEXPECT:
        got = vals.get(o)
        check("[6] %s = %g" % (text, want), got is not None and abs(got - want) < 1e-12, "got %s" % got)
    vals = compile_and_run("boolparam", pports, "n=5 pb=7")
    got = vals.get("p2")
    check("[6] pb=7 on the model card: pb + 0.5 = 7.5 (the integer parameter takes any integer)",
          got is not None and abs(got - 7.5) < 1e-12, "got %s" % got)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
