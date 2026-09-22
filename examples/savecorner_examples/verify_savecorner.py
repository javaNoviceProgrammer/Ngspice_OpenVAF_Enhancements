#!/usr/bin/env python3
"""Enhancement-701: `.option savecorner` -- the corner runs of a circuit whose
Verilog-A models declare process corners, one row per corner run, in a file
beside the netlist: the corner twin of `.option savemc` (E-610), keyed by
CORNER where savemc keys by trial.

A row is `corner`, `analysis`, `status`, then the value in force of every
cornered parameter (each parameter carrying a `corner` attribute, E-654),
read off the devices as `@<model>[<param>]` / `@<instance>[<param>]`, then
what the run computed: the `corners -output` values, `writemc`'s (on an
autocorner combined plot, evaluated per corner and put on that corner's
row), and under `corners -mc N` the montecarlo's yield, npass, nsamples,
nfailed. A corner run is a run-class command that is not a loop command's
sample: a plain run at the deck's corner (tt without one), each corner of
an `.option autocorner` pass, each corner of the `corners` command.

Checks (per solver):
  [1]  corners -output: the csv beside the deck, its header, one row per
       corner with the cornered values (100/115/88, 2/2.2/1.8, .45/.51/.39)
       and the outputs; the note
  [2]  corners -mc N under osdimc: one summary row per corner with yield,
       npass, nsamples, nfailed; the drawn parameter's cell empty at tt and
       the corner's value under ss/ff; no per-sample rows
  [3]  .option autocorner: a row per corner for `op`, the writemc values
       evaluated per corner on their own rows; a batch `.tran` too
  [4]  a plain op at `.option corner=ss` is a row `ss`, after `unset corner`
       a row `tt`; a reset continues the file
  [5]  formats: txt tab-separated; excel a genuine .xlsx with sheet
       `corners`, a model parameter's header bold and an output's blue;
       `savecorner=<name>.csv` names the file; missing directories are made
  [6]  `nosavecorner` last turns it off; none of the seven option names
       draws an "unknown option" warning
  [7]  nothing to record when no loaded model declares a corner: the note,
       once, and no file
  [8]  a corner whose run fails is a row marked failed, its output empty
  [9]  a montecarlo alone and a sweep alone make no rows
  [10] savemc and savecorner together: two files, each its own
  [11] writemc on a plain run lands on the row; `writemc corner=...` is
       refused for the savecorner row by name
  [12] savecorner_font / savecorner_model set the workbook's fonts, and a
       savemc_font is the fallback
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
WORK = tempfile.mkdtemp(prefix="savecorner_")
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

HEAD = ("* savecorner {tag}\n.control\npre_osdi cr.osdi\npre_osdi cf.osdi\npre_osdi cn.osdi\n.endc\n{opts}\n"
        "v1 in 0 dc 1\nn1 in 0 rm\nr1 in out 1k\nr2 out 0 1k\n"
        ".model rm cr rsh=100\n{cards}.control\n{body}\n.endc\n.end\n")


def run(body, tag, opts="", cards="", head=HEAD):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(head.format(tag=tag, opts=opts, body=body, cards=cards))
    for junk in glob.glob(os.path.join(WORK, "corners_*")) + glob.glob(os.path.join(WORK, "mcparams_*")):
        os.remove(junk)
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=600, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


def rows_of(name, sep=","):
    p = os.path.join(WORK, name)
    if not os.path.exists(p):
        return None, []
    lines = open(p).read().splitlines()
    if not lines:
        return [], []
    hdr = lines[0].split(sep)
    return hdr, [dict(zip(hdr, l.split(sep))) for l in lines[1:]]


def near(x, y, tol=1e-6):
    try:
        return abs(float(x) - y) <= tol * max(1.0, abs(y))
    except (TypeError, ValueError):
        return False


def dated(ext="csv"):
    return sorted(glob.glob(os.path.join(WORK, f"corners_*.{ext}")))


def xlsx_table(path):
    """the sheet as (header, rows of strings), and the sheet's name"""
    if not (os.path.exists(path) and zipfile.is_zipfile(path)):
        return None, [], None
    with zipfile.ZipFile(path) as z:
        sh = z.read("xl/worksheets/sheet1.xml").decode()
        wb = z.read("xl/workbook.xml").decode()
    rows = []
    for rm in re.finditer(r'<row r="(\d+)">(.*?)</row>', sh):
        cells = {}
        for cm in re.finditer(r'<c r="([A-Z]+)\d+"[^>]*?(?:><v>(.*?)</v></c>|><is><t>(.*?)</t></is></c>)', rm.group(2)):
            cells[cm.group(1)] = cm.group(2) if cm.group(2) is not None else cm.group(3)
        rows.append(cells)
    if not rows:
        return [], [], None
    cols = sorted(rows[0], key=lambda c: (len(c), c))
    hdr = [rows[0][c] for c in cols]
    data = [dict((rows[0][c], r.get(c, "")) for c in cols) for r in rows[1:]]
    return hdr, data, re.search(r'sheet name="(.*?)"', wb).group(1)


