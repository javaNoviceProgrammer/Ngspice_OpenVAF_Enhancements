#!/usr/bin/env python3
"""Enhancement-345: naming a plot no longer walks the plot list.

`plot_alloc()` and `plot_add()` pick a unique plot name by counting a shared,
monotone `plot_num` up until `<abbrev><plot_num>` is not the typename of any
plot in `plot_list`. That membership test walked the WHOLE list with a
case-insensitive compare, so naming a plot cost O(plots). A sweep creates a plot
per point, so naming them was quadratic in the sweep length -- after
Enhancement-343 removed the other quadratic term, 89% of a 64000-point sweep sat
in `plot_alloc -> cieq -> tolower`.

E-345 keeps a hash index of the typenames currently in `plot_list`. ONLY the
membership test changed: the search still counted up by one from a shared
`plot_num`, so the sequence of names was byte-identical.

ENHANCEMENT-371 DELIBERATELY CHANGED THAT SEQUENCE, and the expectations below
were updated with it. The shared counter meant one type's plots numbered another:
a 500-point `sweep` keeps a plot per point, so op1..op500 pushed the shared
counter and the sweep's own plot came out `sweep500`. Each abbreviation now
carries its OWN counter, so the first sweep is `sweep1` regardless of what else
ran, and a single-plot `destroy` recycles the freed number the way `destroy all`
always did.

What E-371 had to preserve -- and what check [4] is really guarding -- is E-345's
LINEARITY. A per-type counter that restarted the search at 1 each time would have
reintroduced exactly the quadratic this example was written for, so the counter is
remembered per type and only walks back down when a plot is removed.

The index is maintained where the list is mutated: `plot_new()` (now the single
insertion point -- the callers that open-coded the same two lines were converted)
and `plot_forget()` from `killplot()`. It is built lazily from `plot_list`
itself, so plots that predate it are covered without registration.

  [1] the PER-TYPE name sequence (E-371; was one shared counter)
  [2] `destroy all` frees the numbers, and the next plots reuse them
  [3] naming survives the paths that build plots by other routes
      (fft, linearize, spec, rawfile load) and through single-plot destroys
  [4] a sweep's per-point cost is now FLAT in the point count
  [5] and the sweep still computes the right values
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


BODY = ".param pr = 1k\nV1 in 0 dc 1\nR1 in out 1k\nC1 out 0 1p\n"


def run(name, control, timeout=300, body=None):
    p = os.path.join(HERE, "_%s.cir" % name)
    with open(p, "w") as f:
        f.write("t %s\n%s.control\n%s\n.endc\n.end\n"
                % (name, body or BODY, control))
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


def plots_line(out, tag):
    m = re.search(r"^%s (.*)$" % tag, out, re.M)
    return m.group(1).split() if m else []


def main():
    # [1] the per-type sequence (E-371). Each abbreviation counts independently,
    # so this runs op1 tran1 op2 ac1 op3 -- under the old shared counter the `ac`
    # plot came out `ac2`, numbered by the `op` plots that preceded it.
    rc, out, _ = run("seq", "op\ntran 1n 5n\nop\nac dec 2 1 100\nop\necho P $plots")
    got = plots_line(out, "P")
    want = ["const", "op1", "tran1", "op2", "ac1", "op3"]
    check("the per-type name sequence is as expected", rc == 0 and got == want,
          f"{got}")

    # [2] destroy frees the numbers for reuse -- the behaviour a superset cache
    # would have broken
    rc, out, _ = run("reuse", "op\nop\nop\ndestroy all\nop\nop\necho P $plots")
    got = plots_line(out, "P")
    check("`destroy all` frees the numbers and the next plots reuse them",
          rc == 0 and got == ["const", "op1", "op2"], f"{got}")

    rc, out, _ = run("done", "op\nop\nop\ndestroy op2\nop\nop\necho P $plots")
    got = plots_line(out, "P")
    # E-371: the freed number is now RECYCLED, as `destroy all` always did --
    # destroying op2 walks that type's counter back down to 2, so the next plot
    # takes op2 and the one after it takes op4.
    check("destroying ONE plot frees its number for reuse",
          rc == 0 and got == ["const", "op1", "op3", "op2", "op4"], f"{got}")

    # [3] the other routes that create plots
    rc, out, _ = run("fft", "tran 0.1n 20n\nlinearize\nfft v(out)\nop\necho P $plots")
    got_fft = plots_line(out, "P")
    # E-371: sp1/op1 here, not sp2/op2 -- no longer numbered by the two trans.
    ok_fft = rc == 0 and got_fft == ["const", "tran1", "tran2", "sp1", "op1"]

    rc2, out2, _ = run("load",
                       "set filetype=ascii\nop\nwrite _p.raw v(out)\nload _p.raw\n"
                       "op\nload _p.raw\nop\necho P $plots")
    got_ld = plots_line(out2, "P")
    ok_ld = rc2 == 0 and got_ld == ["const", "op1", "op2", "op3", "op4", "op5"]
    for junk in ("_p.raw",):
        q = os.path.join(HERE, junk)
        if os.path.exists(q):
            os.remove(q)
    check("fft/linearize and rawfile load still name plots identically",
          ok_fft and ok_ld, f"fft={got_fft} load={got_ld}")

    # [4] the point of the change: per-point cost must no longer grow
    run("warm", "sweep pr lin 200 1k 3k -analysis op -output v(out)")
    per = {}
    for n in (4000, 16000):
        best = None
        for _ in range(2):
            rc, _, el = run("sc%d" % n,
                            "sweep pr lin %d 1k 3k -analysis op -output v(out)" % n)
            if rc != 0:
                check("a sweep at %d points completes" % n, False, f"rc={rc}")
                print(f"\nFAILURES: {passed}/{checks} passed")
                sys.exit(1)
            best = el if best is None else min(best, el)
        per[n] = best / n

    ratio = per[16000] / per[4000]
    # Before E-345 this was ~2.8 over the same 4x span (32 -> 91 us/point).
    # Flat is 1.0; 1.6 leaves room for a loaded machine without admitting the
    # old growth.
    check("per-point cost is FLAT in the point count (4x the points)",
          ratio <= 1.6,
          f"{per[4000] * 1e6:.0f} -> {per[16000] * 1e6:.0f} us/point, "
          f"ratio {ratio:.2f} (was ~2.8)")

    # [5] and the numbers are still right
    # its own body: the shared one has no load to ground, so v(out) would be a
    # constant 1 V and the sweep would prove nothing
    divider = ".param pr = 1k\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 {pr}\n"
    rc, out, _ = run("vals", "set numdgt=12\nsweep pr lin 3 1k 3k -analysis op "
                             "-output v(out)\nprint v(out)", body=divider)
    vals = [float(x) for x in
            re.findall(r"^\s*\d+\s+([-\d.]+e[-+]\d+)\s*$", out, re.M)]
    want_v = [1.0 / 2.0, 2.0 / 3.0, 3.0 / 4.0]
    check("the sweep still computes the right values",
          rc == 0 and len(vals) == 3
          and all(abs(g - w) < 1e-10 * w for g, w in zip(vals, want_v)),
          f"{[round(v, 10) for v in vals]}")

    # [6] E-371: every plot carries a DATE. Only the analysis path (outitf.c) used
    # to set one, so plots created directly by a command -- sweep, hb, envelope,
    # eye, loadpull, stb, rfstab, qpac -- had a NULL date that `print` rendered as
    # "(null)". plot_alloc() now stamps them all at the single point of creation.
    DATE = re.compile(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} +\d+ [\d:]+ +\d{4}")
    for label, ctl, vec in (
            ("tran (analysis path)", "tran 1n 10n", "v(out)"),
            ("sweep (command path)", "sweep V1 0 1 0.5", "out"),
    ):
        rc, out, _ = run("dt_" + label[:4], "%s\nprint %s" % (ctl, vec))
        check("%s plot has a date" % label,
              rc == 0 and bool(DATE.search(out)) and "(null)" not in out,
              (DATE.search(out).group(0) if DATE.search(out) else "no date")
              + (" + (null) present" if "(null)" in out else ""))

    # the committed deck
    r = subprocess.run([NGSPICE, "-b", "plotname.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    t = r.stdout + r.stderr
    check("the committed deck runs and names match",
          r.returncode == 0 and "SURVIVED" in t
          and plots_line(t, "NAMES") == ["const", "op1", "tran1", "op2", "ac1", "op3"]
          and plots_line(t, "REUSED") == ["const", "op1", "op2"],
          f"rc={r.returncode}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
