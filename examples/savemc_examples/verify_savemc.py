#!/usr/bin/env python3
"""Enhancement-610: `.option savemc` -- the value of every parameter with
statistics, one row per analysis run, in a file beside the netlist.

`.option savemc[=csv|excel|txt|<name>.<ext>]` records, for every run-class
command (op, tran, run, ... -- one row each, a failed run marked), the
value in force of every parameter with statistics: a device slot whose value
draws (`r1 in out {agauss(1k,50,1)}`, or a random .param inlined there, as
ngspice inlines them -- each use its own draw), named `<instance>` or
`<instance>:<key>`; a subcircuit call's own drawn value, `x1.p`; and, under
`.option osdimc`, every OSDI parameter declared with `(* std= *)`, read off
the devices as `@<model>[<param>]` / `@<instance>[<param>]`. The file is
`mcparams_<date>_<time>.<ext>` in the netlist's directory (unique within a
second), csv by default; `txt` is tab-separated; `excel` a genuine .xlsx.
`.option automc_save` (alias `osdimc_save`) records the OSDI parameters only.
One file per deck: a `reset` continues it (every montecarlo sample is one),
a different deck starts another.

Checks:
  [1] the default: op, reset, op -> a csv beside the deck (not in the working
      directory), header trial/analysis/status + r1, r2, x1.p, r.x1.r1, two
      rows whose values are the devices' own (`@r1[r]` ... per run)
  [2] montecarlo on the fast path: one row per sample; r1 and r.x1.r1 equal
      the -expr records; x1.p is blank there (not re-evaluated on that path)
  [3] osdimc: `@n1[dr]`, `@sm[r]` per sample equal the -expr records; the
      baseline row is the nominal
  [4] savemc=excel: a valid .xlsx (zip), the sheet's header and rows, all
      samples present at exit
  [5] savemc=txt tab-separated; savemc=myrun.txt names the file, in the
      deck's directory; savemc=csv
  [6] automc_save / osdimc_save: the OSDI columns only
  [7] nothing to record: the note, once, and no file; OSDI statistics with
      osdimc off: the note
  [8] a failed run is a row, status failed
  [9] two decks within one second get distinct names; a second deck sourced
      in one session gets its own file and the first stays complete
  [10] no "unknown option" warning for the four spellings
  [11] (Enhancement-612) the file name keeps its case: savemc=MixedCase/Draws.csv
      writes exactly that, the note names it, and the other options on the
      same card (osdimc mcseed=5) are still folded and honoured
  [12] (Enhancement-612) a quoted name keeps its spaces, a non-ASCII name its
      bytes: savemc="dir with space/My Draws.csv", savemc=Résumé_MC.csv
  [13] (Enhancement-612) automc_save=MixedCase/Osdi.TXT (the extension picks
      the writer, case-insensitively), the `option` command of a .control
      block, and savemc=CSV still meaning the format
  [14] (Enhancement-613) a name whose directories do not exist: they are
      created (two levels), the csv holds the rows and the writemc column;
      the same for an .xlsx
  [15] (Enhancement-613) a name that cannot be opened (it is a directory):
      a warning with the reason, and the rows go to the dated default beside
      the deck instead -- the note names that file
  [16] (Enhancement-613) the directory removed while the file is open: the
      next rewrite says so once, the rows are kept in memory, and the file is
      complete once the directory is back
  [17] (Enhancement-615) a second deck sourced in one session with the SAME
      fixed name goes to <stem>_2.<ext> and says whose rows the first file
      holds; a third to _3; the first file keeps its rows. A separate ngspice
      run with the same fixed name replaces the file, as any output file
  [18] (Enhancement-617) savemc=excel: the header row sets a MODEL parameter's
      name in bold -- a `.model` card's slot (`rm:r`), an OSDI model parameter
      (`@rm[r]`) -- and an instance parameter's (`r1`, `n1:dr`, `x1.c`,
      `@n1[dr]`) in the regular font
  [19] (Enhancement-619) a writemc / -writemc column's header is blue; the
      workbook's fonts are options: savemc_font (a name, quoted when it has
      spaces), savemc_fontsize, and savemc_model / savemc_instance /
      savemc_writemc as `+`-joined style lists (bold+navy, italic,
      red+underline, a hex RRGGBB); an unknown token is said once; none of
      the five draws an "unknown option" warning
"""
import glob
import os
import re
import subprocess
import sys
import tempfile
import zipfile

