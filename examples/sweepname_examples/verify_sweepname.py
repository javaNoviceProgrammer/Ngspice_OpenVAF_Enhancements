#!/usr/bin/env python3
"""Enhancement-367: `sweep` produced plots nobody could name.

Asking a simple question -- "if I run several sweeps, what are the plots called?"
-- turned up two defects that had been shipping since `sweep` was added in
[E-146](../../enhancements_doc/Enhancement-146.md).

  [1] THE PLOTS WERE CALLED "unknown".  plot_alloc() names a plot by looking its
      type up in the plotabs[] table in typesdef.c and falling back to the
      literal "unknown" when there is no entry. Every plot type this project
      ADDED -- sweep, sweepwave, hb, envelope, eye, loadpull, rfstab, stb -- was
      missing from that table, so `sweep` created unknown4, unknown7, unknown10.

  [2] THE MESSAGE NAMED A PLOT THAT DID NOT EXIST.  `sweep` printed

          sweep: 3 points into the 'sweep' plot (now current); ...

      with 'sweep' as a LITERAL. No plot was ever called that, so the one hint
      the command gave for getting back to an earlier sweep -- `setplot sweep` --
      always failed. It now prints the plot's real name.

WHY THE NUMBERS ARE NOT 1, 2, 3.  plot_unique_typename() draws from a counter
SHARED by every plot type, and advances it only far enough to avoid a collision.
Each `sweep` internally runs one analysis per point, so three points burn op1,
op2, op3 and the sweep plot lands on sweep3. That is pre-existing ngspice
behaviour, it is not what this fixes, and the fix is what makes it visible: the
message now tells you the name instead of leaving you to guess it.

ORDER MATTERS IN plotabs[].  ft_plotabbrev() returns the FIRST entry whose
pattern is a substring of the plot name, so "sweepwave" has to precede "sweep"
or a sweep-waveform plot would be abbreviated "sweep" and collide with the point
plot.

ENHANCEMENT-383 -- this fix broke its own rule.  Of the eight entries added here,
`envelope` went in at the BOTTOM of the table, below { "op", "op" }; "envel-OP-e"
contains "op", so that entry was never reachable and envelope plots kept coming
out as op1. Adding an entry is not enough, it has to go in the right PLACE. The
same audit found `qpac` and `qpxf` shadowed by `pac`/`pxf`, and settled the
"existing quirk" this comment used to record -- a plot named "spectrum" matching
the earlier "sp" entry rather than "spect" -- which was not a quirk but the same
defect, and is now fixed too. See examples/plotorder_examples, which asserts the
ordering invariant against the table so a future entry cannot repeat this.

The struct is {p_name, p_pattern} -- the SECOND field is the one matched and the
FIRST is the abbreviation returned, which reads backwards from the table and is
now documented in the source.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


NET = """sweep plot naming
V1 in 0 dc 0.5
Rs in mid 1k
Rl mid 0 2k
"""


def run(ctl, tag, timeout=180):
    p = os.path.join(HERE, "_sn_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\n" + ctl + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.returncode, r.stdout + r.stderr


def main():
    # [1] the plot must no longer be called "unknown"
    _, out = run("sweep V1 0 1 0.5\nsetplot", "a")
    names = re.findall(r"^\s*(?:Current\s+)?(\S+)\s+\S.*\(Sweep\)", out, re.M)
    check("sweep plot is named sweepN, not unknownN", bool(names) and
          all(re.fullmatch(r"sweep\d+", n) for n in names),
          "got %s" % (names or "no Sweep plot at all"))

    # [2] the name the message prints must be one `setplot` accepts. This is the
    #     whole point: quoting a literal that no plot answers to is the defect.
    _, out = run("sweep V1 0 1 0.5\nsetplot", "b")
    m = re.search(r"into plot '([^']+)'", out)
    if not m:
        check("summary message quotes the real plot name", False, "no 'into plot' message")
    else:
        printed = m.group(1)
        _, sel = run("sweep V1 0 1 0.5\nsetplot %s\nprint mid" % printed, "c")
        check("the name the message prints is selectable", "no such plot" not in sel.lower(),
              "setplot %s" % printed)
        check("selecting it yields the sweep's data", bool(
            re.search(r"^\s*\d+\s+[-+0-9.eE]+\s*$", sel, re.M)), "printed mid")

    # [3] two sweeps in one session must get DISTINCT names -- the case where
    #     guessing 'sweep' hurt most, because there is more than one to return to
    _, out = run("sweep V1 0 1 0.5\nsweep Rs 500 1500 500\nsetplot", "d")
    got = re.findall(r"into plot '([^']+)'", out)
    check("two sweeps get distinct names", len(got) == 2 and got[0] != got[1],
          " vs ".join(got) if got else "none")

    # [4] the curve-family form takes the SECOND fprintf branch, which carried the
    #     same literal. The outer knob needs the `-vs` flag (`-family` is its alias).
    _, out = run("sweep V1 0 1 0.5 -vs Rs 500 1500 500\nsetplot", "e")
    fam = re.search(r"into plot '([^']+)'", out)
    check("-family summary also quotes a real name", bool(fam) and
          re.fullmatch(r"sweep\d+", fam.group(1)),
          fam.group(1) if fam else "no message")

    # [5] the other newly-registered types must not collide with each other or
    #     with "sweep" -- ordering in plotabs[] is what guarantees this
    _, out = run("op\nsetplot", "f")
    check("no plot falls back to 'unknown' for these decks",
          "unknown" not in out, "setplot listing is free of unknownN")

    for j in os.listdir(HERE):
        if j.startswith("_sn_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
