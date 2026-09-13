#!/usr/bin/env python3
"""Enhancement-611: `writemc` and `montecarlo -writemc` -- values computed after
a run, onto that run's row of the `.option savemc` file.

`.option savemc` (E-610) writes one row per analysis run with the draws behind
it. What the .control block computes from the run -- a peak, a `meas` result,
a track's hit count -- came after the row was written. Now the row of the last
run stays addressable:

  writemc [name=]<expression> ...           after a run, in a repeat/reset loop
  montecarlo ... -writemc [name=]<expr> ... per sample, after the tracks,
                                            specs and exprs (so an -expr name or
                                            a track<k>.<vector> may be listed)

Each value must be a scalar (a vector is refused with a message, reduce or
index it); a column is added on first use and a row that never gets it is
empty there; a name that is a draw's gets a `*` beside it. For csv/txt the last
line is rewritten in place, so the file stays complete row by row; a new column
rewrites the header once. With `.option savemc` off both say so once and do
nothing. Found on the way: `x[0]` on a one-point vector was refused ("indexing
a scalar"), which broke `track1.time[0]` -- the first hit -- on every sample
with exactly one hit; element 0 of a one-point vector is now itself.

Checks:
  [1] -writemc with an -expr name, track1.hits, track1.time[0] and an
      expression: the columns, every sample filled (a one-hit sample too),
      the values equal to the montecarlo and track records
  [2] writemc in a repeat/reset loop: pk, a meas result, name=expr, on each
      run's row; the montecarlo rows keep their columns empty there
  [3] a vector item is refused with the message; the row keeps its other
      values; an undefined name is refused
  [4] writemc before any run: the message; -writemc and writemc with savemc
      off: said once, nothing written
  [5] a name that is a draw's (r1) lands as r1* beside the draw
  [6] savemc=excel: the writemc values are in the .xlsx at exit
  [7] -writemc track2. with one -track is refused at parse time
  [8] the file stays complete row by row: after the last sample the csv
      already holds every row with its writemc values
  [9] [0] on a one-point vector is the element; [1] is still refused
  Found by driving the shared library from a schematic front end (it spells
  every net `/name`, and its own run is a plain `.op`):
  [10] `/`-prefixed node names evaluate in writemc, -writemc and -expr, as
       they already did in print (the same auto-quoting)
  [11] a `.model` card draw is a column on a plain run too (it was only
       recorded on montecarlo's fast path), named `<model>:<key>` on both
  [12] `montecarlo N -analysis op -writemc ...` with nothing else to judge
       or record is a run with a result, not "nothing to do"; with savemc
       off it still is nothing to do, said without "the run proceeds"
  Enhancement-624 (hunt F8 of 2026-09-12): the row a plain writemc lands on
  must be the run whose plot it reads:
  [13] after a trial whose `op` failed at setup (a draw outside the model's
       range) the cell stays empty and the message names the row and the
       plot that is really current -- the previous run's value used to be
       copied onto the failed row; a transient that failed part-way keeps
       its partial plot and still records from it; a `writemc` whose current
       plot was made after the row by a run that has none (the recorder was
       off for it) is refused, naming both; a `setplot` back to an older plot
       is deliberate and writes
  Enhancement-625 (hunt F9): a run stopped at a breakpoint is a row:
  [14] `stop when time > 2u; tran` writes the trial's row at the pause,
       status `paused`, and a `writemc` there lands on it; the `resume` that
       completes the run turns that row `ok` (a later `writemc` replaces the
       value), a `resume` that fails turns it `failed` -- one row for the
       trial, no row for the resume; a run left paused stays `paused`
"""
import glob
import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="writemc_")
A = "@"     # the accessor prefix, spelled apart so no line reads as a GitHub mention


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def clean():
    for f in glob.glob(os.path.join(WORK, "mcparams_*")):
        os.remove(f)


RLC = (".param rr = agauss(20, 30, 3)\nV1 in 0 pulse(0 1 0 1n 1n 1m 2m)\nR1 in a {rr}\nL1 a out 1m\nC1 out 0 1u\n")


def run(body, tag, ctl):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* writemc {tag}\n{body}.control\nset noinit\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def files(ext="csv"):
    return sorted(glob.glob(os.path.join(WORK, f"mcparams_*.{ext}")))


