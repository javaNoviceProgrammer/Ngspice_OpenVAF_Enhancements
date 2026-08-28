#!/usr/bin/env python3
"""Enhancement-499: what the loop commands accept, and what they claim afterwards.

Round 58 probed the `sweep`/`optimize` fast path again, after Enhancement-498 had
fixed the transient side. Nothing was wrong with the reuse arithmetic this time.
What was wrong was everything around it: the arguments the commands accept, the
verdict they print, and -- underneath both -- one genuine memory bug in the KLU
solver that setup reuse made reachable.

THE SOLVER BUG. klu_z_refactor refills an existing factorisation in place, walking
the L and U index arrays klu_z_factor built. Handed a REAL Numeric object it walks
half-sized arrays with complex strides: it reads and writes past their ends, and a
later klu_free_numeric frees whatever it scribbled -- the malloc abort names object
0x3ff0000000000000, which is the bit pattern of the double 1.0, a matrix VALUE
being freed as a pointer. Every AC/SP/NOISE run is preceded by a real operating
point, and Enhancement-471's setup reuse keeps the matrix standing between sweep
points instead of rebuilding it, so the second and later points arrived with the
operating point's real Numeric. `sweep -analysis ac` under `.option klu` returned
0.0 for every reused point, `optimize -analysis ac` fitted a parameter 10x wrong
while reporting "converged", and `sp` crashed outright on 9 of 10 runs. SPARSE was
never affected, and neither was any analysis that stays real.

THE ARGUMENTS. `com_optimize.c` has had a SPICE-aware number parser, optnum(),
since it was written, and uses it for the bounds, `-target` and `-spec`. Its
integer options did not: `-maxiter`, `-samples` and `-swarmsize` called atoi() and
`-tol` called atof(), which stop at the first character they cannot use. So `1k`
meant 1000 in a bound and 1 in `-maxiter` ON THE SAME COMMAND LINE, `-maxiter 2e2`
ran 2 iterations rather than 200 and returned a worse fit, `-samples 2e2` ran 2
Monte-Carlo samples while design centering still printed a yield and a confidence
interval, and `abc` was 0 everywhere in silence. `sweep lin 2e2` (200 points) and
`montecarlo 2e2` (200 samples) were already right, so optimize was the odd one of
the three. `-seed` had the matching hole: Enhancement-497 taught the `setseed`
COMMAND to refuse `3.7`, but the OPTION spelling truncated it without a word, and
`-seed 0` / `-seed -3` left the run unseeded and NOT reproducible.

THE VERDICT. "converged" describes the search stopping, not the answer being the
one the author wanted. It was printed when the objective never moved at all -- a
parameter outside the signal path, or a name that does not resolve, hands back the
STARTING value after three evaluations -- and when the answer sat on a search
bound, meaning the optimum is outside the range. `-target x 0.4 0`, whose zero
weight makes the residual identically 0, printed the most convincing number the
command can produce for a fit that never happened.

THE SAME SHAPE IN `sweep`. sw_kind() falls through to SW_ALTER for any name it
does not recognise; `alter` then reports "no such device", the sweep runs anyway
over a knob that never moves, and the user gets a full set of points, rc = 0, and
a plottable FLAT curve whose x-axis is named after the typo. That is the shape
Enhancement-435 removed for a subcircuit-local model name, Enhancement-488 for
`temp`, and Enhancement-431 for an unresolved `-output` -- "a typo, not data".

AND WHAT `-overlay` DID TO A WAVEFORM. It resampled onto a UNIFORM grid of the
same point count as the longest run. A transient chooses its timepoints where the
waveform moves; keeping the count and discarding the placement is exactly
backwards, and the overlay of an RC driven by a 0.2 us pulse reported a peak 39%
below what every one of its own runs said.
"""
import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

_SOLVER = (os.environ.get("_NG_SOLVER") or os.environ.get("NGSPICE_SOLVER")
           or "sparse").lower()


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lg_"):
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


