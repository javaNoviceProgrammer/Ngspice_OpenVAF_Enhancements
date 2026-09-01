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
    # reset+run, so the trial-2 draw lands through OSDIsetup's late apply.
    # Sample 1 = the nominal baseline (0.5), sample 2 = trial 2, which at
    # mcseed 7 gives v(2) = 0.49240 for this deck. -min 0.497 is violated by
    # the drawn sample only: exactly 1 when the draw reaches the hoisted
    # init code, 0 when it lands too late (the bug this run pins).
    rc, out = run("mchoist",
                  "montecarlo 2 -analysis op -spec v(2) -min 0.497")
    m = re.search(r"spec 1 \(v\(2\)\): (\d+) violation", out)
    check("montecarlo's internal-reset path reaches init-resident code (bug 1)",
          rc == 0 and m and m.group(1) == "1",
          f"violations={m.group(1) if m else '?'} (want 1; the bug gave 0)")

    # [6] the PRESERVE leg: samples keep drawing across internal resets.
    # Trials 1..3 at mcseed 7 give v(2) = 0.5, 0.49511, 0.50077; only the
    # third exceeds 0.5005. A dead sequence (every sample the baseline)
    # scores 0.
    rc, out = run("mcres", "montecarlo 3 -analysis op -spec v(2) -max 0.5005")
    m = re.search(r"spec 1 \(v\(2\)\): (\d+) violation", out)
    check("montecarlo samples differ across internal resets (preserve)",
          rc == 0 and m and m.group(1) == "1",
          f"violations={m.group(1) if m else '?'} (want 1)")

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

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: "
          f"{passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
