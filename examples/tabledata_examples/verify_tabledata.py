#!/usr/bin/env python3
"""Enhancement-425: three things a compiler accepted that are not numbers.

[1] A CORRUPT ROW IN A `$table_model` DATA FILE WAS SILENTLY DROPPED.

    Table (0,0) (1,100) (2,20), queried at x = 0.5, gives 50. Replace the middle
    row with `N/A N/A`, `abc def` or `--- ---` and it compiles clean and gives 5 --
    a TENFOLD wrong answer, because the row simply vanishes.

    Root cause: `table_file_is_usable` and the readers in `hir_lower` both did
    `filter_map(|tok| tok.parse::<f64>().ok())` -- non-numeric tokens silently
    skipped -- and the ONLY shape check was global token-count PARITY,
    `nums.len() % 2 == 0`. Detection was therefore luck: dropping TWO tokens keeps
    the count even and passes, dropping ONE makes it odd and is caught. The
    source's own E-396 comment states the premise that is false -- "A non-numeric
    token such as `abc` was already rejected" -- it was not, except by accident.

[2] THE N-DIMENSIONAL FORM WAS STRICTLY WORSE, AND WAS NOT IN THE ORIGINAL REPORT.

    Corrupting ONE token in a real 2-D grid file (examples/mdtable_examples/
    mos_iv.tbl) leaves 50 numbers -- even, so the parity rule accepted it --
    `read_table_grid_nd` then returns None and `lower_table_model` does
    `return F_ZERO`. The WHOLE TABLE contributes exactly zero.
    Measured: drain current -3.2e-04 -> 0.000000e+00, compile clean.
    Adding a surplus token instead restores the count and silently SHIFTS the grid,
    because the reader consumes the stream positionally and ignores leftovers.

    WHY THE FIX NEEDED `ndim` FROM THE CALL. The two forms have different grammars
    and CANNOT be told apart by looking at the file: `2 3 / 4 5 / 6 7` is a
    perfectly good 1-D table whose leading numbers also read as a 2-dimensional
    header. The old code guessed (`let d = nums[0]`), which false-positives on real
    1-D data. `ndim` is now carried in the diagnostic, computed at the validator's
    push site exactly as `lower_table_model` computes it -- the number of input
    arguments before the data argument.

    A PER-LINE RULE FOR EVERYTHING WOULD HAVE BEEN WRONG. The 1-D form is strictly
    one pair per line (`read_noise_table_file` reads `it.next(), it.next()` and
    discards the rest of the line), but the N-D form is free-form whitespace across
    lines -- grid4.tbl puts its entire 36-value tensor on ONE line. Applying the
    line rule to N-D would have rejected mos_iv.tbl, grid4.tbl and grid5.tbl, all of
    which back live example suites. So: line rule for ndim == 1 (and for every
    `noise_table` file, which is always 1-D), exact-shape token rule for ndim >= 2.

[3] A REAL LITERAL THAT OVERFLOWS TO INFINITY WAS SILENTLY ACCEPTED.

    `r = 1e309;` compiled clean and the model returned INF. `f64::from_str` does
    not fail on an overflowing exponent -- it returns an infinity -- and
    `StdRealNumber::value` is `src.parse().unwrap()`, so the `.unwrap()` never
    fires. This compiler had ALREADY decided twice that this is a mistake worth
    reporting: E-396 refuses `1e400` in a data file (its comment names this exact
    `from_str` behaviour) and E-422 refuses `abstol = 1e400`.

    ONLY the literal. `1e308*10.0` is also an infinity, but that is ARITHMETIC
    overflow -- a runtime property of the expression, not a mis-written constant --
    and E-396 drew exactly that line. Underflow is left alone too: `1e-320` is a
    legitimate subnormal and `1e-400` is 0.0, both defined by IEEE 754.

[4] A BASED LITERAL WITH A ZERO SIZE WAS ACCEPTED AND EVALUATED TO NONSENSE.

    IEEE 1364-2005 3.5.1: the size "shall be a non-zero unsigned decimal number".
    `parse_based_int_masked` ends in `.clamp(1, 32)`, so a zero size silently became
    ONE BIT: `0'd5` evaluated to 1 (5 masked to a single bit), `0'h1` to 1.

    The upper half of that clamp is deliberately LEFT ALONE. Enhancement-46
    documents "clamped 1..=32 ... wrap to the 32-bit `integer` type" as the intended
    semantics, and truncating a wider literal is the LRM assignment rule -- `4'hFF`
    is 15 and `32'hFFFFFFFF` is -1, both correct.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n'
EX = os.path.dirname(HERE)


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(files, src, tag):
    d = os.path.join(HERE, "_td_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    for name, body in files.items():
        open(os.path.join(d, name), "w").write(body)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def crashed(rc, out):
    return rc < 0 or "has crashed" in out or "openvaf-crash" in out or "panicked" in out


def opvar(d, name="r", nodes="a 0", model="dut"):
    open(os.path.join(d, "q.cir"), "w").write(
        f"* q\nV1 a 0 dc 1\nN1 {nodes} {model}\n.model {model} {model}()\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=16\nop\n"
        f"echo {name} = $&@n1[{name}]\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 40; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    m = re.search(r"^%s = (\S+)" % name, r.stdout + r.stderr, re.M)
    return float(m.group(1)) if m else None


# a 1-D table whose MIDDLE ROW MATTERS: at x=0.5 the full table gives 50 and a
# table missing the middle row gives 5. A probe value that cannot tell those apart
# proves nothing -- the first attempt at this used (0,0)(1,10)(2,20) at x=1.5,
# where both answers are 15.
T1 = "0.0 0.0\n1.0 100.0\n2.0 20.0\n"
VA1 = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
       ' (*desc="r"*) real r;\n analog begin\n  r = $table_model(0.5, "t.tbl", "1L");\n'
       "  I(p, n) <+ 1e-3*V(p, n);\n end\nendmodule\n")


def rejected(label, files, src, tag):
    _, rc, out = build(files, src, tag)
    ok = rc != 0 and not crashed(rc, out)
    check(label, ok, f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:70])


def clean(label, files, src, tag, want=None):
    d, rc, out = build(files, src, tag)
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    if rc != 0 or noisy:
        check(label, False, f"rc={rc} " + (noisy or [""])[0][:66]); return
    if want is None:
        check(label, True); return
    got = opvar(d)
    check(label, got is not None and abs(got - want) < 1e-9, f"r={got}, want {want}")


def main():
    # =====================================================================
    print("\n[1] a 1-D data file: a corrupt row, measured as a NUMBER")
    clean("the clean table gives 50 at x=0.5 (the reference)", {"t.tbl": T1}, VA1, "ref", 50.0)
    for tag, row, note in [
        ("na",   "N/A N/A",   "a missing-data marker on both columns"),
        ("abc",  "abc def",   "two garbage tokens"),
        ("dash", "--- ---",   "another marker"),
        ("one",  "abc",       "one garbage token"),
        ("half", "1.0 oops",  "a good abscissa and a garbage value"),
    ]:
        rejected(f"{note} is rejected (it used to give 5)",
                 {"t.tbl": T1.replace("1.0 100.0", row)}, VA1, "c_" + tag)
    rejected("a surplus third column is rejected (the reader drops it)",
             {"t.tbl": T1.replace("1.0 100.0", "1.0 100.0 99")}, VA1, "c_col")
    rejected("a row with a missing column",
             {"t.tbl": T1.replace("1.0 100.0", "1.0")}, VA1, "c_short")
    rejected("two pairs on one line (the reader keeps only the first)",
             {"t.tbl": "0.0 0.0\n1.0 100.0 2.0 20.0\n"}, VA1, "c_two")
    rejected("an overflowing value, as E-396 requires",
             {"t.tbl": T1.replace("1.0 100.0", "1.0 1e400")}, VA1, "c_inf")
    rejected("a NaN value", {"t.tbl": T1.replace("1.0 100.0", "1.0 nan")}, VA1, "c_nan")

    print("\n[1b] and everything legitimate about a 1-D file still works")
    clean("whole-line # comments", {"t.tbl": "# header\n" + T1}, VA1, "k_hash", 50.0)
    clean("// and * comment lines", {"t.tbl": "// a\n* b\n" + T1}, VA1, "k_cmt", 50.0)
    clean("blank lines", {"t.tbl": "\n" + T1 + "\n\n"}, VA1, "k_blank", 50.0)
    clean("tab separators", {"t.tbl": T1.replace(" ", "\t")}, VA1, "k_tab", 50.0)
    clean("CRLF line endings", {"t.tbl": T1.replace("\n", "\r\n")}, VA1, "k_crlf", 50.0)
    clean("leading and trailing whitespace",
          {"t.tbl": "".join("   %s   \n" % l for l in T1.strip().split("\n"))}, VA1, "k_ws", 50.0)
    # the real shipped files
    for name, path in [("diode_iv.tbl", "table_model_examples/diode_iv.tbl"),
                       ("elab_noise.tbl", "elabguard_examples/elab_noise.tbl")]:
        body = open(os.path.join(EX, path)).read()
        va = VA1.replace("t.tbl", name)
        clean(f"the shipped {name} still compiles", {name: body}, va, "k_" + name.split(".")[0])

    print("\n[1c] a noise_table data file is the same grammar")
    NV = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
          " analog begin\n  I(p, n) <+ 1e-3*V(p, n);\n"
          '  I(p, n) <+ noise_table("nt.txt");\n end\nendmodule\n')
    NT = "1 1e-12\n100 1e-12\n10000 1e-16\n"
    clean("a clean noise file", {"nt.txt": NT}, NV, "n_ok")
    rejected("a corrupt row in a noise file",
             {"nt.txt": NT.replace("100 1e-12", "N/A N/A")}, NV, "n_bad")
    rejected("a surplus column in a noise file",
             {"nt.txt": NT.replace("100 1e-12", "100 1e-12 9")}, NV, "n_col")
    body = open(os.path.join(EX, "noise_examples/noise_table.txt")).read()
    clean("the shipped noise_table.txt still compiles",
          {"nt.txt": body}, NV, "n_ship")

    # =====================================================================
    print("\n[2] the N-dimensional form -- the case that gave EXACTLY ZERO")
    ND = open(os.path.join(EX, "mdtable_examples/mos_iv.tbl")).read()
    VAND = (HDR + "module dut(g, d, s);\n inout g, d, s; electrical g, d, s;\n"
            ' analog I(d, s) <+ $table_model(V(g,s), V(d,s), "mos_iv.tbl", "1L,1L");\nendmodule\n')
    clean("the shipped 2-D mos_iv.tbl still compiles", {"mos_iv.tbl": ND}, VAND, "d_ok")
    rejected("one corrupted token (it used to contribute EXACTLY 0.0)",
             {"mos_iv.tbl": ND.replace("0.000000e+00", "N/A", 1)}, VAND, "d_corrupt")
    rejected("one SURPLUS token (it used to shift the grid silently)",
             {"mos_iv.tbl": ND.rstrip() + " 0.0\n"}, VAND, "d_extra")
    rejected("a truncated file", {"mos_iv.tbl": "\n".join(ND.split("\n")[:-2]) + "\n"},
             VAND, "d_trunc")
    rejected("a header that disagrees with the call's dimensionality",
             {"mos_iv.tbl": ND.replace("\n2\n", "\n3\n", 1)}, VAND, "d_ndim")
    # the other shipped grids, at their own dimensionalities
    for name, path, ndim in [("grid4.tbl", "ndtable_examples/grid4.tbl", 4),
                             ("grid5.tbl", "ndtable_examples/grid5.tbl", 5)]:
        body = open(os.path.join(EX, path)).read()
        args = ", ".join(["0.5"] * ndim)
        ctrl = ",".join(["1L"] * ndim)
        va = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
              f' analog I(p, n) <+ $table_model({args}, "{name}", "{ctrl}");\nendmodule\n')
        clean(f"the shipped {ndim}-D {name} still compiles", {name: body}, va,
              "d_" + name.split(".")[0])

    print("\n[2b] the 1-D file that LOOKS N-dimensional must stay accepted")
    # `2 3 / 4 5 / 6 7`: leading numbers read as ndim=2, sizes=[3,4] -- which is why
    # the dimensionality has to come from the CALL and not from the file.
    clean("a 1-D table whose first numbers look like an N-D header",
          {"t.tbl": "2 3\n4 5\n6 7\n"},
          VA1.replace("0.5", "3.0"), "d_lookalike")

    # =====================================================================
    print("\n[3] a real literal that overflows to infinity")
    def lit(expr, ty="real"):
        return (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
                f' (*desc="r"*) {ty} r;\n analog begin\n  r = {expr};\n'
                "  I(p, n) <+ 1e-3*V(p, n);\n end\nendmodule\n")
    for e in ("1e309", "1e400", "-1e309", "2e308", "1e1000"):
        rejected(f"`{e}` is rejected", {}, lit(e), "o_" + re.sub(r"\W", "", e))
    for e, want in [("1e308", 1e308), ("1.7e308", 1.7e308), ("1e307", 1e307),
                    ("1.0", 1.0), ("0.0", 0.0), ("-1e308", -1e308)]:
        clean(f"`{e}` is accepted and correct", {}, lit(e), "ok_" + re.sub(r"\W", "", e), want)
    clean("ARITHMETIC overflow stays out of scope (`1e308*10.0`)", {}, lit("1e308*10.0"), "o_arith")
    clean("a subnormal `1e-320` is left alone", {}, lit("1e-320"), "o_sub")
    clean("underflow `1e-400` is left alone", {}, lit("1e-400"), "o_under")
    clean("`inf` as a range bound is untouched", {},
          (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
           " parameter real g = 1e-3 from [0:inf);\n"
           " analog I(p, n) <+ g*V(p, n);\nendmodule\n"), "o_inf")

    # =====================================================================
    print("\n[4] a based literal with a zero size")
    for e in ("0'h1", "0'b0", "0'd5", "00'h1", "0'sb1", "0'o7"):
        rejected(f"`{e}` is rejected", {}, lit(e, "integer"), "z_" + re.sub(r"\W", "", e))
    for e, want in [("1'h1", 1), ("4'hF", 15), ("32'hFFFFFFFF", -1), ("'hFF", 255),
                    ("3'sb101", -3), ("8'hF_F", 255), ("4'b1010", 10)]:
        clean(f"`{e}` is accepted and correct", {}, lit(e, "integer"),
              "zk_" + re.sub(r"\W", "", e), want)
    clean("a size ABOVE 32 still truncates, as E-46 documents", {},
          lit("100'h1", "integer"), "z_big", 1.0)

    for j in os.listdir(HERE):
        if j.startswith("_td_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