def run(deck, tag, timeout=900):
    p = os.path.join(HERE, f"_lg_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


NUM = r"-?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|nan|inf)"


def rows(out):
    """`nan`/`inf` are matched deliberately: a regex that took only ordinary
    numbers would DROP a NaN row instead of reporting it."""
    return [l.split()[1:] for l in out.splitlines()
            if re.match(rf"^\d+\s+{NUM}\b", l, re.I)]


def col(out, i=1):
    return [r[i] for r in rows(out) if len(r) > i]


def scalar(out, name):
    m = re.findall(rf"{re.escape(name)}\s*=\s*({NUM})", out, re.I)
    return m[-1] if m else None


def evals(out):
    m = re.search(r"after (\d+) evaluations", out)
    return int(m.group(1)) if m else None


def deck(body, ctl, opt=""):
    return (f"loopguard\n{opt}{body}.control\noption noacct\nset numdgt=12\n"
            f"{ctl}\n.endc\n.end\n")


DIV = "V1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n"
RC = "V1 a 0 dc 0 ac 1\nR1 a n 1k\nC1 n 0 1n\n"
PWL = "dc 0 PWL(0 0 1u 1 1.2u 0 20u 0 21u 1 21.2u 0)"
RCT = f"V1 a 0 {PWL}\nR1 a n 1k\nC1 n 0 1n\n"

print("Enhancement-499: loop-command arguments, verdicts, and a KLU refactor kind\n")

# ------------------------------------------------------- the solver bug ----
# The severe one. Under KLU these three analyses returned zeros or crashed as
# soon as the setup was reused; every other analysis, and all of SPARSE, was
# always fine. Asserted on BOTH solvers so the fix cannot be solver-specific.
print("KLU: a complex refactor must never be handed a real factorisation")

SPD = ("V1 in 0 dc 0 ac 1 portnum 1 z0 50\nR1 in o 1k\nC1 o 0 1n\n"
       "V2 o 0 dc 0 ac 0 portnum 2 z0 50\n")
rc, o = run(deck(SPD, "sweep @r1[resistance] 1k 5k 1k -analysis sp dec 2 1meg 100meg"
                      " -output y=all\nsetplot sweep1\nprint all"), "sp")
check("[1] `sweep -analysis sp` with setup reuse does not crash",
      rc == 0 and len(col(o)) == 5, f"rc={rc}, {len(col(o))} rows")

for nm, body, cmd in (
        ("ac", RC, "-analysis ac dec 3 1k 100k -output y=mag(v(n))[2]"),
        ("noise", "V1 in 0 dc 0 ac 1\nR1 in o 1k\nC1 o 0 1n\n",
         "-analysis noise v(o) V1 dec 2 1k 10k -output y=onoise_total"),
        ("sp", SPD, "-analysis sp dec 2 1meg 100meg -output y=all")):
    a = col(run(deck(body, f"sweep @r1[resistance] 1k 5k 1k {cmd}\n"
                           f"setplot sweep1\nprint all"), f"r{nm}")[1])
    b = col(run(deck(body, f"sweep @r1[resistance] 1k 5k 1k {cmd}\n"
                           f"setplot sweep1\nprint all",
                     opt=".option reusesetup=0\n"), f"n{nm}")[1])
    check(f"[2-{nm}] reusing the setup gives the same answer as not reusing",
          a == b and len(a) == 5, f"{a} vs {b}")

# the fit that came back 10x wrong
OPTAC = ("optimize -param R1 1k 100 10k -analysis ac dec 5 1k 1meg"
         " -minimize (mag(v(n))[3]-0.9)^2 -maxiter 200 -tol 1e-16\n"
         "print @r1[resistance]")
a = scalar(run(deck(RC, OPTAC), "oa")[1], "@r1[resistance]")
b = scalar(run(deck(RC, OPTAC, opt=".option reusesetup=0\n"), "ob")[1], "@r1[resistance]")
check("[3] an AC-objective fit does not depend on the fast path", a is not None and a == b,
      f"{a} vs {b}")

# a transient still refactors normally -- the guard must not disable refactoring
_, o = run(deck(RCT, "sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
                     " -output y=maximum(v(n))\nsetplot sweep1\nprint all"), "tr")
_, o2 = run(deck(RCT, "sweep @r1[resistance] 1k 5k 1k -analysis tran 10u 200u"
                      " -output y=maximum(v(n))\nsetplot sweep1\nprint all",
                 opt=".option reusesetup=0\n"), "tr2")
check("[4] (control) a transient sweep is unchanged", col(o) == col(o2) and len(col(o)) == 5)

# ------------------------------------------------- optimize's arguments ----
# optnum() was in the same file all along; four options did not use it.
print("\noptimize: a number is a number in every argument")

OPTBASE = ("optimize -param R1 1k 100 10k -analysis op -minimize (v(out)-0.4)^2"
           " -tol 1e-16 -maxiter %s\nprint @r1[resistance]")
ref = None
for spec in ("1000", "1k", "2e2", "200"):
    rc, o = run(deck(DIV, OPTBASE % spec), "mi" + re.sub(r"\W", "", spec))
    e, v = evals(o), scalar(o, "@r1[resistance]")
    if spec == "1000":
        ref = (e, v)
    check(f"[5-{spec}] `-maxiter {spec}` is read as a whole number, not truncated",
          e is not None and v == "1.500000000000e+03" and e == ref[0] if spec in ("1000", "1k")
          else (e is not None and v == "1.500000000000e+03"),
          f"{e} evaluations, R1={v}")

# a SPICE suffix means the same thing in a bound and in a count
rc, o = run(deck(DIV, OPTBASE % "1k"), "sfx")
check("[6] `1k` means 1000 in `-maxiter`, as it already did in a bound",
      scalar(o, "@r1[resistance]") == "1.500000000000e+03", f"R1={scalar(o,'@r1[resistance]')}")

for opt, why in (("-maxiter abc", "text"), ("-maxiter 0", "zero"),
                 ("-maxiter 5.7", "fractional"), ("-tol abc", "text"),
                 ("-tol nan", "NaN"), ("-tol -1", "negative"),
                 ("-seed 3.7", "fractional seed"), ("-seed 0", "zero seed")):
    rc, o = run(deck(DIV, f"optimize -param R1 1k 100 10k -analysis op"
                          f" -minimize (v(out)-0.4)^2 {opt}\n"), "bad" + re.sub(r"\W", "", opt))
    said = re.search(r"optimize: -\S+ (needs|must)", o)
    check(f"[7] `{opt}` ({why}) is refused and named", rc != 0 and said is not None,
          (said.group(0) if said else o.strip().splitlines()[-1][:52]))

# -samples, the one whose misreading is a statistical claim
MC = ".param xc=4.0\n.param vo=agauss(xc,1.5,3)\nV1 out 0 dc {vo}\nR1 out 0 1k\n"
for spec, want in (("50", 50), ("5e1", 50), ("2e2", 200)):
    _, o = run(deck(MC, f"optimize -dparam xc 4.0 3 7 -center -lhs -samples {spec}"
                        f" -analysis op -spec v(out) -max 6 -min 4 -seed 3 -maxiter 4\n"),
               "smp" + spec.replace("e", "E"))
    m = re.search(r"\((\d+) MC samples\)", o)
    check(f"[8-{spec}] `-samples {spec}` runs {want} samples",
          m is not None and int(m.group(1)) == want, f"{m.group(1) if m else '?'} samples")

# ------------------------------------------------------- the verdict ----
print("\noptimize: what it says when nothing was optimised")

# R3 hangs off an isolated node: the objective cannot depend on it
NOINF = DIV + "R3 q 0 1k\nVq q 0 dc 0\n"
for start in ("1k", "5k", "9k"):
    _, o = run(deck(NOINF, f"optimize -param R3 {start} 100 10k -analysis op"
                           f" -minimize (v(out)-0.4)^2 -maxiter 300 -tol 1e-16\n"
                           f"print @r3[resistance]"), "ni" + start)
    check(f"[9-{start}] a parameter the objective cannot depend on is called out",
          "nothing was optimised" in o, o.strip().splitlines()[-1][:60])

_, o = run(deck(NOINF, "optimize -param R1 5k 4k 6k -analysis op"
                       " -minimize (v(out)-0.4)^2 -maxiter 300 -tol 1e-16\n"), "bnd")
check("[10] a result that finished ON a bound is called out",
      "ON a search bound" in o, o.strip().splitlines()[-1][:60])

_, o = run(deck(DIV, "optimize -param R1 1k 100 10k -analysis op -target v(out) 0.4 0"
                     " -maxiter 200 -tol 1e-16\n"), "w0")
check("[11] a zero-weight target no longer reads as a perfect fit",
      "nothing was optimised" in o, o.strip().splitlines()[-1][:60])

_, o = run(deck(DIV, "optimize -param R1 1k 100 10k -analysis op"
                     " -minimize (v(out)-0.4)^2 -maxiter 300 -tol 1e-16\n"), "good")
check("[12] (control) a real fit is NOT annotated",
      "converged" in o and "nothing was optimised" not in o and "ON a search bound" not in o)

# ---------------------------------------------------- montecarlo -seed ----
print("\nmontecarlo: -seed obeys the same rule as `setseed`")

MCD = ".param rv=agauss(1000,100,3)\nV1 in 0 dc 1\nR1 in out {rv}\nR2 out 0 1k\n"
for s, why in (("3.7", "fractional"), ("0", "zero"), ("-3", "negative"), ("abc", "text")):
    rc, o = run(deck(MCD, f"montecarlo 20 -analysis op -spec v(out) -min 0.4 -max 0.6"
                          f" -seed {s}\n"), "ms" + re.sub(r"\W", "", s))
    check(f"[13-{s}] a {why} -seed is refused rather than silently changed",
          "-seed" in o and re.search(r"montecarlo: -seed", o) is not None,
          o.strip().splitlines()[-1][:56])

y = []
for rep in (1, 2):
    _, o = run(deck(MCD, "montecarlo 40 -analysis op -spec v(out) -min 0.495 -max 0.505"
                         " -seed 3\n"), f"mr{rep}")
    m = re.search(r"\((\d+) / (\d+) pass\)", o)
    y.append(m.group(1) if m else "?")
check("[14] (control) a legal seed still pins the run", y[0] == y[1] and y[0] != "?", f"{y}")

# ------------------------------------------------------- sweep's knob ----
print("\nsweep: a knob that names nothing is a typo, not a sweep")

for nm, knob in (("device", "@rnope[resistance]"), ("parameter", "@r1[nosuch]"),
                 ("bare name", "nosuchparam")):
    rc, o = run(deck(DIV, f"sweep {knob} 1k 5k 1k -analysis op -output v(out)\n"
                          f"setplot sweep1\nprint all"), "kb" + nm[:4])
    check(f"[15-{nm}] a nonexistent {nm} produces no curve",
          rc != 0 and len(col(o)) == 0 and "names no device" in o,
          f"rc={rc}, {len(col(o))} points")

for nm, knob, body in (("bare device", "R1", DIV), ("@form", "@r1[resistance]", DIV),
                       ("temp", "temp", DIV),
                       ("deck .param", "rv",
                        ".param rv=1k\nV1 in 0 dc 1\nR1 in out {rv}\nR2 out 0 1k\n")):
    lo = "27 31 1" if knob == "temp" else "1k 5k 1k"
    rc, o = run(deck(body, f"sweep {knob} {lo} -analysis op -output v(out)\n"
                           f"setplot sweep1\nprint all"), "ok" + re.sub(r"\W", "", nm)[:6])
    check(f"[16-{nm}] (control) a legitimate {nm} knob still sweeps",
          rc == 0 and len(col(o)) == 5, f"rc={rc}, {len(col(o))} points")

# ------------------------------------------------------ list parsing ----
print("\nsweep: a list value that cannot be used stops the sweep, not just the list")

for spec in ("list 1k inf 2k 3k", "list 1k 2k inf 3k", "list 1k nan 3k"):
    rc, o = run(deck(DIV, f"sweep @r1[resistance] {spec} -analysis op -output v(out)\n"),
                "ls" + re.sub(r"\W", "", spec)[:10])
    check(f"[17] `{spec}` is refused, naming the offending token",
          rc != 0 and "is not a value that `list` can use" in o,
          o.strip().splitlines()[-1][:56])

rc, o = run(deck(DIV, "sweep @r1[resistance] list 1k 2k 3k -analysis op -output v(out)\n"
                      "setplot sweep1\nprint all"), "lsok")
check("[18] (control) a good list is unchanged", rc == 0 and len(col(o)) == 3, f"{col(o)}")

rc, o = run(deck(DIV + "C1 out 0 1n\n",
                 "sweep @r1[resistance] list 1k 3k @c1[capacitance] list 1n 2n"
                 " -analysis op -output v(out)\nsetplot sweep1\nprint all"), "ls2k")
check("[19] (control) a two-knob sweep still parses -- the token after a list "
      "is often the next knob", rc == 0 and len(col(o)) >= 2, f"rc={rc}, {col(o)}")

# --------------------------------------------------------- -overlay ----
print("\n-overlay: keep the timepoints the runs actually took")

_, o = run(deck(RCT, "sweep @r1[resistance] list 1k 3k 5k -analysis tran 10u 200u"
                     " -output vn=v(n) -overlay\nsetplot sweepwave\n"
                     "print maximum(vn_1000) maximum(vn_3000) maximum(vn_5000)"), "ovl")
want = {"maximum(vn_1000)": "4.021751128868e-01",
        "maximum(vn_3000)": "1.712082943109e-01",
        "maximum(vn_5000)": "1.113745283463e-01"}
got = {k: scalar(o, k) for k in want}
check("[20] each overlay curve keeps its own peak (was 39% low)", got == want, f"{got}")
check("[21] ...and the message says which grid was used",
      "union of their own timepoints" in o, "")

_, o = run(deck(RCT, "sweep @r1[resistance] list 1000.0001 1000.0002 1000.0003"
                     " -analysis tran 10u 200u -output vn=v(n) -overlay\n"
                     "setplot sweepwave\ndisplay"), "ovn")
names = sorted({l.split()[0] for l in o.splitlines() if l.strip().startswith("vn_")})
check("[22] values differing past 6 digits get DISTINCT vector names",
      len(names) == 3, f"{names}")

# ------------------------------------------------- the two warnings ----
print("\nsweep: the failure warnings must not contradict each other")

BADP = ("V1 a 0 dc 1\nRs a n 1k\nD1 n 0 dm\n.model dm d(is=1e-14)\n")
_, o = run(deck(DIV, "sweep @r1[resistance] list 1k 2k 3k -analysis op -output vv=v(nosuch)\n"),
           "wz")
check("[23] an output that never resolves is still reported as zero-filled",
      "never resolved" in o or "entries are zero" in o, o.strip().splitlines()[-1][:56])

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