def read_csv(path):
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    return lines[0].split(","), [l.split(",") for l in lines[1:]]


def col(head, rows, name):
    i = head.index(name)
    return [float(r[i]) if i < len(r) and r[i] != "" else None for r in rows]


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


MC = 'montecarlo 6 -seed 3 -analysis "tran 2u 1m" -expr pk=maximum(v(out)) -track "v(out) -spec localmax -prominence 20m" '
print("Enhancement-611: writemc and montecarlo -writemc\n")

# ------------------------------------------------------------- [1] ---
clean()
out = run(".option savemc\n" + RLC, "t1", MC + '-writemc pk npk=track1.hits tpk=track1.time[0] over=maximum(v(out))-1\n'
          'print montecarlo1.pk track1.hits track1.time[0]')
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
tab = re.findall(r"^\d+\s+([-+.\deE]+)\s+([-+.\deE]+)\s+([-+.\deE]+)\s*$", out, re.M)
check("[1] -writemc: pk, npk (track1.hits), tpk (track1.time[0]) and an expression, on every sample's row",
      head == ["trial", "analysis", "status", "r1", "pk", "npk", "tpk", "over"] and len(rows) == 6 and len(tab) == 6
      and all(close(col(head, rows, "pk")[i], float(tab[i][0])) and close(col(head, rows, "npk")[i], float(tab[i][1]))
              and close(col(head, rows, "tpk")[i], float(tab[i][2]))
              and close(col(head, rows, "over")[i], float(tab[i][0]) - 1) for i in range(6)),
      f"{head} {rows[:2]} {tab[:2]}")
check("[1] ...a one-hit sample has its tpk too (track1.time[0] on a one-point vector)",
      any(float(t[1]) == 1.0 for t in tab) and all(v is not None for v in col(head, rows, "tpk")),
      f"hits {[t[1] for t in tab]} tpk {col(head, rows, 'tpk')}")

# ------------------------------------------------------------- [2] ---
clean()
out = run(".option savemc\n" + RLC, "t2", MC + "-writemc pk\nrepeat 3\n  reset\n  tran 2u 1m\n  let pk = maximum(v(out))\n"
          "  meas tran tr trig v(out) val=0.1 rise=1 targ v(out) val=0.9 rise=1\n  writemc pk tr q=pk*2\n  print pk\nend")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
pks = [float(x) for x in re.findall(r"^pk = ([-+.\deE]+)", out, re.M)]
trs = [float(x) for x in re.findall(r"^tr\s+=\s+([-+.\deE]+)", out, re.M)]
check("[2] writemc in a repeat/reset loop: pk, the meas result and name=expr on each run's row; the montecarlo rows empty there",
      head == ["trial", "analysis", "status", "r1", "pk", "tr", "q"] and len(rows) == 9 and len(pks) == 3 and len(trs) == 3
      and all(close(col(head, rows, "pk")[6 + i], pks[i]) and close(col(head, rows, "tr")[6 + i], trs[i], 1e-5)
              and close(col(head, rows, "q")[6 + i], 2 * pks[i]) for i in range(3))
      and all(col(head, rows, "tr")[i] is None and col(head, rows, "q")[i] is None for i in range(6)),
      f"{head} {rows[5:8]} {pks} {trs}")

# ------------------------------------------------------------- [3] ---
clean()
out = run(".option savemc\n" + RLC, "t3", "tran 2u 1m\nlet pk = maximum(v(out))\nwritemc pk v(out) nosuch\nprint pk")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
pk = [float(x) for x in re.findall(r"^pk = ([-+.\deE]+)", out, re.M)]
check("[3] a vector item is refused with the message, an undefined name too; the row keeps pk",
      "writemc: v(out): it has" in out and "a row holds one number" in out and "writemc: nosuch: it does not evaluate" in out
      and head == ["trial", "analysis", "status", "r1", "pk"] and len(rows) == 1 and close(col(head, rows, "pk")[0], pk[0]),
      out[-400:])

# ------------------------------------------------------------- [4] ---
clean()
out = run(".option savemc\n" + RLC, "t4a", "writemc x=1\ntran 2u 1m")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[4] writemc before any run: the message, no column",
      "writemc: no analysis has run yet, so there is no row to put x on" in out and head == ["trial", "analysis", "status", "r1"],
      out[-300:])