def xlsx_fonts(path):
    """header name -> (bold, rgb, font name, size); {} when there is no workbook"""
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
            out[name] = ("<b/>" in fx, m.group(1) if m else None,
                         re.search(r'<name val="(.*?)"/>', fx).group(1), float(re.search(r'<sz val="(.*?)"/>', fx).group(1)))
    return out


RSH = f"{A}rm[rsh]"
K = f"{A}rm[k]"
VTH = f"{A}rm[vth]"
FIXED = ["corner", "analysis", "status"]

# ---- [1] corners -output ----------------------------------------------------
print("[1] corners -output")
rc, out = run("corners -output v(out) gain=v(out)/v(in)", "c1", ".option savecorner=c1.csv")
hdr, rows = rows_of("c1.csv")
check("the file beside the deck, named by the option, with the note",
      hdr is not None and "Note: savecorner: recording the 3 cornered parameters, one row per corner run, to" in out, out[-300:].replace("\n", "|") if hdr is None else "")
check("header: corner, analysis, status, the three cornered parameters, then the outputs",
      hdr == FIXED + [RSH, K, VTH, "v(out)", "gain"], str(hdr))
check("one row per corner, tt first, each marked ok",
      [r.get("corner") for r in rows] == ["tt", "ss", "ff"] and all(r.get("status") == "ok" and r.get("analysis") == "op" for r in rows),
      str([(r.get("corner"), r.get("analysis"), r.get("status")) for r in rows]))
exp = {"tt": (100, 2.0, 0.45), "ss": (115, 2.2, 0.51), "ff": (88, 1.8, 0.39)}
check("the cornered values per row: rsh 100/115/88, k 2/2.2/1.8, vth .45/.51/.39",
      len(rows) == 3 and all(near(r[RSH], exp[r["corner"]][0]) and near(r[K], exp[r["corner"]][1]) and near(r[VTH], exp[r["corner"]][2]) for r in rows),
      str([(r.get(RSH), r.get(K), r.get(VTH)) for r in rows]))
check("the -output values on each corner's row (v(out) 0.5, gain 0.5)",
      len(rows) == 3 and all(near(r["v(out)"], 0.5) and near(r["gain"], 0.5) for r in rows),
      str([(r.get("v(out)"), r.get("gain")) for r in rows]))

# ---- [2] corners -mc --------------------------------------------------------
print("\n[2] corners -mc N: one summary row per corner")
rc, out = run("corners -mc 5 -analysis op -spec v(out) -max 0.6", "c2", ".option savecorner=c2.csv osdimc mcseed=3")
hdr, rows = rows_of("c2.csv")
check("three rows -- the samples' runs are not corner runs -- with yield, npass, nsamples, nfailed",
      hdr == FIXED + [RSH, K, VTH, "yield", "npass", "nsamples", "nfailed"] and [r.get("corner") for r in rows] == ["tt", "ss", "ff"],
      f"{hdr} {[r.get('corner') for r in rows]}")
