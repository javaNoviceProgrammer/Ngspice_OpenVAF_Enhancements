#!/usr/bin/env python3
"""verify_pyplotmore.py -- Enhancements 296-300: pyplot additions.

  [296] appearance controls: pyplot_grid / pyplot_legend / pyplot_markers /
        pyplot_axhline / pyplot_axvline / pyplot_dpi / pyplot_transparent.
  [297] `-fft`: one-sided amplitude spectrum (amplitude-correct against a closed-form
        two-tone oracle), with pyplot_fft_window / _db / _points / _logf.
  [298] `-bode` / `-nyquist` / `-polar`: complex-aware AC views (keep the imaginary
        part, which an ordinary `pyplot v(out)` discards). Checked against the exact
        RC low-pass values at fc: -3.01 dB and -45 deg.
  [299] cross-run overlay of different-length runs renders every trace fully; the
        `pyplot_cursor` crosshair is emitted only in an interactive window.
  [300] `pyplot_mplcursors` selects the mplcursors backend (data cursors) instead of
        the built-in Cursor crosshair, with a graceful fallback if mplcursors is not
        importable; still window-only.
  [301] `pyplot_cursor` is the single master switch: OFF by default, the only thing
        that enables any cursor. `pyplot_mplcursors` only selects the backend when the
        cursor is on -- on its own it does nothing.

Every generated script is also executed (matplotlib Agg) so a syntactically broken
emission fails, not just a missing keyword.

The cursor cases ([299]-[301]) have to run in WINDOW mode, because the cursor is
gated on `!hardcopy` -- that gating is the thing under test, so `pyplot_terminal`
would delete it. They set `pyplot_backend=Agg` instead: the window-mode code path
is untouched (plt.show() and the Cursor lines are still emitted, which is what the
checks read) but matplotlib renders headless, so the suite opens no windows. Do
not drop those `set pyplot_backend=Agg` lines -- without them this suite pops five
matplotlib windows on every run, twice over, once per solver.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))


def run(deck, name):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


def script(base):
    p = os.path.join(HERE, base + ".py")
    return open(p).read() if os.path.isfile(p) else ""


def data(base):
    """Enhancement-549: the table as a 2-D array, whichever format was written."""
    import numpy as np
    q = os.path.join(HERE, base + ".npy")
    if os.path.isfile(q):
        d = np.load(q)
        return np.stack([d[n] for n in d.dtype.names], axis=1)
    p = os.path.join(HERE, base + ".data")
    return np.loadtxt(p) if os.path.isfile(p) else None


def run_generated(base):
    """Execute the emitted matplotlib script; True iff it runs clean and prints 'wrote'."""
    p = os.path.join(HERE, base + ".py")
    if not os.path.isfile(p):
        return False
    r = subprocess.run([sys.executable, p], cwd=HERE, capture_output=True,
                       text=True, timeout=120, errors="replace")
    return r.returncode == 0 and "wrote" in (r.stdout + r.stderr)


HEAD = ("* pyplotmore\nv1 in 0 dc 0 ac 1 sin(0 1 1k)\nr1 in out 1591.55\n"
        "c1 out 0 100n\n")

print("Enhancements 296-299: pyplot additions\n")

# ---------------------------------------------------------------- [296]
print("[296] appearance controls")
out = run(HEAD + ".control\ntran 10u 3m\nset pyplot_terminal=png\nset pyplot_backend=Agg\n"
          "set pyplot_markers\nset pyplot_grid=off\nset pyplot_legend=upper_right\n"
          "set pyplot_axhline=0.5,-0.5\nset pyplot_axvline=1m,2m\nset pyplot_dpi=150\n"
          "set pyplot_transparent\npyplot e296 v(in) v(out)\n.endc\n.end\n", "e296.cir")
s = script("e296")
for tag, probe in (("markers", "marker='o'"), ("grid off", "grid(False)"),
                   ("legend loc", "legend(loc='upper right')"),
                   ("axhline", "axhline(5.000000e-01"),
                   ("axvline", "axvline(1.000000e-03"),
                   ("dpi", "dpi=150"), ("transparent", "transparent=True")):
    check(f"296: {tag}", probe in s)
check("296: the generated script runs clean", run_generated("e296"))

# default path unchanged (backward compat)
run(HEAD + ".control\ntran 10u 3m\nset pyplot_terminal=png\nset pyplot_backend=Agg\n"
    "pyplot e296def v(out)\n.endc\n.end\n", "e296def.cir")
sd = script("e296def")
check("296: default path unchanged (plain legend, dpi=100, no reflines)",
      "legend()" in sd and "dpi=100" in sd and "axhline" not in sd and "marker=" not in sd)

# ---------------------------------------------------------------- [297]
print("\n[297] -fft magnitude spectrum")
out = run("* fft two-tone\nv1 a 0 dc 0 sin(0 2 1k)\nr1 a 0 1k\n.control\ntran 5u 20m\n"
          "let sig = 2*sin(2*3.14159265*1000*time) + 0.5*sin(2*3.14159265*3000*time)\n"
          "set pyplot_terminal=png\nset pyplot_backend=Agg\npyplot e297 -fft sig\n"
          ".endc\n.end\n", "e297.cir")
check("297: -fft compiles a spectrum script that runs", run_generated("e297"))
import numpy as np
d = data("e297")
ok_amp = False
if d is not None and d.ndim == 2:
    t, y = d[:, 0], d[:, 1]
    m = ~np.isnan(t) & ~np.isnan(y)
    t, y = t[m], y[m]
    N = 1 << int(np.ceil(np.log2(max(8, t.size))))
    tu = np.linspace(t[0], t[-1], N)
    yu = np.interp(tu, t, y)
    w = np.hanning(N)
    Y = np.fft.rfft((yu - yu.mean()) * w)
    f = np.fft.rfftfreq(N, (t[-1] - t[0]) / (N - 1))
    mag = np.abs(Y) * 2 / np.sum(w)
    a1 = mag[max(0, np.argmin(abs(f - 1000)) - 2):np.argmin(abs(f - 1000)) + 3].max()
    a3 = mag[max(0, np.argmin(abs(f - 3000)) - 2):np.argmin(abs(f - 3000)) + 3].max()
    ok_amp = abs(a1 - 2.0) / 2.0 < 0.02 and abs(a3 - 0.5) / 0.5 < 0.02
check("297: a 2.0 @ 1kHz + 0.5 @ 3kHz tone reads back its amplitude (oracle)", ok_amp)

out = run("* fft options\nv1 a 0 dc 0 sin(0 1 1k)\nr1 a 0 1k\n.control\ntran 5u 20m\n"
          "let sig = sin(2*3.14159265*1000*time)\nset pyplot_terminal=png\n"
          "set pyplot_backend=Agg\nset pyplot_fft_window=blackman\nset pyplot_fft_db\n"
          "set pyplot_fft_points=8192\nset pyplot_fft_logf\npyplot e297b -fft sig\n"
          ".endc\n.end\n", "e297b.cir")
sb = script("e297b")
check("297: window/db/points/logf all applied",
      "np.blackman(_N)" in sb and "np.log10" in sb and "_N = 8192" in sb
      and "_f = _f[1:]" in sb and "set_xscale('log')" in sb)
check("297: the options script runs clean", run_generated("e297b"))

# ---------------------------------------------------------------- [298]
print("\n[298] complex-aware AC modes")
out = run(HEAD + ".control\nac dec 30 10 1e6\nset pyplot_terminal=png\n"
          "set pyplot_backend=Agg\npyplot bode1 -bode v(out)\npyplot nyq1 -nyquist v(out)\n"
          "pyplot pol1 -polar v(out)\n.endc\n.end\n", "e298.cir")
for m in ("bode1", "nyq1", "pol1"):
    check(f"298: {m} renders and runs", run_generated(m))
db = data("bode1")   # cols: vi, freq, re, im  -- the imaginary part is KEPT
ok_bode = False
if db is not None and db.ndim == 2:
    f = db[:, 1]
    z = db[:, 2] + 1j * db[:, 3]
    k = np.argmin(abs(f - 1000))
    mag = 20 * np.log10(abs(z[k]))
    ph = math.degrees(math.atan2(z[k].imag, z[k].real))
    ok_bode = abs(mag - (-3.01)) < 0.05 and abs(ph - (-45.0)) < 0.5
check("298: Bode keeps the imag part: -3.01 dB / -45 deg at fc (RC oracle)", ok_bode)

# ---------------------------------------------------------------- [299]
print("\n[299] overlay robustness + cursor gating")
out = run("* different-length overlay\nv1 in 0 dc 0 pulse(0 1 0 1u 1u 1m 2m)\n"
          "r1 in out 1k\nc1 out 0 100n\n.control\nset pyplot_terminal=png\n"
          "set pyplot_backend=Agg\ntran 5u 3m\ntran 2u 3m\nsetplot\n"
          "pyplot ovl tran1.v(out) tran2.v(out)\n.endc\n.end\n", "e299.cir")
do = data("ovl")
ok_ovl = False
if do is not None and do.ndim == 2 and do.shape[1] >= 4:
    n1 = np.sum(~np.isnan(do[:, 1]))
    n2 = np.sum(~np.isnan(do[:, 3]))
    ok_ovl = n1 > 100 and n2 > 100 and n2 > n1     # finer 2nd run fully present
check("299: overlay of different-length runs keeps every trace full", ok_ovl,
      "" if ok_ovl else "truncated")
check("299: the overlay script runs clean", run_generated("ovl"))

# `pyplot_backend=Agg` up front: these cases must stay in WINDOW mode, because
# that is exactly what they check -- the cursor is gated on `!hardcopy`, so
# switching them to pyplot_terminal=png would delete the behaviour under test.
# Setting only the matplotlib BACKEND keeps the window-mode code path intact
# (plt.show() and the Cursor lines are still emitted, which is what `script()`
# reads) while rendering headless, so the suite opens no windows.
run("* cursor gating\nv1 a 0 dc 0 sin(0 1 1k)\nr1 a 0 1k\n.control\ntran 10u 3m\n"
    "set pyplot_backend=Agg\n"
    "set pyplot_cursor\npyplot curwin v(a)\nset pyplot_terminal=png\n"
    "pyplot curfile v(a)\n.endc\n.end\n", "e299cur.cir")
check("299: pyplot_cursor emitted in a window, NOT in a hardcopy",
      "Cursor" in script("curwin") and "Cursor" not in script("curfile"))

# ------------------------------------------------------------ [300]/[301]
print("\n[300]/[301] pyplot_cursor master switch + pyplot_mplcursors backend")
# every gating case in one deck
run("* cursor gating\nv1 a 0 dc 0 sin(0 1 1k)\nr1 a 0 1k\n.control\ntran 10u 3m\n"
    "set pyplot_backend=Agg\n"          # headless; window mode otherwise unchanged
    "pyplot none v(a)\n"                                   # nothing -> OFF (default)
    "set pyplot_cursor\npyplot cur v(a)\nunset pyplot_cursor\n"      # cursor -> built-in
    "set pyplot_mplcursors\npyplot mplonly v(a)\n"                   # mplcursors ONLY -> OFF
    "set pyplot_cursor\npyplot curmpl v(a)\n"                        # both -> mplcursors
    "set pyplot_terminal=png\n"
    "pyplot file v(a)\n.endc\n.end\n", "e301.cir")

def has_builtin(b):  return "from matplotlib.widgets import Cursor" in script(b)
def has_mpl(b):      return "import mplcursors" in script(b)

check("301: default -> NO cursor (disabled by default)",
      not has_builtin("none") and not has_mpl("none"))
check("301: pyplot_cursor alone -> built-in Cursor crosshair",
      has_builtin("cur") and not has_mpl("cur"))
check("301: pyplot_mplcursors ALONE -> NO cursor (master switch off)",
      not has_builtin("mplonly") and not has_mpl("mplonly"))
check("300: pyplot_cursor + pyplot_mplcursors -> mplcursors, hover=True",
      has_mpl("curmpl") and "mplcursors.cursor(hover=True)" in script("curmpl"))
check("300: mplcursors path has a graceful built-in fallback",
      has_builtin("curmpl") and "except" in script("curmpl"))
check("301: no cursor of any kind in a hardcopy",
      not has_builtin("file") and not has_mpl("file"))

# tidy the generated artifacts (NOT this script or the README)
import glob
KEEP = {"verify_pyplotmore.py", "README.md"}
for pat in ("*.cir", "*.py", "*.data", "*.npy", "*.png"):
    for g in glob.glob(os.path.join(HERE, pat)):
        if os.path.basename(g) in KEEP:
            continue
        try:
            os.remove(g)
        except OSError:
            pass

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