clean()
out = run(RLC, "t4b", MC + "-writemc pk\nwritemc pk=1\nwritemc pk=2")
check("[4] -writemc and writemc with savemc off: said once each, nothing written",
      out.count("montecarlo: -writemc: nothing is recorded") == 1
      and len(re.findall(r"^writemc: nothing is recorded", out, re.M)) == 1
      and not files() and "6 samples recorded" in out, out[-400:])

# ------------------------------------------------------------- [5] ---
clean()
out = run(".option savemc\n" + RLC, "t5", f"tran 2u 1m\nwritemc r1={A}r1[resistance]\nprint {A}r1[resistance]")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
r1 = [float(x) for x in re.findall(rf"^{re.escape(A + 'r1[resistance]')} = ([-+.\deE]+)", out, re.M)]
check("[5] a name that is a draw's lands as r1* beside the draw, equal here",
      head == ["trial", "analysis", "status", "r1", "r1*"] and close(col(head, rows, "r1*")[0], r1[0])
      and close(col(head, rows, "r1")[0], r1[0]), f"{head} {rows}")

# ------------------------------------------------------------- [6] ---
clean()
out = run(".option savemc=excel\n" + RLC, "t6", MC + "-writemc pk\nrepeat 2\n  reset\n  tran 2u 1m\n  writemc pk=maximum(v(out))\nend")
fs = files("xlsx")
ok = False
if fs:
    z = zipfile.ZipFile(fs[0]); x = z.read("xl/worksheets/sheet1.xml").decode()
    xrows = re.findall(r'<row r="(\d+)">(.*?)</row>', x)
    cells = [[c[0] or c[1] for c in re.findall(r'<c r="[A-Z]+\d+"(?: s="\d+")?(?: t="inlineStr")?>(?:<is><t>(.*?)</t></is>|<v>(.*?)</v>)</c>', b)]
             for _, b in xrows]     # E-617/E-619: a header cell may carry a style
    ok = z.testzip() is None and cells[0] == ["trial", "analysis", "status", "r1", "pk"] and len(cells) == 9 \
        and all(len(c) == 5 for c in cells[1:])
check("[6] savemc=excel: every row's writemc value is in the .xlsx at exit", ok, str(fs))

# ------------------------------------------------------------- [7] ---
out = run(".option savemc\n" + RLC, "t7", MC + "-writemc x=track2.value")
check("[7] -writemc track2. with one -track: refused at parse time",
      "-writemc 'track2.value' reads track2, but only one -track was given" in out and "yield" not in out, out[-300:])

# ------------------------------------------------------------- [8] ---
clean()
out = run(".option savemc\n" + RLC, "t8", MC + "-writemc pk\nshell cp mcparams_*.csv _after.txt")
after = open(os.path.join(WORK, "_after.txt")).read().strip().splitlines() if os.path.exists(os.path.join(WORK, "_after.txt")) else []
check("[8] csv: complete row by row -- right after the run, every row already carries its writemc value",
      len(after) == 7 and all(len(l.split(",")) == 5 and l.split(",")[4] != "" for l in after[1:]), str(after[:3]))

# ------------------------------------------------------------- [9] ---
out = run(RLC, "t9", "let s = 3\nprint s[0]\nprint s[1]")
check("[9] [0] on a one-point vector is the element; [1] is refused, naming the one element",
      "s[0] = 3" in out and "indexing a scalar (s): its one element is [0]" in out, out[-300:])

# ------------------------------------------------------------ [10] ---
KIC = (".model dm d is={agauss(1e-14, 1e-15, 3)} n=1.5\nV1 /in 0 DC 1\nR1 /in /mid {agauss(1k, 50, 3)}\n"
       "D1 /mid 0 dm\n")
clean()
out = run(".option savemc\n" + KIC, "t10", "op\nprint v(/mid)\nwritemc gain=v(/mid)/v(/in) vmid=v(/mid)[0]\n"
          "montecarlo 3 -seed 2 -analysis op -expr e=v(/mid)/v(/in) -writemc gain=v(/mid)/v(/in)\n"
          "print montecarlo1.e")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