check("the summary values: yield 1, npass 5, nsamples 5, nfailed 0 at every corner, the analysis the montecarlo command",
      len(rows) == 3 and all(near(r["yield"], 1) and near(r["npass"], 5) and near(r["nsamples"], 5) and near(r["nfailed"], 0)
                             and r["analysis"].startswith("montecarlo 5") for r in rows),
      str([(r.get("yield"), r.get("npass"), r.get("analysis")) for r in rows]))
check("the drawn parameter's cell is EMPTY on the tt row (the montecarlo drew it) and the corner's value under ss/ff (0.51, 0.39)",
      len(rows) == 3 and rows[0][VTH] == "" and near(rows[1][VTH], 0.51) and near(rows[2][VTH], 0.39)
      and near(rows[0][RSH], 100) and near(rows[1][RSH], 115),
      str([r.get(VTH) for r in rows]))
rc, out = run("corners -mc 4 -analysis op -spec v(out) -max 0.6", "c2b", ".option savecorner=c2b.csv",
              cards=".param rr = agauss(1k, 50, 3)\n")
hdr, rows = rows_of("c2b.csv")
check("without osdimc nothing draws the model parameters: the tt row keeps vth's nominal 0.45",
      len(rows) == 3 and near(rows[0][VTH], 0.45) and near(rows[0]["nsamples"], 4), str([r.get(VTH) for r in rows]))

# ---- [3] autocorner ---------------------------------------------------------
print("\n[3] .option autocorner")
rc, out = run("op\nwritemc vout=v(out) g=v(out)/v(in)", "c3", ".option savecorner=c3.csv autocorner")
hdr, rows = rows_of("c3.csv")
check("a row per corner of the pass, tt ss ff, analysis op",
      [(r.get("corner"), r.get("analysis")) for r in rows] == [("tt", "op"), ("ss", "op"), ("ff", "op")], str(rows)[:200])
check("writemc on the combined plot: each value evaluated on every corner's own plot and put on that corner's row",
      hdr == FIXED + [RSH, K, VTH, "vout", "g"] and len(rows) == 3 and all(near(r["vout"], 0.5) and near(r["g"], 0.5) for r in rows)
      and "put on that corner's row" in out, str(hdr))
rc, out = run("", "c3b", ".option savecorner=c3b.csv autocorner", cards=".tran 1u 4u\n.op\n")
hdr, rows = rows_of("c3b.csv")
check("a batch deck's .op and .tran under autocorner: the batch `run` is one run per corner, three rows labelled run",
      [(r.get("corner"), r.get("analysis")) for r in rows] == [("tt", "run"), ("ss", "run"), ("ff", "run")]
      and near(rows[1][RSH], 115), str([(r.get("corner"), r.get("analysis")) for r in rows]))

# ---- [4] plain runs at a corner, reset ----------------------------------------
print("\n[4] a plain run at the deck's corner")
rc, out = run("op\nunset corner\nop\nreset\nset corner=ff\nop", "c4", ".option savecorner=c4.csv corner=ss")
hdr, rows = rows_of("c4.csv")
check("op at .option corner=ss is a row ss; after `unset corner` a row tt; after a reset the file continues (ff)",
      [r.get("corner") for r in rows] == ["ss", "tt", "ff"] and near(rows[0][RSH], 115) and near(rows[1][RSH], 100) and near(rows[2][RSH], 88),
      str([(r.get("corner"), r.get(RSH)) for r in rows]))
check("the note once, not per row", out.count("Note: savecorner: recording") == 1, str(out.count("Note: savecorner: recording")))

# ---- [5] formats and names ----------------------------------------------------
print("\n[5] txt, excel, a named file, directories")
rc, out = run("corners -output v(out)", "c5", ".option savecorner=txt")
files = dated("txt")
hdr, rows = rows_of(os.path.basename(files[-1]), "\t") if files else (None, [])
check("savecorner=txt: corners_<date>_<time>.txt beside the deck, tab-separated",
      len(files) == 1 and hdr == FIXED + [RSH, K, VTH, "v(out)"] and len(rows) == 3, str(files) + str(hdr))