A = "@"     # the accessor prefix, spelled apart so no line reads as a GitHub mention

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="savemc_")
RUNDIR = tempfile.mkdtemp(prefix="savemc_cwd_")      # ngspice's working directory, NOT the deck's


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "st.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule st(p, n);\ninout p, n; electrical p, n;\n'
            '(* std=25.0 *) parameter real r = 1000.0 from (0:inf);\n'
            '(* type="instance", std=10.0 *) parameter real dr = 0.0;\n'
            'analog I(p,n) <+ V(p,n)/(r+dr);\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "st.va"), "-o", os.path.join(WORK, "st.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def clean():
    for f in glob.glob(os.path.join(WORK, "mcparams_*")) + glob.glob(os.path.join(RUNDIR, "mcparams_*")) \
            + glob.glob(os.path.join(WORK, "myrun.*")) + glob.glob(os.path.join(WORK, "MixedCase", "*")) \
            + glob.glob(os.path.join(WORK, "dir with space", "*")) + glob.glob(os.path.join(WORK, "R*sum*.csv")) \
            + glob.glob(os.path.join(WORK, "NewDir", "*", "*")) + glob.glob(os.path.join(WORK, "NewDir", "*.xlsx")) \
            + glob.glob(os.path.join(WORK, "Shared*.csv")) + glob.glob(os.path.join(WORK, "Bold.xlsx")) \
            + glob.glob(os.path.join(WORK, "Fonts*.xlsx")):
        os.remove(f)


def run(body, tag, ctl, cwd=RUNDIR):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* savemc {tag}\n{body}.control\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=cwd, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def files(ext="csv", where=WORK):
    return sorted(glob.glob(os.path.join(where, f"mcparams_*.{ext}")))


def read_csv(path, sep=","):
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    head = lines[0].split(sep)
    rows = [l.split(sep) for l in lines[1:]]
    return head, rows


def vals(out, name):
    return [float(x) for x in re.findall(rf"^{re.escape(name)} = ([-+.\deE]+)", out, re.M)]


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))


NOTE = "Note: savemc: recording the"
PRE = ".control\npre_osdi st.osdi\n.endc\n"
DIV = (".subckt sub a b p=1k\nr1 a b {p}\n.ends\nv1 in 0 dc 1\nr1 in mid {agauss(1k, 50, 1)}\n"
       "r2 mid out {agauss(2k, 100, 1)}\nx1 out 0 sub p={gauss(500, 0.1, 1)}\n")
print("Enhancement-610: .option savemc\n")

# ------------------------------------------------------------- [1] ---
clean()
out = run(".option savemc\n" + DIV, "t1", f"op\nprint {A}r1[r] {A}r2[r] {A}r.x1.r1[r]\nreset\nop\nprint {A}r1[r] {A}r2[r] {A}r.x1.r1[r]")
fs = files()
check("[1] .option savemc: a csv named mcparams_<date>_<time>.csv beside the deck, not in the working directory",
      len(fs) == 1 and re.search(r"mcparams_\d{8}_\d{6}\.csv$", fs[0]) and not files(where=RUNDIR)
      and out.count(NOTE) == 1, f"{fs} {files(where=RUNDIR)}")
head, rows = read_csv(fs[0]) if fs else ([], [])
r1 = vals(out, f"{A}r1[r]"); r2 = vals(out, f"{A}r2[r]"); rx = vals(out, f"{A}r.x1.r1[r]")
check("[1] ...header trial,analysis,status,r1,r2,x1.p,r.x1.r1; a row per op (2), the values the devices' own",
      head == ["trial", "analysis", "status", "r1", "r2", "x1.p", "r.x1.r1"] and len(rows) == 2
      and all(rows[i][0] == str(i + 1) and rows[i][1] == "op" and rows[i][2] == "ok" for i in range(2))
      and all(close(float(rows[i][3]), r1[i]) and close(float(rows[i][4]), r2[i]) and close(float(rows[i][6]), rx[i])
              and close(float(rows[i][5]), rx[i]) for i in range(2)),
      f"{head} {rows}")

