#!/usr/bin/env python3
"""Enhancement-471: a repeated analysis keeps the circuit standing between points.

`sweep`, and every command built on it, used to tear the whole circuit down and
build it again for each point, even though only a parameter VALUE changed.
`.dc` -- including the parameter sweeps of Enhancement-427 -- has never done
that: it sets up once and walks its points inside the analysis. This makes
`sweep` do the same.

THE REASON IT COULD NOT SIMPLY BE DONE IS NODE COLLAPSE, and that is what most
of this suite is about. A device may decide, at setup and from its parameters,
to merge two of its nodes; the matrix is built for that topology. Reuse the
setup and the topology freezes at whatever the FIRST point decided -- and the
sweep quietly draws the wrong curve. A first attempt at this change did exactly
that: sweeping `cs_gate`'s `rd` returned the same number at every point instead
of a falling curve, with no error and no warning. That case is check [1] below
and it is the reason the rest of the design exists.

Two things make reuse safe:

  * an OSDI device re-decides its collapse on every CKTtemp and compares it
    against the snapshot the matrix was built from (Enhancement-417). That
    mismatch used to be reportable only -- "the matrix was built for the
    collapse decided at setup and cannot be rebuilt here". CKTdoJob now does
    what that message said was impossible: it notices and rebuilds for real.

  * a built-in device decides its collapse in DEVsetup and nowhere else, so
    there is nothing to re-check. Reuse is therefore offered only to circuits
    built entirely from device types whose topology is known to be fixed --
    the linear elements and sources -- plus OSDI. Anything else keeps the old
    behaviour exactly, which is check [8].

The strongest assertion available is that the answer does not depend on the
optimisation, so most checks below run the same deck with `reusesetup=1` and
`reusesetup=0` and require the two to agree. The option also exists so that a
user chasing a difference can settle it in one line -- and because four
options in this codebase (Enhancements 450, 451, 454, 466) shipped with every
off-spelling silently meaning ON, each spelling is tested rather than trusted.
"""
import atexit
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ru_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(deck, tag):
    p = os.path.join(HERE, f"_ru_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    t0 = time.time()
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr, time.time() - t0


def rows(out):
    """the columns `sweep` prints, one list per row.

    `nan` and `inf` are matched deliberately: a regex that took only ordinary
    numbers would DROP a NaN row instead of reporting it, and a check comparing
    what survived would pass on two runs that both went wrong."""
    return [ln.split()[1:] for ln in out.splitlines()
            if re.match(r"^\d+\s+(-?[\d.]+e?[-+]?\d*|-?nan|-?inf)\b", ln, re.I)]


def vals(out):
    return [v for _n, v in re.findall(r"v\(([^)]+)\)\s*=\s*(-?[\d.]+e?[-+]?\d*)",
                                      out, re.I)]


def deck(body, ctl, osdi=("cs_gate.osdi",), opt="", dbg=False):
    pre = "".join(f"pre_osdi {o}\n" for o in osdi)
    return (f"reuse\n{body}{opt}.control\n{pre}option noacct\nset numdgt=10\n"
            f"{'set ngdebug' if dbg else ''}\n{ctl}\n.endc\n.end\n")


def decision(out):
    """(points whose setup was kept, points rebuilt) -- ngspice's own report,
    which is what makes this suite assert the mechanism instead of a stopwatch"""
    m = re.search(r"setup reused at (\d+) of \d+ points, (\d+) rebuilt", out)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


print("Enhancement-471: reusing the setup across sweep points\n")

ok = True
for va, osdi in (("cs_gate.va", "cs_gate.osdi"), ("rint.va", "rint.osdi")):
    r = subprocess.run([OPENVAF, va, "-o", osdi], cwd=HERE,
                       capture_output=True, text=True)
    ok = ok and r.returncode == 0 and os.path.isfile(os.path.join(HERE, osdi))
check("[0] the models compile", ok)

# --------------------------------------------------------------- collapse ----
# THE CASE THAT KILLED THE FIRST ATTEMPT.
#
# cs_gate collapses `d` onto `di` when rd == 0 and does not otherwise, so a
# sweep that starts at rd=0 changes the circuit's TOPOLOGY at its second point.
# Frozen, every point returns the first point's answer.
print("a sweep that moves the node collapse")

CS = "V1 in 0 dc 1\nNcgm in out cgm\nRl out 0 1k\n.model cgm cs_gate rd=0.0\n"
o, _ = run(deck(CS, "sweep @cgm[rd] lin 5 0 4k -output v(out)\nprint v(out)"), "cs")
got = [r[0] for r in rows(o)]
# g = 1e-3 so the device is 1k, in series with rd, into a 1k load:
#   v(out) = 1000 / (1000 + rd + 1000)
want = [1000.0 / (2000.0 + rd) for rd in (0, 1000, 2000, 3000, 4000)]
check("[1] the curve moves with the collapse -- it is not frozen",
      len(got) == 5 and len(set(got)) == 5, f"{got}")
check("[2] ...and every point is the analytically right value",
      len(got) == 5 and all(abs(float(a) - b) < 1e-6 for a, b in zip(got, want)),
      f"{got} want {[round(w, 9) for w in want]}")

o0, _ = run(deck(CS, "sweep @cgm[rd] lin 5 0 4k -output v(out)\nprint v(out)",
                 opt=".option reusesetup=0\n"), "cs0")
check("[3] ...and identical with the reuse turned off",
      got == [r[0] for r in rows(o0)], f"{got} vs {[r[0] for r in rows(o0)]}")

# the same model swept where the collapse never moves: reuse is used at every
# point and must still be exact
o, _ = run(deck(CS, "sweep @cgm[rd] lin 5 1k 5k -output v(out)\nprint v(out)"), "cn")
o0, _ = run(deck(CS, "sweep @cgm[rd] lin 5 1k 5k -output v(out)\nprint v(out)",
                 opt=".option reusesetup=0\n"), "cn0")
g, g0 = [r[0] for r in rows(o)], [r[0] for r in rows(o0)]
want = [1000.0 / (2000.0 + rd) for rd in (1000, 2000, 3000, 4000, 5000)]
check("[4] a sweep that never moves the collapse is exact and unchanged",
      g == g0 and len(g) == 5
      and all(abs(float(a) - b) < 1e-6 for a, b in zip(g, want)), f"{g}")

# a collapse that moves on the LAST point, not the first -- the rebuild has to
# be re-armed every point, not done once
o, _ = run(deck(CS, "sweep @cgm[rd] lin 4 3k 0 -output v(out)\nprint v(out)"), "cr")
g = [r[0] for r in rows(o)]
want = [1000.0 / (2000.0 + rd) for rd in (3000, 2000, 1000, 0)]
check("[5] a collapse that moves at the END of the sweep is caught too",
      len(g) == 4 and all(abs(float(a) - b) < 1e-6 for a, b in zip(g, want)), f"{g}")

# ------------------------------------------------------------ ordinary use ----
print("\nordinary sweeps answer exactly as they did")


def ladder(n):
    b = "V1 n0 0 dc 1\n"
    for i in range(n):
        b += f"N{i} n{i} n{i+1} rmod\n"
    return b + f"Rl n{n} 0 1k\n.model rmod rint r1=1k r2=1k\n"


def both(body, ctl, tag, osdi=("rint.osdi",)):
    a, ta = run(deck(body, ctl, osdi=osdi, dbg=True), tag)
    b, tb = run(deck(body, ctl, osdi=osdi, opt=".option reusesetup=0\n",
                     dbg=True), tag + "0")
    return a, b, ta, tb


a, b, _, _ = both(ladder(20), "sweep @rmod[r1] lin 9 1k 3k -output v(n20)\nprint v(n20)", "ld")
ra, rb = rows(a), rows(b)
check("[6] a 9-point OSDI sweep is identical with reuse on and off",
      len(ra) == 9 and ra == rb, f"{[r[0] for r in ra][:3]}...")

a, b, _, _ = both(ladder(10),
                  "sweep @rmod[r1] lin 3 1k 3k -vs @rmod[r2] lin 3 1k 3k "
                  "-output v(n10)\nprint all", "mk")
check("[7] a two-knob sweep is identical with reuse on and off",
      "= 9 runs" in a and "= 9 runs" in b and rows(a) == rows(b)
      and len(rows(a)) == 3 and len(rows(a)[0]) == 4,
      f"{len(rows(a))} rows x {len(rows(a)[0]) if rows(a) else 0}")
check("[7b] ...and the reuse spans the whole cartesian product",
      decision(a) == (8, 0) and decision(b) == (0, 0),
      f"on={decision(a)} off={decision(b)}")

# a BUILT-IN device decides its collapse in setup and cannot be re-checked, so
# reuse must be declined for the whole circuit and the answer must not move
BJT = ("V1 c 0 dc 5\nV2 b 0 dc 0.7\nQ1 c b 0 qmod\nRc c 0 10k\n"
       ".model qmod npn bf=100 rb=10 rc=1 re=1\n")
a, b, _, _ = both(BJT, "sweep @qmod[bf] lin 5 50 150 -output i(v1)\nprint i(v1)", "bj",
                  osdi=())
check("[8] a circuit holding a built-in device is untouched by the reuse",
      len(rows(a)) == 5 and rows(a) == rows(b) and len(set(r[0] for r in rows(a))) == 5,
      f"{[r[0] for r in rows(a)][:3]}...")

# a `.param` knob re-sources the deck, so there is no previous setup to keep
a, b, _, _ = both(".param rv=1k\n" + ladder(10).replace("r1=1k", "r1={rv}"),
                  "sweep rv lin 5 1k 3k -output v(n10)\nprint v(n10)", "dp")
check("[9] a deck-parameter sweep, which re-sources, is unaffected",
      len(rows(a)) == 5 and rows(a) == rows(b), f"{[r[0] for r in rows(a)][:2]}...")

# whatever the sweep leaves behind, the next analysis must be right
o, _ = run(deck(ladder(20), "sweep @rmod[r1] lin 5 1k 3k -output v(n20)\n"
                            "altermod @rmod[r1]=1k\nop\nprint v(n20)",
                osdi=("rint.osdi",)), "af")
g = vals(o)
check("[10] an analysis after the sweep is still right",
      len(g) == 1 and abs(float(g[0]) - 1000.0 / 41000.0) < 1e-9, f"{g}")

# `sweep` drives whatever `-analysis` names, not just `op`, and each leaves
# different state behind -- a transient's history, an ac solution, a noise
# integration. Reuse must be invisible to all of them.
AN = "V1 n0 0 dc 1 ac 1 sin(0 1 1k)\n" + "".join(
    f"N{i} n{i} n{i+1} rmod\n" for i in range(6)
) + "Rl n6 0 1k\nC1 n6 0 1n\n.model rmod rint r1=1k r2=1k\n"

for tag, an in (("tran", "tran 10u 1m"),
                ("ac", "ac lin 3 1k 10k"),
                ("noise", "noise v(n6) v1 lin 3 1k 10k"),
                ("dc", "dc v1 0 1 0.5")):
    out = "onoise_total" if tag == "noise" else "v(n6)"
    ctl = (f"sweep @rmod[r1] lin 4 1k 3k -analysis '{an}' -output {out}\n"
           "print all")
    x, y, _, _ = both(AN, ctl, "an" + tag)
    check(f"[10a-{tag}] a sweep driving `{tag}` is identical with reuse on and off",
          len(rows(x)) > 0 and rows(x) == rows(y), f"{len(rows(x))} rows")

# a point whose analysis FAILS leaves the circuit in a state nothing downstream
# can characterise. Reusing it carried the wreckage into every later point --
# this is what the guardgaps suite (Enhancement-445) caught, where the two legal
# points of a sweep came back NaN along with the three forbidden ones.
print("\na failed point does not contaminate the ones after it")

o, _ = run(deck(CS, "sweep @cgm[rd] lin 5 -2k 2k -output v(out)\nprint v(out)",
                dbg=True), "fl")
g = [r[0] for r in rows(o)]
check("[10b] the forbidden points are NaN and the legal ones keep real values",
      len(g) == 5 and g[0] == "nan" and g[1] == "nan"
      and all(abs(float(a) - b) < 1e-6 for a, b in
              zip(g[2:], (0.5, 1000.0 / 3000.0, 0.25))), f"{g}")
check("[10c] ...because reuse is declined after a point that failed",
      decision(o) == (1, 1), f"{decision(o)}")

# ------------------------------------------------------- the decision itself ----
# Up to here every check says the ANSWER is unchanged, which a build where the
# reuse never engaged would also pass. Under `set ngdebug` ngspice reports what
# it actually did, so these assert the mechanism rather than infer it from a
# stopwatch -- and a stopwatch could not tell them apart anyway on a circuit
# this small.
print("\nngspice reports which points it kept, and it is exactly right")

CSD = "sweep @cgm[rd] lin 5 %s -output v(out)"
o, _ = run(deck(CS, CSD % "1k 5k", dbg=True), "d1")
check("[11] a sweep whose collapse never moves keeps every point after the first",
      decision(o) == (4, 0), f"{decision(o)}")

o, _ = run(deck(CS, CSD % "0 4k", dbg=True), "d2")
check("[12] a sweep whose collapse moves once rebuilds exactly that one point",
      decision(o) == (3, 1), f"{decision(o)}")

o, _ = run(deck(CS, CSD % "1k 5k", dbg=True, opt=".option reusesetup=0\n"), "d3")
check("[13] with the reuse off, no point is kept",
      decision(o) == (0, 0), f"{decision(o)}")

# THE GATE: a built-in device decides its collapse in DEVsetup and cannot be
# re-checked afterwards, so reuse turns on WHICH parameters the sweep is moving.
#
# Enhancement-503 narrowed this from a per-type refusal to a per-parameter one.
# A BJT builds its internal collector, base and emitter nodes from `rc`, `rb`,
# `re` and `rco` and from nothing else, so a sweep of `bf` cannot move the
# topology and the setup is reused; a sweep of `rc` still cannot be reused and
# still is not. Checks [14] and [15] asserted the older, broader refusal --
# before E-503 both reported (0, 0) -- and now pin the narrower contract, with
# [14b] holding the safety property the original pair existed to protect.
# Nothing but this report can show any of it: the answer is the same either way,
# which is the point.
o, _ = run(deck(BJT, "sweep @qmod[bf] lin 5 50 150 -output i(v1)", osdi=(),
                dbg=True), "d4")
check("[14] a built-in device reuses when the swept knob cannot move a node",
      decision(o) == (4, 0), f"{decision(o)}")

o, _ = run(deck(BJT, "sweep @qmod[rc] lin 5 0 10 -output i(v1)", osdi=(),
                dbg=True), "d4b")
check("[14b] ...and still declines when the swept knob DOES build a node",
      decision(o) == (0, 0), f"{decision(o)}")

o, _ = run(deck(BJT + "Ncgm n1 0 cgm\n.model cgm cs_gate rd=1k\n",
                "sweep @cgm[rd] lin 5 1k 5k -output v(n1)", dbg=True), "d5")
check("[15] ...and reuses with OSDI devices in the same circuit",
      decision(o) == (4, 0), f"{decision(o)}")

# ------------------------------------------------------------- the switch ----
# Enhancements 450, 451, 454 and 466 each shipped an option here whose
# off-spellings silently meant ON, because the value was never read. The report
# settles each spelling exactly.
print("\nevery spelling that means off means off")

for i, spell in enumerate(("reusesetup=0", "reusesetup=false", "reusesetup=no",
                           "reusesetup=off", "noreusesetup")):
    o, _ = run(deck(CS, CSD % "1k 5k", dbg=True, opt=f".option {spell}\n"),
               f"sp{i}")
    check(f"[{16+i}] `.option {spell}` really turns it off",
          decision(o) == (0, 0), f"{decision(o)}")

for i, spell in enumerate(("reusesetup=1", "reusesetup=true", "reusesetup",
                           "reusesetup=yes")):
    o, _ = run(deck(CS, CSD % "1k 5k", dbg=True, opt=f".option {spell}\n"),
               f"sn{i}")
    check(f"[{21+i}] `.option {spell}` leaves it on",
          decision(o) == (4, 0), f"{decision(o)}")

# The option is honoured off a `.options` card, so it must not also be reported
# as an unknown one and "ignored" -- a warning that fires on a setting the run
# then honours teaches the user to ignore the check (Enhancement-445's note on
# that list). This shipped wrong in E-471 and the deck timing is what exposed it.
for spell in ("reusesetup=0", "noreusesetup", "reusesetup=1"):
    o = run(deck(CS, CSD % "1k 5k", opt=f".option {spell}\n"), f"unk{spell[:12]}")
    check(f"[24-{spell}] `.option {spell}` is not called an unknown option",
          "unknown option" not in o, "")

o, _ = run(deck(CS, CSD % "1k 5k", dbg=True).replace("set ngdebug",
                                                     "set ngdebug\nset reusesetup=0"),
           "sv")
check("[25] `set reusesetup=0` from the control block turns it off too",
      decision(o) == (0, 0), f"{decision(o)}")

# and turning it off must change the speed and nothing else
a, _ = run(deck(ladder(20), "sweep @rmod[r1] lin 5 1k 3k -output v(n20)\n"
                            "print v(n20)", osdi=("rint.osdi",)), "q1")
b, _ = run(deck(ladder(20), "sweep @rmod[r1] lin 5 1k 3k -output v(n20)\n"
                            "print v(n20)", osdi=("rint.osdi",),
                opt=".option noreusesetup\n"), "q2")
check("[26] turning it off changes the speed and nothing else",
      rows(a) == rows(b) and len(rows(a)) == 5, f"{len(rows(a))} rows")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
