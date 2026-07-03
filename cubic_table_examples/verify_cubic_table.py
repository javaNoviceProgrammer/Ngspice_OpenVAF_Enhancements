#!/usr/bin/env python3
"""
verify_cubic_table.py -- verifies Enhancement-22 natural CUBIC SPLINE
interpolation in $table_model (control code "3"), end-to-end through version11's
own openvaf-r + ngspice.

`cubic_demo.va` samples sin(V) on a coarse grid and interpolates it both cubically
and linearly, plus a straight-line table and a 2-D sin(x)cos(y) surface. The
checks prove the point of splines over the existing piecewise-linear interpolation:

  1. accuracy   -- cubic tracks sin(V) far better than linear at off-grid points;
  2. smoothness -- the derivative gm = dI/dV is C1: cubic gm is *continuous*
                   across a grid node (and matches cos(V)), while linear gm jumps;
  3. exactness  -- a natural cubic spline reproduces straight-line data exactly;
  4. N-D        -- 2-D tensor-product cubic reproduces sin(x)cos(y) accurately;

all lowered to differentiable MIR (the AC gm is the autodiff Jacobian).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE

OSDI = os.path.join(HERE, "cubic_demo.osdi")


def write_surf_grid():
    """Self-describing 2-D grid file for f(x,y) = sin(x)*cos(y)."""
    xs = [round(0.5 * i, 1) for i in range(7)]   # 0 .. 3.0
    ys = [round(0.5 * i, 1) for i in range(7)]
    with open(os.path.join(HERE, "surf.grid"), "w") as f:
        f.write("2\n")
        f.write(f"{len(xs)} {len(ys)}\n")
        f.write(" ".join(f"{x:g}" for x in xs) + "\n")
        f.write(" ".join(f"{y:g}" for y in ys) + "\n")
        for x in xs:
            f.write(" ".join(f"{math.sin(x) * math.cos(y):.6f}" for y in ys) + "\n")


def last_val(fname):
    with open(os.path.join(HERE, fname)) as fh:
        return float(fh.read().split()[-1])


def dc_I(model_line, inst_model, node_lines, source, sweep):
    deck = (
        f"* cubic dc\n{node_lines}\n{model_line}\n"
        f".control\npre_osdi cubic_demo.osdi\ndc {source} {sweep}\n"
        f"wrdata _o.txt i({source})\n.endc\n.end\n"
    )
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    rows = [l.split() for l in open(os.path.join(HERE, "_o.txt")) if l.strip()]
    return [(float(r[0]), -float(r[1])) for r in rows]   # (Vbias, device current)


def ac_gm(model_type, vbias):
    deck = (
        f"* cubic gm\nva a 0 dc {vbias} ac 1\nn1 a 0 dm\n.model dm {model_type}\n"
        f".control\npre_osdi cubic_demo.osdi\nac lin 1 1 1\n"
        f"wrdata _o.txt mag(i(va))\n.endc\n.end\n"
    )
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return last_val("_o.txt")


def main():
    write_surf_grid()
    subprocess.run([OPENVAF, "cubic_demo.va", "-o", OSDI], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    # 1. accuracy: sweep off-grid midpoints, compare max error to sin(V).
    cub = dc_I(".model dm sin_cubic", "dm", "va a 0 dc 0\nn1 a 0 dm", "va", "0.2 3.0 0.4")
    lin = dc_I(".model dm sin_linear", "dm", "va a 0 dc 0\nn1 a 0 dm", "va", "0.2 3.0 0.4")
    ec = max(abs(i - math.sin(v)) for v, i in cub)
    el = max(abs(i - math.sin(v)) for v, i in lin)
    print("\n[1] accuracy vs sin(V) at off-grid midpoints")
    check("cubic much more accurate than linear",
          ec < el / 5 and ec < 5e-3, f"max err cubic={ec:.2e}  linear={el:.2e}  ({el/ec:.0f}x)")

    # 2. smoothness: gm just below/above the grid node V=0.8 (cos(0.8)=0.6967).
    # The cubic derivative is C1 -- it varies only by the true curvature across the
    # node -- while the linear derivative jumps by the full segment-slope difference.
    print("\n[2] derivative continuity across grid node V=0.8  (cos(0.8) = %.4f)" % math.cos(0.8))
    gcl, gcr = ac_gm("sin_cubic", 0.78), ac_gm("sin_cubic", 0.82)
    gll, glr = ac_gm("sin_linear", 0.78), ac_gm("sin_linear", 0.82)
    cub_jump, lin_jump = abs(gcl - gcr), abs(gll - glr)
    check("cubic gm ~ |cos(V)| on both sides",
          abs(gcl - abs(math.cos(0.78))) < 0.02 and abs(gcr - abs(math.cos(0.82))) < 0.02,
          f"gm(0.78)={gcl:.4f}~{abs(math.cos(0.78)):.4f}  gm(0.82)={gcr:.4f}~{abs(math.cos(0.82)):.4f}")
    check("linear gm JUMPS at the node, cubic stays smooth",
          lin_jump > 0.1 and lin_jump > 5 * cub_jump,
          f"linear jump={lin_jump:.3f}  cubic change={cub_jump:.3f}  ({lin_jump/max(cub_jump,1e-9):.0f}x)")

    # 3. exactness: natural spline reproduces the line y = 2x+1 exactly.
    print("\n[3] natural spline reproduces straight-line data exactly")
    line = dc_I(".model dm line_cubic", "dm", "va a 0 dc 0\nn1 a 0 dm", "va", "0.3 2.7 0.6")
    le = max(abs(i - (2 * v + 1)) for v, i in line)
    check("cubic(line) == line", le < 1e-9, f"max |I - (2V+1)| = {le:.2e}")

    # 4. 2-D tensor-product cubic reproduces sin(x)*cos(y).
    print("\n[4] 2-D tensor-product cubic  f(x,y)=sin(x)cos(y)")
    err2d = 0.0
    for x, y in [(0.75, 1.25), (1.25, 0.75), (2.25, 2.25)]:
        deck = (
            f"* surf\nvp p 0 dc {x}\nvn n 0 dc {y}\nn1 p n sm\n.model sm surf_cubic\n"
            f".control\npre_osdi cubic_demo.osdi\nop\nwrdata _o.txt i(vp)\n.endc\n.end\n"
        )
        with open(os.path.join(HERE, "_o.cir"), "w") as fh:
            fh.write(deck)
        subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
        got = -last_val("_o.txt")
        err2d = max(err2d, abs(got - math.sin(x) * math.cos(y)))
    check("2-D cubic accurate", err2d < 5e-3, f"max err = {err2d:.2e}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