rc, out = run("corners -output v(out) gain=v(out)/v(in)", "c5x", ".option savecorner=excel")
files = dated("xlsx")
xh, xr, sheet = xlsx_table(files[-1]) if files else (None, [], None)
check("savecorner=excel: a genuine .xlsx, sheet `corners`, the header and three rows",
      len(files) == 1 and sheet == "corners" and xh == FIXED + [RSH, K, VTH, "v(out)", "gain"] and [r.get("corner") for r in xr] == ["tt", "ss", "ff"],
      f"{files} {sheet} {xh}")
check("...with the values in their cells (ss: rsh 115, gain 0.5)",
      len(xr) == 3 and near(xr[1].get(RSH), 115) and near(xr[1].get("gain"), 0.5), str(xr[1] if len(xr) > 1 else xr))
fx = xlsx_fonts(files[-1]) if files else {}
check("a model parameter's header is bold, an output's blue, the fixed columns plain (Calibri 11)",
      fx.get(RSH, (None,))[0] is True and fx.get("gain", (None, None))[1] == "0000FF" and fx.get("corner", (True,))[0] is False
      and fx.get("corner", (0, 0, ""))[2] == "Calibri" and fx.get("corner", (0, 0, "", 0))[3] == 11.0, str(fx))
rc, out = run("op", "c5n", ".option savecorner=Runs/Deep/Corners.csv corner=ss")
p = os.path.join(WORK, "Runs", "Deep", "Corners.csv")
check("savecorner=Runs/Deep/Corners.csv: the directories made, the name's case kept, the row there",
      os.path.exists(p) and rows_of(os.path.join("Runs", "Deep", "Corners.csv"))[1][0].get("corner") == "ss", str(os.path.exists(p)))

# ---- [6] nosavecorner, no unknown-option warnings ---------------------------
print("\n[6] the option names")
rc, out = run("op", "c6", ".option savecorner=c6.csv nosavecorner corner=ss")
check("`nosavecorner` last turns the recorder off: no file, no note",
      not os.path.exists(os.path.join(WORK, "c6.csv")) and "savecorner: recording" not in out, out[-200:].replace("\n", "|"))
rc, out = run("op", "c6b", ".option savecorner=c6b.csv savecorner_font=Arial savecorner_fontsize=9 savecorner_model=italic "
                           "savecorner_instance=regular savecorner_output=red corner=ss")
check("none of the seven option names draws an `unknown option` warning",
      "unknown" not in out.lower() and "ignored" not in out.lower() and os.path.exists(os.path.join(WORK, "c6b.csv")),
      "|".join(l for l in out.splitlines() if "nknown" in l or "gnored" in l)[:200])

# ---- [7] nothing to record ------------------------------------------------------
print("\n[7] nothing to record")
NOCORNER = HEAD.replace("n1 in 0 rm\n", "n1 in 0 nm\n").replace(".model rm cr rsh=100\n", ".model nm cn\n")
rc, out = run("op\nop", "c7", ".option savecorner=c7.csv", head=NOCORNER)
check("no loaded model declares a corner: the note names the attribute, once, and no file is made",
      out.count("Note: savecorner: nothing to record -- no loaded Verilog-A model declares a corner") == 1
      and not os.path.exists(os.path.join(WORK, "c7.csv")), out[-250:].replace("\n", "|"))

# ---- [8] a failed corner run --------------------------------------------------
print("\n[8] a corner whose run fails")
FAILING = HEAD.replace("n1 in 0 rm\n", "n1 in 0 rm\nn3 in 0 fm\n").replace(".model rm cr rsh=100\n", ".model rm cr rsh=100\n.model fm cf\n")
rc, out = run("corners -list ss,bad -output v(out)", "c8", ".option savecorner=c8.csv", head=FAILING)
hdr, rows = rows_of("c8.csv")
check("corner `bad` moves g out of its range: its row is marked failed and its output cell is empty; ss is ok with 0.5",
      len(rows) == 2 and rows[0]["corner"] == "ss" and rows[0]["status"] == "ok" and near(rows[0]["v(out)"], 0.5)
      and rows[1]["corner"] == "bad" and rows[1]["status"] == "failed" and rows[1]["v(out)"] == "",
      str([(r.get("corner"), r.get("status"), r.get("v(out)")) for r in rows]))

