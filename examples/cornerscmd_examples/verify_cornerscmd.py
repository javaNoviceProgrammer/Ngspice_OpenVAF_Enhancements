#!/usr/bin/env python3
"""Enhancement-655: the `corners` command -- the analysis at every process
corner the loaded Verilog-A models declare (E-654), and `-mc N` for a
montecarlo per corner.

  corners [-list <c1>[,<c2>...]] [-nonominal] [-analysis <cmd>] [-output <expr> ...]
  corners [-list ...] [-nonominal] [-analysis <cmd>] -mc <N> <montecarlo arguments>

For each corner (the nominal `tt` first, then the declared ones in
declaration order) the command sets the `corner` variable, runs the analysis
and evaluates each -output (its LAST value); the values go into a
`corners<n>` plot whose scale `corner` is the corner's index, the names in
$corners_names. Under -mc the rest of the line is a montecarlo run once per
corner; the plot records yield, npass, nsamples, nfailed. A `.option savemc`
file gains a `corner` column with the first cornered row.

Checks (per solver):
  [1]  the default set (tt, then the declared corners), the table, the plot
       with the `corner` scale and the -output vectors, the values per corner
  [2]  -list with commas or spaces, in the given order; nom is tt
  [3]  -nonominal drops tt
  [4]  $corners_n / $corners_names / $corners_plot; cleared by a refusal
  [5]  a listed corner nobody declares: the error names the declared ones,
       nothing runs
  [6]  refusals: a destructive -analysis, an unknown option, -mc 0, -output
       under -mc (either order), -list without names
  [7]  an -output that never resolves is an error and not recorded
  [8]  a corner whose analysis fails: "(the analysis failed)", nan in the
       vector, the other corners intact
  [9]  -mc N -spec: a montecarlo per corner, the yield table and plot; the
       cornered parameter pinned on the cornered rows, drawn on the tt rows
  [10] -analysis before -mc is forwarded, a quoted analysis reaches
       montecarlo intact
  [11] the `corner` variable is put back: an earlier `set corner=ff` holds
       after the command, none stays none
  [12] savemc: the `corner` column appears with the first cornered row, the
       earlier row's cell empty; the xlsx workbook has it too
  [13] `.option corner=tt` by name tags its rows `tt`
  [14] `writemc corner=...` is refused: a fixed column's name
  [15] no -output: nothing recorded, said; the plot holds the scale alone
  [16] a circuit whose models declare no corner: refused
  [17] `oldhelp corners` prints the entry
  [18] a deck that names a corner in .option: the loop still visits tt and
       the deck's corner is back afterwards
"""
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
WORK = tempfile.mkdtemp(prefix="cornerscmd_")
A = "@"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


MODELS = {
    "cr": '''`include "disciplines.vams"
module cr(p, n);
inout p, n; electrical p, n;
(* corner="ss=115, ff=88" *)                     parameter real rsh = 100 from (0:inf);
(* corner="ss=+10% ff=-10%" *)                  parameter real k   = 2.0;
(* std=0.02, corner="ss=+3sigma, ff=-3sigma" *)  parameter real vth = 0.45;
analog I(p,n) <+ V(p,n)/(rsh*k) + V(p,n)*vth*0;
endmodule
''',
    "cs": '''`include "disciplines.vams"
module cs(p, n);
inout p, n; electrical p, n;
(* std=5, corner="ss=+2sigma, ff=-2sigma" *) parameter real r = 100 from (0:inf);
(* std=1 *)                                 parameter real q = 10;
(* corner="fs=2" *)                          parameter real w = 1;
analog I(p,n) <+ V(p,n)/r + V(p,n)*q*0 + V(p,n)*w*0;
endmodule
''',
    "cf": '''`include "disciplines.vams"
module cf(p, n);
inout p, n; electrical p, n;
(* corner="bad=-1, ss=2" *) parameter real g = 1 from (0:inf);
analog I(p,n) <+ V(p,n)*g*1e-3;
endmodule
''',
    "cn": '''`include "disciplines.vams"
module cn(p, n);
inout p, n; electrical p, n;
(* std=1 *) parameter real z = 1;
analog I(p,n) <+ V(p,n)*z*1e-3;
endmodule
''',
}
for name, src in MODELS.items():
    with open(os.path.join(WORK, name + ".va"), "w") as f:
        f.write(src)
    r = subprocess.run([VAF, name + ".va", "-o", name + ".osdi"], capture_output=True, text=True, cwd=WORK)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)