vmid = re.search(r"^v\(/mid\) = ([-+.\deE]+)", out, re.M)
es = re.findall(r"^\d+\s+([-+.\deE]+)\s*$", out, re.M)
check("[10] /-prefixed nets: writemc, -writemc and -expr all evaluate v(/mid)/v(/in), v(/mid)[0]",
      "does not evaluate" not in out and "PPerror" not in out and vmid is not None and len(rows) == 4
      and head[-2:] == ["gain", "vmid"] and close(col(head, rows, "gain")[0], float(vmid.group(1)))
      and close(col(head, rows, "vmid")[0], float(vmid.group(1))) and len(es) == 3
      and all(close(col(head, rows, "gain")[1 + i], float(es[i])) for i in range(3)),
      f"{head} {rows[:2]} {es} {out[-200:]}")

# ------------------------------------------------------------ [11] ---
check("[11] a .model card draw (dm:is) is a column on the plain run and on montecarlo's fast path alike",
      "dm:is" in head and all(v is not None and 5e-15 < v < 2e-14 for v in col(head, rows, "dm:is"))
      and len(set(col(head, rows, "dm:is"))) == 4, f"{head} {col(head, rows, 'dm:is') if 'dm:is' in head else ''}")

# ------------------------------------------------------------ [12] ---
clean()
out = run(".option savemc\n" + KIC, "t12", "montecarlo 3 -seed 2 -analysis op -writemc gain=v(/mid)/v(/in)")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[12] montecarlo with only -writemc (and savemc on) runs: three rows, each with its gain",
      "nothing to do" not in out and len(rows) == 3 and "gain" in head
      and all(v is not None and 0.8 < v < 1.0 for v in col(head, rows, "gain")), f"{head} {rows} {out[-200:]}")
out = run(KIC, "t12b", "montecarlo 3 -seed 2 -analysis op -writemc gain=v(/mid)/v(/in)")
check("[12] ...with savemc off it is nothing to do: both messages, no 'the run proceeds', no samples run",
      "nothing to do" in out and "-writemc [name=]<expression>" in out
      and "-writemc: nothing is recorded -- `.option savemc` is not set" in out
      and "the run proceeds" not in out and "random samples" not in out, out[-400:])

