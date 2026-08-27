#!/usr/bin/env python3
"""Enhancement-496: `.option saveused` read a plot keyword as a signal name.

REPORTED FROM USE, not from a hunt:

    .option saveused
    ...
    pyplot v(a[0]) xlabel 'something'

    -> Warning: save 'xlabel': nothing of that name is in this analysis,
                so no such vector is produced.

`xlabel` is the plot command's own grammar. The author never asked for a vector
of that name, and the message tells them one is missing.

WHY IT HAPPENED. Enhancement-469's `.option saveused` reads the control block
before it runs and saves every vector it believes is mentioned there. Its
bare-word scan took EVERY argument of an output command that was not a number, a
redirection or an expression:

    if (strpbrk(tok, "()[]@=*/+-,'\\"")) { ... continue; }   /* the ref scan has it */
    e469_add(wl, tok);                                      /* everything else */

with no knowledge of those commands' own keywords. All 22 plot keywords were
collected (`xlabel`, `ylabel`, `title`, `vs`, `xlog`, `xlimit`, `samep`, ...),
`hardcopy` the same, and `meas` was worse -- `meas tran m1 FIND v(b) AT 50u`
offered `tran`, `m1`, `find` and `at`.

The answer was never affected: Enhancement-469 deliberately over-collects,
because under-saving would cost the answer, and a save matching nothing produces
nothing. The names were collected in silence until Enhancement-493 added the
unmatched-save warning, which exposed the flaw rather than causing it.

THE FIX IS IN TWO PARTS, and the ORDER OF IMPORTANCE IS THE REVERSE OF THE
OBVIOUS ONE.

1. AN INFERRED SAVE IS NEVER REPORTED. Enhancement-493's warning exists to catch
   a name the AUTHOR wrote and got wrong. A name `saveused` guessed on their
   behalf is not that, so it is marked at registration (`db_auto` ->
   `save_info.autosaved`) and excluded from the warning. This covers every
   keyword of every command, including any this file fails to enumerate.

2. The plot grammar is skipped by the scan, and `meas` contributes no bare words
   at all (its vectors arrive as `v(...)`/`i(...)`, which the reference scan
   already takes from every line). This stops the pointless work, but on its own
   it would be a hand-maintained list that silently rots -- Enhancement-487's
   trap -- which is why (1) and not (2) is what actually answers the report.

Nothing about WHAT IS SAVED changes. The suite pins that: every value is
compared against the same run without the option.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_kw_"):
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


CIRC = ("V1 a0 0 dc 0 PULSE(0 1 0 1u 1u 1m 2m)\n"
        "R1 a0 b0 1k\nC1 b0 0 1n\nR2 b0 c0 2k\nC2 c0 0 1n\n")


def run(ctl, tag, opts=".option saveused\n", body=None):
    deck = (f"savekw {tag}\n{opts}{body if body is not None else CIRC}\n"
            f".control\noption noacct\ntran 10u 100u\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_kw_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=180,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def unmatched(out):
    """the names E-493's warning reports as absent"""
    return sorted({m.group(1) for m in
                   re.finditer(r"save '([^']+)': nothing of that name", out)})


print("Enhancement-496: a plot keyword is not a signal name\n")

# ================================================== the reported case exactly ==
print("the reported case")
BUS = (".option saveused\n.option autobus\n"
       "V1 a[0] 0 dc 0 PULSE(0 1 0 1u 1u 1m 2m)\nR1 a[0] 0 1k\n")
rc, out = run("plot v(a[0]) xlabel 'something'", "rep", opts="", body=None)
rc, out = run("plot v(a[0]) xlabel 'something'", "rep2", opts=BUS,
              body="")
check("[E-496] `plot v(a[0]) xlabel 'something'` reports nothing absent",
      unmatched(out) == [], f"{unmatched(out)}")
check("[E-496] ...and the run still succeeds", rc == 0, f"rc={rc}")

# ========================================================== every plot keyword ==
print("\nevery word of the plot grammar is grammar, not a signal")
KW = ["xlabel 'x'", "ylabel 'y'", "title 'T'", "xlog", "ylog", "loglog",
      "linear", "xlimit 0 1", "ylimit 0 1", "vs v(b0)", "xindices 0 5",
      "xcompress 2", "samep", "polar", "smith", "smithgrid", "nogrid",
      "xdelta 0.1", "ydelta 0.1", "linplot", "combplot", "pointplot",
      "nointerp", "lingrid"]
for k in KW:
    rc, out = run(f"plot v(b0) {k}", "k" + re.sub(r"\W", "", k)[:12])
    check(f"[E-496] plot ... {k}", unmatched(out) == [], f"{unmatched(out)}")

rc, out = run("plot v(b0) xlabel 'x' ylabel 'y' title 'T' xlog ylog",
              "kmany")
check("[E-496] several keywords at once", unmatched(out) == [], f"{unmatched(out)}")

rc, out = run("hardcopy _kw_h.ps v(b0) xlabel 'x'", "hard")
check("[E-496] hardcopy takes the same grammar", unmatched(out) == [],
      f"{unmatched(out)}")

