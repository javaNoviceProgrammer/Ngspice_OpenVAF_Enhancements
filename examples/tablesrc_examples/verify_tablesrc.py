#!/usr/bin/env python3
"""
verify_tablesrc.py -- the lookup-table features of the 2026-09-05 book audit
(Enhancement-562), end-to-end through the committed openvaf-r + ngspice:

  1. column ARRAYS as the data source (LRM 9.21.1), filled in `analog initial`
     -- the book's idiom -- reproduce f = 2x + y on ragged isolines exactly,
     inside the hull and under linear extrapolation
  2. one 2-D array (rows = columns of the table) gives the same values
  3. `localparam` arrays, a `localparam string` control string and a
     `localparam string` file name
  4. Table 9-30's 'I' ignores a tag column, in a data file and in the array form
  5. Table 9-30's '2', the quadratic spline, on inline data and on runtime
     arrays, against an independent Python evaluation of the same spline
     (z_0 = s_0, z_{i+1} = 2 s_i - z_i), with 'L' and 'C' ends
  6. the refusals: an overridable `parameter string` as control string or file
     name, an overridable `parameter` array, an array written at run time,
     'I' on runtime arrays, 'I' on inline `'{...}` data, a wrong array shape

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def compile_va(src, dst):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst)), \
        (r.stdout + r.stderr)


def refused(src, needle):
    r = subprocess.run([OPENVAF, os.path.join("refused", src)],
                       cwd=HERE, capture_output=True, text=True)
    log = r.stdout + r.stderr
    return r.returncode != 0 and needle in log, log


def op_current(osdi, model, params):
    deck = ("* tablesrc\nvin a 0 dc 1\nn1 a 0 dm\n"
            f".model dm {model}({params})\n"
            f".control\npre_osdi {osdi}\nop\nprint i(vin)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    for line in out.splitlines():
        if line.strip().lower().startswith("i(vin) "):
            return float(line.split("=", 1)[1])
    return None


def quad_spline(xs, vs, x, clamp):
    """The LRM 9.21.4 quadratic spline as the compiler builds it: knot slopes
    z_0 = s_0, z_{i+1} = 2 s_i - z_i; piece v_i + z_i dx + (z_{i+1}-z_i)/(2h) dx^2;
    the end tangents continue ('L') or the endpoints hold ('C')."""
    n = len(xs)
    s = [(vs[i + 1] - vs[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    z = [s[0]]
    for i in range(n - 1):
        z.append(2 * s[i] - z[i])
    if x < xs[0]:
        return vs[0] if clamp else vs[0] + z[0] * (x - xs[0])
    if x > xs[-1]:
        return vs[-1] if clamp else vs[-1] + z[-1] * (x - xs[-1])
    i = max(j for j in range(n - 1) if x >= xs[j])
    dx = x - xs[i]
    return vs[i] + z[i] * dx + (z[i + 1] - z[i]) / (2 * (xs[i + 1] - xs[i])) * dx * dx


POINTS = ((1.5, 0.25), (4.0, 0.75), (2.5, 0.5), (6.0, 1.5), (0.5, -0.5))
f2 = lambda x, y: 2 * x + y


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    models = ["tablesrc_cols", "tablesrc_matrix", "tablesrc_locparam", "tablesrc_ignore",
              "tablesrc_quad"]
    print("[0] the five models compile")
    for m in models:
        built, log = compile_va(f"{m}.va", f"{m}.osdi")
        check(f"openvaf-r {m}.va", built, "" if built else log.strip().splitlines()[0])
    if not ok:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[1] column arrays filled in `analog initial`: f = 2x + y, exact (ragged isolines)")
    for xx, yy in POINTS:
        i = op_current("tablesrc_cols.osdi", "tablesrc_cols", f"xx={xx} yy={yy}")
        exp = f2(xx, yy)
        check(f"f({xx},{yy}) == {exp:g}", i is not None and abs(i + 1e-3 * exp) < 1e-12,
              f"i = {i!r}")

    print("[2] one 2-D array, rows = table columns: the same values")
    for xx, yy in POINTS:
        i = op_current("tablesrc_matrix.osdi", "tablesrc_matrix", f"xx={xx} yy={yy}")
        exp = f2(xx, yy)
        check(f"f({xx},{yy}) == {exp:g}", i is not None and abs(i + 1e-3 * exp) < 1e-12,
              f"i = {i!r}")

    print("[3] localparam arrays + localparam string control and file name (summed twice)")
    for xx, yy in POINTS[:3]:
        i = op_current("tablesrc_locparam.osdi", "tablesrc_locparam", f"xx={xx} yy={yy}")
        exp = 2 * f2(xx, yy)
        check(f"2 f({xx},{yy}) == {exp:g}", i is not None and abs(i + 1e-3 * exp) < 1e-12,
              f"i = {i!r}")

    print("[4] 'I' ignores the tag column, in the file and in the array form (summed twice)")
    for xx, yy in POINTS[:3]:
        i = op_current("tablesrc_ignore.osdi", "tablesrc_ignore", f"xx={xx} yy={yy}")
        exp = 2 * f2(xx, yy)
        check(f"2 f({xx},{yy}) == {exp:g}", i is not None and abs(i + 1e-3 * exp) < 1e-12,
              f"i = {i!r}")

    print("[5] '2' quadratic spline on x^2 knots 0..3, inline and runtime, 'L' and 'C' ends")
    xs, vs = [0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 4.0, 9.0]
    for runtime in (0, 1):
        for ends in (0, 1):
            for xx in (0.5, 1.5, 2.25, -1.0, 4.0):
                i = op_current("tablesrc_quad.osdi", "tablesrc_quad",
                               f"xx={xx} ends={ends} runtime={runtime}")
                exp = quad_spline(xs, vs, xx, clamp=bool(ends))
                check(f"{'runtime' if runtime else 'inline '} '2{'C' if ends else 'L'}' "
                      f"q({xx}) == {exp:g}",
                      i is not None and abs(i + 1e-3 * exp) < 1e-9, f"i = {i!r}")

    print("[6] the refusals")
    for src, needle in (
        ("param_string_ctl.va", "control string must be a compile-time constant string"),
        ("param_string_file.va", "data file name must be a compile-time constant string"),
        ("param_array.va", "is an overridable `parameter`"),
        ("written_array.va", "is written at run time"),
        ("runtime_ignore.va", "not supported for runtime array data"),
        ("inline_ignore.va", "inline `'{...}` data has no column to ignore"),
        ("array_shape.va", "invalid array data source for $table_model"),
    ):
        r, log = refused(src, needle)
        check(f"refused/{src}: {needle}", r, "" if r else log.strip().splitlines()[0])

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