# ---- [9] loops that are not corner runs -------------------------------------------
print("\n[9] a montecarlo or a sweep alone")
rc, out = run("montecarlo 3 -analysis op -spec v(out) -max 0.6\nsweep " + RSH + " 90 110 10 -analysis op -output v(out)\nop",
              "c9", ".option savecorner=c9.csv osdimc mcseed=1")
hdr, rows = rows_of("c9.csv")
check("the montecarlo's three samples make no rows; the sweep's fast path is one dc run (a row whose swept "
      "cell is empty, E-626's rule); the op after them a row (tt)",
      [(r.get("corner"), r.get("analysis")) for r in rows] == [("tt", "dc"), ("tt", "op")]
      and rows[0][RSH] == "" and near(rows[0][K], 2) and near(rows[1][RSH], 100),
      str([(r.get("corner"), r.get("analysis"), r.get(RSH)) for r in rows]))

# ---- [10] with savemc ---------------------------------------------------------------
print("\n[10] beside savemc")
rc, out = run("corners -output v(out)", "c10", ".option savecorner=c10c.csv savemc=c10m.csv")
ch, cr_ = rows_of("c10c.csv")
mh, mr = rows_of("c10m.csv")
check("both recorders write their own file: savecorner keyed by corner, savemc by trial with its corner column",
      [r.get("corner") for r in cr_] == ["tt", "ss", "ff"] and mh is not None and mh[:3] == ["trial", "analysis", "status"] and "corner" in mh
      and [r.get("trial") for r in mr] == ["1", "2", "3"], f"{ch} / {mh}")

# ---- [11] writemc on a plain run ----------------------------------------------------
print("\n[11] writemc")
rc, out = run("op\nwritemc vo=v(out)\nwritemc corner=7 status=1", "c11", ".option savecorner=c11.csv corner=ff")
hdr, rows = rows_of("c11.csv")
check("writemc after a plain run puts the value on that run's row (savemc off: no complaint about it)",
      len(rows) == 1 and near(rows[0].get("vo"), 0.5) and "nothing is recorded" not in out, str(rows))
check("`writemc corner=...` and `status=...` are refused for the savecorner row by name",
      out.count("is one of the savecorner row's fixed columns") == 2 and "corner" not in hdr[3:] and near(rows[0].get(RSH), 88),
      str(hdr))

# ---- [12] the workbook's fonts ------------------------------------------------------
print("\n[12] savecorner_font and the savemc fallback")
rc, out = run("corners -output v(out)", "c12", ".option savecorner=F.xlsx savecorner_font=Arial savecorner_fontsize=9 "
                                              "savecorner_model=italic+red savecorner_output=green")
fx = xlsx_fonts(os.path.join(WORK, "F.xlsx"))
check("savecorner_font Arial 9, savecorner_model italic+red on the model parameter, savecorner_output green on the output",
      fx.get("corner", (0, 0, "", 0))[2] == "Arial" and fx.get("corner", (0, 0, "", 0))[3] == 9.0
      and fx.get(RSH, (True, None))[1] == "FF0000" and fx.get("v(out)", (0, None))[1] == "008000", str(fx))
rc, out = run("corners -output v(out)", "c12b", ".option savecorner=G.xlsx savemc_font=Verdana savemc_writemc=navy")
fx = xlsx_fonts(os.path.join(WORK, "G.xlsx"))
check("a savemc font option is the fallback: Verdana, and savemc_writemc styles the output column navy",
      fx.get("corner", (0, 0, "", 0))[2] == "Verdana" and fx.get("v(out)", (0, None))[1] == "000080", str(fx))

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
