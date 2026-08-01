#!/usr/bin/env python3
"""Enhancement-391: repeated abscissae in a RUNTIME `$table_model`, cubic case.

Enhancement-390 made the runtime array form of `$table_model` agree with the
compile-time forms -- it sorts, de-duplicates and honours the cubic control code.
One case was left open and documented: **a repeated abscissa with cubic
interpolation**.

WHY IT RESISTED THE OBVIOUS FIX. The compile-time forms de-duplicate by
SHORTENING the point vector (`pts.dedup_by`), so the spline is solved over `m`
distinct knots. E-390's runtime de-duplication instead carried the first value
forward over each repeat, which is exactly equivalent for LINEAR interpolation --
a zero-width segment whose endpoints are equal contributes nothing -- but not for
a spline, where the dead knot still occupies a row of the tridiagonal system and
perturbs every moment in it.

A runtime array cannot shrink. So the repeats are instead partitioned to the END
(a stable 0/1 bubble network on an "is a repeat" flag that travels with its
point), the trailing slots take the last distinct knot, and two things follow the
live prefix rather than the array:

  * the NATURAL BOUNDARY CONDITION `M = 0` is forced onto the last LIVE knot and
    every replica after it, not merely onto the final slot;
  * the upper END TANGENT is computed from the last two LIVE knots. This one is
    easy to get wrong and hard to see: after compaction the last two slots are
    both replicas, so their spacing is zero, and the guarded division silently
    turned the extrapolation into a CLAMP -- correct everywhere inside the grid
    and wrong only past its end.

The live prefix is then exactly the de-duplicated table, and the two forms agree
on every input below, including three repeats of one abscissa and a table whose
abscissae are all equal.

WHAT THE ACCEPT HALF IS GUARDING. Compaction runs on every runtime cubic table,
including the ordinary ones with no repeats at all, so the strictly-increasing
cases matter as much as the degenerate ones -- as does linear, which shares the
sort and must not have moved.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n'
PROBES = ("-1.0", "-0.5", "0.5", "1.5", "2.5", "3.5", "4.5")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_td_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode


def sim(d, vdc):
    open(os.path.join(d, "q.cir"), "w").write(
        "q\n.control\npre_osdi m.osdi\n.endc\n"
        f"V1 a 0 dc {vdc}\nN1 a 0 mymod\n.model mymod dut()\n"
        ".control\noption noacct\nset numdgt=15\nop\nprint i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 25; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    if r.returncode not in (0, 1):
        return None
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    return None if m is None else -float(m.group(1)) / 1e-3


def runtime_src(data, ctrl):
    n = len(data)
    body = "".join(f"  xs[{i}]={x}; ys[{i}]={y};\n" for i, (x, y) in enumerate(data))
    return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
            f" real xs[0:{n-1}]; real ys[0:{n-1}];\n analog begin\n" + body +
            f'  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, ys, "{ctrl}");\n end\nendmodule\n')


def literal_src(data, ctrl):
    lit = ", ".join(f"{x},{y}" for x, y in data)
    return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
            f" analog I(p,n) <+ 1e-3*$table_model(V(p,n), '{{{lit}}}, \"{ctrl}\");\nendmodule\n")


def curve(src, tag):
    d, rc = build(src, tag)
    if rc != 0:
        return None
    return [sim(d, v) for v in PROBES]


def agree(label, data, ctrl):
    a = curve(runtime_src(data, ctrl), "r" + re.sub(r"\W", "", label)[:14])
    b = curve(literal_src(data, ctrl), "l" + re.sub(r"\W", "", label)[:14])
    ok = a is not None and b is not None and len(a) == len(b)
    if ok:
        for u, v in zip(a, b):
            # a relative tolerance, not bit equality: the runtime path DIVIDES
            # where the compile-time path folds the same coefficient to a
            # constant, so the cubic can land a ULP or two apart.
            if u is None or v is None or abs(u - v) > 1e-9 * max(abs(u), abs(v), 1e-30):
                ok = False
                break
    check("runtime == compile-time: %s" % label, ok, "rt=%s ct=%s" % (a, b))


ASC = [(0.0, 0.0), (1.0, 1.0), (2.0, 4.0), (3.0, 9.0)]


def main():
    # ---- repeated abscissae, cubic: the case E-390 left open ----------------
    agree("repeat in the middle", [(0., 0.), (1., 1.), (1., 5.), (2., 4.)], "3L")
    agree("repeat at the start", [(0., 0.), (0., 7.), (1., 1.), (2., 4.)], "3L")
    agree("repeat at the end", [(0., 0.), (1., 1.), (2., 4.), (2., 9.)], "3L")
    agree("two separate repeats",
          [(0., 0.), (1., 1.), (1., 5.), (2., 4.), (2., 8.), (3., 9.)], "3L")
    agree("one abscissa three times",
          [(0., 0.), (1., 1.), (1., 5.), (1., 6.), (2., 4.), (3., 9.)], "3L")
    agree("repeat, clamped (no L)", [(0., 0.), (1., 1.), (1., 5.), (2., 4.)], "3")
    agree("unsorted AND repeated",
          [(2., 4.), (0., 0.), (1., 1.), (1., 9.), (3., 9.)], "3L")
    agree("every abscissa equal", [(1., 1.), (1., 2.), (1., 3.)], "3L")
    agree("only two distinct left", [(0., 0.), (1., 1.), (1., 5.), (1., 6.)], "3L")

    # ======================= ACCEPT HALF ====================================
    # Compaction runs on EVERY runtime cubic table, so the ordinary strictly
    # increasing ones matter as much as the degenerate ones.
    agree("ascending, cubic", ASC, "3L")
    agree("ascending, cubic clamped", ASC, "3")
    agree("descending, cubic", list(reversed(ASC)), "3L")
    agree("five knots, cubic", ASC + [(4.0, 16.0)], "3L")
    agree("six knots, cubic", ASC + [(4.0, 16.0), (5.0, 25.0)], "3L")
    agree("three knots, cubic", ASC[:3], "3L")
    # linear shares the sort and must not have moved
    agree("ascending, linear", ASC, "1L")
    agree("descending, linear", list(reversed(ASC)), "1L")
    agree("repeat, linear", [(0., 0.), (1., 1.), (1., 5.), (2., 4.)], "1L")
    agree("every abscissa equal, linear", [(1., 1.), (1., 2.), (1., 3.)], "1L")

    # a table the body never fills in is all zeros -- every abscissa repeats.
    # It must still produce a finite result rather than a NaN that surfaces as
    # "Timestep too small".
    src = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
           " real xs[0:3]; real ys[0:3];\n analog begin\n"
           "  ys[0]=0.0; ys[1]=1.0; ys[2]=4.0; ys[3]=9.0;\n"
           '  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, ys, "3L");\n end\nendmodule\n')
    d, rc = build(src, "unset")
    check("an unfilled runtime table stays finite under cubic",
          rc == 0 and sim(d, "0.5") is not None)

    for j in os.listdir(HERE):
        if j.startswith("_td_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
