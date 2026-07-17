#!/usr/bin/env python3
"""
verify_pyplotcontour.py -- Enhancement-218: the `pyplot -contour` render mode.

`pyplot -contour <z> <x> <y>` renders a 2-D contour map of a quantity z over the
(x, y) plane -- the natural view of a 2-D parameter sweep. It reuses the whole
pyplot pipeline (the E-94 matplotlib back end, `set pyplot_terminal=png` for a
headless PNG, styles, figsize); the (x,y) points are triangulated (matplotlib
tricontourf), so gridded OR scattered sweep data plots with no dimension metadata.

`pyplotcontour_demo.cir` builds a grid with a KNOWN analytic surface:
  z = x^2 + y^2   over x,y in [-2,2]  ->  concentric circular contours
                                          (a paraboloid: z=0 at the centre,
                                           z=8 at the corners)

Checks (parsing the generated .data table + .py script + the PNG):
  1. the -contour path is taken -- the .py uses ax.tricontourf (not plot/hist),
     draws a colorbar, and labels the axes x/y and the colorbar z;
  2. the data table has THREE columns (x, y, z), all N rows (not truncated);
  3. the column mapping is correct -- z == x^2 + y^2 reconstructed from the .data
     (confirms x=col0, y=col1, z=col2);
  4. the sweep is genuinely 2-D -- x AND y each span a real range, and z runs
     from ~0 at the grid centre to ~8 at a corner (a paraboloid, not a line);
  5. a valid, non-trivial PNG is rendered.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # both solvers

NX = NY = 41
N = NX * NY
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def main():
    for f in ("pyplotcontour.py", "pyplotcontour.data", "pyplotcontour.png"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
    subprocess.run([NGSPICE, "-b", "pyplotcontour_demo.cir"], cwd=HERE,
                   capture_output=True, text=True, timeout=120)

    py = os.path.join(HERE, "pyplotcontour.py")
    data = os.path.join(HERE, "pyplotcontour.data")
    png = os.path.join(HERE, "pyplotcontour.png")

    print("[1] the -contour render path was taken")
    pytext = open(py).read() if os.path.exists(py) else ""
    check("pyplotcontour.py uses tricontourf, not plot/hist",
          "tricontourf(" in pytext and ".plot(" not in pytext and ".hist(" not in pytext)
    check("a colorbar is drawn and labelled z", "colorbar(" in pytext and "set_label('z')" in pytext)
    check("axes are labelled x and y",
          "set_xlabel('x')" in pytext and "set_ylabel('y')" in pytext)

    print("[2] the data table has three columns (x, y, z), all N rows")
    rows = [ln.split() for ln in open(data)] if os.path.exists(data) else []
    ncol = len(rows[0]) if rows else 0
    check("data table has 3 columns per row", ncol == 3, f"{ncol} columns")
    check("data table has all N samples", len(rows) == N, f"{len(rows)} rows, want {N}")
    if ncol != 3 or len(rows) != N:
        print("\nSOME FAILED")
        sys.exit(1)
    x = [float(r[0]) for r in rows]
    y = [float(r[1]) for r in rows]
    z = [float(r[2]) for r in rows]

    print("[3] the column mapping is correct: z == x^2 + y^2")
    maxerr = max(abs(z[k] - (x[k] * x[k] + y[k] * y[k])) for k in range(N))
    check("z reconstructs x^2 + y^2 from the .data", maxerr < 1e-9, f"max err {maxerr:.1e}")

    print("[4] the sweep is genuinely 2-D (a paraboloid, not a line)")
    xr = max(x) - min(x)
    yr = max(y) - min(y)
    check("x and y each span a real range", xr > 3.5 and yr > 3.5,
          f"x span {xr:.2f}, y span {yr:.2f}")
    # z ~ 0 at the point nearest the grid centre, ~8 at the farthest corner
    kc = min(range(N), key=lambda k: x[k] * x[k] + y[k] * y[k])
    check("z ~0 at centre, ~8 at corner (paraboloid)",
          z[kc] < 0.05 and max(z) > 7.5, f"z_centre {z[kc]:.3f}, z_max {max(z):.3f}")

    print("[5] a valid PNG was rendered")
    ok_png = False
    if os.path.exists(png):
        with open(png, "rb") as fh:
            ok_png = fh.read(8) == b"\x89PNG\r\n\x1a\n" and os.path.getsize(png) > 2000
    check("pyplotcontour.png is a valid, non-trivial PNG", ok_png,
          f"{os.path.getsize(png) if os.path.exists(png) else 0} bytes")

    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