HEAD = ("* cornerscmd {tag}\n.control\npre_osdi cr.osdi\npre_osdi cs.osdi\n.endc\n{opts}\n"
        "v1 in 0 dc 1\nn1 in 0 rm\nn2 in 0 sm\nr1 in out 1k\nr2 out 0 1k\n"
        ".model rm cr rsh=100\n.model sm cs r=100\n.control\n{body}\n.endc\n.end\n")


def run(body, tag, opts="", head=HEAD):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(head.format(tag=tag, opts=opts, body=body))
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=600, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


def table(out, after=""):
    """the corners table rows after `after`: list of (idx, name, cells...)"""
    seg = out.split(after, 1)[1] if after and after in out else out
    rows = []
    for m in re.finditer(r"^  (\d+)\s+(\S+)\s+(.*)$", seg, re.M):
        rows.append((int(m.group(1)), m.group(2), m.group(3).split()))
    return rows


def near(x, y, tol=1e-6):
    try:
        return abs(float(x) - y) <= tol * max(1.0, abs(y))
    except (TypeError, ValueError):
        return False


def csv_rows(name):
    p = os.path.join(WORK, name)
    if not os.path.exists(p):
        return [], []
    lines = open(p).read().splitlines()
    return lines[0].split(","), [l.split(",") for l in lines[1:] if l.strip()]


# [1] default set
rc, out = run(f"corners -output v(out) rsh={A}rm[rsh] r={A}sm[r]\nprint corner v(out) rsh r\n", "c1")
rows = table(out, "into plot")
ok1 = ([r[1] for r in rows] == ["tt", "ss", "ff", "fs"]
       and all(near(r[2][0], 0.5) for r in rows)
       and [round(float(r[2][1])) for r in rows] == [100, 115, 88, 100]
       and [round(float(r[2][2])) for r in rows] == [100, 110, 90, 100]
       and "into plot 'corners1'" in out
       and re.search(r"^3\s+3\.0+e\+00\s+5\.0+e-01\s+1\.0+e\+02\s+1\.0+e\+02", out, re.M) is not None)
check("[1] the default set tt, ss, ff, fs in declaration order; the table and the corners1 plot with the `corner` scale and the outputs",
      ok1, f"rows={rows}")

# [2] -list forms, [3] -nonominal
rc, out = run(f"corners -list ff,ss -output {A}rm[rsh]\ncorners -list ff ss nom -output {A}rm[rsh]\ncorners -nonominal -output {A}rm[rsh]\n", "c2")
segs = out.split("corners: ")
lists = [[r[1] for r in table(s)] for s in segs if "into plot" in s]
check("[2] -list with commas or spaces, in the given order; nom is tt",
      lists[:2] == [["ff", "ss"], ["ff", "ss", "tt"]], f"{lists}")
check("[3] -nonominal drops tt", lists[2:3] == [["ss", "ff", "fs"]], f"{lists}")

# [4] result variables, cleared by a refusal
rc, out = run(f"corners -list tt ss -output {A}rm[rsh]\necho \"n=$corners_n names=$corners_names plot=$corners_plot\"\n"
              f"corners -list sss -output {A}rm[rsh]\necho \"set=$?corners_names n=$?corners_n\"\n", "c4")
check("[4] $corners_n, $corners_names, $corners_plot are set; a refused run clears them",
      "n=2 names=tt ss plot=corners1" in out and "set=0 n=0" in out, out[-200:].replace("\n", "|"))

# [5] unknown listed corner
check("[5] a listed corner nobody declares: the error names the declared ones and nothing runs",
      "corners: 'sss' is a corner no loaded model declares (declared: ss, ff, fs)" in out
      and out.count("into plot") == 1, out[-200:].replace("\n", "|"))

# [6] refusals
rc, out = run("corners -analysis reset -output v(out)\ncorners -bogus\ncorners -mc 0\ncorners -mc 3 -output v(out)\n"
              "corners -output v(out) -mc 3\ncorners -list\ncorners -list -output v(out)\n", "c6")
want = ["would destroy the circuit", "unknown option '-bogus'", "-mc needs a positive integer",
        "-output records a value per corner; under -mc", "-list needs corner names"]
