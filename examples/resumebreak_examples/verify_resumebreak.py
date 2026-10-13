#!/usr/bin/env python3
"""verify_resumebreak.py -- Enhancement-880: a resumed transient keeps the
breakpoint spacing it ran with.

F7 of the transient stress campaign of 2026-10-12.

With no `minbreak` given, a run starts with ten times delmin under XSPICE.
CKTdoJob puts the option's 0 back for every job, and a `resume` -- in memory,
or from a checkpoint (`loadstate`) -- re-derived it as tmax/20 000, the rule of
a build without XSPICE: 5e6 times larger on these decks. A pulse edge shorter
than that is skipped, so the continuation stepped over the ends of edges the
run had landed on: on a network of the campaign the continuation was 0.19 off
where the uninterrupted run was 0.011. Checkpoints need Sparse
(Enhancement-131), so every deck pins it.

  [1] an RC driven by a pulse with 10 fs edges: after the stop, a checkpoint
      continuation lands on every corner the uninterrupted run lands on
      (E-875: on 9 of its 17)
  [2] the in-memory resume: the same
  [3] the campaign network: the continuation follows the uninterrupted run to
      1e-4 of the range (E-875: 0.16 of it)
  [4] (control) the checkpoint continuation and the in-memory resume are the
      same run, point for point
  [5] (control) with `.option minbreak=1p` the 10 fs edges' ends are skipped by
      the run and by the continuation alike

Exit code 0 = pass.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="resumebreak_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def read(path):
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append([float(x) for x in line.split()])
            except ValueError:
                pass
    return rows


def run(name, body, opts, tran, ctl, probes):
    out = os.path.join(WORK, name + ".txt")
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.option sparse %s\n%s\n.control\nset numdgt=17\nset wr_singlescale\n%s\nwrdata %s %s\n.endc\n.end\n"
                % (name, body, opts, tran, ctl, out, probes))
    subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    return read(out) if os.path.exists(out) else []


def three(tag, body, opts, tran, t1, probes):
    """the checkpoint continuation, the in-memory resume and the uninterrupted run"""
    ck = os.path.join(WORK, tag + ".bin")
    run(tag + "_save", body, opts, tran, "stop when time > %s\nrun\nsavestate %s" % (t1, ck), probes)
    cont = run(tag + "_load", body, opts, tran, "loadstate %s" % ck, probes)
    mem = run(tag + "_mem", body, opts, tran, "stop when time > %s\nrun\ndelete all\nresume" % t1, probes)
    ref = run(tag + "_ref", body, opts, tran, "run", probes)
    return cont, mem, ref


RC = "v1 a 0 pulse(0 1 0.3u 1e-14 1e-14 0.7u 1.5u)\nr1 a b 1k\nc1 b 0 1n"
TD, PER, TR, PW = 0.3e-6, 1.5e-6, 1e-14, 0.7e-6
corners = [c for k in range(6) for c in (TD + k * PER, TD + k * PER + TR, TD + k * PER + TR + PW,
                                         TD + k * PER + 2 * TR + PW) if 2.2e-6 < c < 9e-6]


def landed(rows):
    ts = [r[0] for r in rows]
    return {c for c in corners if ts and min(abs(t - c) for t in ts) <= 1e-21}


cont, mem, ref = three("rc", RC, "", ".tran 20n 9u", "2.1u", "v(b)")
lr = landed(ref)
check("[1] a checkpoint continuation lands on every corner the uninterrupted run lands on",
      cont and lr <= landed(cont), "continuation %d, uninterrupted %d of %d" % (len(landed(cont)), len(lr), len(corners)))
check("[2] the in-memory resume lands on them too",
      mem and lr <= landed(mem), "resume %d, uninterrupted %d of %d" % (len(landed(mem)), len(lr), len(corners)))

NET = """c0 1 0 7.104784141913704e-12
c1 2 0 2.254857477451511e-12
c2 5 0 8.572641739361607e-12
c3 6 0 1.6998569628452094e-10
r4 3 0 69.82986433075482
r5 2 3 19.94368021104557
r6 4 3 37.25820337127326
r7 6 0 49185.03563925098
r8 5 3 191.72008575436456
r9 1 2 12600.041584372124
r10 3 1 12.159978209613934
c11 2 4 1.251839034526791e-10
g12 4 6 4 6 0.0006018314262364168
v0 3 0 pulse(-0.5006578490142721 0.4230628702547159 6.222066016178019e-08 8.158938674012381e-14 1.275151392813386e-13 7.819330839215617e-08 4.553623066605453e-07)
v1 4 0 pwl(0.0 0.08654285458185607 8.449859719294037e-08 0.2605656761012971 7.037530410657172e-07 0.5432294501135277 8.527837613818545e-07 -0.3635103359692491 1.2332301026459082e-06 -0.6637012037207226)"""
c3, m3, r3 = three("net", NET, "", ".tran 6.83043459990818e-09 1.366086919981636e-06", "5.468209498171507e-07",
                   "v(1) v(2) v(5) v(6)")


def interp(rows, t, j):
    lo, hi = 0, len(rows) - 1
    if t <= rows[0][0]:
        return rows[0][j]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if rows[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    (ta, *va), (tb, *vb) = rows[lo], rows[hi]
    w = (t - ta) / (tb - ta) if tb > ta else 0.0
    return va[j - 1] + w * (vb[j - 1] - va[j - 1])


if c3 and r3:
    span = max(max(r[j] for r in r3) - min(r[j] for r in r3) for j in range(1, 5))
    dev = max(abs(interp(c3, r[0], j) - r[j]) for r in r3 if r[0] >= c3[0][0] for j in range(1, 5)) / span
else:
    dev = float("inf")
check("[3] the campaign network: the continuation follows the uninterrupted run to 1e-4 of the range",
      dev < 1e-4, "max deviation %.2e of the range" % dev)

same = cont and len(cont) == len([r for r in mem if r[0] >= cont[0][0]]) and all(
    a == b for a, b in zip(cont, [r for r in mem if r[0] >= cont[0][0]]))
check("[4] (control) the checkpoint continuation and the in-memory resume are the same run, point for point",
      bool(same), "%d and %d points" % (len(cont), len([r for r in mem if cont and r[0] >= cont[0][0]])))

cont5, mem5, ref5 = three("rc_mb", RC, "minbreak=1p", ".tran 20n 9u", "2.1u", "v(b)")
check("[5] (control) with minbreak=1p the run and the continuation land on the same corners",
      cont5 and landed(cont5) == landed(ref5) and len(landed(ref5)) < len(corners),
      "continuation %d, uninterrupted %d of %d" % (len(landed(cont5)), len(landed(ref5)), len(corners)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