# ------------------------------------------------------------- [2] ---
clean()
out = run(".option savemc\n" + DIV, "t2",
          f'montecarlo 6 -seed 3 -analysis op -expr rr={A}r1[r] -expr rx={A}r.x1.r1[r]\n'
          'print montecarlo1.rr montecarlo1.rx')
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
rr = [float(x) for x in re.findall(r"^\d+\s+([-+.\deE]+)\s+([-+.\deE]+)", out.split("montecarlo1.rr")[-1], re.M)[:0]]
tab = re.findall(r"^\d+\s+([-+.\deE]+)\s+([-+.\deE]+)\s*$", out, re.M)
check("[2] montecarlo (fast path): one row per sample; r1 and r.x1.r1 equal the -expr records; x1.p blank there",
      "fast path armed" in out and len(rows) == 6 and len(tab) == 6
      and all(close(float(rows[i][3]), float(tab[i][0])) and close(float(rows[i][6]), float(tab[i][1]))
              and rows[i][5] == "" for i in range(6)), f"{head} {rows[:3]} {tab[:3]}")

# ------------------------------------------------------------- [3] ---
OSDI = PRE + "v1 in 0 dc 1\nr1 in out {agauss(1k, 50, 1)}\nn1 out 0 sm\n.model sm st r=1k\n"
clean()
out = run(".option savemc osdimc mcseed=5\n" + OSDI, "t3",
          f'op\nmontecarlo 5 -seed 3 -analysis op -expr d1={A}n1[dr] -expr smr={A}sm[r]\nprint montecarlo1.d1 montecarlo1.smr')
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
tab = re.findall(r"^\d+\s+([-+.\deE]+)\s+([-+.\deE]+)\s*$", out, re.M)
check(f"[3] osdimc: the baseline op row is the nominal (0, 1000); each sample's {A}n1[dr], {A}sm[r] equal the -expr records",
      head == ["trial", "analysis", "status", "r1", f"{A}n1[dr]", f"{A}sm[r]"] and len(rows) == 6 and len(tab) == 5
      and float(rows[0][4]) == 0.0 and float(rows[0][5]) == 1000.0
      and all(close(float(rows[i + 1][4]), float(tab[i][0])) and close(float(rows[i + 1][5]), float(tab[i][1]))
              for i in range(5)), f"{head} {rows[:3]} {tab[:2]}")

# ------------------------------------------------------------- [4] ---
clean()
out = run(".option savemc=excel osdimc mcseed=5\n" + OSDI, "t4",
          f'montecarlo 30 -seed 3 -analysis op -expr rr={A}r1[r] -expr d1={A}n1[dr]\nprint montecarlo1.rr[2] montecarlo1.d1[2]')
fs = files("xlsx")
ok = False
detail = str(fs)
if fs:
    z = zipfile.ZipFile(fs[0])
    bad = z.testzip()
    names = z.namelist()
    x = z.read("xl/worksheets/sheet1.xml").decode()
    xrows = re.findall(r'<row r="(\d+)">(.*?)</row>', x)
    cells = [[c[0] or c[1] for c in re.findall(r'<c r="[A-Z]+\d+"(?: s="\d+")?(?: t="inlineStr")?>(?:<is><t>(.*?)</t></is>|<v>(.*?)</v>)</c>', b)]
             for _, b in xrows]     # E-617: a header cell may carry a style
    ok = (bad is None and "xl/workbook.xml" in names and "xl/styles.xml" in names
          and cells[0] == ["trial", "analysis", "status", "r1", f"{A}n1[dr]", f"{A}sm[r]"] and len(cells) == 31
          and close(float(cells[3][3]), vals(out, "montecarlo1.rr[2]")[0])
          and close(float(cells[3][4]), vals(out, "montecarlo1.d1[2]")[0]))
    detail = f"{bad} {names} {cells[:2]} {len(cells)}"
check("[4] savemc=excel: a valid .xlsx, the header, all 30 samples present at exit, sample 3 equal to the record", ok, detail)

# ------------------------------------------------------------- [5] ---
clean()
out = run(".option savemc=txt\n" + OSDI, "t5a", "op\nreset\nop")
fs = files("txt"); head, rows = read_csv(fs[0], "\t") if fs else ([], [])
check("[5] savemc=txt: tab-separated, two rows", len(fs) == 1 and head == ["trial", "analysis", "status", "r1"]
      and len(rows) == 2 and "\t" in open(fs[0]).readline(), f"{fs} {head}")