check("[6] refusals: a destructive -analysis, an unknown option, -mc 0, -output under -mc in either order, -list without names",
      all(w in out for w in want) and out.count("under -mc") == 2 and out.count("-list needs") == 2 and "into plot" not in out,
      f"missing={[w for w in want if w not in out]}")

# [7] an output that never resolves
rc, out = run(f"corners -list tt ss -output v(out) nothere=v(nowhere)\nprint nothere\n", "c7")
check("[7] an -output that never resolves is an error and its column is not recorded",
      "corners -output v(nowhere) never resolved" in out and "vector nothere is not available" in out
      and len(table(out, "into plot")) == 2, out[-300:].replace("\n", "|"))

# [8] a corner whose analysis fails
HEADF = ("* cornerscmd {tag}\n.control\npre_osdi cf.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in 0 fm\nr1 in out 1k\nr2 out 0 1k\n"
         ".model fm cf\n.control\n{body}\n.endc\n.end\n")
rc, out = run(f"corners -list tt bad ss -output v(out) g={A}fm[g]\nprint g\n", "c8", head=HEADF)
rows = table(out, "into plot")
check("[8] a corner whose analysis fails: '(the analysis failed)', nan in the vector, the other corners intact",
      len(rows) == 3 and rows[1][2][:2] == ["(the", "analysis"] and near(rows[0][2][1], 1.0) and near(rows[2][2][1], 2.0)
      and re.search(r"^1\s+nan", out, re.M | re.I) is not None, f"rows={rows} " + out[-200:].replace("\n", "|"))

# [9] -mc per corner
rc, out = run(f"corners -list tt ss ff -mc 4 -analysis op -spec {A}sm[q] -max 10.5 -seed 5\nprint corner yield npass nsamples nfailed\n",
              "c9", ".option osdimc savemc=c9.csv")
rows = table(out, "into plot")
hdr, data = csv_rows("c9.csv")
ci = hdr.index("corner") if "corner" in hdr else -1
ri = hdr.index(A + "sm[r]") if A + "sm[r]" in hdr else -1
tt_r = [float(r[ri]) for r in data if ci >= 0 and r[ci] == "tt"]
ss_r = [float(r[ri]) for r in data if ci >= 0 and r[ci] == "ss"]
check("[9] -mc N -spec: a montecarlo per corner, the yield table and plot; savemc rows tagged, the cornered parameter pinned under ss and drawn under tt",
      out.count("corners: --- corner") == 3 and [r[1] for r in rows] == ["tt", "ss", "ff"]
      and all(r[2][0].endswith("%") and r[2][2] == "4" for r in rows)
      and hdr[:4] == ["trial", "analysis", "status", "corner"]
      and len(tt_r) == 4 and len(set(tt_r)) > 1 and len(ss_r) == 4 and all(near(v, 110.0) for v in ss_r)
      and re.search(r"^1\s+1\.0+e\+00\s+\S+\s+\S+\s+4\.0+e\+00", out, re.M) is not None,
      f"rows={rows} hdr={hdr[:5]} tt_r={tt_r} ss_r={ss_r}")

# [10] -analysis forwarding, quoted analysis
rc, out = run(f"corners -list tt -analysis op -mc 2 -spec {A}sm[q] -max 10.5\n"
              f"corners -list tt -mc 2 -analysis \"tran 1u 3u\" -spec {A}sm[q] -max 10.5\n", "c10", ".option osdimc")
check("[10] -analysis before -mc is forwarded; a quoted analysis reaches montecarlo intact",
      "montecarlo 2 per corner: -analysis op" in out and "analysis 'op'" in out
      and "analysis 'tran 1u 3u'" in out, out[-300:].replace("\n", "|"))

# [11] the corner variable is put back
rc, out = run(f"set corner=ff\ncorners -list tt ss -output {A}rm[rsh]\necho \"var=$corner\"\nop\nprint {A}rm[rsh]\n"
              f"unset corner\ncorners -list ss -output {A}rm[rsh]\necho \"set=$?corner\"\nop\nprint {A}rm[rsh]\n", "c11")
vals = re.findall(re.escape(A + "rm[rsh]") + r" = ([0-9.e+-]+)", out)
check("[11] the `corner` variable is put back: an earlier ff holds and the next run is at ff; none stays none",
      "var=ff" in out and "set=0" in out and [round(float(v)) for v in vals] == [88, 100], f"vals={vals} " + out[-200:].replace("\n", "|"))

