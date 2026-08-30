#!/usr/bin/env python3
"""Enhancement-513: a note about the DECK, repeated once per ANALYSIS.

User-reported, from a 100-sample Monte Carlo run:

    Note: v1: dc value used for op instead of transient time=0 value.
    Note: v1: dc value used for op instead of transient time=0 value.ran   0%)
    Note: v1: dc value used for op instead of transient time=0 value.ran   5%)
    ...

Two things are wrong there and the second is the one that matters.

The note describes a STATIC property of the deck -- the source carries both a DC
value and a transient function whose t=0 value differs -- but it is emitted from
VSRCtemp, which CKTdoJob runs once per ANALYSIS. Any loop command therefore
repeats it per point: 100 samples, 100 notes. Three plain `tran` commands in one
`.control` block printed it three times for the same reason.

The worse half is the collision. Enhancement-477's progress line redraws with
'\\r', so every copy of the note landed on the bar and mangled both -- that is the
`...time=0 value.ran  47%)` above. Two features that are individually correct
produced corrupt output together.

THE FIX latches the note per instance (`VSRCdcNoteDone`, and the same for ISRC),
following the bitfield idiom already in those structs. Device instances are
rebuilt when the deck is re-sourced, so "once per instance" is exactly "once per
deck load, and again after a reset" with no extra bookkeeping.

DELIBERATE TRADE: if a deck later `alter`s the source so the mismatch appears or
disappears, that change is not re-announced. This is an informational note about a
deck property and "once per load" is the normal treatment for those, but it is a
trade rather than a free win, so it is recorded here.

NOT A DEFECT, worth knowing: a deck can avoid the note entirely. `V1 in 0 dc 1
PULSE(0 1 ...)` asks for 1 V at the operating point and 0 V at t=0; dropping the
`dc 1` removes the disagreement the note exists to report.
"""

import atexit
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_sn_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0
NOTE = "dc value used for op instead of transient time=0 value"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, timeout=300):
    p = os.path.join(HERE, f"_sn_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"srcnote\n{body}.control\noption noacct\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def notes(out):
    return out.count(NOTE)


print("Enhancement-513: a deck note said once, not once per analysis")

# ---------------------------------------------------------------------------
# 1. repeated analyses in one run
# ---------------------------------------------------------------------------
print("\n  the note is said once per deck load, however many analyses run")

V = "V1 in 0 dc 1 PULSE(0 1 1n 1n 1n 500n 1u)\nR1 in 0 1k\n"
out = run(V, "tran 1n 5n", "one")
check("[1] a single tran still says it", notes(out) == 1, f"{notes(out)}")

out = run(V, "tran 1n 5n\ntran 1n 5n\ntran 1n 5n", "three")
check("[2] three trans say it ONCE (was three times)", notes(out) == 1, f"{notes(out)}")

out = run(V, "tran 1n 5n\nreset\ntran 1n 5n", "reset")
check("[3] a re-source says it again -- the instance is rebuilt",
      notes(out) == 2, f"{notes(out)}")

# ---------------------------------------------------------------------------
# 2. the loop command the user hit
# ---------------------------------------------------------------------------
print("\n  a loop command no longer repeats it per point")

MC = ("V1 in 0 dc 1 PULSE(0 1 1n 1n 1n 500n 1u)\n"
      "R1 in a 1k\nR2 a 0 {rv}\n.param rv=agauss(1000,100,1)\n")
out = run(MC, "montecarlo 12 -analysis tran 1n 20n -spec v(a) -min -1e9 -max 1e9", "mc")
check("[4] 12 Monte Carlo samples say it once (was 12 times)",
      notes(out) == 1, f"{notes(out)}")
check("[5]   ... and the run still completes", "yield" in out)

out = run(MC, "sweep rv 900 1100 6 -analysis tran 1n 20n", "sw")
check("[6] a sweep says it once too", notes(out) <= 1, f"{notes(out)}")

# ---------------------------------------------------------------------------
# 3. the progress line is no longer mangled
# ---------------------------------------------------------------------------
print("\n  Enhancement-477's progress line survives intact")

out = run(MC, "set loopbar\nmontecarlo 12 -analysis tran 1n 20n "
              "-spec v(a) -min -1e9 -max 1e9", "bar")
frames = [ln for ln in out.replace("\r", "\n").splitlines() if "montecarlo: sample" in ln]
merged = [ln for ln in frames if NOTE in ln]
check("[7] no progress frame carries the note's text", not merged,
      merged[:1] if merged else "")
check("[8]   ... and the bar reaches 100%", any("100%" in f for f in frames))

# ---------------------------------------------------------------------------
# 4. what must NOT change
# ---------------------------------------------------------------------------
print("\n  the note still fires exactly when it should")

out = run("V1 in 0 dc 0 PULSE(0 1 1n 1n 1n 500n 1u)\nR1 in 0 1k\n", "tran 1n 5n", "same")
check("[9] a source whose dc EQUALS its t=0 value stays silent",
      notes(out) == 0, f"{notes(out)}")

out = run("V1 in 0 PULSE(0 1 1n 1n 1n 500n 1u)\nR1 in 0 1k\n", "tran 1n 5n", "nodc")
check("[10] a source with no dc value at all stays silent",
      notes(out) == 0, f"{notes(out)}")

# the current source carries the same code and the same fix
I = "I1 0 in dc 1 PULSE(0 1 1n 1n 1n 500n 1u)\nR1 in 0 1k\n"
out = run(I, "tran 1n 5n", "i1")
check("[11] a CURRENT source says it too", notes(out) == 1, f"{notes(out)}")
out = run(I, "tran 1n 5n\ntran 1n 5n\ntran 1n 5n", "i3")
check("[12]   ... once, not three times", notes(out) == 1, f"{notes(out)}")

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
