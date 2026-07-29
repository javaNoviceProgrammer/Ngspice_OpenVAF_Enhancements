#!/usr/bin/env python3
"""Enhancement-368: the periodic small-signal analyses named their plots wrong.

[E-367](../../enhancements_doc/Enhancement-367.md) registered eight missing plot
types, but it found them by grepping for STRING LITERALS passed to plot_alloc().
That grep is blind to the main path: `outitf.c` calls `plot_alloc(run->type)`
with a runtime string each analysis supplies via `beginPlot(analName)`. Every
standard and RF analysis goes through that path, so the literal audit proved
nothing about them -- and asking "did you actually check them all?" turned up
seven more wrong.

FOUR OF THEM COLLIDED WITH AN UNRELATED ANALYSIS, which is worse than being
called "unknown", because the name looks right:

    PAC Analysis    -> ac      collides with ordinary AC
    PSP Analysis    -> sp      collides with S-parameters
    PNoise Analysis -> noise   collides with ordinary noise
    qpnoise         -> noise   ... and with pnoise
    phasenoise      -> noise   ... and with both
    Frequency Domain Periodic Steady State (QPSS) -> pss   collides with PSS

and one was still unnamed:

    PXF Analysis    -> unknown

The cause in every case is that ft_plotabbrev() returns the FIRST entry whose
pattern is a substring of the plot name. "PAC Analysis" contains "ac", so the
general entry won; "PXF Analysis" contains nothing in the table at all. The fix
is to give each periodic analysis its own pattern placed BEFORE the general one
its name happens to contain. Two ordering traps: "qpnoise" contains "pnoise", so
it must come first of the three noise entries; and QPSS/PSS differ only by
"Frequency Domain" vs "Time Domain", so the QPSS pattern has to carry those words
rather than just "periodic".

The regression checks below matter as much as the new ones: ordinary `noise`,
`ac`, `sp` and `tran` plots must keep the names they have always had, since decks
elsewhere in this repo select them (`setplot noise1`, `print noise1.onoise_...`).
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


# A driven RC low-pass -- the same circuit the .pac/.pxf/.pnoise examples use.
# The `DC 0 AC 1` matters: .pxf and `noise` both need an AC-specified source, and
# without it they run but emit no plot, which reads as a naming failure.
RC = """V1 a 0 DC 0 AC 1 SIN(0 1 1meg)
R1 a b 1k
C1 b 0 1n
"""
# a 2-port for the S-parameter regression control
SP = """V1 in 0 dc 0 ac 1 portnum 1 z0 50
V2 out 0 dc 0 ac 0 portnum 2 z0 50
R1 in out 1k
C1 out 0 1n
"""


def run(net, cards, ctl, tag, timeout=300):
    p = os.path.join(HERE, "_pl_%s.cir" % tag)
    with open(p, "w") as f:
        f.write("plot naming\n" + net + cards +
                ".control\noption noacct\n" + ctl + "\nsetplot\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout + r.stderr


def plots(out):
    """Parse `setplot`. NOTE: a blank line follows the header, so a non-greedy
    match to the first blank line captures NOTHING -- that bug made an earlier
    harness report 'no plot' for all 25 analyses and call the run clean."""
    i = out.find("List of plots available:")
    if i < 0:
        return []
    names = []
    for line in out[i:].splitlines()[1:]:
        if "\t" not in line:
            if names:
                break
            continue
        m = re.match(r"\s*(?:Current\s+)?(\S+)\t", line)
        if m and m.group(1) != "const":
            names.append(m.group(1))
    return names


# (label, netlist, analysis cards, control, expected plot prefix, must-not-appear)
CASES = [
    ("pac",  RC, ".pac 1meg 1u b 1024 10 50 5u dec 4 10k 1meg\n",     "run", "pac",  "unknown"),
    ("pxf",  RC, ".pxf 1meg 1u b 1024 10 50 5u b dec 4 10k 1meg 1\n", "run", "pxf",  "unknown"),
    ("pnoise", RC, ".pnoise 1meg 1u b 1024 6 50 5u b v1 lin 3 1k 100k\n", "run", "pnoise", "unknown"),
]

REGRESSIONS = [
    ("ordinary noise keeps noise1", RC, "", "noise v(b) V1 dec 3 1e4 1e6", "noise"),
    ("ordinary ac keeps ac1",       RC, "", "ac dec 3 1e4 1e8",            "ac"),
    ("ordinary tran keeps tran1",   RC, "", "tran 50n 2u",                 "tran"),
    ("s-parameters keep sp1",       SP, "", "sp lin 3 1e6 1e8",            "sp"),
]


def main():
    # [1] each periodic analysis gets its OWN name, and nothing is "unknown"
    for i, (label, net, cards, ctl, want, bad) in enumerate(CASES):
        got = plots(run(net, cards, ctl, "a%d" % i))
        if not got:
            check("%s names its plot %s<N>" % (label, want), False, "analysis did not run")
            continue
        hit = [n for n in got if n.startswith(want)]
        unk = [n for n in got if n.startswith(bad)]
        check("%s names its plot %s<N>" % (label, want), bool(hit) and not unk,
              " ".join(got))

    # [2] the collision that mattered most: PSS and QPSS are distinct plots.
    #     .pac runs a PSS first, so one deck produces both.
    got = plots(run(RC, ".pac 1meg 1u b 1024 10 50 5u dec 4 10k 1meg\n", "run", "b"))
    pss = [n for n in got if re.fullmatch(r"pss\d+", n)]
    qpss = [n for n in got if re.fullmatch(r"qpss\d+", n)]
    check("PSS and QPSS no longer share a name", bool(pss) and bool(qpss),
          " ".join(got))

    # [3] the unaffected analyses must keep the names decks already rely on
    for i, (label, net, cards, ctl, want) in enumerate(REGRESSIONS):
        got = plots(run(net, cards, ctl, "r%d" % i))
        ok = bool(got) and any(re.fullmatch(want + r"\d+", n) for n in got)
        check(label, ok, " ".join(got) if got else "no plot")

    # [4] no analysis anywhere in this file falls back to "unknown"
    allnames = []
    for i, (_, net, cards, ctl, _, _) in enumerate(CASES):
        allnames += plots(run(net, cards, ctl, "z%d" % i))
    check("no plot falls back to 'unknown'",
          not [n for n in allnames if n.startswith("unknown")],
          "%d plots checked" % len(allnames))

    for j in os.listdir(HERE):
        if j.startswith("_pl_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
