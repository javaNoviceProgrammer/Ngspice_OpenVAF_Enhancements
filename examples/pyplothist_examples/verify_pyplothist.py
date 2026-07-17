#!/usr/bin/env python3
"""
verify_pyplothist.py -- Enhancement-217: the `pyplot -hist` histogram mode.

`pyplot -hist <sig> ...` renders each signal's VALUE distribution as a histogram
(matplotlib plt.hist) instead of a trace. It reuses the whole pyplot pipeline (the
E-94 matplotlib back end, `set pyplot_terminal=png` for headless PNG, subplots,
styles); only the render changes.

`pyplothist_demo.cir` builds two signals with known analytic distributions:
  ramp = i/(N-1)         -> UNIFORM on [0,1]  (flat histogram)
  sine = sin(2*pi*i/100) -> ARCSINE on [-1,1] (U-shaped -- a sinusoid dwells near
                                               its peaks, so the edges tower)

Checks (parsing the generated .data table + .py script + the PNG):
  1. the -hist path is taken -- the .py uses plt.hist (not plt.plot) and does NOT
     share the x-axis (histograms of different signals have unrelated ranges);
  2. the data table holds the FULL signal length (a histogram of a raw `let` vector
     whose scale length differs must not be truncated to the scale -- the E-217 fix);
  3. the ramp histogram is UNIFORM (flat: every bin within ~15% of the mean);
  4. the sine histogram is ARCSINE (the edge bins tower over the middle);
  5. a valid PNG of non-trivial size is rendered.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # both solvers

N = 20000
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def histogram(vals, lo, hi, nbins):
    """Plain fixed-range histogram (no numpy) -> list of bin counts."""
    counts = [0] * nbins
    w = (hi - lo) / nbins
    for v in vals:
        if lo <= v <= hi:
            b = min(int((v - lo) / w), nbins - 1)
            counts[b] += 1
    return counts


def main():
    for f in ("pyplothist.py", "pyplothist.data", "pyplothist.png"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
    subprocess.run([NGSPICE, "-b", "pyplothist_demo.cir"], cwd=HERE,
                   capture_output=True, text=True, timeout=120)

    py = os.path.join(HERE, "pyplothist.py")
    data = os.path.join(HERE, "pyplothist.data")
    png = os.path.join(HERE, "pyplothist.png")

    print("[1] the -hist render path was taken")
    pytext = open(py).read() if os.path.exists(py) else ""
    check("pyplothist.py uses plt.hist, not plt.plot",
          ".hist(" in pytext and ".plot(" not in pytext)
    check("histogram panels do not share the x-axis", "sharex=False" in pytext)

    print("[2] the full signal length is histogrammed (not truncated to the scale)")
    rows = [ln.split() for ln in open(data)] if os.path.exists(data) else []
    check("data table has all N samples", len(rows) == N, f"{len(rows)} rows, want {N}")
    if len(rows) != N:
        print("\nSOME FAILED")
        sys.exit(1)
    # columns are "scale value" per vector: ramp=col1, sine=col3
    ramp = [float(r[1]) for r in rows]
    sine = [float(r[3]) for r in rows]

    print("[3] ramp -> uniform distribution (flat histogram)")
    rc = histogram(ramp, 0.0, 1.0, 10)
    mean = sum(rc) / len(rc)
    flat = all(abs(c - mean) <= 0.15 * mean for c in rc)
    check("every bin within 15% of the mean", flat,
          f"bins {min(rc)}..{max(rc)}, mean {mean:.0f}")

    print("[4] sine -> arcsine distribution (edges tower over the middle)")
    sc = histogram(sine, -1.0, 1.0, 20)
    edges = sc[0] + sc[1] + sc[-1] + sc[-2]          # |v| > 0.8
    middle = sc[9] + sc[10]                          # |v| < 0.1
    check("edge bins >> middle bins (U-shape)", edges > 4 * middle,
          f"edges {edges} vs middle {middle}")

    print("[5] a valid PNG was rendered")
    ok_png = False
    if os.path.exists(png):
        with open(png, "rb") as fh:
            ok_png = fh.read(8) == b"\x89PNG\r\n\x1a\n" and os.path.getsize(png) > 2000
    check("pyplothist.png is a valid, non-trivial PNG", ok_png,
          f"{os.path.getsize(png) if os.path.exists(png) else 0} bytes")

    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