clean()
out = run(".option savemc=myrun.txt\n" + OSDI, "t5b", "op")
p = os.path.join(WORK, "myrun.txt")
check("[5] savemc=myrun.txt: the named file, in the deck's directory, tab-separated by its extension",
      os.path.exists(p) and "\t" in open(p).readline() and not files("txt") and f"to {p}" in out, out[-200:])
clean()
out = run(".option savemc=csv\n" + OSDI, "t5c", "op")
check("[5] savemc=csv: the same as the bare option", len(files()) == 1 and NOTE in out, str(files()))

# ------------------------------------------------------------- [6] ---
clean()
out = run(".option automc_save osdimc mcseed=5\n" + OSDI, "t6a",
          f'montecarlo 4 -seed 3 -analysis op -expr d1={A}n1[dr]\nprint montecarlo1.d1')
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
tab = re.findall(r"^\d+\s+([-+.\deE]+)\s*$", out, re.M)
check("[6] automc_save: the OSDI columns only; the values per sample equal the record",
      head == ["trial", "analysis", "status", f"{A}n1[dr]", f"{A}sm[r]"] and len(rows) == 4 and len(tab) == 4
      and all(close(float(rows[i][3]), float(tab[i])) for i in range(4)), f"{head} {rows[:2]}")
clean()
out = run(".option osdimc_save=txt osdimc mcseed=5\n" + OSDI, "t6b", "op")
fs = files("txt"); head, rows = read_csv(fs[0], "\t") if fs else ([], [])
check("[6] osdimc_save=txt: the alias, with a format", head == ["trial", "analysis", "status", f"{A}n1[dr]", f"{A}sm[r]"], f"{head}")

# ------------------------------------------------------------- [7] ---
clean()
out = run(".option savemc\nv1 in 0 dc 1\nr1 in out 1k\nr2 out 0 1k\n", "t7a", "op\nop")
check("[7] nothing statistical: the note once, no file",
      out.count("nothing to record -- no parameter with statistics") == 1 and not files() and NOTE not in out, out[-300:])
clean()
out = run(".option savemc\n" + PRE + "v1 in 0 dc 1\nr1 in out 1k\nn1 out 0 sm\n.model sm st r=1k\n", "t7b", "op")
check("[7] OSDI statistics declared, osdimc off: the note says they are not drawn nor recorded",
      "declare statistics, but `.option osdimc` is off" in out and not files(), out[-300:])
clean()
out = run(".option automc_save\n" + DIV, "t7c", "op")
check("[7] automc_save on a deck with no OSDI statistics: the note names the scope",
      "no OSDI parameter with statistics" in out and "automc_save records OSDI parameters only" in out and not files(),
      out[-300:])

# ------------------------------------------------------------- [8] ---
clean()
out = run(".option savemc\nv1 in 0 dc 1\nr1 in out {agauss(1k, 50, 1)}\nr2 out 0 1k\n", "t8",
          "op\ntran 1n 10n\ndc v1 0 1 -0.1")
fs = files(); head, rows = read_csv(fs[0]) if fs else ([], [])
check("[8] op, tran and a refused dc: three rows, the dc marked failed, the same draw on all",
      [r[1:3] for r in rows] == [["op", "ok"], ["tran", "ok"], ["dc", "failed"]]
      and len({r[3] for r in rows}) == 1, f"{rows}")

# ------------------------------------------------------------- [9] ---
clean()
out1 = run(".option savemc\n" + OSDI, "t9a", "op")
out2 = run(".option savemc\n" + OSDI, "t9b", "op")
fs = files()
check("[9] two runs within one second: two files, distinct names",
      len(fs) == 2 and fs[0] != fs[1], str([os.path.basename(f) for f in fs]))
clean()
with open(os.path.join(WORK, "second.cir"), "w") as f:
    f.write("* savemc second deck\n.option savemc\nv1 in 0 dc 1\nr1 in out {agauss(3k, 50, 1)}\nr2 out 0 1k\n"
            ".control\nop\n.endc\n.end\n")
