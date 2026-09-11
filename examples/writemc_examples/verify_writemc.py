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
from _setup import NG as NGSPICE  # noqa: E402
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
    cells = [[c[0] or c[1] for c in re.findall(r'<c r="[A-Z]+\d+"(?: t="inlineStr")?>(?:<is><t>(.*?)</t></is>|<v>(.*?)</v>)</c>', b)]
             for _, b in xrows]
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

clean()
print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
