#!/usr/bin/env python3
"""Enhancement-498: per-RUN state must be re-armed when the setup is reused.

Enhancement-471 lets `sweep`, `optimize` and `montecarlo -warm` keep a circuit
standing between points: CKTdoJob skips CKTunsetup/CKTsetup and only re-runs
CKTtemp. That is sound for TOPOLOGY, which is what E-471 reasoned about and what
its own suite tests. What it missed is that a couple of devices keep TRANSIENT
RUN state on the instance and seed it in DEVsetup -- so reuse left that state
holding the PREVIOUS run's values.

  * `VSRCbreak_time` is how a voltage source walks its own breakpoint schedule:
    VSRCaccept arms the next edge only when `CKTtime >= VSRCbreak_time`, and
    VSRCsetup seeds it to -1.0 so the first accepted point arms the first edge.
    Reused, the instance carried the previous run's break time -- a value at or
    past that run's TSTOP -- so the test was false at t=0 and stayed false for
    the whole run. A PULSE or PWL source scheduled NO BREAKPOINTS AT ALL and the
    stepper walked straight over every edge.

    This was not a rounding difference. E-471's own comment promises reuse
    "changes nothing a user can see except the time ... a few ulp". A 5-point
    sweep of an RC driven by a narrow PWL pulse put `maximum(v(n))` -- a
    grid-INDEPENDENT quantity -- 44% out, 106% at other spacings, in silence;
    and `optimize` fitted a parameter 13% wrong while reporting "converged".
    The same resistance even returned two different answers depending on
    whether the sweep ran up or down, because only the FIRST point of a sweep
    still had a correct schedule.

  * OSDI's `crossing_time[]` is the `last_crossing()` cache. osdiaccept.c states
    the contract: it "starts at 0.0 ... before any crossing has been observed",
    and is otherwise left alone so V(z) keeps reporting the LAST crossing per
    the LRM. Only OSDIsetup seeded it, so a reused point began holding the
    previous point's crossing: a model asking "has it crossed yet?" was answered
    with another run's answer.

    Its sibling operator `absdelay` was already right -- osdiload.c re-seeds
    `delay_hist[k][0]` on `is_init_tran`, the first transient call of each run,
    not at setup. That is the pattern; `last_crossing` simply did not follow it.

Both are re-armed in the DEVtemperature method, which CKTtemp runs once per job
on BOTH the reuse and the rebuild path, and which does not run on a `resume`
(CKTdoJob's reset branch is skipped there), so a continued run is left alone.

One thing this suite does NOT assert is called out where it is skipped: under
KLU, `sweep -analysis ac` with reuse returns zeros and intermittently crashes.
That is a separate pre-existing defect (see KLU_AC_NOTE below), not something
Enhancement-498 fixed, and it is reported rather than quietly tested around.

The assertion throughout is the strongest one available: a swept point must
equal a STANDALONE run of the same circuit, bit for bit. Checks marked
"(control)" passed before the fix as well -- they are here to prove the fix did
not buy correctness by quietly disabling the optimisation, which is why the
reuse tally itself is asserted.
"""
import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

# Which solver this (single-solver) process is running under. The AC and noise
# controls below are asserted under Sparse only -- see KLU_AC_NOTE.
_SOLVER = (os.environ.get("_NG_SOLVER") or os.environ.get("NGSPICE_SOLVER")
           or "sparse").lower()

