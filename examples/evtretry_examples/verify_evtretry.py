#!/usr/bin/env python3
"""Enhancement-909: an event body's effects are undone with a rejected attempt.

F1 of the 2026-10-19 correctness campaign. A `@(cross(...))` body that ran in
a transient attempt which was then rejected -- another event or another
instance asked for a landing, or the truncation error failed -- kept what it
had done, and the retry that reached the same crossing ran it again: two
counters on one 1 MHz sine, one with the default time tolerance and one with
`time_tol` = 1 ps, read 30 and 20 after 20 crossings. Its `$strobe` printed
twice. A landing that fell short of its crossing was not chased, so a
crossing fired up to a step late. A timer that fired in the rejected attempt
had its event moved to it.

Checks (both solvers):
  [1] the two counters at max steps of 5 ns and 20 ns, dir 0, +1 and -1: both
      read 20 or 10, and their real-valued twin half of that (the default-
      tolerance counter read 30, 27, 17 and 11)
  [2] a `$strobe` in the body prints once per crossing: 20 lines numbered 1 to
      20 in time order, each within 3e-3 of the step of its analytic crossing
      (a full step late before), and the `@(final_step)` line once
  [3] a crossing and a timer in one module (the campaign deck whose landing
      rejected the attempt the timer fired in): every timer line within 1e-9
      of tstart + k tper, every crossing within 3e-2 of the step (the step
      floor of E-504 bounds a refinement here), and at EVERY accepted point
      both counters equal the number of events up to that time (the timer
      used to count its event at the retry before it)
  [4] under hb, which evaluates sample times with no accepted point between
      them, a variable set by @(initial_step) still reads 1 at the final step
      (an interim build rolled it back to 0); a tran as the control
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="evtretry_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


r = subprocess.run([VAF, os.path.join(HERE, "evtretry.va"), "-o", os.path.join(WORK, "evtretry.osdi")],
                   capture_output=True, text=True)
check("evtretry.va compiles", r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.returncode else "")


def run(deck, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* evtretry {tag}\n{deck}\n.control\nset noinit\nset numdgt=15\nset wr_singlescale\n"
                f"pre_osdi evtretry.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300, cwd=WORK)
    return p.stdout + p.stderr


def val(out, name):
    m = re.findall(r"(?m)^" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


def crossings(off, amp, freq, thr, dr, tstop):
    a0 = math.asin((thr - off) / amp)
    ex = []
    for k in range(int(tstop * freq) + 2):
        for t, rising in ((a0 / (2 * math.pi * freq) + k / freq, math.cos(a0) > 0),
                          ((math.pi - a0) / (2 * math.pi * freq) + k / freq, math.cos(math.pi - a0) > 0)):
            if 0 < t < tstop and (dr == 0 or (dr == 1) == rising):
                ex.append(t)
    return sorted(ex)


def lines(out, tag, inst="n1"):
    return [(int(a), float(b)) for a, b in re.findall(r"OSDI " + inst + r": " + tag + r" (\d+) (\S+)", out)]


print("Enhancement-909: event bodies and rejected attempts\n")

# ------------------------------------------------------------- [1] ---
COUNTERS = "\n".join([
    "V1 in 0 dc 0 sin(0 1 1meg)",
    "N1 in on1 os1 m1", ".model m1 cnt(thr=0.3 dir={d})",
    "N2 in on2 os2 m2", ".model m2 cntt(thr=0.3 dir={d})",
    "R1 on1 0 1k", "R2 os1 0 1k", "R3 on2 0 1k", "R4 os2 0 1k"])
FINAL = ("let last = length(v(on1)) - 1\n"
         "print v(on1)[last] v(os1)[last] v(on2)[last] v(os2)[last]")
for d, want in ((0, 20), (1, 10), (-1, 10)):
    for h in ("5n", "20n"):
        out = run(COUNTERS.format(d=d), f"tran {h} 10u 0 {h}\n{FINAL}", f"cnt_{d}_{h}")
        got = [val(out, f"v({n})[last]") for n in ("on1", "os1", "on2", "os2")]
        check(f"[1] dir {d if d <= 0 else '+1'}, max step {h}: both counters read {want}, their real twins {want / 2:g}",
              got == [want, want / 2, want, want / 2], str(got))

# ------------------------------------------------------------- [2] ---
deck = COUNTERS.format(d=0).replace("cnt(thr=0.3 dir=0)", "cnt(thr=0.3 dir=0 talk=1)")
out = run(deck, f"tran 5n 10u 0 5n\n{FINAL}", "strobe")
xc = lines(out, "XC")
check("[2] the body's $strobe prints once per crossing: 20 lines numbered 1 to 20",
      [k for k, _ in xc] == list(range(1, 21)), str(len(xc)))
check("[2] ... in time order", all(b[1] > a[1] for a, b in zip(xc, xc[1:])))
ex = crossings(0.0, 1.0, 1e6, 0.3, 0, 10e-6)
err = max((abs(t - e) / 5e-9 for (_, t), e in zip(xc, ex)), default=float("inf")) if len(xc) == len(ex) else float("inf")
check("[2] ... each within 3e-3 of the step of its analytic crossing (a short landing is chased)",
      err <= 3e-3, f"{err:.2e}")
fin = re.findall(r"OSDI n1: FIN (\d+)", out)
check("[2] the @(final_step) line prints once, with the count", fin == ["20"], str(fin))

# ------------------------------------------------------------- [3] ---
OFF, AMP, FREQ = 0.385760083, 0.833471336, 3657.42227
THR, TST, TPER = 0.311301192, 7.60186238e-05, 3.25218638e-05
STEP, TSTOP = 5.46833221e-06, 0.0027341661
deck = "\n".join([
    f"V1 in 0 dc {OFF} sin({OFF} {AMP} {FREQ})",
    "N1 in on om mx", f".model mx tmx(thr={THR} dir=0 tstart={TST} tper={TPER})",
    "R1 on 0 1k", "R2 om 0 1k"])
data = os.path.join(WORK, "tmx.txt")
out = run(deck, f"tran {STEP} {TSTOP} 0 {STEP}\nwrdata {data} v(on) v(om)", "tmx")
tm = lines(out, "TM")
sched = [TST + k * TPER for k in range(int((TSTOP - TST) / TPER) + 1) if TST + k * TPER < TSTOP * (1 - 1e-9)]
terr = (max(abs(t - e) / TPER for (_, t), e in zip(tm, sched))
        if len(tm) == len(sched) and tm else float("inf"))
check(f"[3] a timer beside a crossing: {len(sched)} timer lines, each within 1e-9 of tstart + k tper",
      terr <= 1e-9, f"{len(tm)} lines, {terr:.2e}")
xc = lines(out, "XC")
ex = crossings(OFF, AMP, FREQ, THR, 0, TSTOP)
xerr = (max(abs(t - e) / STEP for (_, t), e in zip(xc, ex))
        if len(xc) == len(ex) and xc else float("inf"))
check(f"[3] ... {len(ex)} crossing lines, each within 3e-2 of the step", xerr <= 3e-2,
      f"{len(xc)} lines, {xerr:.2e}")
rows = []
try:
    with open(data) as f:
        for ln in f:
            p = ln.split()
            if len(p) >= 3:
                rows.append((float(p[0]), float(p[1]), float(p[2])))
except OSError:
    pass
bad_n = bad_m = 0
for t, n, m in rows:
    if t <= 0:
        continue
    # a crossing is landed a margin past it; a point within that margin may
    # count it or not
    lo = sum(1 for e in ex if e <= t - 3e-2 * STEP)
    hi = sum(1 for e in ex if e <= t)
    if not (lo <= n <= hi):
        bad_n += 1
    if m != sum(1 for e in sched if e <= t * (1 + 1e-12)):
        bad_m += 1
check(f"[3] at every one of the {len(rows)} accepted points the timer counter is the number of "
      "events up to that time", rows and bad_m == 0, f"{bad_m} wrong")
check("[3] ... and the crossing counter too", rows and bad_n == 0, f"{bad_n} wrong")

# ------------------------------------------------------------- [4] ---
DRIVEN = "V1 a 0 SIN(0 1 1meg)\nR1 a b 1k\nC1 b 0 1n\nN1 b 0 mi\n.model mi ini"
for cmd, what in (("hb 1meg 8", "hb"), ("tran 1n 2u", "tran (control)")):
    out = run(DRIVEN, cmd, "ini_" + what.split()[0])
    got = re.findall(r"OSDI n1: INI (\d+)", out)
    check(f"[4] {what}: a variable set at the initial step still reads 1 at the final step "
          "(the count is served only while a transient steps)", got == ["1"], str(got))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
