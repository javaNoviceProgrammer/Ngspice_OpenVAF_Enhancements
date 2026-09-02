#!/usr/bin/env python3
"""Enhancement-535: the osdimc trial policy for loop commands -- and the hunt
round that made it honest.

E-530/531 gave `.option osdimc` its per-run draw semantics; this enhancement
teaches the LOOP commands a policy (HOLD one sample per sweep/optimize/wcd/
loadpull, PRESERVE the sequence across a command's own internal resets,
SCALE sigmas for highsigma) and fixes what the hunt round proved wrong with
the first cut:

  * draws that could not land at run start (the nominal table is empty right
    after an internal re-source) are applied at the END of OSDIsetup -- after
    the setup loops resolve deck defaults, BEFORE OSDItemp evaluates the
    init-resident code. The first cut applied them at the end of OSDItemp:
    a parameter feeding only a hoisted assignment (geff = 1/rr) was drawn in
    STORAGE but nominal in the PHYSICS -- every montecarlo sample computed
    the nominal while logging distinct draws (hunt bug 1);
  * a machine write (a sweep point push, a `.dc` level, a `sens`
    perturbation) PINS its statistical parameter, so the trial's draw applier
    leaves the written value alone until the bracket ends. The first cut
    re-applied nominal+delta over every machine write: `.dc @n1[dr]` and
    `sweep @n1[dr]` returned the SAME point N times, `sens` reported ~1e-14
    where -2.5e-4 was the answer (hunt bugs 13/14);
  * the baseline never draws, EXPLICITLY (trial < 2 guard) -- not by the
    accident of an empty table, which an optimize flow or an
    `unset osdimc`/`set osdimc` toggle defeats (hunt bug 15);
  * init-resident $strobe output prints for EVERY point of a `.dc temp`
    sweep (OSDItemp re-enters setup-phase display), and `$monitor`
    change-detection history resets per ANALYSIS, so a new run's first
    accepted point is never suppressed by the previous run's text
    (hunt bugs 3/4).

What this suite pins (mcseed=7 throughout; every expectation is either
closed-form from the same run's parameter readbacks, or the exact
deterministic draw of the pinned seed):

  [1]  both fixture models compile clean
  [2]  the first run is the exact nominal baseline
  [3]  run 2 draws, and the physics matches the drawn values it reports
  [4]  a hoisted-only parameter moves the physics on the plain-run path
  [5]  ...and through montecarlo's internal-reset path (BUG 1's pin)
  [6]  montecarlo samples differ (the PRESERVE leg keeps the sequence alive)
  [7]  `.dc` of a statistical parameter SWEEPS it under a drawn trial
  [8]  `sweep` of a statistical parameter likewise (pin beats re-apply)
  [9]  a whole sweep is ONE held sample (same draw at every point)
  [10] `sens` of statistical parameters is finite and closed-form correct
  [11] the baseline guard: an option toggle cannot make trial 1 draw
  [12] a USER reset after a sweep restarts the sequence at the baseline

Enhancement-536 closed the known-open ledger E-535 shipped; checks [13]-[18]
pin those repairs, each one a former ledger entry with its own repro:

  [13] the hold is a DEPTH -- a loop command nested as another's -analysis
       no longer releases the outer bracket (it drew a fresh trial per
       optimizer evaluation before, the stochastic objective again)
  [14] optimize's internal resets PRESERVE the sequence, like sweep's
  [15] optimize -center replays a trial window per candidate: its inner
       Monte-Carlo samples osdimc variation AND is deterministic
  [16] the clash guard catches a wildcard covering a source's principal
       parameter, and restores the knob
  [17] a failed LATER .dc nest level restores the earlier applied levels
  [18] highsigma -scale weights the OSDI draws it inflates (P(fail) was the
       raw inflated failure fraction)

Enhancement-537 -- a second hunt over the shipped work -- adds [19]-[28]:

  [19] a degenerate importance weight is CALLED OUT (effective sample size),
       not printed as though it were an estimate: inflating many statistical
       dimensions at once collapses the weights, and twenty bystander devices
       that cannot affect the metric took a true P(fail) of 0.297 to 2.5e-11
  [20] highsigma EXCLUDES samples whose analysis never solved, and says so --
       it used to count them using the previous sample's metric, biasing the
       rare-failure probability LOW because -scale makes failures cluster in
       the tail
  [21] a weighted mean is clamped into [0,1] (it printed 1.0445), with the
       equivalent sigma reported n/a at the boundary rather than a 0.000 that
       reads as P = 0.5
  [22] a metric that never varied is NAMED, not blamed on resolution ("increase
       -scale or N" sent the user to chase a mis-typed node with a bigger run)
  [23] aging's machine-computed dose does not recentre a statistical nominal
       (E-531's rule: only what the USER typed recentres)
  [24] montecarlo N draws N samples in every session state -- it used to spend
       the first on the nominal baseline and fold that fixed point into the
       yield
  [25] -seed varies the osdimc draws, so independent replications really are
       independent (they were byte-identical, making an estimate look stable
       when nothing had been re-sampled)
  [26] -lhs says it does not cover osdimc draws (it silently did nothing for
       model-declared variability)
  [27] a refused command leaves its result variables UNSET instead of showing
       the previous run's answer to the scripts they exist for
  [28] an out-of-range altermod refuses instead of calling controlled_exit --
       a typo used to destroy the session once a dc/tran had run

Enhancement-538 makes `-scale` scopeable, which is what makes highsigma
usable on a deck with more than a couple of statistical dimensions; [29]-[33]
pin it:

  [29] scoping -scale to the parameter the metric turns on takes a collapsed
       deck from 3.35e-05 to 0.2967 against a true 0.29670536
  [30] and the weight counts EXACTLY the inflated dimensions: a scoped run on
       a deck with twenty bystander devices equals, bit for bit, the same deck
       without them
  [31] -inflate accepts the @owner[param] accessor as well as a bare name
  [32] a spec matching no statistical parameter is reported (it inflated
       nothing, so the run sampled the nominal spread)
  [33] a malformed spec is refused before the run, not silently ignored

Not pinned here, by nature: the interrupt repairs (an interrupted command no
longer leaks the hold, the sigma inflation, the sampling mode, ft_optimizing
or the progress bar; and the loop commands now poll ft_intrpt). They need a
signal delivered to a live interactive process mid-command, which this
batch harness cannot stage; they are verified by hand and described in the
enhancement.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402
check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_model(stem):
    r = subprocess.run([OPENVAF, f"{stem}.va", "-o", f"{stem}.osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def run(model, script, timeout=300):
    """One deck: v1 -- n1(model mm) -- r1 1k to ground, osdimc on, mcseed 7."""
    p = os.path.join(HERE, "_mp.cir")
    with open(p, "w") as f:
        f.write("mcpolicy\n.option osdimc\nv1 1 0 dc 1\nn1 1 2 mm\nr1 2 0 1k\n"
                ".model mm %s\n.control\npre_osdi %s.osdi\nset mcseed = 7\n"
                "%s\n.endc\n.end\n" % (model, model, script))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "HANG", ""
    finally:
        if os.path.exists(p):
            os.remove(p)


def seq(out, name):
    """Every printed value of `name`, in order."""
    pat = re.escape(name) + r"\s*=\s*([-\d.eE+]+)"
    return [float(x) for x in re.findall(pat, out)]


def trials(out):
    """The distinct osdimc trial numbers that drew, in first-seen order
    (needs `set osdimc_verbose`)."""
    seen = []
    for t in re.findall(r"osdimc: trial (\d+):", out):
        if t not in seen:
            seen.append(t)
    return seen


def main():
    # [1] fixtures compile
    rc1, o1 = compile_model("mcres")
    rc2, o2 = compile_model("mchoist")
    check("both fixture models compile clean", rc1 == 0 and rc2 == 0
          and "warning" not in (o1 + o2).lower(), f"rc={rc1},{rc2}")

    # [2]+[3] baseline exact, then a drawn run whose physics matches its own
    # readbacks: v(2) = 1k/(r+dr+1k) from the SAME run's r and dr
    rc, out = run("mcres", "op\nprint v(2) @mm[r] @n1[dr]\n"
                           "op\nprint v(2) @mm[r] @n1[dr]")
    v, r, dr = seq(out, "v(2)"), seq(out, "@mm[r]"), seq(out, "@n1[dr]")
    check("run 1 is the exact nominal baseline",
          rc == 0 and len(v) == 2 and v[0] == 0.5 and r[0] == 1000.0
          and dr[0] == 0.0, f"v={v[:1]} r={r[:1]} dr={dr[:1]}")
    ok3 = (rc == 0 and len(v) == 2 and (r[1], dr[1]) != (1000.0, 0.0)
           and abs(v[1] - 1000.0 / (r[1] + dr[1] + 1000.0)) < 1e-6)
    check("run 2 draws and the physics matches the reported draw", ok3,
          f"v={v[1] if len(v) > 1 else '?'} closed-form="
          f"{1000.0 / (r[1] + dr[1] + 1000.0) if len(r) > 1 else '?'}")

    # [4] hoisted-only parameter, plain-run path: trial 2 moves the node
    rc, out = run("mchoist", "op\nprint v(2)\nop\nprint v(2)")
    v = seq(out, "v(2)")
    check("a hoisted-only parameter moves the physics on the plain-run path",
          rc == 0 and len(v) == 2 and v[0] == 0.5 and abs(v[1] - 0.5) > 1e-3,
          f"v={v}")

    # [5] BUG 1's pin: montecarlo runs its samples through an internal
    # reset+run, so the draw has to land through OSDIsetup's late apply. The
    # metric only dips below 0.497 when the draw actually reaches the HOISTED
    # init code; if it lands too late every sample computes the nominal 0.5 and
    # nothing violates. So "at least one violation" is exactly the property,
    # and 0 is the bug. (E-537 hunt J: montecarlo no longer spends a sample on
    # the nominal baseline, so both samples here are draws.)
    rc, out = run("mchoist",
                  "montecarlo 2 -analysis op -spec v(2) -min 0.497")
    m = re.search(r"spec 1 \(v\(2\)\): (\d+) violation", out)
    check("montecarlo's internal-reset path reaches init-resident code (bug 1)",
          rc == 0 and m and int(m.group(1)) >= 1,
          f"violations={m.group(1) if m else '?'} (want >=1; the bug gave 0)")

    # [6] the PRESERVE leg: the samples must DIFFER from each other across the
    # internal resets. A dead sequence -- every sample falling back to the same
    # nominal -- scores all-or-nothing against a threshold that sits inside the
    # spread, so a count strictly between 0 and N is the property. Pinning one
    # exact count instead made this brittle to how many trials the command
    # spends (E-537 hunt J changed that legitimately).
    rc, out = run("mcres", "montecarlo 3 -analysis op -spec v(2) -max 0.5005")
    m = re.search(r"spec 1 \(v\(2\)\): (\d+) violation", out)
    nv = int(m.group(1)) if m else -1
    check("montecarlo samples differ across internal resets (preserve)",
          rc == 0 and 0 < nv < 3,
          f"violations={nv} of 3 (want strictly between 0 and 3: all-same "
          f"samples would score 0 or 3)")

    # [7] `.dc` of a statistical parameter under a DRAWN trial: the machine
    # write pins dr, the held r draw stays applied -- the curve is
    # 1k/(r + dr_i + 1k) against the run's own r readback, not one point
    # repeated three times.
    rc, out = run("mcres", "op\nop\ndc @n1[dr] 0 1000 500\n"
                           "print dc1.v(2)\nprint @mm[r]")
    r3 = seq(out, "@mm[r]")
    rows = [float(x) for x in re.findall(
        r"^\s*\d+\s+\S+\s+([-\d.]+e[-+]\d+)", out, re.M)]
    ok7 = (rc == 0 and len(r3) == 1 and len(rows) == 3
           and all(abs(g - 1000.0 / (r3[0] + d + 1000.0)) < 1e-6
                   for g, d in zip(rows, (0.0, 500.0, 1000.0)))
           and rows[0] > rows[1] > rows[2])
    check("`.dc` of a statistical parameter sweeps it under a drawn trial",
          ok7, f"curve={rows} r={r3}")

    # [8] the `sweep` command's per-point runs re-apply the held trial; the
    # pin still lets the pushed dr win at every point, first included.
    rc, out = run("mcres", "op\nop\n"
                           "sweep @n1[dr] lin 3 0 1000 -analysis op -output v(2)\n"
                           "print sweep1.v(2)\nprint @mm[r]")
    r3 = seq(out, "@mm[r]")
    rows = [float(x) for x in re.findall(
        r"^\s*\d+\s+([-\d.]+e[-+]\d+)", out, re.M)]
    ok8 = (rc == 0 and len(r3) == 1 and len(rows) == 3
           and all(abs(g - 1000.0 / (r3[0] + d + 1000.0)) < 1e-6
                   for g, d in zip(rows, (0.0, 500.0, 1000.0)))
           and rows[0] > rows[1] > rows[2])
    check("`sweep` of a statistical parameter sweeps it (pin beats re-apply)",
          ok8, f"curve={rows} r={r3}")

    # [9] HOLD: one sweep, one sample -- every point reads the same drawn r
    rc, out = run("mcres", "op\n"
                           "sweep v1 lin 3 0.8 1.2 -analysis op -output @mm[r]\n"
                           "print sweep1.@mm[r]")
    rows = [float(x) for x in re.findall(
        r"^\s*\d+\s+([-\d.]+e[-+]\d+)", out, re.M)]
    check("a whole sweep is ONE held sample (same draw at every point)",
          rc == 0 and len(rows) == 3 and rows[0] == rows[1] == rows[2]
          and rows[0] != 1000.0, f"@mm[r] per point = {rows}")

    # [10] `sens` under a drawn trial: dv(2)/dr = -1k/(r+dr+1k)^2, from the
    # run's own readbacks -- taken AFTER sens, which is itself a run-class
    # command and computes at the trial it draws. The first cut clobbered
    # the perturbations and reported ~1e-14 here.
    rc, out = run("mcres", "op\nop\nsens v(2)\nprint all\nprint @mm[r] @n1[dr]")
    r3, dr3 = seq(out, "@mm[r]"), seq(out, "@n1[dr]")
    sr = seq(out, "n1:r")
    if r3 and dr3:
        expect = -1000.0 / (r3[0] + dr3[0] + 1000.0) ** 2
    ok10 = (rc == 0 and len(sr) == 1 and r3 and dr3
            and abs(sr[0] - expect) < 0.01 * abs(expect))
    check("`sens` of a statistical parameter is closed-form correct", ok10,
          f"n1:r={sr} expect={expect if r3 and dr3 else '?'}")

    # [11] the explicit baseline guard: after unset/set the table is still
    # populated, and the old empty-table heuristic drew on "trial 1"
    rc, out = run("mcres", "op\nop\nunset osdimc\nop\nprint v(2)\n"
                           "set osdimc\nop\nprint v(2)\nop\nprint v(2)")
    v = seq(out, "v(2)")
    check("an option toggle cannot make the trial-1 baseline draw (bug 15)",
          rc == 0 and len(v) == 3 and v[0] == 0.5 and v[1] == 0.5
          and abs(v[2] - 0.5) > 1e-4, f"v={v}")

    # [12] a USER reset restarts at the baseline, sweep or no sweep before it
    rc, out = run("mcres", "op\nop\n"
                           "sweep v1 lin 3 0.8 1.2 -analysis op -output v(2)\n"
                           "reset\nop\nprint v(2) @mm[r] @n1[dr]")
    v, r, dr = seq(out, "v(2)"), seq(out, "@mm[r]"), seq(out, "@n1[dr]")
    check("a USER reset after a sweep restarts at the nominal baseline",
          rc == 0 and v and v[-1] == 0.5 and r and r[-1] == 1000.0
          and dr and dr[-1] == 0.0, f"v={v[-1:]} r={r[-1:]} dr={dr[-1:]}")

    # ---- E-536: the hunt round's known-open repairs ---------------------

    # [13] bug 16: the hold is a DEPTH, not a flag. A loop command nested as
    # another's -analysis (optimize over a swept-curve objective) must stay
    # ONE sample -- the inner sweep's release must not un-hold the optimizer.
    rc, out = run("mcres", "set osdimc_verbose\nop\n"
                  "optimize -param r1 1000 500 2000 "
                  "-analysis sweep v1 lin 2 0.9 1.1 "
                  "-minimize (v(2)-0.4)^2 -maxiter 4", timeout=600)
    t = trials(out)
    check("nested loop commands hold ONE osdimc sample (bug 16)",
          rc == 0 and t == ["2"], f"trials drawn = {t} (want ['2'])")

    # [14] bug 8, -dparam: opt_run_cmd's per-evaluation reset PRESERVES the
    # held trial, so every evaluation sees the same sample (not the nominal).
    rc, out = run("mcres", "set osdimc_verbose\nop\nop\n"
                  "optimize -dparam rl 1000 500 2000 -analysis op "
                  "-minimize (v(2)-0.4)^2 -maxiter 4", timeout=600)
    # trial 2 is op2's draw; the whole optimize holds trial 3 across its resets
    inopt = out.split("optimize", 1)[-1] if "optimize" in out else out
    topt = trials(inopt)
    check("optimize -dparam holds one trial across its resets (bug 8)",
          rc == 0 and len(topt) == 1 and topt != ["1"],
          f"trials inside optimize = {topt} (want a single non-baseline trial)")

    # [15] bug 8, -center: the inner Monte-Carlo REPLAYS a trial window per
    # candidate -- osdimc variation is present (>1 distinct trial) and the
    # window repeats (a rewound counter revisits the same trials). A dead
    # sequence would draw nothing at all.
    rc, out = run("mcres", "set osdimc_verbose\nop\n"
                  "optimize -param r1 1000 800 1200 -analysis op -center "
                  "-samples 3 -spec v(2) -max 0.55 -maxiter 3", timeout=600)
    tc = trials(out)
    # the same low trial numbers recur across candidates -> counter rewinds
    nums = [int(x) for x in re.findall(r"osdimc: trial (\d+):", out)]
    repeats = len(nums) > len(set(nums))
    check("optimize -center samples osdimc variation, replayed per candidate "
          "(bug 8)", rc == 0 and len(tc) >= 2 and repeats,
          f"distinct trials={tc}, replayed={repeats}")

    # [16] bug 9: a wildcard INSTANCE level and a source level that move the
    # same knob are refused, and v1 is left on its pre-sweep value. Read the
    # SOURCE knob directly (`@v1[dc]`), not a branch current -- every run
    # under osdimc draws a fresh trial, so the current legitimately moves
    # while the knob under test must not.
    rc, out = run("mcres",
                  "op\nprint @v1[dc]\n"
                  "dc v1 0.5 1.5 0.5 @#*[dc] 0 2 1\n"
                  "op\nprint @v1[dc]")
    dcv = seq(out, "@v1[dc]")
    check("a wildcard level clashing with a source level is refused (bug 9)",
          rc == 0 and "same knob" in out and len(dcv) == 2
          and dcv[0] == 1.0 and dcv[1] == 1.0,
          f"same-knob refused={'same knob' in out} @v1[dc]={dcv} (want 1,1)")

    # [17] bug 10: a failure at a LATER .dc nest level restores the earlier
    # level resolution already applied -- v1 must return to 1 V, not stay
    # parked at the refused sweep's start value.
    rc, out = run("mcres",
                  "op\nprint @v1[dc]\n"
                  "dc v1 0.5 1.5 0.5 @n1[nonesuch] 1 2 0.5\n"
                  "op\nprint @v1[dc]")
    dcv = seq(out, "@v1[dc]")
    check("a failed later .dc level restores the earlier level (bug 10)",
          rc == 0 and len(dcv) == 2 and dcv[0] == 1.0 and dcv[1] == 1.0,
          f"@v1[dc] before/after = {dcv} (want 1,1; the bug left 0.5)")

    # [18] bug 7: highsigma -scale weights the inflated OSDI draws. The
    # REPORTED P(fail) (importance-weighted) must sit well below the raw
    # inflated failure fraction -- the weight pulls the lambda-inflated tail
    # back toward the true probability. Deterministic (seeded).
    rc, out = run("mchoist",
                  "op\nhighsigma 1000 -scale 3 -seed 11 -analysis op "
                  "-metric v(2) -min 0.487", timeout=600)
    mfail = re.search(r"failures observed\s*:\s*(\d+)\s*/\s*(\d+)", out)
    mp = re.search(r"P\(fail\)\s*:\s*([-\d.eE+]+)", out)
    if mfail and mp:
        raw = int(mfail.group(1)) / int(mfail.group(2))
        pf = float(mp.group(1))
    ok18 = (rc == 0 and mfail and mp and pf < raw * 0.85
            and abs(pf - 0.297) < 0.06)
    check("highsigma -scale weights the inflated OSDI draws (bug 7)", ok18,
          f"P(fail)={mp.group(1) if mp else '?'} raw_frac="
          f"{raw:.3f} true~0.297" if mfail and mp else "no summary")

    # ---- E-537: the second hunt round's findings ------------------------

    # [19] hunt E: the importance weights degenerate as -scale inflates more
    # dimensions. Bystander devices on a DISCONNECTED subcircuit cannot affect
    # the metric, yet they used to drag a true P(fail) of 0.297 to 2.5e-11 with
    # no warning. The estimate is still poor -- that is inherent -- but it must
    # now SAY the weights collapsed instead of presenting the number plainly.
    with open(os.path.join(HERE, "_by.cir"), "w") as f:
        f.write("bystander\n.option osdimc\nv1 1 0 dc 1\nn1 1 2 mm\nr1 2 0 1k\n"
                ".model mm mchoist rr=1000\n")
        for i in range(20):
            f.write("nx%d %d %d bys\n" % (i, 10 + i, 11 + i))
        f.write("vb 10 0 dc 0\nrb 30 0 1k\n.model bys mcres r=1000\n"
                ".control\npre_osdi mchoist.osdi\npre_osdi mcres.osdi\n"
                "set mcseed = 7\nop\n"
                "highsigma 200 -scale 3 -seed 11 -analysis op -metric v(2) "
                "-min 0.487\nquit\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "_by.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=900, errors="replace")
    o = r.stdout + r.stderr
    os.remove(os.path.join(HERE, "_by.cir"))
    mess = re.search(r"effective sample size of ([\d.]+) out of (\d+)", o)
    check("a degenerate importance weight is called out, not just printed "
          "(hunt E)",
          r.returncode == 0 and "weights have collapsed" in o and mess
          and float(mess.group(1)) < 0.10 * float(mess.group(2)),
          f"ESS={mess.group(1) + '/' + mess.group(2) if mess else 'no note'}")

    # [20] hunt B: a sample whose analysis never solved has no metric; it must
    # be excluded and reported, as montecarlo has done since E-438. The deck
    # drives an OSDI `r ... from (0:inf)` negative, which fails the run.
    with open(os.path.join(HERE, "_bb.cir"), "w") as f:
        f.write("failing samples\n.param rr = agauss(1000, 900, 1)\n"
                "v1 1 0 dc 1\nn1 1 2 mm\nr2 2 0 1k\n.model mm mcres r={rr}\n"
                ".control\npre_osdi mcres.osdi\nset mcseed = 3\n"
                "highsigma 60 -scale 3 -seed 3 -analysis op -metric v(2) "
                "-max 0.6\nquit\n.endc\n.end\n")
    rb = subprocess.run([NGSPICE, "-b", "_bb.cir"], cwd=HERE, capture_output=True,
                        text=True, timeout=900, errors="replace")
    rc, out = rb.returncode, rb.stdout + rb.stderr
    os.remove(os.path.join(HERE, "_bb.cir"))
    mex = re.search(r"(\d+) of (\d+) samples? failed to simulate", out)
    mtot = re.search(r"failures observed\s*:\s*\d+\s*/\s*(\d+)", out)
    check("highsigma excludes samples that did not solve, and says so (hunt B)",
          rc == 0 and mex and mtot
          and int(mex.group(1)) > 0
          and int(mtot.group(1)) == int(mex.group(2)) - int(mex.group(1)),
          f"excluded={mex.group(0) if mex else 'NONE -- deck did not fail any'}; "
          f"denominator={mtot.group(1) if mtot else '?'} "
          f"(must be total minus excluded, and the old code used the total)")

    # [21] hunt M: a weighted mean is not automatically a probability. With a
    # spec every sample violates, the true answer is exactly 1 -- the estimate
    # must be clamped into [0,1] and the equivalent sigma reported as n/a
    # rather than the old 0.000, which reads as P = 0.5.
    rc, out = run("mchoist", "op\nhighsigma 200 -scale 3 -seed 11 -analysis op "
                             "-metric v(2) -min 10", timeout=900)
    mp = re.search(r"P\(fail\)\s*:\s*([-\d.eE+]+)", out)
    pv = float(mp.group(1)) if mp else -1.0
    # every sample violates, so the estimate must never exceed 1 (it printed
    # 1.0445 before); at the boundary the sigma must read n/a, not 0.000.
    at_bound = (pv >= 1.0 - 1e-12)
    check("an all-fail case reports a probability, never >1 (hunt M)",
          rc == 0 and mp and 0.0 <= pv <= 1.0
          and (not at_bound or "equivalent sigma  : n/a" in out),
          f"P(fail)={mp.group(1) if mp else '?'} (<=1 required), "
          f"at-boundary={at_bound}, sigma-n/a={'equivalent sigma  : n/a' in out}")

    # [22] hunt L: a metric that never varies is a mis-typed node far more often
    # than a rare failure, and the old hint sent the user to spend a bigger run
    # chasing it. montecarlo has had this check since E-501.
    rc, out = run("mcres", "op\nhighsigma 20 -scale 2 -analysis op "
                           "-metric v(nosuchnode) -max 0.9", timeout=900)
    check("a metric that never varied is named, not blamed on resolution "
          "(hunt L)",
          rc == 0 and "every sample gave the SAME metric value" in out
          and "increase -scale or N" not in out
          and "equivalent sigma  : n/a" in out,
          f"no-variance note={'every sample gave the SAME' in out}, "
          f"misleading hint={'increase -scale or N' in out}, "
          f"sigma n/a at P=0={'equivalent sigma  : n/a' in out}")

    # [23] hunt G: aging's dose is MACHINE-computed, so it must not recenter a
    # statistical nominal the way a user's `alter` does (E-531's rule). The
    # fixture's aging parameter carries (* std *), so a recentre is visible in
    # the verbose "(nominal ...)" of every later draw.
    with open(os.path.join(HERE, "_ag.cir"), "w") as f:
        f.write("aging recentre\n.option osdimc\nv1 1 0 dc 1\nn1 1 2 am\n"
                "r1 2 0 1k\n.model am agestat r=1000\n.control\n"
                "pre_osdi agestat.osdi\nset mcseed = 7\nset osdimc_verbose\n"
                "op\nop\naging 1e9 rate srate param dr\nop\nop\n"
                "quit\n.endc\n.end\n")
    compile_model("agestat")
    ra = subprocess.run([NGSPICE, "-b", "_ag.cir"], cwd=HERE, capture_output=True,
                        text=True, timeout=900, errors="replace")
    oa = ra.stdout + ra.stderr
    os.remove(os.path.join(HERE, "_ag.cir"))
    noms = set(re.findall(r"n1:dr = [-\d.e+]+ \(nominal ([-\d.e+]+)\)", oa))
    check("aging's dose does not recentre a statistical nominal (hunt G)",
          ra.returncode == 0 and noms and noms == {"0"},
          f"nominals seen after aging = {sorted(noms) if noms else 'none'} "
          f"(want only 0)")

    # [24] hunt J: N samples must be N DRAWS regardless of session history --
    # the banner says "N random samples", and the yield and its interval must
    # not fold in a deterministic point.
    rc1, o1 = run("mcres", "set osdimc_verbose\n"
                           "montecarlo 4 -analysis op -spec v(2) -max 0.9")
    rc2, o2 = run("mcres", "set osdimc_verbose\nop\n"
                           "montecarlo 4 -analysis op -spec v(2) -max 0.9")
    n1 = len(re.findall(r"osdimc: trial \d+: mm:r", o1))
    n2 = len(re.findall(r"osdimc: trial \d+: mm:r", o2))
    check("montecarlo N draws N samples in every session state (hunt J)",
          rc1 == 0 and rc2 == 0 and n1 == 4 and n2 == 4,
          f"draws: fresh={n1}, after an op={n2} (want 4 and 4; the bug gave 3)")

    # [25] hunt P: varying -seed is how one checks a Monte-Carlo estimate is
    # stable. It keyed only the netlist PRNG, so every "independent"
    # replication returned the SAME osdimc samples.
    rc1, o1 = run("mcres", "set osdimc_verbose\n"
                           "montecarlo 4 -analysis op -seed 1 -spec v(2) -max 0.9")
    rc2, o2 = run("mcres", "set osdimc_verbose\n"
                           "montecarlo 4 -analysis op -seed 999 -spec v(2) -max 0.9")
    d1 = re.findall(r"mm:r = ([\d.]+)", o1)
    d2 = re.findall(r"mm:r = ([\d.]+)", o2)
    check("-seed varies the osdimc draws, so replications are independent "
          "(hunt P)",
          rc1 == 0 and rc2 == 0 and d1 and d2 and d1 != d2,
          f"seed 1 -> {d1[:2]}, seed 999 -> {d2[:2]} (were byte-identical)")

    # [26] hunt O: -lhs stratifies the netlist's own draws only. Say so on a
    # deck whose variability is declared in the models, which is exactly where
    # a user would expect it to apply.
    rc, out = run("mcres", "montecarlo 4 -analysis op -lhs -spec v(2) -max 0.9")
    check("-lhs says it does not cover osdimc draws (hunt O)",
          rc == 0 and "does NOT cover" in out and "osdimc" in out,
          f"note present={'does NOT cover' in out}")

    # [27] hunt H: the result variables exist for scripting, so a command that
    # REFUSES must leave them unset rather than showing the last run's answer.
    with open(os.path.join(HERE, "_hh.cir"), "w") as f:
        f.write("wcd result vars\n.param rr = agauss(1000, 60, 1)\n"
                "v1 1 0 dc 1\nr1 1 2 {rr}\nr2 2 0 1k\n.control\n"
                "wcd -metric v(2) -max 0.53 -analysis op -maxiter 8\n"
                "echo GOOD=$wcd_beta\n"
                "wcd -metric v(nosuchnode) -max 0.9 -analysis op -maxiter 8\n"
                "echo AFTER=$wcd_beta\nquit\n.endc\n.end\n")
    rh = subprocess.run([NGSPICE, "-b", "_hh.cir"], cwd=HERE, capture_output=True,
                        text=True, timeout=900, errors="replace")
    rc, out = rh.returncode, rh.stdout + rh.stderr
    os.remove(os.path.join(HERE, "_hh.cir"))
    mg = re.search(r"^GOOD=(\S*)$", out, re.M)
    ma = re.search(r"^AFTER=(\S*)$", out, re.M)
    check("a refused command leaves its result variables unset (hunt H)",
          rc == 0 and mg and mg.group(1) and ma and not ma.group(1),
          f"after a good run: {mg.group(1) if mg else '?'!r}; "
          f"after a refusal: {ma.group(1) if ma else '?'!r} (want empty)")

    # [28] hunt N: a mistyped MODEL parameter value used to call controlled_exit
    # once a dc/tran had run -- the whole session gone to a typo. It must
    # refuse and stay alive, as `alter` and every built-in already did.
    rc, out = run("mcres", "dc v1 0 1 0.5\naltermod mm r = -500\n"
                           "echo SURVIVED_THE_TYPO")
    check("an out-of-range altermod refuses instead of killing the session "
          "(hunt N)",
          rc == 0 and "SURVIVED_THE_TYPO" in out
          and "did not take effect" in out,
          f"survived={'SURVIVED_THE_TYPO' in out}, "
          f"refusal explained={'did not take effect' in out}")

    # ---- E-538: -scale is scopeable, so highsigma is usable -------------

    def bystander_deck(name, inflate):
        """The E-537 degenerate deck: the metric depends only on n1's rr, and
        twenty statistically-declared bystanders sit on a DISCONNECTED
        subcircuit where they cannot affect it."""
        with open(os.path.join(HERE, name), "w") as f:
            f.write("bystander\n.option osdimc\nv1 1 0 dc 1\nn1 1 2 mm\n"
                    "r1 2 0 1k\n.model mm mchoist rr=1000\n")
            for i in range(20):
                f.write("nx%d %d %d bys\n" % (i, 10 + i, 11 + i))
            f.write("vb 10 0 dc 0\nrb 30 0 1k\n.model bys mcres r=1000\n"
                    ".control\npre_osdi mchoist.osdi\npre_osdi mcres.osdi\n"
                    "set mcseed = 7\nop\n"
                    "highsigma 2000 -scale 3 -seed 11 %s-analysis op "
                    "-metric v(2) -min 0.487\nquit\n.endc\n.end\n" % inflate)

    def hs_run(name):
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=1800, errors="replace")
        o = r.stdout + r.stderr
        os.remove(os.path.join(HERE, name))
        m = re.search(r"P\(fail\)\s*:\s*([-\d.eE+]+)", o)
        return r.returncode, o, (float(m.group(1)) if m else -1.0)

    # [29] the headline: scoping -scale to the one parameter the metric turns
    # on makes an unusable deck estimate correctly. True P(fail) = 0.29670536
    # by quadrature; unscoped this deck reports ~1e-9.
    bystander_deck("_s1.cir", "")
    rc_u, out_u, p_u = hs_run("_s1.cir")
    bystander_deck("_s2.cir", "-inflate rr ")
    rc_s, out_s, p_s = hs_run("_s2.cir")
    TRUE_P = 0.29670536
    check("scoping -scale makes a degenerate deck estimate correctly (E-538)",
          rc_u == 0 and rc_s == 0
          and p_u >= 0 and p_u < 0.5 * TRUE_P          # unscoped: collapsed
          and abs(p_s - TRUE_P) < 0.05                 # scoped: on target
          and "weights have collapsed" in out_u
          and "weights have collapsed" not in out_s,
          f"unscoped={p_u:.4g} (collapsed, flagged={'weights have collapsed' in out_u}), "
          f"scoped={p_s:.4g} vs true {TRUE_P:.5g}")

    # [30] the weight must count EXACTLY the inflated dimensions, so scoping a
    # deck down to its only relevant parameter must reproduce the same answer
    # as a deck that never had the bystanders at all.
    with open(os.path.join(HERE, "_s3.cir"), "w") as f:
        f.write("no bystanders\n.option osdimc\nv1 1 0 dc 1\nn1 1 2 mm\n"
                "r1 2 0 1k\n.model mm mchoist rr=1000\n.control\n"
                "pre_osdi mchoist.osdi\nset mcseed = 7\nop\n"
                "highsigma 2000 -scale 3 -seed 11 -analysis op -metric v(2) "
                "-min 0.487\nquit\n.endc\n.end\n")
    rc_b, _, p_b = hs_run("_s3.cir")
    check("a scoped run matches the deck without the extra dimensions (E-538)",
          rc_b == 0 and p_s > 0 and abs(p_s - p_b) < 1e-9,
          f"scoped-with-bystanders={p_s:.6g}, without-bystanders={p_b:.6g} "
          f"(must be identical: the bystanders now cost nothing)")

    # [31] the accessor spellings, and an unscoped run left untouched
    bystander_deck("_s4.cir", "-inflate @mm[rr] ")
    rc_a, _, p_a = hs_run("_s4.cir")
    check("-inflate accepts the @owner[param] spelling (E-538)",
          rc_a == 0 and abs(p_a - p_s) < 1e-9,
          f"@mm[rr] -> {p_a:.6g}, bare rr -> {p_s:.6g} (same parameter)")

    # [32] a spec naming nothing inflated nothing, so the run measured the
    # NOMINAL spread -- that must be said, not reported as a scoped result.
    bystander_deck("_s5.cir", "-inflate nosuchparam ")
    rc_n, out_n, _ = hs_run("_s5.cir")
    check("an -inflate spec that matched nothing is reported (E-538)",
          rc_n == 0 and "matched a statistical parameter" in out_n,
          f"note present={'matched a statistical parameter' in out_n}")

    # [33] a malformed spec is refused before the run, not silently ignored
    rc_m, out_m = run("mcres", "highsigma 20 -scale 2 -inflate @bad[ "
                               "-analysis op -metric v(2) -max 0.9")
    # (the deck then runs no analysis at all, so batch mode exits non-zero --
    # that is the refusal working, not a failure of this check)
    check("a malformed -inflate spec is refused, not ignored (E-538)",
          "is not a parameter name" in out_m and "P(fail)" not in out_m,
          f"refused={'is not a parameter name' in out_m}, "
          f"ran anyway={'P(fail)' in out_m}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: "
          f"{passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
