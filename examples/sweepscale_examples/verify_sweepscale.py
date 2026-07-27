#!/usr/bin/env python3
"""Enhancement-343: `cp_getvar()` synthesized the whole user-variable list.

`cp_getvar(name, ...)` looks up ONE name, but its first statement built all five
synthetic user variables -- `$plots`, `$curplot`, `$curplottitle`,
`$curplotname`, `$curplotdate` -- searched the result, and freed it again.

Synthesizing `$plots` walks the live plot list and copies a string per plot, so
that call cost O(number of plots in the session). `beginPlot()` does two
`cp_getvar()` lookups per analysis (`printinfo` and `interp`) and a sweep
creates a plot per point, which made a long sweep quadratic in its own point
count: 174 us/point over 1000 points, 2449 us/point over 16000.

Neither hot lookup is one of the five names, so the fix is to gate on the name
and build nothing at all. An earlier attempt deferred construction until the
`variables` search missed and measured NO improvement -- those variables are
normally unset, so the search misses and the list gets built anyway. The gate
has to be on the name, not on the order of searching.

Gating is safe because every caller that uses it also searches
`plot_cur->pl_env` and `ft_curckt->ci_vars` separately, which is the only other
thing `cp_enqvar()` could have returned.

  [1] the five synthetic variables still read back correctly
  [2] `unset` of a synthetic variable still reports read-only (cp_remvar path)
  [3] a sweep's per-point cost no longer grows the way it did
  [4] and the sweep still computes the right answer

Note on [3]: a residual O(N) per point remains in `plot_alloc()`, which scans
the plot list to pick a unique name. That is a separate root cause, documented
in the enhancement. So this checks a large, stable improvement in the growth
rate rather than asserting flat scaling.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=300):
    p = os.path.join(HERE, "_ss.cir")
    with open(p, "w") as f:
        f.write("sweep scale\n.param pr = 1k\nV1 in 0 dc 1\nR1 in out 1k\n"
                "R2 out 0 {pr}\n.control\n%s\n.endc\n.end\n" % control)
    try:
        t0 = time.time()
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return "HANG", "", timeout
    finally:
        if os.path.exists(p):
            os.remove(p)


def main():
    # [1] the synthetic variables still work
    rc, out, _ = run("op\nop\necho A $plots\necho B $curplot\n"
                     "echo C $curplotname\necho D $curplottitle\necho E $curplotdate")

    def field(k):
        m = re.search(r"^%s (.*)$" % k, out, re.M)
        return m.group(1).strip() if m else ""

    plots = field("A").split()
    check("the five synthetic variables still read back correctly",
          rc == 0 and "op1" in plots and "op2" in plots and field("B") == "op2"
          and field("C") and field("D") and field("E"),
          f"$plots={plots} $curplot={field('B')!r}")

    # [2] the cp_remvar path still refuses, and still does not crash
    rc, out, _ = run("op\nunset plots\necho SURVIVED")
    check("`unset plots` still reports read-only and survives",
          rc == 0 and "read-only" in out and "SURVIVED" in out, f"rc={rc}")

    # [3] growth rate. Cost per point used to roughly DOUBLE with each doubling
    # of the point count (the signature of O(N) work per point). Measure the
    # ratio of per-point cost between 2000 and 8000 points -- a 4x span.
    _, _, warm = run("sweep pr lin 200 1k 3k -analysis op -output v(out)")
    times = {}
    for n in (2000, 8000):
        best = None
        for _ in range(2):
            rc, out, el = run("sweep pr lin %d 1k 3k -analysis op -output v(out)" % n)
            if rc != 0:
                check("a sweep at %d points completes" % n, False, f"rc={rc}")
                print(f"\nFAILURES: {passed}/{checks} passed")
                sys.exit(1)
            best = el if best is None else min(best, el)
        times[n] = best / n

    growth = times[8000] / times[2000]
    # Before the fix this ratio was ~3.8 (643 -> 2449 us/point). A perfectly
    # flat cost would be 1.0; plot_alloc's residual O(N) keeps it above that.
    # Anything at or below 2.5 is far outside the old behaviour, with headroom
    # for a loaded machine.
    check("per-point cost no longer grows the way it did (4x the points)",
          growth <= 2.5,
          f"{times[2000] * 1e6:.0f} -> {times[8000] * 1e6:.0f} us/point, "
          f"ratio {growth:.2f} (was ~3.8)")

    # [4] and the numbers are still right: R2 = 1k..3k against a 1k series
    # resistor from a 1 V source, so v(out) runs 0.5 .. 0.75
    rc, out, _ = run("sweep pr lin 3 1k 3k -analysis op -output v(out)\nprint v(out)")
    # `print` emits "<index>\t<value>" rows under an "Index  v(out)" header
    vals = [float(x) for x in re.findall(r"^\s*\d+\s+([-\d.]+e[-+]\d+)\s*$",
                                         out, re.M)]
    expect = [1.0 / (1.0 + 1.0), 2.0 / (1.0 + 2.0), 3.0 / (1.0 + 3.0)]
    ok = (rc == 0 and len(vals) == 3
          and all(abs(g - e) < 1e-6 * e for g, e in zip(vals, expect)))
    check("the sweep still computes the right values", ok,
          f"got {vals} expected {[round(e, 6) for e in expect]}")

    # [5] the committed 4000-point deck
    r = subprocess.run([NGSPICE, "-b", "sweepscale.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=300,
                       errors="replace")
    t = r.stdout + r.stderr
    ends = re.findall(r"v\(out\)\[\d+\] = ([-\d.]+e[-+]\d+)", t)
    check("the committed 4000-point deck runs and its endpoints are right",
          r.returncode == 0 and "SURVIVED" in t and len(ends) == 2
          and abs(float(ends[0]) - 0.5) < 1e-6
          and abs(float(ends[1]) - 0.75) < 1e-6,
          f"rc={r.returncode} endpoints={ends}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
