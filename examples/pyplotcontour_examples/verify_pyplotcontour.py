#!/usr/bin/env python3
"""
verify_pyplotcontour.py -- Enhancement-218: the `pyplot -contour` render mode.

`pyplot -contour <z> <x> <y>` renders a 2-D contour map of a quantity z over the
(x, y) plane -- the natural view of a 2-D parameter sweep. It reuses the whole
pyplot pipeline (the E-94 matplotlib back end, `set pyplot_terminal=png` for a
headless PNG, styles, figsize); the (x,y) points are triangulated (matplotlib
tricontourf), so gridded OR scattered sweep data plots with no dimension metadata.

Two demos are verified, both under both solvers:

  (A) pyplotcontour_demo.cir -- a grid built in .control with a KNOWN analytic
      surface, z = x^2 + y^2 over x,y in [-2,2] (a paraboloid: concentric circular
      contours, z=0 at the centre and z=8 at the corners). Checked analytically.

  (B) bridge_dc_demo.cir -- a REAL nested .dc sweep of a diode-OR bridge. v1 drives
      node a and v2 drives node b, so V(a)/V(b) are the two swept values at every
      point and V(c) is the output; `pyplot -contour v(c) v(a) v(b)` maps it over
      the (V(a),V(b)) plane. The output follows whichever input is higher, so it
      rises toward the top and right edges -- a max-like corner surface. This
      confirms the feature on genuine simulation output (not just .control math).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # both solvers

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def run(deck, base):
    """Run a deck, remove any stale outputs first, and return (pytext, rows)."""
    for ext in ("py", "data", "png"):
        p = os.path.join(HERE, f"{base}.{ext}")
        if os.path.exists(p):
            os.remove(p)
    subprocess.run([NGSPICE, "-b", deck], cwd=HERE,
                   capture_output=True, text=True, timeout=180)
    py = os.path.join(HERE, f"{base}.py")
    data = os.path.join(HERE, f"{base}.data")
    pytext = open(py).read() if os.path.exists(py) else ""
    rows = [ln.split() for ln in open(data)] if os.path.exists(data) else []
    return pytext, rows


def valid_png(base):
    png = os.path.join(HERE, f"{base}.png")
    if not os.path.exists(png):
        return False, 0
    with open(png, "rb") as fh:
        sig = fh.read(8) == b"\x89PNG\r\n\x1a\n"
    sz = os.path.getsize(png)
    return (sig and sz > 2000), sz


def nearest(rows, cx, cy):
    """Index of the (x, y) row closest to the corner (cx, cy)."""
    return min(range(len(rows)),
               key=lambda k: (rows[k][0] - cx) ** 2 + (rows[k][1] - cy) ** 2)


def demo_analytic():
    """(A) z = x^2 + y^2 over a 41x41 grid built in .control."""
    NX = NY = 41
    N = NX * NY
    print("=== (A) analytic surface: z = x^2 + y^2 (pyplotcontour_demo.cir) ===")
    pytext, rowstr = run("pyplotcontour_demo.cir", "pyplotcontour")

    print("[A1] the -contour render path was taken")
    check("pyplotcontour.py uses tricontourf, not plot/hist",
          "tricontourf(" in pytext and ".plot(" not in pytext and ".hist(" not in pytext)
    check("a colorbar is drawn and labelled z", "colorbar(" in pytext and "set_label('z')" in pytext)
    check("axes are labelled x and y",
          "set_xlabel('x')" in pytext and "set_ylabel('y')" in pytext)

    print("[A2] the data table has three columns (x, y, z), all N rows")
    ncol = len(rowstr[0]) if rowstr else 0
    check("data table has 3 columns per row", ncol == 3, f"{ncol} columns")
    check("data table has all N samples", len(rowstr) == N, f"{len(rowstr)} rows, want {N}")
    if ncol != 3 or len(rowstr) != N:
        return
    rows = [(float(r[0]), float(r[1]), float(r[2])) for r in rowstr]
    x = [r[0] for r in rows]; y = [r[1] for r in rows]; z = [r[2] for r in rows]

    print("[A3] the column mapping is correct: z == x^2 + y^2")
    maxerr = max(abs(z[k] - (x[k] ** 2 + y[k] ** 2)) for k in range(N))
    check("z reconstructs x^2 + y^2 from the .data", maxerr < 1e-9, f"max err {maxerr:.1e}")

    print("[A4] the sweep is genuinely 2-D (a paraboloid, not a line)")
    check("x and y each span a real range", (max(x) - min(x)) > 3.5 and (max(y) - min(y)) > 3.5,
          f"x span {max(x)-min(x):.2f}, y span {max(y)-min(y):.2f}")
    kc = min(range(N), key=lambda k: x[k] ** 2 + y[k] ** 2)
    check("z ~0 at centre, ~8 at corner (paraboloid)",
          z[kc] < 0.05 and max(z) > 7.5, f"z_centre {z[kc]:.3f}, z_max {max(z):.3f}")

    print("[A5] a valid PNG was rendered")
    ok, sz = valid_png("pyplotcontour")
    check("pyplotcontour.png is a valid, non-trivial PNG", ok, f"{sz} bytes")


def demo_bridge():
    """(B) a real nested .dc sweep: diode-OR bridge output over its two inputs."""
    N = 51 * 51
    print("\n=== (B) real nested .dc sweep: diode-OR bridge (bridge_dc_demo.cir) ===")
    pytext, rowstr = run("bridge_dc_demo.cir", "bridge")

    print("[B1] the -contour path was taken with the requested knobs")
    check("bridge.py uses tricontourf with cmap=turbo",
          "tricontourf(" in pytext and "cmap='turbo'" in pytext)
    check("colorbar labelled v(c), axes v(a)/v(b)",
          "set_label('v(c)')" in pytext
          and "set_xlabel('v(a)')" in pytext and "set_ylabel('v(b)')" in pytext)
    check("contour lines overlaid (pyplot_contour_lines)", "tricontour(" in pytext)

    print("[B2] the nested .dc produced the flattened 3-column grid")
    ncol = len(rowstr[0]) if rowstr else 0
    check("data table has 3 columns (v(a), v(b), v(c))", ncol == 3, f"{ncol} columns")
    check("data table has all 51x51 samples", len(rowstr) == N, f"{len(rowstr)} rows, want {N}")
    if ncol != 3 or len(rowstr) != N:
        return
    rows = [(float(r[0]), float(r[1]), float(r[2])) for r in rowstr]
    va = [r[0] for r in rows]; vb = [r[1] for r in rows]

    print("[B3] the axes are the two real swept sources")
    check("v(a) and v(b) each span [-1, 1]",
          abs(min(va) + 1) < 1e-6 and abs(max(va) - 1) < 1e-6
          and abs(min(vb) + 1) < 1e-6 and abs(max(vb) - 1) < 1e-6,
          f"v(a) [{min(va):.2f},{max(va):.2f}]  v(b) [{min(vb):.2f},{max(vb):.2f}]")

    print("[B4] the output is the diode-OR (max-like) surface -- columns map right")
    z_ll = rows[nearest(rows, -1, -1)][2]   # both inputs low  -> both diodes off -> ~0
    z_hh = rows[nearest(rows,  1,  1)][2]   # both inputs high -> maximum output
    z_hl = rows[nearest(rows,  1, -1)][2]   # only v(a) high
    z_lh = rows[nearest(rows, -1,  1)][2]   # only v(b) high
    check("output ~0 when both inputs low", z_ll < 0.01, f"z(-1,-1)={z_ll:.3f}")
    check("output rises when EITHER input is high (v(a) or v(b))",
          z_hl > 0.3 and z_lh > 0.3, f"z(1,-1)={z_hl:.3f}, z(-1,1)={z_lh:.3f}")
    check("both-high corner is the maximum", z_hh >= max(z_hl, z_lh) - 1e-6,
          f"z(1,1)={z_hh:.3f}")

    print("[B5] a valid PNG was rendered")
    ok, sz = valid_png("bridge")
    check("bridge.png is a valid, non-trivial PNG", ok, f"{sz} bytes")


def main():
    demo_analytic()
    demo_bridge()
    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
