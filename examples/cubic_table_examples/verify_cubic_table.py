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
  5. end conditions (Enhancement-704) -- LRM 9.21.4: a 'C' end pins the end
                   derivative to zero, so the value near the edge is the
                   clamped-end spline's and gm runs to zero into the constant
                   extension instead of jumping there; 'L' keeps the natural
                   spline;

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
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

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

    # 5. Enhancement-704 (hunt F3 of 2026-09-21): LRM 9.21.4's end conditions.
    # "If the user selects linear extrapolation this leads to a natural spline.
    # If constant extrapolation is specified the end point derivative is set to
    # zero thus avoiding a discontinuity in the first order derivative at that
    # end point." Every spline used to be the natural one, with the constant
    # extension bolted on outside the last knot, so gm jumped at the table edge.
    print("\n[5] LRM 9.21.4 end conditions: a 'C' end pins the end derivative to zero (E-704)")

    def at(model, x):
        pts = dc_I(f".model dm {model}", "dm", "va a 0 dc 0\nn1 a 0 dm", "va", f"{x} {x} 1")
        return pts[0][1] if pts else None

    def near(got, want, tol=1e-7):   # wrdata writes nine significant digits
        return got is not None and abs(got - want) <= tol * max(1.0, abs(want))

    # y = x^2 sampled at 0..4. The exact fractions come from the moment systems:
    # the natural spline gives 125/56 at 1.5; with both end derivatives zero
    # (2h0*M0 + h0*M1 = 6*s0 at the bottom, its mirror at the top) it is 131/56,
    # with the top end alone 1799/776 and the bottom alone 1751/776. A linear
    # end continues the tangent of the spline the OTHER end shaped.
    for model, x, want, note in [
            ("edge_cubic_l", 1.5, 125 / 56, "\"3L\": the natural spline, as before"),
            ("edge_cubic_c", 1.5, 131 / 56, "\"3C\": both end derivatives zero"),
            ("edge_cubic_lc", 1.5, 1799 / 776, "\"3LC\": the top end derivative zero"),
            ("edge_cubic_cl", 1.5, 1751 / 776, "\"3CL\": the bottom end derivative zero"),
            ("edge_cubic_cl", 5.0, 16 + 720 / 97, "\"3CL\" above the table continues the bottom-clamped spline's tangent (natural: 16 + 52/7)"),
            ("edge_cubic_lc", -1.0, -48 / 97, "\"3LC\" below the table continues the top-clamped spline's tangent (natural: -4/7)"),
            ("edge_cubic_c", 5.0, 16.0, "\"3C\" above the table holds the endpoint"),
            ("edge_line_c", 3.9, 5577 / 1400, "y = x under \"3C\" bends to meet the flat extension (the line gives 3.9)")]:
        got = at(model, x)
        check(f"{note}: {want:.9g} at x={x:g}", near(got, want), f"got {got}")
    # the derivative that feeds the Jacobian is continuous across a 'C' edge
    gcl, gcr = ac_gm("edge_cubic_c", 3.99), ac_gm("edge_cubic_c", 4.01)
    check("\"3C\": gm runs to 0 at the top edge and is 0 outside (it dropped from 7.43 to 0)",
          abs(gcl - 0.255385714) < 1e-6 and abs(gcr) < 1e-12, f"gm(3.99)={gcl:.6f} gm(4.01)={gcr:.6f}")
    gc0, gc0m = ac_gm("edge_cubic_c", 0.01), ac_gm("edge_cubic_c", -0.01)
    check("\"3C\": the same at the bottom edge",
          abs(gc0 - 0.017185714) < 1e-6 and abs(gc0m) < 1e-12, f"gm(0.01)={gc0:.6f} gm(-0.01)={gc0m:.6f}")
    gll, glr = ac_gm("edge_cubic_l", 3.99), ac_gm("edge_cubic_l", 4.01)
    check("\"3L\": gm continues the natural spline's tangent, 7.43 on both sides",
          abs(gll - 7.428442857) < 1e-6 and abs(glr - 52 / 7) < 1e-6, f"gm(3.99)={gll:.6f} gm(4.01)={glr:.6f}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
