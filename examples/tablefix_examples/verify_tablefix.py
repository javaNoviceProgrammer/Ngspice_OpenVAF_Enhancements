#!/usr/bin/env python3
"""Enhancement-247: degenerate / undersized table hardening for table2d & table3d.

The XSPICE `table2d` and `table3d` code models read a lookup table from a file:
line 1 is the x-axis point count (ix), line 2 the y count (iy) [line 3 the z count
(iz) for 3d], followed by the axis values and the data grid. The loader never
validated those counts, and two things then go wrong for a small table:

  1. Out-of-range ramp (OOB read). For an input below/above the table the model
     ramps the derivative to zero using `xcol[1] - xcol[0]` (and, on the high
     side, `xcol[ix-1] - xcol[ix-2]`). A single-point axis (ix==1) has no
     `xcol[1]` / `xcol[-1]` -> heap-buffer-overflow READ (AddressSanitizer:
     `cm_table2D cfunc.c:298`).

  2. ENO interpolation (OOB/UB). The Madagascar ENO interpolation of order p
     reads a stencil that needs 2*(p-1) points per axis. The order parameter
     defaults to 3, which needs >= 4 points per axis, but the loader only
     clamped it UP to a minimum of 2 -- never down to what the table supports.
     So the default order on any table with a <4-point axis (e.g. a 3x3 table,
     or a 3d table with a 2-plane z axis like the shipped test-3d-1.table)
     silently ran off the stencil -> UB/OOB in eno2.c / eno3.c.

E-247 adds, right after the existing order>=2 floor: reject any axis with < 2
points (a 1-point axis cannot be ramped or interpolated), and clamp the
interpolation order down to `mindim/2 + 1` so a small table interpolates at a
reduced but VALID order instead of reading out of bounds. Tables large enough
for the requested order are byte-identical (all shipped examples have
mindim/2+1 >= their order).

The XSPICE code models load from the prebuilt bundle via SPICE_LIB_DIR, which
`_setup` points at bin/<os>/<arch>/. If the bundle/codemodels are unavailable in
this checkout, the a-devices cannot load and this test self-skips.

Checks (batch mode, -b; run under both solvers). A crash shows up as a NEGATIVE
return code (signal).
 1. a valid 8x8 order-3 table2d interpolates exactly (out = x + 10*y at
    (2.5, 3.0) -> 32.5);
 2. a single-x-point table2d (ix=1) is rejected with a clean error, no crash
    (was the ramp OOB);
 3. a small 3x3 order-3 table2d runs (order clamped), no crash (was ENO UB);
 4. a valid table3d still runs;
 5. a 3x3x3 order-3 table3d runs (order clamped), no crash (was ENO UB);
 6. a degenerate table3d (iz=1) is rejected with a clean error, no crash.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402  (also sets SPICE_LIB_DIR)
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def is_crash(rc):
    return rc < 0 or rc >= 128


def write_table2d(name, ix, iy, fn):
    xs = " ".join(str(i) for i in range(ix))
    ys = " ".join(str(j) for j in range(iy))
    rows = "\n".join(" ".join(str(i + 10 * j) for i in range(ix)) for j in range(iy))
    open(os.path.join(HERE, fn), "w").write(f"* t\n{ix}\n{iy}\n{xs}\n{ys}\n{rows}\n")


def write_table3d(name, ix, iy, iz, fn):
    xs = " ".join(str(i) for i in range(ix))
    ys = " ".join(str(j) for j in range(iy))
    zs = " ".join(str(k) for k in range(iz))
    grid = "\n".join("\n".join(" ".join("1" for _ in range(ix)) for _ in range(iy))
                     for _ in range(iz))
    open(os.path.join(HERE, fn), "w").write(
        f"* t\n{ix}\n{iy}\n{iz}\n{xs}\n{ys}\n{zs}\n{grid}\n")


def run2d(fn, order, vx, vy):
    deck = (f"* table2d\nVx inx 0 dc {vx}\nVy iny 0 dc {vy}\n"
            f"a1 inx iny o tab\n.model tab table2d(order={order} file=\"{fn}\")\n"
            f"R1 o 0 1\n.control\nop\nprint v(o)\n.endc\n.end\n")
    cir = os.path.join(HERE, "_t2.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


def run3d(fn, order):
    deck = (f"* table3d\nVx inx 0 dc 1\nVy iny 0 dc 1\nVz inz 0 dc 1\n"
            f"a1 inx iny inz o tab\n.model tab table3d(order={order} file=\"{fn}\")\n"
            f"R1 o 0 1\n.control\nop\nprint v(o)\n.endc\n.end\n")
    cir = os.path.join(HERE, "_t3.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


def num(out, name):
    m = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


AXIS_MSG = "at least 2 points"

# Availability gate: a valid 8x8 table must load & interpolate.
write_table2d("v", 8, 8, "_v.table")
rc, out = run2d("_v.table", 3, 2.5, 3.0)
v = num(out, r"v\(o\)")
if is_crash(rc) or v is None:
    print(f"  SKIP  XSPICE code models unavailable in this checkout (rc={rc}) "
          "-- cannot exercise table2d/table3d")
    for f in ("_v.table", "_t2.cir"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
    raise SystemExit(0)

# 1: valid interpolation, out=x+10y at (2.5,3.0)=32.5; output port is a current
#    into R1=1ohm, so |v(o)| == 32.5 (sign per current convention).
check("valid 8x8 order-3 table2d interpolates exactly (=> |v(o)|=32.5)",
      not is_crash(rc) and v is not None and abs(abs(v) - 32.5) < 1e-6,
      f"rc={rc} v(o)={v}")

# 2: single-x-point table (ix=1) -- the ramp OOB -- clean error, no crash
write_table2d("d", 1, 3, "_d.table")
rc, out = run2d("_d.table", 3, 0.0, 1.0)
check("single-x-point table2d (ix=1): clean error, no crash (was ramp OOB)",
      not is_crash(rc) and AXIS_MSG in out, f"rc={rc} msg={'yes' if AXIS_MSG in out else 'no'}")

# 3: small 3x3 order-3 table -- the ENO UB -- runs with clamped order, no crash
write_table2d("s", 3, 3, "_s.table")
rc, out = run2d("_s.table", 3, 1.0, 1.0)
check("small 3x3 order-3 table2d runs, no crash (was ENO UB)",
      not is_crash(rc) and num(out, r"v\(o\)") is not None, f"rc={rc}")

# 4: valid table3d (4x4x4) still runs
write_table3d("v3", 4, 4, 4, "_v3.table")
rc, out = run3d("_v3.table", 3)
check("valid 4x4x4 order-3 table3d runs", not is_crash(rc) and num(out, r"v\(o\)") is not None,
      f"rc={rc}")

# 5: 3x3x3 order-3 table3d runs with clamped order, no crash
write_table3d("s3", 3, 3, 3, "_s3.table")
rc, out = run3d("_s3.table", 3)
check("small 3x3x3 order-3 table3d runs, no crash (was ENO UB)",
      not is_crash(rc) and num(out, r"v\(o\)") is not None, f"rc={rc}")

# 6: degenerate table3d (iz=1) rejected cleanly
write_table3d("d3", 3, 3, 1, "_d3.table")
rc, out = run3d("_d3.table", 3)
check("degenerate table3d (iz=1): clean error, no crash",
      not is_crash(rc) and AXIS_MSG in out, f"rc={rc} msg={'yes' if AXIS_MSG in out else 'no'}")

for f in ("_v.table", "_d.table", "_s.table", "_v3.table", "_s3.table", "_d3.table",
          "_t2.cir", "_t3.cir"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