out = run(".option savemc\n" + OSDI, "t9c", f"op\nreset\nop\nsource {os.path.join(WORK, 'second.cir')}\nop")
fs = files()
heads = [read_csv(f) for f in fs]
check("[9] a second deck sourced in one session: its own file; the first holds its two rows",
      len(fs) == 2 and sorted(len(h[1]) for h in heads) == [2, 2] and out.count(NOTE) == 2,
      f"{[os.path.basename(f) for f in fs]} {[len(h[1]) for h in heads]}")

# ------------------------------------------------------------ [10] ---
clean()
out = run(".option savemc nosavemc automc_save osdimc_save\n" + OSDI, "t10", "op")
check("[10] no 'unknown option' warning for savemc, nosavemc, automc_save, osdimc_save; nosavemc turns it off",
      "unknown option" not in out and not files() and NOTE not in out, out[-300:])

# ------------------------------------------------------------ [11] ---
# Enhancement-612: the value of a file-name option keeps its bytes. The deck
# reader folded it to lower case and inp_casefix() replaced every non-ASCII
# byte with `_`, so `savemc=MyRun/Draws.csv` wrote `myrun/draws.csv` and
# `Résumé.csv` was written as `r__sum__.csv`.
clean()
os.makedirs(os.path.join(WORK, "MixedCase"), exist_ok=True)
os.makedirs(os.path.join(WORK, "dir with space"), exist_ok=True)
out = run(".option savemc=MixedCase/Draws.csv OSDIMC MCSEED=5\n" + OSDI, "t11", "op\nop\nlisting")
path = os.path.join(WORK, "MixedCase", "Draws.csv")
ok = os.path.exists(path) and NOTE in out and "MixedCase/Draws.csv" in out
head, rows = read_csv(path) if ok else ([], [])
col = head.index(f"{A}sm[r]") if f"{A}sm[r]" in head else -1
check("[11] savemc=MixedCase/Draws.csv: the file has exactly that name, the note and the listing show it",
      ok and " .option savemc=MixedCase/Draws.csv osdimc mcseed=5" in out, out[-400:] if not ok else "")
check("[11] the other options on the card are still folded and honoured: osdimc drew on trial 2",
      col >= 0 and len(rows) == 2 and rows[0][col] == "1000" and rows[1][col] != "1000", f"{head} {rows}")

# ------------------------------------------------------------ [12] ---
clean()
out = run('.option savemc="dir with space/My Draws.csv"\n' + DIV, "t12a", "op")
path = os.path.join(WORK, "dir with space", "My Draws.csv")
check('[12] savemc="dir with space/My Draws.csv": a quoted name keeps its spaces (one file, two rows)',
      os.path.exists(path) and len(read_csv(path)[1]) == 1 and "dir with space/My Draws.csv" in out,
      out[-300:] if not os.path.exists(path) else "")
out = run(".option savemc=R\u00e9sum\u00e9_MC.csv\n" + DIV, "t12b", "op")
path = os.path.join(WORK, "R\u00e9sum\u00e9_MC.csv")
check("[12] savemc=Résumé_MC.csv: a non-ASCII name keeps its bytes",
      os.path.exists(path) and "R\u00e9sum\u00e9_MC.csv" in out, out[-300:] if not os.path.exists(path) else "")

# ------------------------------------------------------------ [13] ---
clean()
out = run(".option automc_save=MixedCase/Osdi.TXT osdimc\n" + OSDI, "t13a", "op")
path = os.path.join(WORK, "MixedCase", "Osdi.TXT")
head = read_csv(path, "\t")[0] if os.path.exists(path) else []
check("[13] automc_save=MixedCase/Osdi.TXT: the name kept, the .TXT extension picks the tab-separated writer",
      head == ["trial", "analysis", "status", f"{A}n1[dr]", f"{A}sm[r]"], f"{head} {out[-200:] if not head else ''}")
out = run(DIV, "t13b", "option savemc=MixedCase/FromControl.csv\nop")
ok = os.path.exists(os.path.join(WORK, "MixedCase", "FromControl.csv"))
check("[13] the `option` command of a .control block keeps the name too", ok, "" if ok else out[-300:])
clean()
out = run(".option savemc=CSV\n" + DIV, "t13c", "op")
check("[13] savemc=CSV is still the format keyword (a dated mcparams_ file)",
      len(files()) == 1 and not os.path.exists(os.path.join(WORK, "CSV")), str(files()))

