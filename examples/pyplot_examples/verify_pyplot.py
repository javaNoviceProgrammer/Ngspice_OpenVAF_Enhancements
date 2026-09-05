#!/usr/bin/env python3
"""
verify_pyplot.py -- verifies Enhancement-94 (the ngspice `pyplot` command,
matplotlib backend), end-to-end through the committed openvaf-r + ngspice.

`pyplot` mirrors ngspice's `gnuplot` command but renders with matplotlib: it
writes a `<file>.data` table and a `<file>.py` script and runs Python. With
`set pyplot_terminal=png` it renders headless (Agg) to `<file>.png`.

  [1] the OSDI model compiles and the transient runs
  [2] `pyplot rc v(out) v(in)` writes rc.py, rc.data and rc.png
  [3] rc.png is a valid PNG (magic bytes) of non-trivial size
  [4] the generated rc.py references both plotted vectors and uses matplotlib
  [5] an AC log-scale plot (`set type=...`/loglog) also renders a PNG

Enhancement-183 (this session's options):
  [E-183a] two omitted-file-name plots get DISTINCT names (pyplot, pyplot-2)
           with their own titles -- no interactive-window collision
  [E-183b] the .py/.data/.png are written next to the CIRCUIT FILE, not the cwd
  [E-183c] `set pyplot_linewidth=<w>` -> linewidth in the plot() calls
  [E-183d] `set pyplot_backend=<name>` -> matplotlib.use(<name>)

Enhancement-208:
  [E-208] `pyplot [name] -eye <expr> -ui <T>` runs the `eye` analysis and renders
          the folded eye as a persistence 2-D-histogram eye diagram (hist2d),
          honouring the same pyplot_* settings; the base name defaults to "eye".

Enhancement-547 (the launch: quoting and the exit status):
  [E-547a] a deck folder with a SPACE in its path renders (the launch used to
           hand Python the path's first word)
  [E-547b] a deck folder with an APOSTROPHE renders (the shell used to wait for
           a closing quote, and the script's own print line broke the same way)
  [E-547c] an interpreter that exits non-zero is NAMED: "Error: pyplot: ...
           exited with status 3; <file>.png was not written", and `pyplot_status`
           reads 3 in the deck (it used to be Python's traceback and nothing else)
  [E-547d] a missing interpreter: status 127, the same message, no image
  [E-547e] a success publishes `pyplot_status` = 0
  [E-547f] `pyplot_python` still carries options (`/usr/bin/env python3`)
  [E-547g] an interpreter PATH with a space is one word

Enhancement-548 (the script and its data):
  [E-548a] the data table carries full precision: a time axis offset to 1 s with
           1 ns steps keeps every x distinct, a microvolt ripple on 1 V survives
           (six digits used to collapse both)
  [E-548b] `ylimit lo hi` under `ylog` is applied (it used to be dropped
           silently); a non-positive bound is refused by the command itself
  [E-548c] a voltage and a current on one plot get two y scales (twinx), each
           labelled with its type, one combined legend, distinct colours
  [E-548d] the generated script runs from any directory: its data and image are
           found next to the script itself

Enhancement-549 (the data table: .npy by default, `set pyplot_export`, `-export`):
  [E-549a] the default table is `<name>.npy`, a structured numpy array with one
           field per column (`time`, `v(out)`, `time_2`, `v(in)`), exact doubles,
           and the script loads it and renders
  [E-549b] `set pyplot_export=ascii` writes `<name>.data` with a `# name ...`
           header line and 17-digit numbers, and the script loads that instead
  [E-549c] `pyplot -export sig v(out) i(v1)` writes sig.npy and no script, and
           says so; `vs` names the x column after the vector plotted against
  [E-549d] `-export` refuses the other markers, and says what to do instead
  [E-549e] the -contour, -smith and -bode tables carry their own field names
  [E-549f] an unknown pyplot_export value is said and falls back to .npy

Enhancement-550 (envelope decimation of long traces):
  [E-550a] a 200k-sample trace on a hardcopy is drawn as its min/max envelope:
           at most two points per pixel column, the same extremes per column
           as the full data, the script says so, the PNG renders
  [E-550b] `set pyplot_decimate=off` draws every sample
  [E-550c] `set pyplot_decimate=500` uses 500 bins whatever the width
  [E-550d] a window re-decimates on zoom: setting the x-limits to a slice
           replaces the line's data with that slice's envelope, in detail
  [E-550e] a point plot (`set pointstyle=markers`) and a `vs` plot whose x runs
           backwards are left whole

Enhancement-551 (engineering ticks, typed labels, a clean title):
  [E-551a] the default labels read `time [s]` / `voltage [V]`, and the ticks
           read `500 µs` / `-500 mV` (an EngFormatter keyed on the vector type)
  [E-551b] a mixed plot labels `voltage [V]` left and `current [A]` right, with
           `µA`-style ticks on the twin
  [E-551c] a label the user gave is kept verbatim; the ticks still carry the unit
  [E-551d] `set pyplot_eng=off` keeps plain tick numbers, and the typed labels
  [E-551e] a `db(v(out))` trace has plain dB ticks and `10 kHz`-style ones on
           the log frequency axis
  [E-551f] the deck's `* ` comment marker is dropped from the default title;
           a `title` the user gave is untouched
  [E-551g] `-fft` and `-hist` label their axes `Frequency [Hz]` / `voltage [V]`
"""
import os
import random
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def is_png(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 1000:
        return False
    with open(path, "rb") as f:
        sig = f.read(8)
    return sig == b"\x89PNG\r\n\x1a\n"

for stale in ("rc.png", "rc.py", "rc.data", "rc.npy", "acmag.png", "acmag.py", "acmag.data", "acmag.npy"):
    p = os.path.join(HERE, stale)
    if os.path.exists(p):
        os.remove(p)

# compile the OSDI model
r = subprocess.run([OPENVAF, "rcload.va"], capture_output=True, text=True, cwd=HERE)
check("rcload.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:120])

# transient + pyplot to PNG
deck = """* pyplot transient demo (Enhancement-94)
.model rl rcload
V1 in 0 PULSE(0 1 0 1n 1n 1m 2m)
N1 in out rl
C1 out 0 1u
.tran 10u 3m
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot rc v(out) v(in)
.endc
.end
"""
with open(os.path.join(HERE, "tran.sp"), "w") as f:
    f.write(deck)
r = subprocess.run([NGSPICE, "-b", "tran.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
check("transient runs and pyplot reports writing the PNG", "wrote rc.png" in log,
      log.strip()[-160:])
check("pyplot wrote rc.py, rc.npy and rc.png",
      all(os.path.isfile(os.path.join(HERE, f)) for f in ("rc.py", "rc.npy", "rc.png")))
check("rc.png is a valid PNG image", is_png(os.path.join(HERE, "rc.png")))
py = open(os.path.join(HERE, "rc.py")).read() if os.path.isfile(os.path.join(HERE, "rc.py")) else ""
check("rc.py uses matplotlib and plots both vectors",
      "matplotlib" in py and "v(out)" in py and "v(in)" in py)

# Enhancement-182: without explicit user limits the script must NOT pin the
# axes -- matplotlib's autoscaling + fig.tight_layout() frame the data (the
# old behavior forwarded ngspice's grid-rounded internal ranges).
check("E-182: auto plot has no set_xlim/set_ylim, relies on tight_layout",
      "set_xlim" not in py and "set_ylim" not in py and "tight_layout" in py)

# ... while explicit `xlimit`/`ylimit` on the command are still honored.
limdeck = deck.replace("pyplot rc v(out) v(in)",
                       "pyplot rclim v(out) v(in) xlimit 0 1m ylimit -1 1")
with open(os.path.join(HERE, "tranlim.sp"), "w") as f:
    f.write(limdeck)
r = subprocess.run([NGSPICE, "-b", "tranlim.sp"], capture_output=True, text=True, cwd=HERE)
pylim = (open(os.path.join(HERE, "rclim.py")).read()
         if os.path.isfile(os.path.join(HERE, "rclim.py")) else "")
check("E-182: explicit xlimit/ylimit still emit set_xlim and set_ylim",
      "set_xlim(0, 0.001)" in pylim and          # E-548: full-precision %.17g spelling
      "set_ylim(-1, 1)" in pylim and
      is_png(os.path.join(HERE, "rclim.png")))
for f_ in ("tranlim.sp", "rclim.py", "rclim.data", "rclim.png"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass

# AC magnitude on a log x-axis
acdeck = """* pyplot AC demo
.model rl rcload
V1 in 0 DC 0 AC 1
N1 in out rl
C1 out 0 1u
.ac dec 20 1 1meg
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot acmag db(v(out))
.endc
.end
"""
with open(os.path.join(HERE, "ac.sp"), "w") as f:
    f.write(acdeck)
subprocess.run([NGSPICE, "-b", "ac.sp"], capture_output=True, text=True, cwd=HERE)
check("AC log-scale plot renders a PNG", is_png(os.path.join(HERE, "acmag.png")))

# Enhancement-95: the file name is optional -- `pyplot v(out)` (no file name)
# defaults the base name to "pyplot".
nofndeck = """* pyplot without a file name
.model rl rcload
V1 in 0 PULSE(0 1 0 1n 1n 1m 2m)
N1 in out rl
C1 out 0 1u
.tran 10u 3m
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot v(out)
.endc
.end
"""
with open(os.path.join(HERE, "nofn.sp"), "w") as f:
    f.write(nofndeck)
subprocess.run([NGSPICE, "-b", "nofn.sp"], capture_output=True, text=True, cwd=HERE)
check("pyplot with no file name defaults to 'pyplot.png'",
      is_png(os.path.join(HERE, "pyplot.png")))

# ---- Enhancement-183a: distinct default names for successive no-name plots ----
for f_ in ("pyplot.py", "pyplot.data", "pyplot.png",
           "pyplot-2.py", "pyplot-2.data", "pyplot-2.npy", "pyplot-2.png"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass
twodeck = """* two no-name plots
.model rl rcload
V1 in 0 PULSE(0 1 0 1n 1n 1m 2m)
N1 in out rl
C1 out 0 1u
.tran 10u 3m
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot v(out) title first
pyplot v(in) title second
.endc
.end
"""
with open(os.path.join(HERE, "two.sp"), "w") as f:
    f.write(twodeck)
subprocess.run([NGSPICE, "-b", "two.sp"], capture_output=True, text=True, cwd=HERE)
p1 = open(os.path.join(HERE, "pyplot.py")).read() if os.path.isfile(os.path.join(HERE, "pyplot.py")) else ""
p2 = open(os.path.join(HERE, "pyplot-2.py")).read() if os.path.isfile(os.path.join(HERE, "pyplot-2.py")) else ""
check("E-183a: two no-name plots -> distinct pyplot / pyplot-2 with own titles",
      is_png(os.path.join(HERE, "pyplot.png")) and is_png(os.path.join(HERE, "pyplot-2.png"))
      and "suptitle('first')" in p1 and "suptitle('second')" in p2)

# ---- Enhancement-183b: artifacts written next to the CIRCUIT FILE ----
for f_ in ("dir.py", "dir.data", "dir.png"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass
dirdeck = twodeck.replace("pyplot v(out) title first\npyplot v(in) title second",
                          "pyplot dir v(out)")
deckpath = os.path.join(HERE, "dir.sp")
with open(deckpath, "w") as f:
    f.write(dirdeck)
# run from the PARENT dir but give the deck by ABSOLUTE path -> outputs must
# land next to the deck (HERE), not in the cwd (the parent)
parent = os.path.dirname(HERE)
subprocess.run([NGSPICE, "-b", deckpath], capture_output=True, text=True, cwd=parent)
pydir = open(os.path.join(HERE, "dir.py")).read() if os.path.isfile(os.path.join(HERE, "dir.py")) else ""
check("E-183b: artifacts land next to the .cir (abs deck path, run from parent)",
      is_png(os.path.join(HERE, "dir.png"))
      and not os.path.exists(os.path.join(parent, "dir.png"))
      and "'dir.npy'" in pydir and "_here" in pydir)   # E-548: resolved against the script

# ---- Enhancement-183c: pyplot_linewidth ----
lwdeck = twodeck.replace(
    "set pyplot_terminal=png\npyplot v(out) title first\npyplot v(in) title second",
    "set pyplot_terminal=png\nset pyplot_linewidth=3.5\npyplot lw v(out)")
with open(os.path.join(HERE, "lw.sp"), "w") as f:
    f.write(lwdeck)
subprocess.run([NGSPICE, "-b", "lw.sp"], capture_output=True, text=True, cwd=HERE)
pylw = open(os.path.join(HERE, "lw.py")).read() if os.path.isfile(os.path.join(HERE, "lw.py")) else ""
check("E-183c: set pyplot_linewidth=3.5 -> linewidth=3.5 in the plot() call",
      "linewidth=3.5" in pylw and is_png(os.path.join(HERE, "lw.png")))

# ---- Enhancement-183d: pyplot_backend ----
bedeck = twodeck.replace(
    "set pyplot_terminal=png\npyplot v(out) title first\npyplot v(in) title second",
    "set pyplot_terminal=png\nset pyplot_backend=Agg\npyplot be v(out)")
with open(os.path.join(HERE, "be.sp"), "w") as f:
    f.write(bedeck)
subprocess.run([NGSPICE, "-b", "be.sp"], capture_output=True, text=True, cwd=HERE)
pybe = open(os.path.join(HERE, "be.py")).read() if os.path.isfile(os.path.join(HERE, "be.py")) else ""
check("E-183d: set pyplot_backend=Agg -> matplotlib.use('agg') in the script",
      "matplotlib.use('agg')" in pybe and is_png(os.path.join(HERE, "be.png")))

# ---- Enhancement-208: `pyplot -eye` renders an eye diagram via matplotlib ----
# A self-contained data eye: a short pseudo-random NRZ bit stream (PWL) through a
# bandwidth-limiting RC channel (tau ~ 0.5 UI) so the eye is clearly open but
# ISI-shaped -- no OSDI model needed for the rendering path.
for f_ in ("eyefig.py", "eyefig.data", "eyefig.png",
           "eye.py", "eye.data", "eye.npy", "eye.png", "eye.sp"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass
random.seed(7)
_UI, _N, _TR = 0.5e-9, 300, 12e-12
_bits = [random.randint(0, 1) for _ in range(_N)]
_pts = ["0 %d" % _bits[0]]
for _k in range(1, _N):
    if _bits[_k] != _bits[_k - 1]:
        _te = _k * _UI
        _pts.append("%.6e %d" % (_te - _TR / 2, _bits[_k - 1]))
        _pts.append("%.6e %d" % (_te + _TR / 2, _bits[_k]))
eyedeck = """* pyplot -eye: eye diagram straight from a transient (Enhancement-208)
Vtx tx 0 PWL(%s)
Rc tx rx 250
Cc rx 0 1p
.tran 1p %gn
.control
run
set pyplot_terminal=png
pyplot eyefig -eye v(rx) -ui 0.5n -tstart 3n
pyplot -eye v(rx) -ui 0.5n -tstart 3n
.endc
.end
""" % (" ".join(_pts), _N * 0.5)
with open(os.path.join(HERE, "eye.sp"), "w") as f:
    f.write(eyedeck)
r = subprocess.run([NGSPICE, "-b", "eye.sp"], capture_output=True, text=True, cwd=HERE)
elog = r.stdout + r.stderr
pyeye = (open(os.path.join(HERE, "eyefig.py")).read()
         if os.path.isfile(os.path.join(HERE, "eyefig.py")) else "")
check("E-208: `pyplot -eye` runs the eye analysis and reports its metrics",
      "eye height" in elog and "eye width" in elog, elog.strip()[-160:])
check("E-208: `pyplot eyefig -eye v(rx) -ui ...` renders a valid eye PNG",
      is_png(os.path.join(HERE, "eyefig.png")))
check("E-208: the generated eye script is a persistence 2-D-histogram (hist2d)",
      "hist2d" in pyeye and "eye height" in pyeye and "matplotlib" in pyeye)
check("E-208: the no-name form defaults the eye base to 'eye.png'",
      is_png(os.path.join(HERE, "eye.png")))

# ---- Enhancement-547: the launch -- quoting, and the exit status ----
import shutil
import stat
statusdeck = """* pyplot launch probe (Enhancement-547)
V1 in 0 dc 1
R1 in 0 1k
.tran 10u 1m
.control
run
set pyplot_terminal=png
set pyplot_backend=Agg
{extra}
pyplot {name} v(in)
echo pyplot_status=$pyplot_status
.endc
.end
"""
def run_deck(path, cwd):
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, cwd=cwd)
    return r.stdout + r.stderr
def status_of(log):
    m = re.search(r"pyplot_status=(-?\d+)", log)
    return int(m.group(1)) if m else None

e547_dirs = []
for tag, sub in (("a", "with space"), ("b", "it's")):
    d = os.path.join(HERE, sub)
    os.makedirs(d, exist_ok=True)
    e547_dirs.append(d)
    deck = os.path.join(d, "probe.sp")
    with open(deck, "w") as f:
        f.write(statusdeck.format(extra="", name="probe"))
    log = run_deck(deck, HERE)
    png = os.path.join(d, "probe.png")
    check(f"E-547{tag}: a deck folder named '{sub}' renders (run by absolute path)",
          is_png(png) and status_of(log) == 0 and "can't open" not in log
          and "unexpected EOF" not in log and "Error" not in log,
          log.strip()[-200:])

badpy = os.path.join(HERE, "badpy.sh")
with open(badpy, "w") as f:
    f.write("#!/bin/sh\necho 'ModuleNotFoundError: No module named matplotlib' >&2\nexit 3\n")
os.chmod(badpy, os.stat(badpy).st_mode | stat.S_IXUSR)
deck = os.path.join(HERE, "status.sp")
with open(deck, "w") as f:
    # quoted: an unquoted `set` value is lowercased by ngspice, which a
    # case-sensitive file system would not forgive
    f.write(statusdeck.format(extra=f"set pyplot_python=\"{badpy}\"", name="status"))
log = run_deck(deck, HERE)
check("E-547c: an interpreter that exits 3 is named, the missing image is named, pyplot_status=3",
      "Error: pyplot:" in log and "exited with status 3" in log
      and "status.png was not written" in log and status_of(log) == 3
      and not os.path.exists(os.path.join(HERE, "status.png")),
      log.strip()[-240:])

with open(deck, "w") as f:
    f.write(statusdeck.format(extra="set pyplot_python=no_such_python_xyz", name="status"))
log = run_deck(deck, HERE)
check("E-547d: a missing interpreter reports status 127 and no image",
      "exited with status 127" in log and status_of(log) == 127
      and not os.path.exists(os.path.join(HERE, "status.png")),
      log.strip()[-240:])

with open(deck, "w") as f:
    f.write(statusdeck.format(extra="", name="status"))
log = run_deck(deck, HERE)
check("E-547e: a success publishes pyplot_status=0",
      is_png(os.path.join(HERE, "status.png")) and status_of(log) == 0, log.strip()[-200:])

with open(deck, "w") as f:
    f.write(statusdeck.format(extra="set pyplot_python=\"/usr/bin/env python3\"", name="status2"))
log = run_deck(deck, HERE)
check("E-547f: pyplot_python still carries options (/usr/bin/env python3)",
      is_png(os.path.join(HERE, "status2.png")) and status_of(log) == 0, log.strip()[-200:])

real_py = shutil.which("python3")
pydir = os.path.join(HERE, "py dir")
os.makedirs(pydir, exist_ok=True)
e547_dirs.append(pydir)
spaced_py = os.path.join(pydir, "python3")
if real_py and not os.path.exists(spaced_py):
    os.symlink(real_py, spaced_py)
with open(deck, "w") as f:
    f.write(statusdeck.format(extra=f"set pyplot_python=\"{spaced_py}\"", name="status3"))
log = run_deck(deck, HERE)
check("E-547g: an interpreter path with a space is one word",
      is_png(os.path.join(HERE, "status3.png")) and status_of(log) == 0, log.strip()[-200:])

# ---- Enhancement-548: the script and its data ----
import tempfile
E548 = """* pyplot script probe (Enhancement-548)
V1 in 0 dc 1 sin(1 1u 100meg)
R1 in out 1k
C1 out 0 1n
.tran 1n 20n
.control
run
set pyplot_terminal=png
set pyplot_backend=Agg
let t2 = time + 1
pyplot prec v(in) vs t2
ac dec 10 10 1e6
pyplot ylo mag(v(out)) ylog ylimit 1e-3 1
pyplot ybad mag(v(out)) ylog ylimit 0 1
pyplot xlo mag(v(out)) xlog xlimit 0 1e6
tran 10u 1m
pyplot mixed v(out) i(v1)
.endc
.end
"""
deck = os.path.join(HERE, "e548.sp")
with open(deck, "w") as f:
    f.write(E548)
log = run_deck(deck, HERE)
import numpy as np
prec = np.load(os.path.join(HERE, "prec.npy")) if os.path.isfile(os.path.join(HERE, "prec.npy")) else None
rows = prec if prec is not None else []
xs = list(prec["t2"]) if prec is not None else []; ys = list(prec["v(in)"]) if prec is not None else []
check("E-548a: every x of a 1 s-offset, 1 ns-step axis is distinct, and a 1 uV ripple on 1 V survives",
      len(rows) > 10 and len(set(xs)) == len(xs) and 1.5e-6 < (max(ys) - min(ys)) < 2.5e-6,
      f"{len(rows)} rows, {len(set(xs))} distinct x, ripple {max(ys) - min(ys) if ys else None}")
ylo = open(os.path.join(HERE, "ylo.py")).read() if os.path.isfile(os.path.join(HERE, "ylo.py")) else ""
ybad = open(os.path.join(HERE, "ybad.py")).read() if os.path.isfile(os.path.join(HERE, "ybad.py")) else ""
xlo = open(os.path.join(HERE, "xlo.py")).read() if os.path.isfile(os.path.join(HERE, "xlo.py")) else ""
check("E-548b: ylimit 1e-3 1 under ylog is applied",
      "set_yscale('log')" in ylo and "set_ylim(0.001" in ylo and is_png(os.path.join(HERE, "ylo.png")))
check("...E-548b: a non-positive limit under a log axis is refused by the command itself, no script",
      "Y values must be > 0 for log scale" in log and not ybad
      and "X values must be > 0 for log scale" in log and not xlo,
      log.strip()[-300:])
mixed = open(os.path.join(HERE, "mixed.py")).read() if os.path.isfile(os.path.join(HERE, "mixed.py")) else ""
check("E-548c: a voltage and a current get two y scales, labelled by type, one legend, explicit colours",
      "twinx()" in mixed and "_twin(0).plot(" in mixed and "set_ylabel('voltage [V]')" in mixed
      and "_twin(0).set_ylabel('current [A]')" in mixed and "_l1 + _l2" in mixed
      and "color='C0'" in mixed and "color='C1'" in mixed
      and is_png(os.path.join(HERE, "mixed.png")), mixed[-400:])
with tempfile.TemporaryDirectory() as far:
    os.remove(os.path.join(HERE, "mixed.png"))
    r = subprocess.run([sys.executable, os.path.join(HERE, "mixed.py")],
                       capture_output=True, text=True, cwd=far)
    check("E-548d: the generated script runs from another directory and writes its image next to itself",
          r.returncode == 0 and is_png(os.path.join(HERE, "mixed.png"))
          and not os.path.exists(os.path.join(far, "mixed.png")),
          (r.stderr or r.stdout).strip()[-200:])
for f in ("e548.sp", "prec.py", "prec.data", "prec.npy", "prec.png", "ylo.py", "ylo.data", "ylo.npy", "ylo.png",
          "ybad.py", "ybad.data", "ybad.npy", "ybad.png", "xlo.py", "xlo.data", "xlo.npy", "xlo.png",
          "mixed.py", "mixed.data", "mixed.npy", "mixed.png"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

# ---- Enhancement-549: the data table, .npy by default; pyplot_export; -export ----
E549 = """* pyplot table probe (Enhancement-549)
V1 in 0 dc 0 sin(0 1 1k)
R1 in out 1k
C1 out 0 159.155n
.tran 10u 3m
.control
run
set pyplot_terminal=png
set pyplot_backend=Agg
pyplot npyplot v(out) v(in)
set pyplot_export=ascii
pyplot txtplot v(out) v(in)
unset pyplot_export
pyplot -export sig v(out) i(v1)
pyplot -export iv i(v1) vs v(out)
pyplot -export -hist v(out)
set pyplot_export=parquet
pyplot -export odd v(out)
unset pyplot_export
let xs = vector(9)
let ys = floor(xs/3)
let xx = xs - 3*ys
let zz = xx*xx + ys*ys
pyplot cont -contour zz xx ys
ac dec 10 10 1e6
pyplot sm -smith v(out)
pyplot bo -bode v(out)
.endc
.end
"""
deck = os.path.join(HERE, "e549.sp")
with open(deck, "w") as f:
    f.write(E549)
log = run_deck(deck, HERE)
def npy(base):
    q = os.path.join(HERE, base + ".npy")
    return np.load(q) if os.path.isfile(q) else None
def npy_layout_ok(path, rows, cols):
    """numpy format 1.0 as written from C: magic, version 1.0, a little-endian
    u16 header length, the data starting on a 64-byte boundary, rows*cols doubles."""
    with open(path, "rb") as f:
        pre = f.read(10)
    hlen = int.from_bytes(pre[8:10], "little")
    return (pre[:6] == b"\x93NUMPY" and pre[6:8] == b"\x01\x00" and (10 + hlen) % 64 == 0
            and os.path.getsize(path) == 10 + hlen + rows * cols * 8)
a = npy("npyplot")
pynpy = open(os.path.join(HERE, "npyplot.py")).read() if os.path.isfile(os.path.join(HERE, "npyplot.py")) else ""
check("E-549a: the default table is <name>.npy, structured (time, v(out), time_2, v(in)), exact, and the script renders",
      a is not None and a.dtype.names == ("time", "v(out)", "time_2", "v(in)")
      and a.shape[0] > 100 and float(a["time"][1]) == float(a["time_2"][1])
      and not os.path.exists(os.path.join(HERE, "npyplot.data"))
      and "np.load(" in pynpy and "np.stack(" in pynpy and is_png(os.path.join(HERE, "npyplot.png")),
      f"names={a.dtype.names if a is not None else None}")
txt = os.path.join(HERE, "txtplot.data")
head = open(txt).readline().strip() if os.path.isfile(txt) else ""
pytxt = open(os.path.join(HERE, "txtplot.py")).read() if os.path.isfile(os.path.join(HERE, "txtplot.py")) else ""
check("E-549b: pyplot_export=ascii writes <name>.data with a '# time v(out) time_2 v(in)' header, and the script loads it",
      head == "# time v(out) time_2 v(in)" and not os.path.exists(os.path.join(HERE, "txtplot.npy"))
      and "np.loadtxt(" in pytxt and is_png(os.path.join(HERE, "txtplot.png")), head)
sig = npy("sig"); iv = npy("iv")
check("E-549c: `pyplot -export sig v(out) i(v1)` writes sig.npy, no script, and says so; `vs` names the x column",
      sig is not None and sig.dtype.names == ("time", "v(out)", "time_2", "i(v1)")
      and not os.path.exists(os.path.join(HERE, "sig.py")) and "pyplot: exported" in log
      and "sig.npy" in log and iv is not None and iv.dtype.names == ("v(out)", "i(v1)")
      and npy_layout_ok(os.path.join(HERE, "sig.npy"), sig.shape[0], 4),
      f"sig={sig.dtype.names if sig is not None else None} iv={iv.dtype.names if iv is not None else None}")
check("E-549d: -export with -hist is refused with the reason",
      "-export takes plain signals" in log and not os.path.exists(os.path.join(HERE, "export.npy")),
      log.strip()[-200:])
co = npy("cont"); smt = npy("sm"); bo = npy("bo")
check("E-549e: the -contour, -smith and -bode tables carry their own field names",
      co is not None and co.dtype.names == ("xx", "ys", "zz") and co.shape[0] == 9
      and smt is not None and smt.dtype.names == ("vec", "re", "im")
      and bo is not None and bo.dtype.names == ("vec", "frequency", "re", "im"),
      f"cont={co.dtype.names if co is not None else None} sm={smt.dtype.names if smt is not None else None} bo={bo.dtype.names if bo is not None else None}")
check("E-549f: an unknown pyplot_export value is said and falls back to .npy",
      "pyplot_export=parquet is neither" in log and npy("odd") is not None, log.strip()[-200:])
for base in ("npyplot", "txtplot", "sig", "iv", "odd", "cont", "sm", "bo", "export"):
    for ext in (".py", ".data", ".npy", ".png"):
        q = os.path.join(HERE, base + ext)
        if os.path.exists(q):
            os.remove(q)
if os.path.exists(deck):
    os.remove(deck)

# ---- Enhancement-550: envelope decimation ----
E550 = """* pyplot decimation probe (Enhancement-550)
V1 in 0 dc 0 sin(0 1 1k)
R1 in out 1k
C1 out 0 159.155n
.tran 10n 2m
.control
run
set pyplot_terminal=png
set pyplot_backend=Agg
pyplot dec v(out)
set pyplot_decimate=off
pyplot nodec v(out)
set pyplot_decimate=500
pyplot dec500 v(out)
unset pyplot_decimate
set pointstyle=markers
pyplot pts v(out)
unset pointstyle
pyplot xy v(in) vs v(out)
unset pyplot_terminal
pyplot win v(out)
.endc
.end
"""
deck = os.path.join(HERE, "e550.sp")
with open(deck, "w") as f:
    f.write(E550)
log = run_deck(deck, HERE)

def exec_script(base):
    """Run the generated script in-process under Agg (plt.show() is a no-op
    there) and hand back its namespace, with `axes` and `d` in it."""
    import matplotlib
    matplotlib.use("Agg")
    ns = {"__file__": os.path.join(HERE, base + ".py"), "__name__": "__pyplot__"}
    src = open(ns["__file__"]).read() if os.path.isfile(ns["__file__"]) else ""
    if not src:
        return None
    try:
        exec(compile(src, ns["__file__"], "exec"), ns)
    except Exception as e:  # noqa: BLE001
        print("    script failed:", e)
        return None
    return ns

def envelope_matches(ns):
    """The drawn line has at most 2 points per bin and the same min/max per bin as the full data."""
    ln = ns["axes"][0, 0].lines[0]
    xs, ys = ln.get_xdata(), ln.get_ydata()
    full = ns["d"]
    fx, fy = full[:, 0], full[:, 1]
    npix = int(ns["_npix0"])
    if xs.size > 2 * npix or xs.size >= fx.size:
        return False, f"{xs.size} points drawn of {fx.size}, {npix} bins"
    edges = np.linspace(fx[0], fx[-1], npix + 1)
    fb = np.clip(np.searchsorted(edges, fx, side="right") - 1, 0, npix - 1)
    db = np.clip(np.searchsorted(edges, xs, side="right") - 1, 0, npix - 1)
    for b in range(0, npix, max(1, npix // 50)):
        fm, dm = fb == b, db == b
        if fm.any() and dm.any():
            if abs(fy[fm].min() - ys[dm].min()) > 1e-12 or abs(fy[fm].max() - ys[dm].max()) > 1e-12:
                return False, f"bin {b}: full [{fy[fm].min()}, {fy[fm].max()}] drawn [{ys[dm].min()}, {ys[dm].max()}]"
    return True, f"{xs.size} points drawn of {fx.size}, {npix} bins"

ns = exec_script("dec")
ok, why = envelope_matches(ns) if ns else (False, "no script")
check("E-550a: a 200k-sample hardcopy trace is its envelope: <= 2 points per pixel column, the same extremes, and it says so",
      ns is not None and ok and "drawn as a" in log and "-point envelope" in log
      and is_png(os.path.join(HERE, "dec.png")), why)
ns = exec_script("nodec")
check("E-550b: pyplot_decimate=off draws every sample",
      ns is not None and "_envelope" not in open(os.path.join(HERE, "nodec.py")).read()
      and ns["axes"][0, 0].lines[0].get_xdata().size == ns["d"].shape[0],
      f"{ns['axes'][0, 0].lines[0].get_xdata().size if ns else None} points")
ns = exec_script("dec500")
check("E-550c: pyplot_decimate=500 draws at most 1000 points",
      ns is not None and ns["_npix0"] == 500 and 2 <= ns["axes"][0, 0].lines[0].get_xdata().size <= 1000,
      f"{ns['axes'][0, 0].lines[0].get_xdata().size if ns else None} points")
ns = exec_script("win")
if ns:
    ln = ns["axes"][0, 0].lines[0]
    n0 = ln.get_xdata().size
    ns["axes"][0, 0].set_xlim(0.5e-3, 0.51e-3)        # a 10 us slice of the 2 ms run
    x1 = ln.get_xdata()
    inside = x1.size > 50 and x1.min() >= 0.49e-3 and x1.max() <= 0.52e-3
    full_in_slice = ((ns["d"][:, 0] >= 0.5e-3) & (ns["d"][:, 0] <= 0.51e-3)).sum()
    check("E-550d: a window re-decimates on zoom: the line becomes the visible slice, in detail",
          "xlim_changed" in open(os.path.join(HERE, "win.py")).read() and inside
          and x1.size >= min(full_in_slice, 2 * int(ns["axes"][0, 0].bbox.width)) - 4,
          f"{n0} points before, {x1.size} after, {full_in_slice} samples in the slice")
else:
    check("E-550d: (skipped: the window script did not run)", False)
ns_p = exec_script("pts"); ns_xy = exec_script("xy")
check("E-550e: a point plot and a backwards-x `vs` plot keep every sample",
      ns_p is not None and ns_p["axes"][0, 0].lines[0].get_xdata().size == ns_p["d"].shape[0]
      and ns_xy is not None and ns_xy["axes"][0, 0].lines[0].get_xdata().size == ns_xy["d"].shape[0],
      "")
import matplotlib.pyplot as _plt
_plt.close("all")
for base in ("dec", "nodec", "dec500", "pts", "xy", "win"):
    for ext in (".py", ".data", ".npy", ".png"):
        q = os.path.join(HERE, base + ext)
        if os.path.exists(q):
            os.remove(q)
if os.path.exists(deck):
    os.remove(deck)

# ---- Enhancement-551: engineering ticks, typed labels, a clean title ----
E551 = """* eng probe deck
V1 in 0 dc 0 ac 1 sin(0 1 1k)
R1 in out 1k
C1 out 0 159.155n
.tran 10u 3m
.control
run
set pyplot_terminal=png
set pyplot_backend=Agg
pyplot eng v(out)
pyplot mix v(out) i(v1)
pyplot lab v(out) xlabel "my x" ylabel "my y" title "my title"
set pyplot_eng=off
pyplot raw v(out)
unset pyplot_eng
pyplot fft -fft v(out)
let vo = v(out)
pyplot hst -hist vo
ac dec 10 10 1e6
pyplot dbp db(v(out)) xlog
.endc
.end
"""
deck = os.path.join(HERE, "e551.sp")
with open(deck, "w") as f:
    f.write(E551)
log = run_deck(deck, HERE)

def ticks(ax, which):
    """The tick label texts after a draw (formatters run at draw time)."""
    ax.figure.canvas.draw()
    labels = ax.get_xticklabels() if which == "x" else ax.get_yticklabels()
    return [t.get_text() for t in labels if t.get_text()]

ns = exec_script("eng")
py = open(os.path.join(HERE, "eng.py")).read() if os.path.isfile(os.path.join(HERE, "eng.py")) else ""
xt = ticks(ns["axes"][0, 0], "x") if ns else []; yt = ticks(ns["axes"][0, 0], "y") if ns else []
check("E-551a: labels `time [s]` / `voltage [V]`, ticks like `500 µs` and `-500 mV`",
      "set_xlabel('time [s]')" in py and "set_ylabel('voltage [V]')" in py
      and any("ms" in t for t in xt) and any("mV" in t for t in yt), f"x={xt[:4]} y={yt[:4]}")
ns = exec_script("mix")
py = open(os.path.join(HERE, "mix.py")).read() if os.path.isfile(os.path.join(HERE, "mix.py")) else ""
tw = list(ns["_tw"].values())[0] if ns and ns.get("_tw") else None
rt = ticks(tw, "y") if tw is not None else []
check("E-551b: a mixed plot reads `voltage [V]` left, `current [A]` right, with µA ticks on the twin",
      "set_ylabel('voltage [V]')" in py and "_twin(0).set_ylabel('current [A]')" in py
      and any("µA" in t or "mA" in t for t in rt), f"right={rt[:4]}")
ns = exec_script("lab")
py = open(os.path.join(HERE, "lab.py")).read() if os.path.isfile(os.path.join(HERE, "lab.py")) else ""
xt = ticks(ns["axes"][0, 0], "x") if ns else []
check("E-551c: the user's xlabel/ylabel/title are kept verbatim, the ticks still carry the unit",
      "set_xlabel('my x')" in py and "set_ylabel('my y')" in py and "suptitle('my title')" in py
      and any("ms" in t for t in xt), f"x={xt[:4]}")
ns = exec_script("raw")
py = open(os.path.join(HERE, "raw.py")).read() if os.path.isfile(os.path.join(HERE, "raw.py")) else ""
xt = ticks(ns["axes"][0, 0], "x") if ns else []
check("E-551d: pyplot_eng=off keeps plain tick numbers and the typed labels",
      "EngFormatter(unit=" not in py and "set_xlabel('time [s]')" in py
      and xt and not any("ms" in t for t in xt), f"x={xt[:4]}")
ns = exec_script("dbp")
py = open(os.path.join(HERE, "dbp.py")).read() if os.path.isfile(os.path.join(HERE, "dbp.py")) else ""
xt = ticks(ns["axes"][0, 0], "x") if ns else []; yt = ticks(ns["axes"][0, 0], "y") if ns else []
check("E-551e: db(v(out)) has `decibel [dB]` with plain ticks, and `10 kHz`-style ticks on the log frequency axis",
      "set_ylabel('decibel [dB]')" in py and "set_xlabel('frequency [Hz]')" in py
      and any("kHz" in t for t in xt) and not any("dB" in t for t in yt), f"x={xt[:5]} y={yt[:3]}")
check("E-551f: the deck's `* ` is dropped from the default title; a given title is untouched",
      "suptitle('eng probe deck')" in open(os.path.join(HERE, "eng.py")).read()
      and "suptitle('my title')" in open(os.path.join(HERE, "lab.py")).read())
pf = open(os.path.join(HERE, "fft.py")).read() if os.path.isfile(os.path.join(HERE, "fft.py")) else ""
ph = open(os.path.join(HERE, "hst.py")).read() if os.path.isfile(os.path.join(HERE, "hst.py")) else ""
check("E-551g: -fft labels `Frequency [Hz]` / `Magnitude [V]` with Hz ticks; -hist labels `voltage [V]` with V ticks",
      "set_xlabel('Frequency [Hz]')" in pf and "set_ylabel('Magnitude [V]')" in pf and "EngFormatter(unit='Hz')" in pf
      and "set_xlabel('voltage [V]')" in ph and "EngFormatter(unit='V')" in ph)
_plt.close("all")
for base in ("eng", "mix", "lab", "raw", "fft", "hst", "dbp"):
    for ext in (".py", ".data", ".npy", ".png"):
        q = os.path.join(HERE, base + ext)
        if os.path.exists(q):
            os.remove(q)
if os.path.exists(deck):
    os.remove(deck)

for d in e547_dirs:
    shutil.rmtree(d, ignore_errors=True)
for f in ("badpy.sh", "status.sp", "status.py", "status.data", "status.npy", "status.png",
          "status2.py", "status2.data", "status2.npy", "status2.png",
          "status3.py", "status3.data", "status3.npy", "status3.png"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

for f in ("two.sp", "dir.sp", "lw.sp", "be.sp",
          "pyplot-2.py", "pyplot-2.data", "pyplot-2.npy", "pyplot-2.png",
          "dir.py", "dir.data", "dir.npy", "dir.png", "lw.py", "lw.data", "lw.npy", "lw.png",
          "be.py", "be.data", "be.npy", "be.png",
          "tran.sp", "ac.sp", "nofn.sp", "rc.py", "rc.data", "rc.npy", "rc.png",
          "acmag.py", "acmag.data", "acmag.npy", "acmag.png",
          "eye.sp", "eyefig.py", "eyefig.data", "eyefig.npy", "eyefig.png",
          "eye.py", "eye.data", "eye.npy", "eye.png",
          "pyplot.py", "pyplot.data", "pyplot.npy", "pyplot.png", "rcload.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
