#!/usr/bin/env python3
"""
verify_progressbar.py -- Enhancement: a live progress bar on ngspice's
"Reference value" status line during DC / AC / transient / noise sweeps.

ngspice already printed a throttled (every 0.25 s), redraw-in-place
(" Reference value : <x>\\r") status line during a sweep, showing the current
sweep variable. This enhancement appends a progress bar + percentage:

    Reference value :  5.91926e-04  [==================      ]  74%

The fraction is computed per analysis: transient from elapsed time / TSTOP; AC
and noise from the frequency's position in the (linear or log) start..stop band;
DC from the accepted-point count over the product of the nested step counts.
Analyses with no well-defined span (operating point, ...) keep the plain line.

This is a front-end OUTPUT feature (outitf.c), independent of the linear solver,
so it is checked once (the bar bytes are identical under Sparse and KLU). Each
deck is sized to run well past the 0.25 s throttle so at least one bar is emitted.

Checks:
  [1] each of tran / AC / DC / noise emits the bar (`[...] NN%`);
  [2] the printed percentage matches the analytic sweep fraction at that
      reference value (tran: linear in time; AC/noise: log in frequency;
      DC: linear in the sweep source);
  [3] the bar fill length is proportional to the percentage;
  [4] percentages are monotone non-decreasing and the last is near 100%;
  [5] an operating-point run (no sweep) prints NO bar.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))

BAR_RE = re.compile(r"Reference value :\s*([-\d.eE+]+)\s*\[([=\s]*)\]\s*(\d+)%")


def run_bar_lines(deck):
    """Run a deck in batch mode; return [(refval, fill_count, pct), ...] parsed
    from the carriage-return-updated progress line."""
    p = os.path.join(HERE, "_pb.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    out = (r.stdout + r.stderr).replace("\r", "\n")
    rows = []
    for m in BAR_RE.finditer(out):
        rows.append((float(m.group(1)), m.group(2).count("="), int(m.group(3))))
    return rows, out


BARLEN = 24

def validate(name, rows, expected_pct, tol=3.0):
    """Common per-analysis assertions given a fraction->pct function."""
    check(f"{name}: progress bar emitted ([...] NN%)", len(rows) > 0,
          f"{len(rows)} bar lines")
    if not rows:
        return
    # [2] percentage matches the analytic fraction at that reference value
    worst = max(abs(pct - expected_pct(ref)) for ref, _, pct in rows)
    check(f"{name}: printed % matches sweep fraction (max err {worst:.1f} <= {tol})",
          worst <= tol, f"max err {worst:.2f}")
    # [3] bar fill proportional to percentage
    fillbad = max(abs(fill - round(pct / 100.0 * BARLEN)) for _, fill, pct in rows)
    check(f"{name}: bar fill proportional to % (max off {fillbad})", fillbad <= 1)
    # [4] monotone non-decreasing, ends near 100%
    pcts = [pct for _, _, pct in rows]
    check(f"{name}: % monotone non-decreasing", all(b >= a for a, b in zip(pcts, pcts[1:])))
    check(f"{name}: reaches near 100% ({pcts[-1]}%)", pcts[-1] >= 90)


print("Enhancement: sweep progress bar on the 'Reference value' line")

# [tran] linear in time; TSTOP = 2 ms, TSTART = 0
tr_deck = (".model DM D(is=1e-14)\nV1 1 0 SIN(0 2 2k)\nD1 1 2 DM\nR1 2 0 1k\n"
           "C1 2 0 10n\n.control\ntran 2n 2m\n.endc\n.end\n")
tr_deck = "progressbar tran\n" + tr_deck
rows, _ = run_bar_lines(tr_deck)
validate("tran", rows, lambda ref: 100.0 * ref / 2e-3)

# [AC] log in frequency; 1 Hz .. 1 MHz decade
ac_deck = ("progressbar ac\nV1 1 0 ac 1\nR1 1 2 1k\nC1 2 0 100n\n"
           ".control\nac dec 400000 1 1meg\n.endc\n.end\n")
rows, _ = run_bar_lines(ac_deck)
validate("AC", rows, lambda ref: 100.0 * math.log10(ref / 1.0) / math.log10(1e6 / 1.0))

# [DC] linear in the sweep source; 0 .. 100 V
dc_deck = ("progressbar dc\nV1 1 0 0\nR1 1 2 1k\nR2 2 0 1k\n"
           ".control\ndc V1 0 100 0.00008\n.endc\n.end\n")
rows, _ = run_bar_lines(dc_deck)
validate("DC", rows, lambda ref: 100.0 * (ref - 0.0) / (100.0 - 0.0))

# [noise] log in frequency; 1 Hz .. 1 MHz decade
ns_deck = ("progressbar noise\nV1 1 0 dc 0 ac 1\nR1 1 2 1k\nC1 2 0 100n\n"
           ".control\nnoise v(2) V1 dec 300000 1 1meg\n.endc\n.end\n")
rows, _ = run_bar_lines(ns_deck)
validate("noise", rows, lambda ref: 100.0 * math.log10(ref / 1.0) / math.log10(1e6 / 1.0))

# [5] operating point: no sweep -> no bar
op_deck = ("progressbar op\nV1 1 0 5\nR1 1 2 1k\nR2 2 0 1k\n"
           ".control\nop\nprint v(2)\n.endc\n.end\n")
rows, out = run_bar_lines(op_deck)
check("op: no progress bar for a non-sweep analysis", len(rows) == 0,
      f"{len(rows)} bar lines")
check("op: still produces its result (v(2)=2.5)", "2.500000e+00" in out)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