# ------------------------------------------------------------ [14] ---
# Enhancement-613: a name whose directory does not exist was announced and
# then nothing was written -- no error, every row and writemc value lost.
# The directories are made now (each level), and a name that still cannot
# be opened is reported with the reason and the rows go to the dated
# default beside the deck.
clean()
import shutil  # noqa: E402
shutil.rmtree(os.path.join(WORK, "NewDir"), ignore_errors=True)
out = run(".option savemc=NewDir/Sub/Rows.csv\n" + DIV, "t14a", "op\nwritemc ia=i(v1)\nreset\nop\nwritemc ia=i(v1)")
path = os.path.join(WORK, "NewDir", "Sub", "Rows.csv")
head, rows = read_csv(path) if os.path.exists(path) else ([], [])
ok = (len(rows) == 2 and head[-1] == "ia" and all(r[-1] for r in rows) and "NewDir/Sub/Rows.csv" in out
      and "Warning: savemc" not in out and "Error: savemc" not in out)
check("[14] savemc=NewDir/Sub/Rows.csv with no NewDir: both levels created, two rows, the writemc column, no warning",
      ok, "" if ok else f"{head} {out[-300:]}")
shutil.rmtree(os.path.join(WORK, "NewDir"), ignore_errors=True)
out = run(".option savemc=NewDir/Book.xlsx\n" + DIV, "t14b", "op\nreset\nop")
path = os.path.join(WORK, "NewDir", "Book.xlsx")
ok = False
if os.path.exists(path) and zipfile.is_zipfile(path):
    with zipfile.ZipFile(path) as z:
        ok = len(re.findall(r"<row ", z.read("xl/worksheets/sheet1.xml").decode())) == 3
check("[14] savemc=NewDir/Book.xlsx with no NewDir: the directory created, a valid workbook with the header and two rows",
      ok, out[-300:] if not ok else "")

# ------------------------------------------------------------ [15] ---
clean()
os.makedirs(os.path.join(WORK, "IsADir.csv"), exist_ok=True)
out = run(".option savemc=IsADir.csv\n" + DIV, "t15", "op")
fs = files()
m = re.search(r"Warning: savemc: cannot open \S*IsADir\.csv \((.+?)\); recording to (\S+) instead", out)
check("[15] savemc=IsADir.csv (a directory): the warning gives the reason and the fallback, the note names the fallback",
      bool(m) and len(fs) == 1 and m.group(2) == os.path.join(WORK, os.path.basename(fs[0]))
      and (NOTE + " 4 parameters with statistics, one row per analysis run, to " + m.group(2)) in out,
      out[-400:] if not m else f"{m.group(1)}; {fs}")
check("[15] ...and the fallback holds the row", len(fs) == 1 and len(read_csv(fs[0])[1]) == 1)
os.rmdir(os.path.join(WORK, "IsADir.csv"))

# ------------------------------------------------------------ [16] ---
clean()
shutil.rmtree(os.path.join(WORK, "NewDir"), ignore_errors=True)
out = run(".option savemc=NewDir/Late.csv\n" + DIV, "t16",
          "op\nwritemc ia=i(v1)\nshell rm -r NewDir\nreset\nop\nwritemc ib=i(v1)\nreset\nop\nwritemc ib=i(v1)\n"
          "shell mkdir NewDir\nreset\nop\nwritemc ic=i(v1)", cwd=WORK)
path = os.path.join(WORK, "NewDir", "Late.csv")
head, rows = read_csv(path) if os.path.exists(path) else ([], [])
ok = out.count("Error: savemc: cannot write") == 1 and "rows so far are kept" in out
check("[16] the directory removed while the file is open: 'cannot write ... rows so far are kept' said once",
      ok, "" if ok else out[-300:])
ok = (len(rows) == 4 and head[-3:] == ["ia", "ib", "ic"] and rows[0][-3] and rows[1][-2] and rows[2][-2]
      and rows[3][-1] and not rows[0][-1] and not rows[3][-3])
check("[16] ...and the file is complete once the directory is back: four rows, ia/ib/ic columns filled where written",
      ok, "" if ok else f"{head} {rows}")