# ==================================================================== meas ====
print("\n`meas` names its analysis, result and function as bare words")
for lbl, m in (("TRIG/TARG",
                "meas tran td TRIG v(a0) VAL=0.5 RISE=1 TARG v(b0) VAL=0.5 RISE=1"),
               ("FIND AT", "meas tran m1 FIND v(b0) AT 50u"),
               ("MAX FROM TO", "meas tran m2 MAX v(b0) FROM 0 TO 100u"),
               ("AVG", "meas tran m3 AVG v(b0) FROM 0 TO 100u")):
    rc, out = run(m, "m" + re.sub(r"\W", "", lbl)[:10])
    check(f"[E-496] meas {lbl} reports nothing absent", unmatched(out) == [],
          f"{unmatched(out)}")

# ===================================== NOTHING ABOUT WHAT IS SAVED MAY CHANGE ==
print("\nthe values are identical to the same run without the option")
for lbl, ctl in (("plain plot", "plot v(b0)\nprint v(b0)[3] v(c0)[3]"),
                 ("plot + keywords",
                  "plot v(b0) xlabel 'x' ylabel 'y' title 'T'\n"
                  "print v(b0)[3] v(c0)[3]"),
                 ("plot vs", "plot v(b0) vs v(c0)\nprint v(b0)[3] v(c0)[3]"),
                 ("meas then plot",
                  "meas tran m1 FIND v(b0) AT 50u\nplot v(b0)\n"
                  "print v(b0)[3] v(c0)[3]"),
                 ("let then plot",
                  "let r = v(b0) - v(c0)\nplot r\nprint v(b0)[3] v(c0)[3]")):
    tag = re.sub(r"\W", "", lbl)[:10]
    rc, on = run(ctl, "y" + tag)
    rc, off = run(ctl, "n" + tag, opts="")
    a = (val(on, "v(b0)[3]"), val(on, "v(c0)[3]"))
    b = (val(off, "v(b0)[3]"), val(off, "v(c0)[3]"))
    check(f"[E-496] {lbl}: same values with and without saveused",
          a == b and a[0] is not None, f"{a} vs {b}")

# =============================== a name the DECK wrote is still reported ======
print("\na name the deck really did write is still reported")
rc, out = run("print v(b0)[3]", "usave",
              opts=".save v(nosuch)\n")
check("[E-496] `.save v(nosuch)` still warns", unmatched(out) == ["nosuch"],
      f"{unmatched(out)}")

rc, out = run("print v(b0)[3]", "usave2",
              opts=".option saveused\n.save v(nosuch)\n")
check("[E-496] ...and also when saveused is on beside it",
      unmatched(out) == ["nosuch"], f"{unmatched(out)}")

rc, out = run("print v(b0)[3]", "uprobe", opts=".probe v(nosuch)\n")
check("[E-496] `.probe v(nosuch)` still warns", unmatched(out) == ["nosuch"],
      f"{unmatched(out)}")

# ============================================ E-469's own contract stands =====
print("\nEnhancement-469's contract is untouched")
rc, out = run("plot v(b0)\nprint v(b0)[3]", "std", opts=".option saveused\n")
check("[E-496] saveused still runs and produces the vector",
      val(out, "v(b0)[3]") is not None, "")

rc, on = run("plot all\nprint v(b0)[3] v(c0)[3]", "sall")
rc, off = run("plot all\nprint v(b0)[3] v(c0)[3]", "nall", opts="")
check("[E-496] `all` still means everything",
      val(on, "v(c0)[3]") == val(off, "v(c0)[3]")
      and val(on, "v(c0)[3]") is not None, "")

rc, out = run("wrdata _kw_o.txt v(b0) v(c0)\nprint v(b0)[3]", "wrd")
check("[E-496] wrdata's leading file name is still not a vector",
      unmatched(out) == [] and val(out, "v(b0)[3]") is not None,
      f"{unmatched(out)}")

rc, out = run("plot v(b0)\nprint v(b0)[3]", "expl",
              opts=".option saveused\n.save v(b0)\n")
check("[E-496] an explicit .save still makes saveused stand aside",
      val(out, "v(b0)[3]") is not None and unmatched(out) == [],
      f"{unmatched(out)}")

# ================================ a node genuinely NAMED like a keyword =======
print("\na node genuinely named like a keyword is still reachable")
KWNODE = ("V1 in 0 dc 0 PULSE(0 1 0 1u 1u 1m 2m)\n"
          "R1 in title 1k\nC1 title 0 1n\nR2 in vs 2k\nC2 vs 0 1n\n")
for nm in ("title", "vs"):
    rc, on = run(f"plot {nm}\nprint {nm}[3]", "q" + nm, body=KWNODE)
    rc, off = run(f"plot {nm}\nprint {nm}[3]", "r" + nm, opts="", body=KWNODE)
    check(f"[E-496] a node named `{nm}` keeps the value it has without the option",
          val(on, nm + "[3]") == val(off, nm + "[3]")
          and val(on, nm + "[3]") is not None,
          f"{val(on, nm + '[3]')} vs {val(off, nm + '[3]')}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
