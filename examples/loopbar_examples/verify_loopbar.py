#!/usr/bin/env python3
"""Enhancement-477: a progress line for the commands that run N analyses in a
loop -- `sweep`, `montecarlo`, `highsigma`, `wcd`.

Those commands set `ft_optimizing` to silence per-point chatter (Enhancement-130),
so before this they printed a banner and then nothing at all: a forty-point sweep
of a slow transient looked hung for minutes.

THE INNER ANALYSIS'S OWN BAR IS NOT THE ANSWER. It runs 0 -> 100% for EVERY
point, so it resets N times and never says how far the loop is, and it redraws
the same terminal line with '\\r', so the two would overwrite each other. Instead
one line carries both -- the outer counter and bar, plus the inner analysis's
fraction as a secondary field:

    sweep: point  7/40  [=========               ]  17%   (tran 63%)

The inner fraction also advances the OUTER bar within a point, so it moves
smoothly rather than stepping once per analysis.

TWO DRIVERS ARE REQUIRED, and checks [5] and [6] pin each one separately:
  * while a point runs, the loop command is blocked inside the analysis, so the
    intra-point refresh can only come from outitf.c's data path;
  * but the DEFAULT analysis is `op`, which produces no swept data points and
    never reaches that path -- so the loop command also draws at each point
    boundary.
Neither alone covers both regimes (few slow points / many fast ones).

`wcd` is INDETERMINATE: it iterates to convergence, so a bar drawn against
`maxiter` would sit low and then jump to done. It gets a counter instead ([9]).

The line is auto-enabled only when stdout is a terminal, because it is redrawn
with '\\r' and a redirected run would otherwise collect one enormous line of bar
frames. `set loopbar` / `set noloopbar` force it either way ([12]-[14]).

Checked under one solver only: this is a front-end OUTPUT feature (outitf.c) and
the bar bytes do not depend on the linear solver -- the same reasoning the
sibling `progressbar_examples` suite states. [16] pins that the numbers a sweep
produces are byte-identical with the bar on and off.
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


def run(body, ctl, tag):
    if not body.endswith("\n"):
        body += "\n"
    deck = f"loopbar\n{body}.control\noption noacct\n{ctl}\n.endc\n.end\n"
    p = os.path.join(HERE, f"_lb_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    try:
        os.remove(p)
    except OSError:
        pass
    return r.stdout + r.stderr


def frames(out, label):
    """Every drawn frame of the loop line, in order (they are \\r-separated)."""
    return [f for f in re.split(r"[\r\n]", out) if f.startswith(f" {label}: ")]


def pct(frame):
    m = re.search(r"\]\s*(\d+)%", frame)
    return int(m.group(1)) if m else None


def inner_pct(frame):
    m = re.search(r"\((\w+)\s+(\d+)%\)", frame)
    return (m.group(1), int(m.group(2))) if m else None


RC = "V1 a 0 sin(0 1 1k)\nR1 a b 1k\nC1 b 0 1u\n"
DIV = "V1 a 0 dc 1\nR1 a b 1k\nR2 b 0 1k\n"

print("=== Enhancement-477: a progress line for the loop commands ===")

# ---------------------------------------------------------------------------
print("\n[1-7] sweep")
# ---------------------------------------------------------------------------
o = run(RC, "set loopbar\nsweep @r1[resistance] lin 3 500 4k "
            "-analysis \"tran 4u 1.2\" -output v(b)", "slow")
fr = frames(o, "sweep")
check("[1] a slow sweep draws the line", len(fr) > 3, f"{len(fr)} frames")
check("[2] the outer counter names the point and the total",
      any(re.search(r"sweep: point\s+1/3\b", f) for f in fr)
      and any(re.search(r"sweep: point\s+3/3\b", f) for f in fr))

inn = [inner_pct(f) for f in fr]
inn = [x for x in inn if x]
check("[3] the inner analysis's own fraction is carried on the SAME line",
      len(inn) > 2 and all(n == "tran" for n, _ in inn),
      f"{len(inn)} frames carry it, e.g. {inn[:3]}")
check("[4] ...and it RESETS per point (that is why it cannot be the bar)",
      any(inn[i + 1][1] < inn[i][1] for i in range(len(inn) - 1)) if len(inn) > 2 else False)

ps = [pct(f) for f in fr]
ps = [p for p in ps if p is not None]
check("[5] DRIVER A (outitf, intra-point): the outer % advances WITHIN a point",
      len({p for f, p in zip(fr, ps) if "point  1/3" in f or "point 1/3" in f}) > 1,
      f"distinct % while on point 1: "
      f"{sorted({p for f, p in zip(fr, ps) if '1/3' in f})}")
check("[6] the outer % is monotone non-decreasing across the whole run",
      all(ps[i] <= ps[i + 1] for i in range(len(ps) - 1)), f"{ps[:6]} ... {ps[-3:]}")
check("[7] ...and finishes at exactly 100%", ps and ps[-1] == 100, f"last={ps[-1] if ps else None}")

# ---------------------------------------------------------------------------
print("\n[8] the DEFAULT analysis is op, which never reaches outitf")
# ---------------------------------------------------------------------------
lad = ["V1 n0 0 dc 1"]
for i in range(300):
    lad.append(f"R{i} n{i} n{i+1} 1k")
    lad.append(f"C{i} n{i+1} 0 1n")
lad.append("RL n300 0 1meg")
o = run("\n".join(lad), "set loopbar\nsweep @r0[resistance] lin 2500 500 4k "
                        "-output v(n300)", "op")
fr = frames(o, "sweep")
ps = [pct(f) for f in fr if pct(f) is not None]
check("[8] DRIVER B (point boundary): an op sweep still draws, and reaches 100%",
      len(fr) >= 2 and ps and ps[-1] == 100
      and not any(inner_pct(f) for f in fr),
      f"{len(fr)} frames, no inner field (op has no span)")

# ---------------------------------------------------------------------------
print("\n[9-11] the sibling loop commands")
# ---------------------------------------------------------------------------
MC = ".param rv=agauss(1k,200,1)\nV1 a 0 dc 1\nR1 a b {rv}\nR2 b 0 1k\n"
o = run(MC, "set loopbar\nmontecarlo 300 -seed 7 -analysis op -spec v(b) "
            "-min 0.3 -max 0.7", "mc")
fr = frames(o, "montecarlo")
check("[9] montecarlo draws, and counts SAMPLES rather than points",
      fr and "sample" in fr[0] and pct(fr[-1]) == 100, f"{len(fr)} frames")

o = run(MC, "set loopbar\nhighsigma 300 -analysis op -metric v(b) -max 0.7", "hs")
fr = frames(o, "highsigma")
check("[10] highsigma draws and counts samples",
      fr and "sample" in fr[0] and pct(fr[-1]) == 100, f"{len(fr)} frames")

WC = ".param b=agauss(1000,50,1)\nV1 a 0 dc 1\nR1 a 0 {b}\n"
o = run(WC, "set loopbar\nwcd -metric -1/i(v1) -max 1100 -analysis op", "wcd")
fr = frames(o, "wcd")
ipos = o.find(" wcd: iteration")
rpos = o.find("worst-case distance")
check("[11] wcd is INDETERMINATE: a counter, no bar, and drawn BEFORE its result",
      fr and all("[" not in f for f in fr) and "iteration" in fr[0]
      and 0 <= ipos < rpos,
      f"{len(fr)} frames, first={fr[0].strip() if fr else None!r}")

# ---------------------------------------------------------------------------
print("\n[12-15] the switch, and the two behaviours that must not change")
# ---------------------------------------------------------------------------
SW = "sweep @r1[resistance] lin 40 500 4k -output v(b)"
on = [("set loopbar", 1), ("set loopbar=1", 1), ("set noloopbar=0", 0)]
off = [("set loopbar=0", 0), ("set loopbar=false", 0), ("set loopbar=no", 0),
       ("set loopbar=off", 0), ("set noloopbar", 0), ("", 0)]
bad = []
for ctl, _ in on[:2]:
    if not frames(run(DIV, ctl + "\n" + SW, "on"), "sweep"):
        bad.append(ctl + " (expected ON)")
for ctl, _ in off:
    if frames(run(DIV, (ctl + "\n" if ctl else "") + SW, "off"), "sweep"):
        bad.append((ctl or "(unset)") + " (expected off)")
check("[12] every spelling that means OFF means off, and on means on",
      not bad, f"wrong: {bad}" if bad else "8 spellings")

# the frontend variable is spelled `norefvalue`; it is what sets ft_norefprint.
o = run(DIV, "set loopbar\nset norefvalue\n" + SW, "nrp")
check("[13] `norefvalue` mutes it, like the analysis bar",
      not frames(o, "sweep"))

# long enough to cross the 0.25 s throttle several times -- a short run
# legitimately draws nothing, which is not what this check is about.
o = run(RC, "tran 1u 1.5", "plain")
check("[14] a plain analysis still shows its OWN bar (unregressed)",
      o.count("Reference value") > 2, f"{o.count('Reference value')} frames")

OPT = ".param rv=1k\nV1 a 0 dc 1\nR1 a b {rv}\nR2 b 0 1k\n"
o = run(OPT, "set loopbar\noptimize -dparam rv 600 0 1k -analysis op "
             "-target v(b) 0.4 -maxiter 20", "opt")
check("[15] `optimize` stays silent (Enhancement-130 unchanged)",
      "Reference value" not in o and not frames(o, "optimize")
      and "converged" in o,
      "17-ish evaluations, no frames")

# ---------------------------------------------------------------------------
print("\n[16] the bar changes nothing but the display")
# ---------------------------------------------------------------------------
def numbers(out):
    return re.findall(r"^\d+\s+(\S+)\s+(\S+)", out, re.M)

a = run(DIV, "set loopbar\n" + SW + "\nprint all", "d1")
b = run(DIV, "set noloopbar\n" + SW + "\nprint all", "d2")
check("[16] the swept numbers are identical with the bar on and off",
      numbers(a) == numbers(b) and len(numbers(a)) > 10,
      f"{len(numbers(a))} rows compared")

# ---------------------------------------------------------------------------
print("\n[17-18] auto: on a terminal, off when redirected")
# ---------------------------------------------------------------------------
def run_pty(ctl, tag):
    import pty, select
    deck = f"loopbar\n{DIV}.control\noption noacct\n{ctl}\n{SW}\n.endc\n.end\n"
    p = os.path.join(HERE, f"_lb_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    m, s = pty.openpty()
    pr = subprocess.Popen([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                          stdout=s, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL)
    os.close(s)
    out = b""
    while True:
        r, _, _ = select.select([m], [], [], 60)
        if not r:
            break
        try:
            c = os.read(m, 65536)
        except OSError:
            break
        if not c:
            break
        out += c
    pr.wait()
    os.close(m)
    try:
        os.remove(p)
    except OSError:
        pass
    return out.decode("utf-8", "replace")

try:
    tty_default = frames(run_pty("", "pty1"), "sweep")
    tty_forced_off = frames(run_pty("set loopbar=0", "pty2"), "sweep")
    tty_auto_via_no = frames(run_pty("set noloopbar=0", "pty3"), "sweep")
    check("[17] AUTO on a terminal draws by default, and `loopbar=0` still wins",
          bool(tty_default) and not tty_forced_off,
          f"default={len(tty_default)} frames, forced-off={len(tty_forced_off)}")
    check("[18] `noloopbar=0` means auto -- which on a terminal is ON",
          bool(tty_auto_via_no), f"{len(tty_auto_via_no)} frames")
except Exception as exc:                      # no pty on this platform
    check("[17] AUTO on a terminal (skipped: no pty)", True, str(exc)[:40])
    check("[18] noloopbar=0 on a terminal (skipped: no pty)", True, "")

# ---------------------------------------------------------------------------
print("\n[19] the per-point analysis printout scrolls the line away -- `noinit`")
# ---------------------------------------------------------------------------
# A `tran` prints its "Initial Transient Solution" table once PER POINT, and
# that scrolls the redrawn line out of view. It is not this enhancement's to
# suppress -- it predates it and other things parse it -- but ngspice already
# has the lever, and the bar is only pleasant to watch with it set. Pinned so
# the advice in the README stays true.
# NOTE: run() sets `option noacct`, and the table is gated on
# `!ft_noacctprint && !ft_noinitprint` -- so it must NOT be used here, or both
# sides read zero tables and the check passes vacuously (it did, first run).
def run_raw(ctl, tag):
    deck = (f"loopbar\n{RC}.control\n{ctl}\n"
            "sweep @r1[resistance] lin 3 500 4k -analysis \"tran 50u 0.35\" "
            "-output v(b)\n.endc\n.end\n")
    q = os.path.join(HERE, f"_lb_{tag}.cir")
    with open(q, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(q)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    try:
        os.remove(q)
    except OSError:
        pass
    return r.stdout + r.stderr

o = run_raw("set loopbar", "noi1")
o2 = run_raw("set loopbar\nset noinit", "noi2")
check("[19] `set noinit` removes the per-point tables, leaving the line clean",
      o.count("Initial Transient Solution") == 3
      and o2.count("Initial Transient Solution") == 0
      and frames(o2, "sweep"),
      f"tables without={o.count('Initial Transient Solution')} with=0")

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