shutil.rmtree(os.path.join(WORK, "NewDir"), ignore_errors=True)

# ------------------------------------------------------------ [17] ---
# Enhancement-615: a second deck sourced in one session with the same fixed
# name replaced the first deck's file without a word.
clean()
with open(os.path.join(WORK, "other.cir"), "w") as f:
    f.write("* savemc other deck\n.option savemc=Shared.csv\nv1 in 0 dc 1\nr1 in out {agauss(3k, 50, 1)}\n"
            "r2 out 0 1k\n.control\nop\n.endc\n.end\n")
with open(os.path.join(WORK, "first.cir"), "w") as f:
    f.write("* savemc first deck\n.option savemc=Shared.csv\n" + DIV + ".control\nop\nreset\nop\n.endc\n.end\n")
out = run("v1 in 0 dc 1\nr1 in 0 1k\n", "t17",
          f"source {os.path.join(WORK, 'first.cir')}\nsource {os.path.join(WORK, 'other.cir')}\n"
          f"source {os.path.join(WORK, 'first.cir')}")
p1, p2, p3 = (os.path.join(WORK, n) for n in ("Shared.csv", "Shared_2.csv", "Shared_3.csv"))
rows = [len(read_csv(p)[1]) if os.path.exists(p) else -1 for p in (p1, p2, p3)]
heads = [read_csv(p)[0][3:] if os.path.exists(p) else [] for p in (p1, p2, p3)]
note2 = f"Note: savemc: {p1} holds the rows of '* savemc first deck' from earlier in this session and is kept; this deck's rows go to {p2}"
note3 = f"holds the rows of '* savemc first deck' from earlier in this session and is kept; this deck's rows go to {p3}"
ok = rows[0] == 2 and rows[1] == 1 and heads[1] == ["r1"] and note2 in out
check("[17] the same fixed name from a second deck: Shared_2.csv, the note names the first deck; the first file keeps its two rows",
      ok, "" if ok else f"rows={rows} heads={heads} {out[-400:]}")
ok = rows[2] == 2 and heads[2] == heads[0] and note3 in out and out.count(NOTE) == 3
check("[17] ...the first deck sourced again after it: Shared_3.csv (its own file is kept too), with its two rows",
      ok, "" if ok else f"rows={rows} {out[-300:]}")
out = run(".option savemc=Shared.csv\n" + DIV, "t17b", "op")
ok = os.path.exists(p1) and len(read_csv(p1)[1]) == 1 and "holds the rows of" not in out
check("[17] a separate ngspice run with the same fixed name replaces the file, without the note (one row now)",
      ok, "" if ok else out[-300:])

# ------------------------------------------------------------ [18] ---
# Enhancement-617: the xlsx header tells a model parameter from an instance
# parameter by its font -- bold for a model card's (a `.model` slot drawn in
# the netlist, an OSDI model parameter), regular for the rest.
# Enhancement-619: a writemc column's header is blue; the fonts are options.


def xlsx_fonts(path):
    """header name -> (bold, italic, underline, rgb, font name, size), from the sheet and styles"""
    out = {}
    if not (os.path.exists(path) and zipfile.is_zipfile(path)):
        return out
    with zipfile.ZipFile(path) as z:
        st = z.read("xl/styles.xml").decode()
        fonts = re.findall(r"<font>(.*?)</font>", st)
        xfs = re.findall(r'<xf [^>]*fontId="(\d+)"[^>]*/>', re.search(r"<cellXfs.*?</cellXfs>", st).group(0))
        row1 = re.search(r'<row r="1">(.*?)</row>', z.read("xl/worksheets/sheet1.xml").decode()).group(1)
        for style, name in re.findall(r'<c r="[A-Z]+1"(?: s="(\d+)")? t="inlineStr"><is><t>(.*?)</t>', row1):
            fx = fonts[int(xfs[int(style or 0)])]
            m = re.search(r'<color rgb="FF([0-9A-F]{6})"/>', fx)
            out[name] = ("<b/>" in fx, "<i/>" in fx, "<u/>" in fx, m.group(1) if m else None,
                         re.search(r'<name val="(.*?)"/>', fx).group(1), float(re.search(r'<sz val="(.*?)"/>', fx).group(1)))
    return out