KLU_AC_NOTE = (
    "a SEPARATE, PRE-EXISTING defect, found while building this suite and NOT "
    "fixed by Enhancement-498: under KLU, `sweep -analysis ac` (and noise) with "
    "the setup-reuse fast path returns 0.0 for the reused points, and crashes "
    "outright in roughly one run in ten (SIGTRAP). It is non-deterministic -- "
    "byte-identical decks give different answers run to run -- which points at "
    "memory, not arithmetic. It reproduces on the shipped Jul-18 binary, is "
    "absent with `reusesetup=0`, absent under Sparse, and absent from a manual "
    "`alter`+`ac` loop, so it belongs to the reuse path and needs its own "
    "investigation. Asserting it here would only pin down a bug; these two "
    "controls therefore run under Sparse, where they are meaningful."
)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_rs_"):
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
    p = os.path.join(HERE, f"_rs_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def rows(out):
    """the columns `sweep` prints. `nan`/`inf` are matched on purpose: dropping
    them would hide a run that went wrong instead of reporting it."""
    return [ln.split()[1:] for ln in out.splitlines()
            if re.match(r"^\d+\s+(-?[\d.]+e?[-+]?\d*|-?nan|-?inf)\b", ln, re.I)]


def col(out, i=1):
    return [r[i] for r in rows(out) if len(r) > i]


def scalar(out, name):
    m = re.findall(rf"{re.escape(name)}\s*=\s*(-?[\d.]+e?[-+]?\d*|-?nan|-?inf)",
                   out, re.I)
    return m[-1] if m else None


def decision(out):
    """ngspice's own report of what the fast path did -- this suite asserts the
    mechanism, not a stopwatch."""
    m = re.search(r"setup reused at (\d+) of \d+ points, (\d+) rebuilt", out)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


RS = [1000, 2000, 3000, 4000, 5000]

PULSE = "dc 0 PULSE(0 1 0 1u 1u 1m 2m)"
PWL = "dc 0 PWL(0 0 1u 1 1.2u 0 20u 0 21u 1 21.2u 0)"
SIN = "dc 0 SIN(0 1 200k)"
EXP = "dc 0 EXP(0 1 1u 1u 50u 1u)"
DCO = "dc 1"


def rc(src, r="1k", opt=""):
    return f"reusestate\n{opt}V1 a 0 {src}\nR1 a n {r}\nC1 n 0 1n\n"


def ctl(body, dbg=False):
    return (f".control\noption noacct\nset numdgt=12\n"
            f"{'set ngdebug' if dbg else ''}\n{body}\n.endc\n.end\n")


def sweep_max(src, opt="", tran="10u 200u", tag="s", dbg=False, expr="maximum(v(n))"):
    o = run(rc(src, opt=opt) + ctl(
        f"sweep @r1[resistance] 1k 5k 1k -analysis tran {tran} -output y={expr}\n"
        f"setplot sweep1\nprint all", dbg=dbg), tag)
    return col(o), o


def oracle_max(src, tran="10u 200u", expr="maximum(v(n))"):
    """the ground truth: one standalone ngspice run per value."""
    out = []
    for r in RS:
        o = run(rc(src, r=str(r)) + ctl(f"tran {tran}\nprint {expr}"), f"o{r}")
        out.append(scalar(o, expr))
    return out


print("Enhancement-498: re-arming per-run state when the setup is reused\n")

# ------------------------------------------------- the sources that broke ----
# A source that registers breakpoints is the whole exposure: PULSE and PWL walk
# VSRCbreak_time, everything else recomputes from CKTtime and never cared.
print("a swept transient must equal a standalone run")

for nm, src in (("PULSE", PULSE), ("PWL", PWL)):
    got, o = sweep_max(src, tag=f"a{nm}")
    want = oracle_max(src)
    check(f"[1-{nm}] every swept point equals a standalone run, exactly",
          got == want and len(got) == 5, f"{got} vs {want}")

# the 44% case, stated as the number a user would read
got, _ = sweep_max(PWL, tag="narrow")
want = oracle_max(PWL)
if got and want and len(got) == len(want) == 5:
    err = max(abs(float(a) - float(b)) / max(abs(float(b)), 1e-30)
              for a, b in zip(got, want))
else:
    err = 1.0
check("[2] ...with zero relative error on maximum(v(n)) (was 0.44)",
      err == 0.0, f"worst rel err {err:.3e}")

# reuse OFF has always been right; it is the reference the fix restores
for nm, src in (("PULSE", PULSE), ("PWL", PWL)):
    on, _ = sweep_max(src, tag=f"on{nm}")
    off, _ = sweep_max(src, opt=".option reusesetup=0\n", tag=f"of{nm}")
    check(f"[3-{nm}] reusesetup on and off agree", on == off and len(on) == 5,
          f"{on} vs {off}")

# ------------------------------------------------------ the mechanism ----
# The direct statement of the bug: with a stale schedule the source armed NO
# breakpoints, so the run never landed on a PWL corner. 0/5 before, 5/5 after.
print("\nthe breakpoints themselves")

o = run(rc(PWL, r="3000") + ctl(
    "sweep @r1[resistance] 3000 3000.001 0.001 -analysis tran 10u 200u"
    " -output y=length(v(n))\nsetplot tran2\nprint time"), "bp")
ts = []
for ln in o.splitlines():
    t = ln.split()
    if len(t) >= 2 and t[0].isdigit():
        try:
            ts.append(float(t[1]))
        except ValueError:
            pass
corners = [1e-6, 1.2e-6, 2e-5, 2.1e-5, 2.12e-5]
hit = sum(1 for c in corners if any(abs(t - c) < 1e-15 for t in ts))
check("[4] a REUSED point still lands on every PWL corner (was 0 of 5)",
      hit == 5, f"{hit}/5 corners, {len(ts)} timepoints")

# ------------------------------------------------------------- optimize ----
# E-472 reuses the setup across optimizer evaluations. A wrong objective does
# not merely slow the fit down, it moves the answer -- and still says
# "converged", which is the part a user cannot see.
print("\noptimize with a transient objective")

OPT = ("optimize -param R1 1k 500 8k -analysis tran 10u 200u\n"
       "+  -minimize (maximum(v(n))-0.20)^2\n"
       "+  -maxiter 300 -tol 1e-16\nprint @r1[resistance]")
a = run(rc(PWL) + ctl(OPT), "opta")
b = run(rc(PWL, opt=".option reusesetup=0\n") + ctl(OPT), "optb")
fa, fb = scalar(a, "@r1[resistance]"), scalar(b, "@r1[resistance]")
check("[5] the fitted parameter does not depend on the fast path",
      fa is not None and fa == fb, f"{fa} vs {fb}")

# and the fit is the RIGHT one: put it back and the objective is met
if fa:
    o = run(rc(PWL, r=fa) + ctl("tran 10u 200u\nprint maximum(v(n))"), "optc")
    m = scalar(o, "maximum(v(n))")
    check("[6] ...and it actually hits the target it was fitted to",
          m is not None and abs(float(m) - 0.20) < 1e-6, f"max={m} target=0.20")
else:
    check("[6] ...and it actually hits the target it was fitted to", False, "no fit")

check("[7] both runs report convergence", "converged" in a and "converged" in b)

# ------------------------------------------------------ order dependence ----
# The clearest symptom: only a sweep's FIRST point had a correct schedule, so
# the same resistance answered differently depending on the direction of travel.
print("\nthe answer must not depend on where the point sits in the sweep")

up, _ = sweep_max(PWL, tag="up")
o = run(rc(PWL) + ctl("sweep @r1[resistance] 5k 1k -1k -analysis tran 10u 200u"
                      " -output y=maximum(v(n))\nsetplot sweep1\nprint all"), "dn")
down = col(o)
check("[8] a reversed sweep returns the same values in reverse",
      len(up) == 5 and len(down) == 5 and up == list(reversed(down)),
      f"up={up} down={down}")

# ------------------------------------------------------------- knobs ----
# The stale schedule did not care WHICH knob moved, only that a point ran after
# another one, so every knob kind is exercised.
print("\nevery knob kind")

KNOBS = [("R instance", "@r1[resistance] 3000 3000.004 0.001",
          "V1 a 0 {s}\nR1 a n 1k\nC1 n 0 1n\n"),
         ("C instance", "@c1[capacitance] 1n 1.000004n 0.000001n",
          "V1 a 0 {s}\nR1 a n 3000\nC1 n 0 1n\n"),
         ("V dc", "@v1[dc] 0 0.004 0.001",
          "V1 a 0 {s}\nR1 a n 3000\nC1 n 0 1n\n"),
         ("temp", "temp 27 27.004 0.001",
          "V1 a 0 {s}\nR1 a n 3000\nC1 n 0 1n\n")]
for nm, knob, body in KNOBS:
    d = "reusestate\n" + body.format(s=PWL)
    a = run(d + ctl(f"sweep {knob} -analysis tran 10u 200u"
                    f" -output y=maximum(v(n))\nsetplot sweep1\nprint all"), f"k{nm[:3]}")
    b = run("reusestate\n.option reusesetup=0\n" + body.format(s=PWL) +
            ctl(f"sweep {knob} -analysis tran 10u 200u"
                f" -output y=maximum(v(n))\nsetplot sweep1\nprint all"), f"l{nm[:3]}")
    check(f"[9-{nm}] the {nm} knob agrees with reuse off",
          col(a) == col(b) and len(col(a)) > 1, f"{col(a)} vs {col(b)}")

# ----------------------------------------------------------- the tally ----
# A fix that simply stopped reusing would make every check above pass and throw
# away Enhancement-471. Assert that the fast path is still ON.
print("\nthe optimisation is still doing its job")

_, o = sweep_max(PWL, tag="tally", dbg=True)
check("[10] the setup is still reused at 4 of the 5 points",
      decision(o) == (4, 0), f"{decision(o)}")

o = run(rc(PWL, opt=".option reusesetup=0\n") + ctl(
    "sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
    " -output y=maximum(v(n))", dbg=True), "tally0")
check("[11] ...and `reusesetup=0` still turns it off completely",
      decision(o) == (0, 0), f"{decision(o)}")

# ------------------------------------------------------------ controls ----
# These passed BEFORE the fix too. They are the boundary of the change: a
# source with no breakpoints, and every analysis that is not a transient.
print("\ncontrols -- what was never affected must still be untouched")

for nm, src in (("SIN", SIN), ("EXP", EXP), ("dc-only", DCO)):
    got, _ = sweep_max(src, tag=f"c{nm[:3]}")
    want = oracle_max(src)
    check(f"[12-{nm}] (control) a source with no breakpoints is unchanged",
          got == want and len(got) == 5, f"{got} vs {want}")

NONTRAN = [
    ("op", "V1 a 0 dc 1\nR1 a n 1k\nR2 n 0 1k\n",
     "sweep @r1[resistance] 1k 5k 1k -analysis op -output v(n)"),
    ("ac", "V1 a 0 dc 0 ac 1\nR1 a n 1k\nC1 n 0 1n\n",
     "sweep @r1[resistance] 1k 5k 1k -analysis ac dec 3 1k 100k"
     " -output y=mag(v(n))[2]"),
    ("tf", "V1 in 0 dc 1\nR1 in o 1k\nR2 o 0 2k\n",
     "sweep @r1[resistance] 1k 5k 1k -analysis tf v(o) V1"
     " -output y=transfer_function"),
    ("noise", "V1 in 0 dc 0 ac 1\nR1 in o 1k\nC1 o 0 1n\n",
     "sweep @r1[resistance] 1k 5k 1k -analysis noise v(o) V1 dec 2 1k 10k"
     " -output y=onoise_total"),
]
for nm, body, cmd in NONTRAN:
    if _SOLVER == "klu" and nm in ("ac", "noise"):
        print(f"  NOTE  [13-{nm}] not asserted under KLU -- {KLU_AC_NOTE}")
        continue
    a = run(f"reusestate\n{body}" + ctl(f"{cmd}\nsetplot sweep1\nprint all"), f"n{nm}")
    b = run(f"reusestate\n.option reusesetup=0\n{body}" +
            ctl(f"{cmd}\nsetplot sweep1\nprint all"), f"m{nm}")
    check(f"[13-{nm}] (control) a non-transient analysis is unchanged",
          col(a) == col(b) and len(col(a)) == 5, f"{col(a)} vs {col(b)}")

# a current source computes its edges from CKTtime and keeps no schedule
I = ("reusestate\nI1 0 n PULSE(0 1m 0 1u 1u 1m 2m)\nR1 n 0 1k\nC1 n 0 1n\n")
a = run(I + ctl("sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
                " -output y=maximum(v(n))\nsetplot sweep1\nprint all"), "i1")
b = run(I.replace("reusestate\n", "reusestate\n.option reusesetup=0\n") +
        ctl("sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
            " -output y=maximum(v(n))\nsetplot sweep1\nprint all"), "i2")
check("[14] (control) a PULSE current source keeps no schedule and is unchanged",
      col(a) == col(b) and len(col(a)) == 5, f"{col(a)} vs {col(b)}")

# ---------------------------------------------------------------- OSDI ----
# The second member of the class, and the one that matters most here: a
# Verilog-A model reading last_crossing() got the PREVIOUS point's crossing.
print("\nOSDI: the last_crossing cache")

r = subprocess.run([OPENVAF, "rs_cross.va", "-o", "rs_cross.osdi"], cwd=HERE,
                   capture_output=True, text=True)
built = r.returncode == 0 and os.path.isfile(os.path.join(HERE, "rs_cross.osdi"))
check("[15] the model compiles", built, "" if built else r.stderr[-200:])

if built:
    LC = ("reusestate\n%s.control\npre_osdi rs_cross.osdi\n.endc\n"
          "vin in 0 sin(0 1 100k)\nn1 in out lcm\n"
          ".model lcm rs_cross(dir=1)\nrload out 0 1k\nrdum in 0 1k\n")
    CMD = ("sweep @rdum[resistance] 1k 5k 1k -analysis tran 0.05u 40u"
           " -output y=v(out)[0] -output z=v(out)[1]\nsetplot sweep1\nprint all")
    a = run(LC % "" + ctl(CMD), "lc1")
    b = run(LC % ".option reusesetup=0\n" + ctl(CMD), "lc2")
    ca = [r[1:] for r in rows(a)]
    check("[16] last_crossing starts each reused run at 0, not the previous "
          "run's crossing",
          len(ca) == 5 and all(abs(float(v)) < 1e-15 for r_ in ca for v in r_),
          f"{ca}")
    check("[17] ...and matches the run with reuse turned off",
          ca == [r[1:] for r in rows(b)] and len(ca) == 5)

    # absdelay's sibling path was already correct -- assert it stayed that way
    check("[18] (control) the OSDI deck still reuses the setup",
          decision(run(LC % "" + ctl(CMD, dbg=True), "lc3")) == (4, 0),
          f"{decision(run(LC % '' + ctl(CMD, dbg=True), 'lc4'))}")
else:
    for n in (16, 17, 18):
        check(f"[{n}] skipped -- model did not compile", False)

# ------------------------------------------------------- shape of a run ----
# The grid itself, which is what the stale schedule really damaged.
print("\nthe timestep grid")

got, _ = sweep_max(PULSE, tag="len", expr="length(v(n))")
want = oracle_max(PULSE, expr="length(v(n))")
check("[19] the number of timepoints matches a standalone run at every point",
      got == want and len(got) == 5, f"{got} vs {want}")

got, _ = sweep_max(PULSE, tag="t1", expr="time[1]")
check("[20] the first timestep is the same at every point (it doubled before)",
      len(set(got)) == 1 and len(got) == 5, f"{got}")

# a second, coarser tstep: the defect survived a spec that removed the doubling,
# so the suite must not rest on that one symptom
got, _ = sweep_max(PWL, tran="1u 200u", tag="ts1")
want = oracle_max(PWL, tran="1u 200u")
check("[21] a different tstep agrees too", got == want and len(got) == 5,
      f"{got} vs {want}")

# ------------------------------------------------------------ compound ----
print("\nnested and repeated sweeps")

N = ("sweep @r1[resistance] list 1k 3k @c1[capacitance] list 1n 2n"
     " -analysis tran 10u 200u -output y=maximum(v(n))\nsetplot sweep1\nprint all")
a = run(rc(PWL) + ctl(N), "ne1")
b = run(rc(PWL, opt=".option reusesetup=0\n") + ctl(N), "ne2")
check("[22] a nested two-knob sweep agrees with reuse off",
      col(a) == col(b) and len(col(a)) >= 2, f"{col(a)} vs {col(b)}")

TW = ("sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
      " -output y=maximum(v(n))\nsetplot sweep1\nprint all\n"
      "sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
      " -output y=maximum(v(n))\nsetplot sweep2\nprint all")
o = run(rc(PWL) + ctl(TW), "tw")
c = col(o)
check("[23] two identical sweeps in one session agree with each other",
      len(c) == 10 and c[:5] == c[5:], f"{c}")

# a plain analysis after a sweep must be unaffected either way
o = run(rc(PWL, r="3000") + ctl(
    "sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
    " -output y=maximum(v(n))\nalter @r1[resistance] = 3000\n"
    "tran 10u 200u\nprint maximum(v(n))"), "af")
oo = run(rc(PWL, r="3000") + ctl("tran 10u 200u\nprint maximum(v(n))"), "af0")
check("[24] a standalone analysis run after a sweep is unaffected",
      scalar(o, "maximum(v(n))") == scalar(oo, "maximum(v(n))"),
      f"{scalar(o, 'maximum(v(n))')} vs {scalar(oo, 'maximum(v(n))')}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