# [12] savemc column appears with the first cornered row; xlsx
rc, out = run(f"op\ncorners -list ss ff -output {A}rm[rsh]\n", "c12", ".option osdimc savemc=c12.csv")
hdr, data = csv_rows("c12.csv")
rc2, out2 = run(f"op\ncorners -list ss -output {A}rm[rsh]\n", "c12x", ".option osdimc savemc=c12x.xlsx")
xl_ok = False
try:
    z = zipfile.ZipFile(os.path.join(WORK, "c12x.xlsx"))
    sheet = [n for n in z.namelist() if "sheet1" in n][0]
    x = z.read(sheet).decode()
    row1 = re.search(r'<row r="1".*?</row>', x, re.S).group(0)
    row3 = re.search(r'<row r="3".*?</row>', x, re.S).group(0)
    xl_ok = ('<c r="D1"' in row1 and "corner" in row1) and ('<c r="D3"' in row3 and ">ss<" in row3)
except Exception as e:  # noqa: BLE001
    xl_ok = False
check("[12] savemc: the `corner` column appears with the first cornered row, the earlier row's cell empty; the xlsx workbook has it too",
      hdr[:4] == ["trial", "analysis", "status", "corner"] and len(data) == 3 and data[0][3] == "" and data[1][3] == "ss" and data[2][3] == "ff" and xl_ok,
      f"hdr={hdr[:4]} cells={[d[3] for d in data]} xlsx={xl_ok}")

# [13] .option corner=tt by name tags rows tt
rc, out = run("op\nop\n", "c13", ".option corner=tt savemc=c13.csv")
hdr, data = csv_rows("c13.csv")
check("[13] `.option corner=tt` by name tags its rows `tt` (and records them)",
      hdr[:4] == ["trial", "analysis", "status", "corner"] and [d[3] for d in data] == ["tt", "tt"], f"hdr={hdr[:4]} cells={[d[3] for d in data] if data else None}")

# [14] writemc corner= refused
rc, out = run(f"op\nwritemc corner=5\n", "c14", ".option osdimc corner=ss savemc=c14.csv")
check("[14] `writemc corner=...` is refused: a fixed column's name", "give the value another name" in out, out[-200:].replace("\n", "|"))

# [15] no -output
rc, out = run("corners -list tt ss\nprint corner\n", "c15")
check("[15] no -output: nothing recorded, said; the plot holds the scale alone",
      "no -output: the per-corner plots are kept, nothing is recorded" in out and "into plot 'corners1'" in out
      and re.search(r"^1\s+1\.0+e\+00\s*$", out, re.M) is not None, out[-200:].replace("\n", "|"))

# [16] no corners declared
HEADN = ("* cornerscmd {tag}\n.control\npre_osdi cn.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in 0 nm\nr1 in 0 1k\n.model nm cn\n.control\n{body}\n.endc\n.end\n")
rc, out = run("corners -output v(in)\n", "c16", head=HEADN)
check("[16] a circuit whose models declare no corner: refused", "corners: no loaded Verilog-A model declares a corner" in out and "into plot" not in out,
      out[-200:].replace("\n", "|"))

# [17] help
p = subprocess.run([NGSPICE, "-p"], input="oldhelp corners\nquit\n", capture_output=True, text=True, timeout=120, cwd=WORK)
check("[17] `oldhelp corners` prints the entry", "corners [-list" in p.stdout + p.stderr and "run the analysis at every process corner" in p.stdout + p.stderr)

# [18] a deck naming a corner: the loop visits tt, the deck's corner is back
rc, out = run(f"corners -output {A}rm[rsh]\nop\nprint {A}rm[rsh]\n", "c18", ".option corner=ff")
rows = table(out, "into plot")
vals = re.findall(re.escape(A + "rm[rsh]") + r" = ([0-9.e+-]+)", out)
check("[18] a deck that names a corner in .option: the loop still visits tt, and the deck's corner is back afterwards",
      len(rows) == 4 and rows[0][1] == "tt" and round(float(rows[0][2][0])) == 100 and [round(float(v)) for v in vals] == [88],
      f"rows={[(r[1], r[2][0]) for r in rows]} after={vals}")

print(f"\n{passed} of {checks} checks passed")
sys.exit(0 if passed == checks else 1)