clean()
MIXED = (".param rr = agauss(20, 3, 3)\n.subckt load a b c=1u\nC1 a b {c}\n.ends\nv1 in 0 dc 1\nR1 in m {rr}\n"
         "x1 m 0 load c={gauss(1u, 0.1, 1)}\nN1 m 0 sm dr={agauss(0,30,3)}\nN2 m 0 sm\n"
         ".model sm st r={agauss(1000,300,3)}\n")
out = run(".option savemc=Bold.xlsx osdimc mcseed=1\n" + PRE + MIXED, "t18", "op\nreset\nop")
fx = xlsx_fonts(os.path.join(WORK, "Bold.xlsx"))
bold = sorted(n for n, f in fx.items() if f[0])
plain = sorted(n for n, f in fx.items() if not f[0])
ok = (bold == sorted(["sm:r", f"{A}sm[r]"])
      and plain == sorted(["trial", "analysis", "status", "r1", "x1.c", "c.x1.c1", "n1:dr", f"{A}n2[dr]", f"{A}n1[dr]"])
      and all(f[1:4] == (False, False, None) for f in fx.values()))
check("[18] savemc=Bold.xlsx: the header sets sm:r and @sm[r] (model) in bold, r1 / x1.c / c.x1.c1 / n1:dr / @n1[dr] / @n2[dr] (instance) regular",
      ok, "" if ok else f"bold={bold} plain={plain} {out[-200:]}")

# ------------------------------------------------------------ [19] ---
clean()
WMC = (".param rr = agauss(20, 3, 3)\nv1 in 0 dc 1\nR1 in m {rr}\nN1 m 0 sm dr={agauss(0,30,3)}\n"
       ".model sm st r={agauss(1000,300,3)}\n")
out = run(".option savemc=Fonts.xlsx osdimc mcseed=1\n" + PRE + WMC, "t19a",
          "op\nwritemc ia=i(v1)\nmontecarlo 2 -analysis op -expr rr=@sm[r] -writemc pk=v(m)")
fx = xlsx_fonts(os.path.join(WORK, "Fonts.xlsx"))
ok = (set(fx) == {"trial", "analysis", "status", "r1", "n1:dr", "sm:r", f"{A}n1[dr]", f"{A}sm[r]", "ia", "pk"}
      and fx["ia"] == (False, False, False, "0000FF", "Calibri", 11.0) and fx["pk"] == fx["ia"]
      and fx["sm:r"] == (True, False, False, None, "Calibri", 11.0) and fx["r1"] == (False, False, False, None, "Calibri", 11.0)
      and fx["trial"] == fx["r1"])
check("[19] the defaults: a writemc column (`writemc ia=`) and a -writemc column (`-writemc pk=`) are blue in the header; "
      "model bold, instance and the fixed three regular; Calibri 11 throughout",
      ok, "" if ok else f"{fx} {out[-300:]}")
out = run('.option savemc=Fonts2.xlsx osdimc mcseed=1 savemc_font="Times New Roman" savemc_fontsize=12\n'
          ".option savemc_model=bold+navy savemc_instance=italic savemc_writemc=red+underline+shiny+1A2B3C\n" + PRE + WMC,
          "t19b", "op\nwritemc ia=i(v1)")
fx = xlsx_fonts(os.path.join(WORK, "Fonts2.xlsx"))
ok = (fx.get("sm:r") == (True, False, False, "000080", "Times New Roman", 12.0)
      and fx.get("r1") == (False, True, False, None, "Times New Roman", 12.0)
      and fx.get("ia") == (False, False, True, "1A2B3C", "Times New Roman", 12.0)
      and fx.get("trial") == (False, False, False, None, "Times New Roman", 12.0)
      and out.count("Warning: .option savemc_writemc: 'shiny' is not a style") == 1
      and "unknown option" not in out)
check('[19] savemc_font="Times New Roman" savemc_fontsize=12 savemc_model=bold+navy savemc_instance=italic '
      "savemc_writemc=red+underline+shiny+1A2B3C: the styles land (the last colour wins), 'shiny' is said once, "
      "no 'unknown option' warning for the five names",
      ok, "" if ok else f"{fx} {out[-400:]}")

clean()
print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
