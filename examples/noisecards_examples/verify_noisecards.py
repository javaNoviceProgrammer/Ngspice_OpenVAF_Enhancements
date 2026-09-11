#!/usr/bin/env python3
"""Enhancement-603: a noise analysis is one analysis to its save list, and a
.print card on a noise plot prints what that plot holds.

N7 of the 2026-09-10 integration hunt. A noise analysis publishes two plots in
sequence -- the spectral densities (noise1: onoise_spectrum, inoise_spectrum)
and the integrated totals (noise2: onoise_total, inoise_total) -- and the save
list a `.print noise ...` card registers was applied to each plot on its own.
`.print noise onoise_spectrum` named nothing of the totals plot, so that plot
was refused, "no data saved for Noise analysis; analysis not run" (the analysis
went on into a run descriptor with no plot behind it), after two "can't parse
'onoise_spectrum'" warnings that were not true; `.print noise onoise_total`
named nothing of the densities plot, which is opened first, so the WHOLE
analysis was refused. And ft_cktcoms ran the card on every noise plot with the
whole item list, so a card that did get both plots printed "vector ... is not
available" from the plot that did not hold an item.

Now the analysis tells the front end how many plots follow (CKTplotsToFollow);
within the sequence a plot the saves do not reach is kept whole, the
unmatched-name warning is deferred to the last plot and printed once for the
names no plot held, and a `.print` on a type with several plots gives each
plot the items it can serve, reporting an item no plot serves once.

Checks (batch mode with dot cards unless said; built-in devices, then OSDI):
  [1] .print noise onoise_spectrum inoise_spectrum: both plots, no warnings
  [2] .print noise onoise_total inoise_total: the analysis runs, the totals print
  [3] one card naming an item of each plot: a table from each plot
  [4] a typo beside a good item: the good one prints; the typo reported once
      at save time and once by .print; no "can't parse"
  [5] .print noise v(out): both plots kept whole, the node reported once each way
  [6] .plot noise onoise_spectrum with limits: the ascii plot from noise1 only
  [7] interactive: save onoise_spectrum / onoise_total, two noise runs in a
      row: the other plot is whole, nothing is said
  [8] save out, then tran and noise: the tran pruned to out, the noise whole,
      out reported once
  [9] save nosuch, then noise: reported once
  [10] a single-frequency run (no totals): the spectrum prints; asking for
       the totals is refused as before, with the name reported
  [11] what stays: .print tran v(out) beside a .noise with no card of its own
       still refuses the noise run -- nothing was asked of it
  [12] .print tran v(out) + .print noise onoise_total: tran pruned, noise whole
  [13] -r rawfile with a .save card: the densities pruned, the totals written whole
  [14] .option keepopinfo: the op plot, then the spectrum table, no warnings
  [15] the OSDI shape of the hunt's deck, and a per-generator total by name
"""
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
WORK = tempfile.mkdtemp(prefix="noisecards_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "rc.va"), "w") as f:
    f.write('`include "disciplines.vams"\n`include "constants.vams"\nmodule rc(p, n);\ninout p, n; electrical p, n;\n'
            'parameter real r = 1k from (0:inf);\nparameter real c = 0 from [0:inf);\n'
            'analog begin\n  I(p,n) <+ V(p,n)/r + ddt(c*V(p,n));\n'
            '  I(p,n) <+ white_noise(4*`P_K*$temperature/r, "thermal");\nend\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "rc.va"), "-o", os.path.join(WORK, "rc.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)

CKT = "v1 in 0 dc 1 ac 1\nr1 in out 1k\nr2 out 0 1k\nc1 out 0 1n\n"
NOISE = ".noise v(out) v1 dec 1 1k 10k\n"


def run(cards, tag, ckt=CKT, pre="", args=()):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* noisecards {tag}\n{pre}{ckt}{cards}\n.end\n")
    p = subprocess.run([NGSPICE, "-b", *args, path], capture_output=True, text=True,
                       timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def rows(out):
    return [int(m) for m in re.findall(r"No\. of Data Rows : (\d+)", out)]


def tables(out):
    """the plot titles of the printed tables, in order"""
    return re.findall(r"^\s+(Noise Spectral Density Curves|Integrated Noise|Transient Analysis|AC Analysis)\s+\w{3} \w{3}",
                      out, re.M)


def columns(out, title):
    m = re.search(rf"{title}.*?\n-+\nIndex\s+([^\n]*)\n", out, re.S)
    return m.group(1).split() if m else []


def value(out, name):
    m = re.search(rf"^{re.escape(name)} = ([-+.\deE]+)", out, re.M)
    return float(m.group(1)) if m else None


LOST = "no data saved for"
CANT = "can't parse"
NOTHING = "nothing of that name"
CHECKV = "checkvalid"
print("Enhancement-603: the noise plots as one analysis to the save list\n")

# ------------------------------------------------------------- [1] ---
out = run(NOISE + ".print noise onoise_spectrum inoise_spectrum", "t1")
check("[1] .print noise of the two densities: both plots produced (2 and 1 rows), nothing refused",
      LOST not in out and rows(out) == [2, 1], f"{rows(out)} {out[-200:]}")
check("[1] ...the spectrum table with both columns, and no warning of any kind",
      columns(out, "Noise Spectral Density Curves") == ["frequency", "onoise_spectrum", "inoise_spectrum"]
      and CANT not in out and NOTHING not in out and CHECKV not in out and "Warning" not in out,
      out[-300:])

# ------------------------------------------------------------- [2] ---
out = run(NOISE + ".print noise onoise_total inoise_total", "t2")
check("[2] .print noise of the totals: the analysis runs (was refused outright)",
      LOST not in out and "aborted" not in out and rows(out) == [2, 1], f"{rows(out)} {out[-200:]}")
check("[2] ...the totals table prints, no warnings",
      columns(out, "Integrated Noise") == ["onoise_total", "inoise_total"]
      and re.search(r"^0\s+2\.7302\d+e-07\s+5\.4631\d+e-07", out, re.M)
      and "Warning" not in out, out[-300:])

# ------------------------------------------------------------- [3] ---
out = run(NOISE + ".print noise onoise_spectrum onoise_total", "t3")
check("[3] one card, an item from each plot: a table from each (printed nothing before)",
      sorted(tables(out)) == ["Integrated Noise", "Noise Spectral Density Curves"]
      and columns(out, "Integrated Noise") == ["onoise_total"]
      and columns(out, "Noise Spectral Density Curves") == ["frequency", "onoise_spectrum"]
      and "Warning" not in out, f"{tables(out)} {out[-300:]}")

# ------------------------------------------------------------- [4] ---
out = run(NOISE + ".print noise onoise_spectrum onoise_spectrun", "t4")
check("[4] a typo beside a good item: the good one prints",
      columns(out, "Noise Spectral Density Curves") == ["frequency", "onoise_spectrum"]
      and rows(out) == [2, 1], f"{tables(out)} {out[-300:]}")
check("[4] ...the typo reported once at save time, once by .print, never as unparsable",
      out.count(NOTHING) == 1 and "save 'onoise_spectrun'" in out
      and out.count("is in none of the 2 noise plots") == 1
      and ".print noise: 'onoise_spectrun'" in out and CANT not in out and CHECKV not in out,
      out[-400:])

# ------------------------------------------------------------- [5] ---
out = run(NOISE + ".print noise v(out)", "t5")
check("[5] .print noise v(out): both plots kept whole, the node reported once each way",
      rows(out) == [2, 1] and LOST not in out and out.count(NOTHING) == 1
      and out.count("'v(out)' is in none of the 2 noise plots") == 1 and CHECKV not in out,
      out[-400:])

# ------------------------------------------------------------- [6] ---
out = run(".noise v(out) v1 dec 2 1k 10k\n.plot noise onoise_spectrum (1e-9,1e-8)", "t6")
check("[6] .plot noise onoise_spectrum with limits: one ascii plot, from noise1, no warning",
      out.count("Legend:") == 1 and "Noise Spectral Density Curves" in out
      and CHECKV not in out and "Warning" not in out and rows(out) == [3, 1], out[-400:])

# ------------------------------------------------------------- [7] ---
CTL = ".control\n{}\n.endc\n"
out = run(CTL.format("save onoise_spectrum\nnoise v(out) v1 dec 1 1k 10k\nnoise v(out) v1 dec 1 1k 10k\n"
                     "setplot noise2\ndisplay\nprint onoise_total"), "t7a")
check("[7] interactive `save onoise_spectrum`, two noise runs: the totals plot is there, whole, silent",
      value(out, "onoise_total") is not None and "inoise_total" in out
      and NOTHING not in out and LOST not in out and rows(out) == [2, 1, 2, 1], out[-400:])
out = run(CTL.format("save onoise_total\nnoise v(out) v1 dec 1 1k 10k\nsetplot noise1\ndisplay\n"
                     "setplot noise2\ndisplay"), "t7b")
n1 = re.search(r"Name: noise1.*?(?=Name:|Note:|\Z)", out, re.S)
n2 = re.search(r"Name: noise2.*?(?=Name:|Note:|\Z)", out, re.S)
check("[7] `save onoise_total`: the densities plot is kept whole, the totals plot holds the one name",
      n1 and "onoise_spectrum" in n1.group(0) and "inoise_spectrum" in n1.group(0)
      and n2 and "onoise_total" in n2.group(0) and "inoise_total" not in n2.group(0)
      and NOTHING not in out and LOST not in out, out[-500:])

# ------------------------------------------------------------- [8] ---
out = run(CTL.format("save v(out)\ntran 1u 3u\nnoise v(out) v1 dec 1 1k 10k\nsetplot tran1\ndisplay\n"
                     "setplot noise2\nprint onoise_total"), "t8")
t1 = re.search(r"Name: tran1.*?(?=Name:|Note:|\Z)", out, re.S)
check("[8] `save out`, tran and noise: the tran pruned to out, the noise whole, out reported once",
      t1 and "out" in t1.group(0) and "    in " not in t1.group(0)
      and value(out, "onoise_total") is not None and out.count(NOTHING) == 1
      and "save 'out'" in out and LOST not in out, out[-500:])

# ------------------------------------------------------------- [9] ---
out = run(CTL.format("save nosuch\nnoise v(out) v1 dec 1 1k 10k\nprint onoise_total"), "t9")
check("[9] `save nosuch` before noise: reported once, the run kept whole",
      out.count(NOTHING) == 1 and "save 'nosuch'" in out and value(out, "onoise_total") is not None
      and LOST not in out, out[-400:])

# ------------------------------------------------------------ [10] ---
out = run(".noise v(out) v1 lin 1 1k 1k\n.print noise onoise_spectrum", "t10a")
check("[10] a single-frequency run: the spectrum prints, one plot, no warning",
      columns(out, "Noise Spectral Density Curves") == ["frequency", "onoise_spectrum"]
      and rows(out) == [1] and NOTHING not in out and LOST not in out, out[-300:])
out = run(".noise v(out) v1 lin 1 1k 1k\n.print noise onoise_total", "t10b")
check("[10] ...asking it for the totals it does not publish is refused as before, the name reported",
      "save 'onoise_total'" in out and NOTHING in out and LOST in out and CANT not in out, out[-300:])

# ------------------------------------------------------------ [11] ---
out = run(".tran 1u 2u\n" + NOISE + ".print tran v(out)", "t11")
check("[11] stays: .print tran v(out) beside a .noise with no card: the noise run is refused, as before",
      "no data saved for Noise analysis" in out and columns(out, "Transient Analysis") == ["time", "v(out)"],
      out[-300:])

# ------------------------------------------------------------ [12] ---
out = run(".tran 1u 2u\n" + NOISE + ".print tran v(out)\n.print noise onoise_total", "t12")
check("[12] .print tran v(out) + .print noise onoise_total: both analyses, the noise whole, no warnings",
      LOST not in out and sorted(tables(out)) == ["Integrated Noise", "Transient Analysis"]
      and len(rows(out)) == 3 and rows(out)[1:] == [2, 1] and "Warning" not in out,
      f"{rows(out)} {out[-300:]}")

# ------------------------------------------------------------ [13] ---
raw = os.path.join(WORK, "t13.raw")
out = run(NOISE + ".save onoise_spectrum", "t13", args=("-r", raw))
rawtxt = open(raw, errors="replace").read() if os.path.exists(raw) else ""
n1 = re.search(r"Plotname: Noise Spectral Density Curves.*?No\. Variables: (\d+)", rawtxt, re.S)
check("[13] -r rawfile with `.save onoise_spectrum`: the densities plot pruned to it, the totals plot written whole",
      n1 and n1.group(1) == "2" and "Plotname: Integrated Noise" in rawtxt
      and "onoise_total" in rawtxt and "inoise_total" in rawtxt and LOST not in out
      and rows(out) == [2, 1], f"{rows(out)} {out[-300:]}")

# ------------------------------------------------------------ [14] ---
out = run(NOISE + ".print noise onoise_spectrum", "t14", pre=".option keepopinfo\n")
check("[14] keepopinfo: the op plot, the spectrum and the totals; the table; no warnings",
      rows(out) == [1, 2, 1] and columns(out, "Noise Spectral Density Curves") == ["frequency", "onoise_spectrum"]
      and "Warning" not in out and LOST not in out, f"{rows(out)} {out[-300:]}")

# ------------------------------------------------------------ [15] ---
OCKT = ("v1 in 0 dc 1 ac 1\nn1 in out rcm\nn2 out 0 rcl\n"
        ".model rcm rc r=1k c=0\n.model rcl rc r=1k c=1n\n")
OPRE = ".control\npre_osdi rc.osdi\n.endc\n"
out = run(NOISE + ".print noise onoise_spectrum inoise_spectrum\n.ac dec 1 1k 10k\n.print ac vm(out)",
          "t15a", ckt=OCKT, pre=OPRE)
check("[15] the hunt's OSDI deck: both noise plots, the ac, both tables, no warnings",
      rows(out) == [2, 2, 1] and sorted(tables(out)) == ["AC Analysis", "Noise Spectral Density Curves"]
      and columns(out, "Noise Spectral Density Curves") == ["frequency", "onoise_spectrum", "inoise_spectrum"]
      and "Warning" not in out and LOST not in out and CANT not in out, f"{rows(out)} {out[-300:]}")
out = run(".noise v(out) v1 dec 1 1k 10k 1\n.print noise onoise_total_n1_thermal onoise_total",
          "t15b", ckt=OCKT, pre=OPRE)
check("[15] ...a per-generator total by name beside the total: the totals table, the densities kept whole",
      [c[:15] for c in columns(out, "Integrated Noise")] == ["onoise_total_n1", "onoise_total"]
      and re.search(r"^0\s+1\.9305\d+e-07\s+2\.7302\d+e-07", out, re.M)
      and rows(out) == [2, 1] and "Warning" not in out and LOST not in out, f"{rows(out)} {out[-300:]}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