# ------------------------------------------------------------ [13] ---
# Enhancement-624 (hunt F8): two OSDI resistors -- one whose r may draw outside
# its (0:inf) range (the op is then refused at setup and makes no plot), one
# that $fatals past a time (the transient dies with its partial plot in place)
with open(os.path.join(WORK, "f8.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule f8r(p, n);\ninout p, n; electrical p, n;\n'
            '(* std=25.0 *) parameter real r = 1000.0 from (0:inf);\n'
            'parameter real tdie = -1.0;\n'
            'analog begin\n if (tdie > 0 && $abstime > tdie) $fatal(1, "dies");\n'
            ' I(p,n) <+ V(p,n)/r;\nend\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "f8.va"), "-o", os.path.join(WORK, "f8.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)
F8 = "V1 in 0 pulse(0 1 1u 1n 1n 10u 20u)\nN1 in 0 rm\n.model rm f8r r=1000\n"
clean()
out = run(".option savemc osdimc mcseed=3\n" + F8.replace("pulse(0 1 1u 1n 1n 10u 20u)", "1").replace("r=1000", "r=10"),
          "t13", "pre_osdi f8.osdi\nrepeat 12\n  op\n  writemc ia=i(v1)\nend")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
st = [r[2] for r in rows]
ia = col(head, rows, "ia") if "ia" in head else []
failed = [i for i, x in enumerate(st) if x == "failed"]
msgs = re.findall(r"writemc: row (\d+) \(op\) failed before it made a plot, so the current plot (op\d+) "
                  r"is another run's; nothing is put on that row", out)
check("[13] a trial whose op failed at setup: the row's writemc cell is empty, the ok rows have theirs, "
      "one message per failed row naming it and the plot really current",
      len(rows) == 12 and len(failed) >= 1 and all(ia[i] is None for i in failed)
      and all(ia[i] is not None and ia[i] < 0 for i in range(12) if i not in failed)
      and [int(m[0]) for m in msgs] == [i + 1 for i in failed]
      and all(m[1] == f"op{sum(1 for j in range(i) if st[j] == 'ok')}" for m, i in zip(msgs, failed)),
      f"failed rows {failed} ia {ia} msgs {msgs}")
clean()
out = run(".option savemc osdimc mcseed=3\n" + F8.replace("r=1000", "tdie=3u"), "t13b",
          "pre_osdi f8.osdi\ntran 0.5u 6u\nwritemc n=length(time) tlast=time[length(time)-1]")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[13] ...a transient that died part-way (a $fatal at 3us) is a failed row that keeps its partial plot: "
      "n and tlast are recorded from it",
      len(rows) == 1 and rows[0][1:3] == ["tran", "failed"] and "writemc:" not in out
      and col(head, rows, "n")[0] is not None and col(head, rows, "n")[0] > 5
      and col(head, rows, "tlast")[0] is not None and 2.5e-6 < col(head, rows, "tlast")[0] <= 3.1e-6,
      f"{head} {rows} {out[-300:]}")
clean()
out = run(".option osdimc mcseed=3\n" + F8, "t13c",
          "pre_osdi f8.osdi\nset savemc\nop\nop\nsetplot op1\nwritemc first=i(v1)\nsetplot op2\n"
          "unset savemc\nop\nset savemc\nwritemc late=i(v1)")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
refused = re.findall(r"writemc: the current plot op3 was made after row 2 \(op, plot op2\) by a run that "
                     r"has no row; nothing is put on that row", out)
check("[13] ...a setplot back to op1 writes first=i(v1) onto the later op's row; a run the recorder was off "
      "for has no row, and a writemc that reads its plot (made after row 2) is refused, naming both",
      len(rows) == 2 and "first" in head and "late" not in head and col(head, rows, "first") == [None, 0.0]
      and len(refused) == 1,
      f"{head} {rows} refused {len(refused)} {out[-300:]}")

# ------------------------------------------------------------ [14] ---
# Enhancement-625 (hunt F9): a run stopped at a breakpoint is a row
clean()
out = run(".option savemc osdimc mcseed=3\n" + F8, "t14a",
          "pre_osdi f8.osdi\nop\nstop when time > 2u\ntran 1u 6u\nwritemc n=length(time)")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[14] a run stopped at a breakpoint is a row at the pause, status paused, with its draws; "
      "the writemc there lands on it",
      len(rows) == 2 and rows[1][1:3] == ["tran", "paused"] and "writemc:" not in out
      and col(head, rows, "n") == [None, col(head, rows, "n")[1]] and 5 < col(head, rows, "n")[1] < 60
      and float(rows[1][head.index(f"{A}rm[r]")]) != 1000.0,
      f"{head} {rows} {out[-200:]}")
npause = col(head, rows, "n")[1]
clean()
out = run(".option savemc osdimc mcseed=3\n" + F8, "t14b",
          "pre_osdi f8.osdi\nop\nstop when time > 2u\ntran 1u 6u\nwritemc n=length(time)\nresume\n"
          "writemc n=length(time)\ndelete all\nresume\nwritemc n=length(time)\nop")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[14] ...the resume that completes the run turns that row ok (a resume that pauses again -- the level "
      "condition holds at its first step -- leaves it paused, no row of its own); the last writemc "
      "replaces n; the next op is a new row",
      len(rows) == 3 and rows[1][1:3] == ["tran", "ok"] and rows[2][1:3] == ["op", "ok"]
      and "writemc:" not in out and out.count("pause requested") == 2
      and col(head, rows, "n")[1] is not None and col(head, rows, "n")[1] > npause
      and col(head, rows, "n")[2] is None,
      f"{head} {rows} npause {npause} {out[-200:]}")
clean()
out = run(".option savemc osdimc mcseed=3\n" + F8.replace("r=1000", "tdie=3u"), "t14c",
          "pre_osdi f8.osdi\nop\nstop when time > 2u\ntran 0.5u 6u\nwritemc n=length(time)\n"
          "delete all\nresume\nwritemc n=length(time)")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[14] ...a resume that fails ($fatal at 3us) turns the paused row failed; the writemc after it "
      "still reads the run's own partial plot",
      len(rows) == 2 and rows[1][1:3] == ["tran", "failed"] and "writemc:" not in out
      and col(head, rows, "n")[1] is not None and col(head, rows, "n")[1] > npause,
      f"{head} {rows} {out[-200:]}")

clean()
print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
