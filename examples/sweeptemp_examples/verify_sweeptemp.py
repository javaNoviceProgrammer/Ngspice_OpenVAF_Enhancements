#!/usr/bin/env python3
"""Enhancement-488: `sweep temp` sweeps the global circuit temperature.

`sweep` resolves a knob as a model parameter, an instance/device parameter, or a
deck `.param`. The GLOBAL circuit temperature is none of those, so a bare `temp`
fell through to the instance/device branch, `alter temp=...` found no such device,
and the sweep ran to completion over a knob that never moved -- a full set of
points, rc = 0, and a perfectly plottable FLAT curve.

That is the exact shape this command has already had removed twice:
Enhancement-431 deleted an unresolved `-output` drawn as a zero column, and
Enhancement-435's comment in com_sweep.c describes the same failure for
subcircuit-local model names ("the sweep runs on with a knob that never moved").
`temp` was a third instance, and the one users are most likely to hit, because
sweeping temperature is an ordinary thing to want and EVERY other route already
worked: `.option temp=`, `set temp=`, `alter @dev[temp]=`, `sweep @#*[temp]`.

THE ORACLE IS `dc temp`, which has swept the global temperature all along. The
values here are asserted against it directly rather than against a table of
constants, so this suite tracks ngspice's own answer.

WHY THE FIRST ATTEMPT FAILED, and what the fix therefore had to be. Writing
ckt->CKTtemp directly -- what `.dc temp` does -- left the curve flat. CKTdoJob
opens with

    ckt->CKTtemp = task->TSKtemp;                          (cktdojob.c)

`.dc` gets away with it because its whole sweep runs INSIDE one CKTdoJob;
`sweep` runs a fresh analysis command per point, so the write was discarded
before the next point was solved. The TASK is what has to move, so the knob is
applied with `option temp=`, which is how the frontend already moves it. That
also means the value passes the guarded OPT_TEMP funnel in cktsopt.c instead of
going around it, and inherits Enhancement-426's absolute-zero refusal and
Enhancement-440's sanity check rather than carrying a second copy of them.

WHERE IT DELIBERATELY DOES NOT MATCH `dc temp`. Over a node collapse that MOVES
with temperature, `dc temp` is wrong: it holds one setup for the whole sweep and
never rebuilds, so it returns 0.0 where the answer is 0.5 (round-24's finding,
still live). `sweep` runs a fresh analysis per point and Enhancement-471's logic
rebuilds when the collapse moves, so it is right. Checks [10]-[12] pin all three
against a STATIC op at each temperature, which is the ground truth neither
command is allowed to disagree with.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0

# R1 carries a temperature coefficient and R2 does not, so the divider MUST move
# if and only if the temperature actually reaches the devices.
TC = ("V1 in 0 dc 1\nR1 in a rmod l=1u w=1u\nR2 a 0 1k\n"
      ".model rmod r(rsh=1k tc1=0.01)\n")
# cs_gate collapses d onto di when $temperature > tsw, so the TOPOLOGY moves
# partway through a temperature sweep.
TS = ("V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n"
      ".model cgm cs_gate rd=1k tsw=310 hot=1\n")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, ctl, tag, osdi=None, timeout=180):
    path = os.path.join(HERE, f"_st_{tag}.cir")
    pre = f"pre_osdi {osdi}\n" if osdi else ""
    with open(path, "w") as f:
        f.write(f"* sweeptemp {tag}\n{deck}\n.control\n{pre}option noacct\n"
                f"set numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", "-r", os.devnull, os.path.basename(path)],
                           capture_output=True, text=True, timeout=timeout,
                           cwd=HERE, stdin=subprocess.DEVNULL)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    try:
        os.remove(path)
    except OSError:
        pass
    return out


def rows(out):
    r = []
    for line in out.splitlines():
        m = re.match(r"^\s*\d+\s+((?:[-+0-9.eE]+\s*)+)$", line)
        if m:
            try:
                r.append(tuple(float(x) for x in m.group(1).split()))
            except ValueError:
                pass
    return r


def col(out, k=-1, nd=9):
    return [round(r[k], nd) for r in rows(out)]


def val(out, name):
    m = re.findall(r"(?m)^\s*" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


r = subprocess.run([OPENVAF, "cs_gate.va", "-o", "cs_gate.osdi"], cwd=HERE,
                   capture_output=True, text=True)
check("[0] the collapse model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "cs_gate.osdi")))

# ------------------------------------------------------------ against the oracle
print("\n`sweep temp` against `dc temp`, which has swept the global temperature all along")

dc = col(run(TC, "dc temp 0 80 20\nprint v(a)", "dc"))
check("[1] the oracle itself moves -- a temperature sweep that changes nothing "
      "would make every check below vacuous",
      len(dc) == 5 and len(set(dc)) == 5, f"{dc}")

sw = col(run(TC, "sweep temp lin 5 0 80 -output v(a)\nprint all", "sw"))
check("[2] `sweep temp` produces the SAME numbers as `dc temp`", sw == dc, f"{sw}")

out = run(TC, "sweep temp lin 5 0 80 -output v(a)", "kind")
m = re.search(r"sweep: temp \(([^)]*)\)", out)
check("[3] ...and is reported as the global temperature, not as a device knob",
      m is not None and m.group(1) == "global temperature",
      m.group(1) if m else "no banner")
check("[4] ...with no 'original value could not be read' warning",
      "could not be read" not in out and "not available" not in out, "silent")

sw0 = col(run(TC, "set reusesetup=0\nsweep temp lin 5 0 80 -output v(a)\nprint all", "sw0"))
check("[5] identical with the Enhancement-471 setup reuse turned off", sw0 == dc, f"{sw0}")

# ------------------------------------------------------------------- the restore
print("\nthe nominal temperature is put back")

for tag, deck, want in (("default", TC, "27 C"), ("deckopt", TC + ".option temp=40\n", "40 C")):
    out = run(deck, "op\nlet v0=v(a)\nprint v0\n"
                    "sweep temp lin 5 0 80 -output v(a)\n"
                    "op\nlet v1=v(a)\nprint v1", "r" + tag)
    a, b = val(out, "v0"), val(out, "v1")
    check(f"[6-{tag}] an `op` after the sweep is unchanged (nominal {want})",
          a is not None and a == b, f"{a} -> {b}")

# --------------------------------------------------------------- absolute zero
print("\nan unphysical range is refused, as `dc temp` refuses it")

out = run(TC, "sweep temp lin 3 -600 100 -output v(a)\nprint all", "az")
check("[7] a range reaching below absolute zero sweeps NOTHING",
      len(rows(out)) == 0, f"{len(rows(out))} rows")
check("[8] ...and says why",
      "absolute zero" in out.lower(), "named")
out = run(TC, "sweep temp lin 3 -25 100 -output v(a)\nprint all", "cold")
check("[9] ...while -25 C is ordinary and still sweeps",
      len(rows(out)) == 3, f"{len(rows(out))} rows")

# ------------------------------------------------- the moving node collapse
print("\na node collapse that MOVES with temperature -- ground truth is a static op")

truth = []
for t in (0, 20, 40, 60, 80):
    o = run(TS + f".option temp={t}\n", "op\nprint v(out)", f"gt{t}", osdi="cs_gate.osdi")
    truth.append(round(val(o, "v(out)"), 6))
check("[10] the ground truth itself shows the collapse moving",
      truth == [0.333333, 0.333333, 0.5, 0.5, 0.5], f"{truth}")

swc = col(run(TS, "sweep temp lin 5 0 80 -output v(out)\nprint all", "swc",
              osdi="cs_gate.osdi"), nd=6)
check("[11] `sweep temp` tracks the collapse and matches the static answer",
      swc == truth, f"{swc}")

dcc = col(run(TS, "dc temp 0 80 20\nprint v(out)", "dcc", osdi="cs_gate.osdi"), nd=6)
check("[12] ...which `dc temp` does NOT -- it holds one setup for the whole sweep "
      "and never rebuilds (round-24, still open; do not 'fix' [11] to match it)",
      dcc != truth, f"dc temp gives {dcc}")

out = run(TS, "set ngdebug\nsweep temp lin 5 0 80 -output v(out)", "reuse",
          osdi="cs_gate.osdi")
m = re.search(r"setup reused at (\d+) of (\d+) points, (\d+) rebuilt", out)
check("[13] ...because the reuse rebuilds exactly where the collapse moves",
      m is not None and int(m.group(3)) == 1, m.group(0) if m else "no report")

# ------------------------------------------------------ strictly additive
print("\na deck `.param temp` still wins -- this change adds a fallback, it does not steal a name")

P = "V1 in 0 dc 1\n.param temp=27\nR1 in a {temp*40}\nR2 a 0 1k\n"
out = run(P, "sweep temp lin 3 10 30 -output v(a)\nprint all", "pp")
m = re.search(r"sweep: temp \(([^)]*)\)", out)
pv = col(out)
check("[14] a deck that defines its own `temp` parameter still sweeps THAT",
      m is not None and m.group(1) == ".param", m.group(1) if m else "?")
check("[15] ...and its curve moves, so the parameter really is the one driving it",
      len(pv) == 3 and len(set(pv)) == 3, f"{pv}")

# --------------------------------------------------------- shape and plumbing
print("\nthe knob behaves like every other sweep knob")

out = run(TC, "sweep temp lin 3 0 80 -output v(a)\ndisplay", "ty")
m = re.search(r"^\s{4}temp\s*:\s*([a-z-]+)", out, re.M)
check("[16] the axis carries the temperature type, as `dc temp`'s does",
      m is not None and m.group(1) == "temp-sweep", m.group(1) if m else "missing")

a = col(run(TC, "sweep temp lin 3 0 80 -vs @R2[resistance] list 1k 2k -output v(a)\nprint all", "vi"))
b = col(run(TC, "set reusesetup=0\nsweep temp lin 3 0 80 -vs @R2[resistance] "
                "list 1k 2k -output v(a)\nprint all", "vi0"))
# a == b alone is satisfied by a FLAT curve, which is exactly what the broken
# build produced -- assert the curve actually moves as well.
check("[17] it works as the INNER knob of a two-knob sweep, reuse on and off",
      len(a) == 3 and a == b and len(set(a)) == 3, f"{a}")

a = col(run(TC, "sweep @R2[resistance] list 1k 2k -vs temp lin 3 0 80 -output v(a)\nprint all", "vo"))
b = col(run(TC, "set reusesetup=0\nsweep @R2[resistance] list 1k 2k -vs temp "
                "lin 3 0 80 -output v(a)\nprint all", "vo0"))
check("[18] ...and as the OUTER knob",
      len(a) == 2 and a == b and len(set(a)) == 2, f"{a}")

for f in os.listdir(HERE):
    if f.startswith("_st_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
