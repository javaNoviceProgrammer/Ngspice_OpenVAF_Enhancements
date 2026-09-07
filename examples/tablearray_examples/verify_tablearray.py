#!/usr/bin/env python3
"""
verify_tablearray.py -- `$table_model` fed from arrays, assigned to variables and
called inside analog functions, end-to-end through the committed openvaf-r + ngspice
(the probes of 2026-09-07 that answered "can the table feature interpolate an
array of data?"):

  1. the data-source forms on the same y = x^2 grid: array variables filled in the
     analog block from a model parameter (E-389; linear "1L" and the natural cubic
     spline "3L"), parameter arrays handed over as they are, an inline pair of
     array literals, and the LRM 9.21.1 column-array form of a 2-D table from
     `localparam` arrays (E-562)
  2. what happens past the grid and when the data changes: "L" extrapolates the
     linear table along its end segment; a table built from a model parameter is
     rebuilt when `altermod` changes the parameter
  3. the result assigned to a variable: the value is read back as an operating-point
     variable, and the slope survives the assignment into the AC conductance
  4. inside an analog function: literal arrays, a data file, arrays passed in as
     function arguments (E-18), and arrays filled locally in the function body --
     value and AC slope each
  5. the refusal the N-D array form gives to an overridable `parameter` array

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

MODELS = ("rt_lin", "rt_cub", "par_arr", "lit_pair", "col2d",
          "var_lit", "fn_lit", "fn_file", "fn_arg", "fn_loc")

# the natural cubic spline through (0,0) (1,1) (2,4) (3,9): value at 1.5 and its
# slope there (the spline is symmetric about the middle knot, so the slope is the
# chord slope 3 exactly), and the value at 3.5 from the end tangent ("L")
SPLINE_1P5 = 2.2
SPLINE_SLOPE_1P5 = 3.0


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


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def values(out, names):
    vals = {}
    for line in out.splitlines():
        s = line.strip()
        for n in names:
            if s.lower().startswith(n.lower() + " "):
                try:
                    vals[n] = float(s.split("=", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
    return vals


def run(osdis, lines, control, prints):
    deck = ("* tablearray\n" + "\n".join(lines) + "\n.control\n"
            + "".join(f"pre_osdi {o}.osdi\n" for o in osdis)
            + "set numdgt=10\n" + control + "\n.endc\n.end\n")
    out = ngspice(deck)
    return values(out, prints), out


def near(v, want, tol=1e-9):
    return v is not None and abs(v - want) <= tol


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[0] the models compile")
    for m in MODELS:
        built, log = compile_va(f"{m}.va", f"{m}.osdi")
        check(f"openvaf-r {m}.va", built, "" if built else log.strip().splitlines()[0])
    if not ok:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[1] the data-source forms on y = x^2, queried at x = 1.5")
    v, out = run(("rt_lin", "rt_cub", "par_arr", "lit_pair", "col2d"),
                 ["v1 in 0 1.5", "v2 in2 0 1.5", "vc c 0 1.5",
                  "n1 in 0 m_lin", "n2 in 0 m_cub", "n3 in 0 m_par", "n4 in 0 m_lit", "n5 in2 0 c m_2d",
                  ".model m_lin rt_lin scale=1", ".model m_cub rt_cub scale=1", ".model m_par par_arr",
                  ".model m_lit lit_pair", ".model m_2d col2d"],
                 "op\nprint @n1[i] @n2[i] @n3[i] @n4[i]\nlet i5 = -v2#branch\nprint i5",
                 ["@n1[i]", "@n2[i]", "@n3[i]", "@n4[i]", "i5"])
    check("array variables filled in the analog block, \"1L\": linear between (1,1) and (2,4) -> 2.5e-3",
          near(v.get("@n1[i]"), 2.5e-3), f"{v.get('@n1[i]')}")
    check("the same arrays, \"3L\": the natural cubic spline -> 2.2e-3",
          near(v.get("@n2[i]"), SPLINE_1P5 * 1e-3), f"{v.get('@n2[i]')}")
    check("parameter arrays handed over as they are -> 2.5e-3",
          near(v.get("@n3[i]"), 2.5e-3), f"{v.get('@n3[i]')}")
    check("an inline pair of array literals '{xs}, '{ys} -> 2.5e-3",
          near(v.get("@n4[i]"), 2.5e-3), f"{v.get('@n4[i]')}")
    check("2-D column arrays (localparam), z = x*y at (1.5, 1.5): bilinear is exact -> 2.25e-3",
          near(v.get("i5"), 2.25e-3), f"{v.get('i5')}")

    print("[2] past the grid, and when the parameter behind the table changes")
    v, out = run(("rt_lin", "rt_cub"),
                 ["v1 in 0 3.5", "n1 in 0 m_lin", "n2 in 0 m_cub",
                  ".model m_lin rt_lin scale=1", ".model m_cub rt_cub scale=1"],
                 "op\nlet ilin = @n1[i]\nprint ilin\nlet icub1 = @n2[i]\nprint icub1\naltermod m_cub scale=2\nop\nlet icub2 = @n2[i]\nprint icub2",
                 ["ilin", "icub1", "icub2"])
    check("\"L\" at x = 3.5: the linear table continues its end segment, 9 + 5*0.5 -> 11.5e-3",
          near(v.get("ilin"), 11.5e-3), f"{v.get('ilin')}")
    check("altermod scale=2: the runtime table is rebuilt from the new parameter, the current doubles",
          v.get("icub1") is not None and v.get("icub2") is not None and v["icub1"] > 9e-3
          and near(v["icub2"], 2 * v["icub1"], 1e-12), f"{v.get('icub1')} -> {v.get('icub2')}")

    print("[3] the result assigned to a variable")
    v, out = run(("var_lit",),
                 ["v1 in 0 dc 1.5 ac 1", "n1 in 0 m", ".model m var_lit"],
                 "op\nlet y = @n1[y]\nprint y\nlet i = @n1[i]\nprint i\nac lin 1 1k 1k\nlet g = -real(v1#branch)\nprint g",
                 ["y", "i", "g"])
    check("`y = $table_model(...)` is read back as the operating-point variable y = 2.5",
          near(v.get("y"), 2.5), f"{v.get('y')}")
    check("I = 1e-3*y + 1e-6*y2 (a second, cubic, runtime-array table) -> 2.5e-3 + 2.2e-6",
          near(v.get("i"), 2.5e-3 + SPLINE_1P5 * 1e-6), f"{v.get('i')}")
    check("the slope survives the assignment: AC conductance 3e-3 + 3e-6",
          near(v.get("g"), 3e-3 + SPLINE_SLOPE_1P5 * 1e-6, 1e-12), f"{v.get('g')}")

    print("[4] inside an analog function")
    v, out = run(("fn_lit", "fn_file", "fn_arg", "fn_loc"),
                 ["v1 a 0 dc 1.5 ac 1", "v2 b 0 dc 1.5 ac 1", "v3 c 0 dc 1.5 ac 1", "v4 d 0 dc 1.5 ac 1",
                  "n1 a 0 m1", "n2 b 0 m2", "n3 c 0 m3", "n4 d 0 m4",
                  ".model m1 fn_lit", ".model m2 fn_file", ".model m3 fn_arg scale=1", ".model m4 fn_loc"],
                 "op\nlet i1 = @n1[i]\nlet i2 = @n2[i]\nlet i3 = @n3[i]\nlet i4 = @n4[i]\nprint i1 i2 i3 i4\n"
                 "ac lin 1 1k 1k\nlet g1 = -real(v1#branch)\nlet g2 = -real(v2#branch)\n"
                 "let g3 = -real(v3#branch)\nlet g4 = -real(v4#branch)\nprint g1 g2 g3 g4",
                 ["i1", "i2", "i3", "i4", "g1", "g2", "g3", "g4"])
    for i, (what, want_i, want_g) in enumerate((
            ("literal arrays inside the function", 2.5e-3, 3e-3),
            ("a data file inside the function", 2.5e-3, 3e-3),
            ("arrays passed in as function arguments", 2.5e-3, 3e-3),
            ("arrays filled locally in the function, \"3L\"", SPLINE_1P5 * 1e-3, SPLINE_SLOPE_1P5 * 1e-3)), 1):
        check(f"{what}: I(1.5) -> {want_i:g}", near(v.get(f"i{i}"), want_i), f"{v.get(f'i{i}')}")
        check(f"{what}: AC slope -> {want_g:g}", near(v.get(f"g{i}"), want_g, 1e-12), f"{v.get(f'g{i}')}")

    print("[5] the refusal")
    r, log = refused("col2d_param.va", "declare the array `localparam`")
    check("the N-D array form from an overridable `parameter` array is refused, naming `localparam`",
          r, "" if r else log.strip().splitlines()[0])

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
