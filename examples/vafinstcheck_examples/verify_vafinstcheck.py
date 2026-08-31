#!/usr/bin/env python3
"""Enhancement-392: nine defects from a one-hour openvaf-r hunt, plus two the
differential against the previous build turned up while verifying them.

  [1] MODULE INSTANTIATION WAS NOT VALIDATED AT ALL.

      The headline. A `module_a` instantiated inside `module_b` had its port
      connection list zipped POSITIONALLY against the target's declared ports,
      and its named connections bound without ever asking whether the named port
      exists. Nothing was checked, and nothing was reported:

        * the wrong PORT COUNT -- 0, 1, 2, 4 or 6 actuals on a three-port child.
          A surplus actual was dropped on the floor; a missing one left the port
          unconnected, so the device contributed nothing.
        * a port name that DOES NOT EXIST -- `kid c(.a(p), .b(n), .zz(p));`
        * a parameter that DOES NOT EXIST -- `kid #(.zz(4e-3)) c(p,n);`, where
          the intended override silently did nothing and the DEFAULT was used.

      All three compiled clean, with zero diagnostics, and produced a device
      wired or parameterised differently from what was written.

      Two sharp contrasts, both already inside this project: ngspice rejects the
      same mistake on a `.model` card ("unrecognized parameter (zz) - ignored"),
      and `defparam` rejects it too ("defparam target(s) did not resolve"). Only
      the instance port list and the `#(.param())` override were unchecked.

      Verilog-A creates IMPLICIT NETS, so a mistyped NET name can never be
      caught here -- it just becomes a new net. That is exactly why the things
      that CAN be checked, the arity and the port/parameter names, matter more
      rather than less.

  [2] `generate` DID NOT RENAME BLOCK LABELS OR FUNCTION NAMES.

      Elaboration suffixes everything declared in a generate block (`_0`, `_1`,
      ...) so iterations do not collide. `collect_declared_names` covered nets,
      variables, parameters, instances, branches and aliasparams -- but an
      `analog function` fell into its catch-all arm, and a named analog-block
      label is not a module item at all. Two iterations therefore redeclared the
      same name: `error: 'ab' was already declared in this scope`. Newly
      reachable because E-390 made `analog` legal inside `generate`.

  [3] THE RENAMING REWROTE THE NAME IN A NAMED CONNECTION. (Found by the corpus
      differential once [1] started reporting.) Substitution is lexical over the
      token stream, so a generate block holding

          resistor #(.r(1e3)) r(node[i], node[i+1]);

      -- an instance whose name collides with the child's parameter -- had its
      override rewritten to `.r_0(1e3)`, which named no parameter of `resistor`
      and was silently dropped back to the default. The name after the dot
      belongs to the INSTANTIATED module's namespace and must never be renamed.
      `examples/generate_examples/resistor_ladder_generate.va` was affected; it
      looked correct only because its override happened to equal the default.

  [4] A `$mfactor` OVERRIDE WAS ZIPPED ONTO THE FIRST PARAMETER. (Also from the
      differential.) A system-parameter override is written with a dot but
      carries no NAME child, because `$mfactor` is not an ordinary identifier.
      Keying "is this named?" off `name()` put it in the POSITIONAL branch, so
      `core #(.$mfactor(7)) C1(p,n)` set the target's first declared parameter
      to 7. The LRM's own page-263 example does exactly this, and got `r = 7`
      instead of its default of 1.0 -- a sevenfold wrong answer.

  [5] THE RUNTIME `$table_model` SORT SILENTLY GAVE UP ABOVE 64 KNOTS.

      E-390 taught the runtime array form to sort and de-duplicate so it would
      agree with the compile-time forms, using an unrolled compare-and-swap
      network capped at 64 points -- but the compile-time path sorts at ANY
      size, so above the cap the two diverged again with no diagnostic (65
      reversed knots: cubic gave 160.0 against 6.2566, 25x off). Worse,
      `compact_distinct_runtime` had NO cap, so de-duplication still ran on
      unsorted data. The network is now a Batcher odd-even merge sort, which is
      O(n log^2 n) comparators instead of O(n^2) and so reaches 256 points for
      less code than the old one used at 64; both halves share the cap, and
      exceeding it is a compile error rather than a silent divergence.

  [6] A `localparam` WAS REJECTED AS A GENERATE BOUND.

      "module parameters bind at simulation time under OSDI and cannot shape the
      generated structure" is right for `parameter` and wrong for `localparam`,
      which is fixed at elaboration -- and which the compiler already accepts as
      a constant in every other position: array bounds, bus widths, parameter
      defaults, `repeat` counts. Note this composes with E-92, which freezes any
      parameter that shapes a declaration width INTO a localparam: such a
      parameter is already a compile-time constant, so it may now size a
      generate too. A parameter that shapes nothing is still rejected.

  [7] INT_MIN DEVIATED FROM TWO'S-COMPLEMENT WRAPPING WHEN CONSTANT-FOLDED.

      `-2147483648` is the smallest `integer`, but it parses as unary minus
      applied to `2147483648`, whose magnitude does not fit i32. The operand
      became a REAL literal and the whole expression acquired real semantics:
      `(-2147483648)/3` rounded to -715827883 where integer division truncates
      toward zero to -715827882, and `(-2147483648)-1` saturated at INT_MIN
      instead of wrapping to INT_MAX. The same value arriving at runtime from a
      `.model` card stayed an integer and was right in every case -- so one
      expression had two meanings depending on whether it was folded.

      The one expression that must STILL be rejected is `(-2147483648)/(-1)`:
      it is the only integer operation that genuinely traps the CPU, and E-334
      diagnoses it. Making the literal work correctly is what first brings it
      within reach of that guard (see `vafintub_examples`).

WHAT THE ACCEPT HALF IS GUARDING. A validation pass that rejects too much is
worse than one that rejects nothing, because it breaks working models. The LRM
sanctions several ways of leaving a port unconnected -- a blank positional slot,
omitting the port from a by-name list, an empty `.port()` -- and every one of
them must still compile.
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
KID = ("module kid(a, b, c);\n inout a, b, c; electrical a, b, c;\n"
       " parameter real g = 1e-3;\n analog I(a, b) <+ g*V(a, b);\nendmodule\n")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_ic_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def sim(d, model="top", card="top()"):
    open(os.path.join(d, "q.cir"), "w").write(
        "q\n.control\npre_osdi m.osdi\n.endc\n"
        f"V1 a 0 dc 1\nN1 a 0 {model}\n.model {model} {card}\n"
        ".control\noption noacct\nset numdgt=12\nop\nprint i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 30; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    return None if m is None else float(m.group(1))


def rejected(label, src, tag, needle):
    _, rc, out = build(src, tag)
    check(label, rc != 0 and needle in out and "panicked" not in out,
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:78])


def accepted(label, src, tag):
    _, rc, out = build(src, tag)
    check(label, rc == 0, f"rc={rc} " + (out.strip().splitlines() or [""])[0][:70])


def top(body, extra=""):
    return (HDR + KID + extra + "module top(p, n);\n inout p, n; electrical p, n;\n"
            + body + "endmodule\n")


def main():
    # ---- [1] port arity and port names ------------------------------------
    rejected("too many positional ports is rejected", top(" kid c(p, n, p, n);\n"),
             "many", "connects 4 port(s) but 'kid' declares 3")
    rejected("too few positional ports is rejected", top(" kid c(p, n);\n"),
             "few", "connects 2 port(s) but 'kid' declares 3")
    rejected("zero positional ports is rejected", top(" kid c();\n"),
             "zero", "but 'kid' declares 3")
    rejected("a port name the target does not have is rejected",
             top(" kid c(.a(p), .b(n), .zz(p));\n"), "badport",
             "which is not a port of module 'kid'")
    rejected("the diagnostic lists the ports that DO exist",
             top(" kid c(.a(p), .b(n), .zz(p));\n"), "badport2", "(a, b, c)")

    # ---- [1] parameter overrides ------------------------------------------
    rejected("an override naming no parameter of the target is rejected",
             top(" kid #(.zz(4e-3)) c(p, n, p);\n"), "badparam",
             "names no parameter of module")
    rejected("more positional overrides than the target declares is rejected",
             top(" kid #(1e-3, 2e-3) c(p, n, p);\n"), "manyparam",
             "positional parameter override")

    # ======================= ACCEPT HALF ====================================
    # every LRM-sanctioned way of leaving a port unconnected must still compile
    accepted("all three ports connected positionally", top(" kid c(p, n, p);\n"), "ok1")
    accepted("all three connected by name",
             top(" kid c(.a(p), .b(n), .c(p));\n"), "ok2")
    accepted("by name, reordered", top(" kid c(.c(p), .a(p), .b(n));\n"), "ok3")
    accepted("a BLANK positional slot marks a port unconnected",
             top(" kid c(p, , n);\n"), "ok4")
    accepted("a trailing blank positional slot", top(" kid c(p, n, );\n"), "ok5")
    accepted("OMITTING a port from a by-name list", top(" kid c(.a(p), .b(n));\n"), "ok6")
    accepted("an empty `.c()` marks a port unconnected",
             top(" kid c(.a(p), .b(n), .c());\n"), "ok7")
    accepted("a valid named parameter override",
             top(" kid #(.g(2e-3)) c(p, n, p);\n"), "ok8")
    accepted("a positional parameter override", top(" kid #(2e-3) c(p, n, p);\n"), "ok9")

    # and the override must actually TAKE EFFECT, not merely be accepted
    d, rc, _ = build(top(" kid #(.g(4e-3)) c(p, n, p);\n"), "eff")
    check("a named override reaches the child (g=4e-3 -> I=4e-3)",
          rc == 0 and sim(d) is not None and abs(sim(d) + 4e-3) < 1e-12,
          f"i(v1)={sim(d) if rc == 0 else 'n/a'}")

    # ---- [4] $mfactor: accepted, and NOT zipped onto the first parameter ---
    src = (HDR + "module core(p, n);\n inout p, n; electrical p, n;\n"
           " parameter real r = 1.0;\n analog I(p, n) <+ V(p, n)/r;\nendmodule\n"
           "module top(p, n);\n inout p, n; electrical p, n;\n"
           " core #(.$mfactor(7)) C1(p, n);\nendmodule\n")
    d, rc, out = build(src, "mfac")
    got = sim(d) if rc == 0 else None
    # The override is HONORED per LRM 6.3.6 (the child stands for 7 parallel
    # copies: I = 7 * V/r = 7 A at V=1, r=1) -- it used to be silently ignored
    # (-1.0), and before that risked zipping onto the first parameter (-1/7).
    check("a `$mfactor` override is honored and does NOT leak into the first parameter",
          rc == 0 and got is not None and abs(got + 7.0) < 1e-9,
          f"rc={rc} i(v1)={got} (ignored would give -1.0; leak -1/7 = -0.1428571)")

    # ---- [2] generate renames block labels and function names --------------
    src = (HDR + "module top(p, n);\n inout p, n; electrical p, n;\n genvar i;\n"
           " generate for (i = 0; i < 3; i = i + 1) begin : gb\n"
           "   analog function real dbl;\n     input x; real x;\n     dbl = 2.0*x;\n"
           "   endfunction\n"
           "   analog begin : ab\n     real t;\n     t = dbl(1e-4);\n"
           "     I(p, n) <+ t*V(p, n);\n   end\n"
           " end endgenerate\nendmodule\n")
    d, rc, out = build(src, "genname")
    got = sim(d) if rc == 0 else None
    check("a named analog block and an analog function inside `generate` do not collide",
          rc == 0, f"rc={rc} " + (out.strip().splitlines() or [""])[0][:60])
    check("and all three iterations contribute (3 x 2e-4 = 6e-4)",
          got is not None and abs(got + 6e-4) < 1e-12, f"i(v1)={got}")

    # ---- [3] the renaming must not rewrite a named connection --------------
    src = (HDR + "module res(p, n);\n inout p, n; electrical p, n;\n"
           " parameter real r = 1000;\n analog I(p, n) <+ V(p, n)/r;\nendmodule\n"
           "module top(a, b);\n inout a, b; electrical a, b;\n electrical [0:2] nd;\n"
           " genvar i;\n analog begin V(a, nd[0]) <+ 0.0; V(nd[2], b) <+ 0.0; end\n"
           " generate for (i = 0; i < 2; i = i + 1) begin : gb\n"
           "   res #(.r(2000)) r(nd[i], nd[i+1]);\n"
           " end endgenerate\nendmodule\n")
    d, rc, _ = build(src, "connname")
    got = sim(d) if rc == 0 else None
    check("an instance whose NAME collides with the child's PARAMETER keeps its override",
          rc == 0 and got is not None and abs(got + 1.0 / 4000) < 1e-12,
          f"i(v1)={got} (rewritten to .r_0 and dropped would give -1/2000 = -5e-4)")

    # ---- [6] localparam as a generate bound --------------------------------
    def bound(decl, tag):
        return (HDR + "module top(p, n);\n inout p, n; electrical p, n;\n"
                f" {decl}\n genvar i;\n"
                " generate for (i = 0; i < N; i = i + 1) begin : gb\n"
                "   analog I(p, n) <+ 1e-4*V(p, n);\n"
                " end endgenerate\nendmodule\n"), tag

    s, t = bound("localparam integer N = 3;", "lpbound")
    d, rc, _ = build(s, t)
    got = sim(d) if rc == 0 else None
    check("a localparam is accepted as a generate bound, and unrolls the right count",
          rc == 0 and got is not None and abs(got + 3e-4) < 1e-12, f"rc={rc} i(v1)={got}")
    s, t = bound("localparam integer M = 2; localparam integer N = M + 1;", "lpchain")
    accepted("a localparam built from an earlier localparam is accepted too", s, t)
    s, t = bound("parameter integer N = 3;", "pbound")
    rejected("a plain parameter is STILL rejected as a bound", s, t,
             "bind at simulation time")
    s, t = bound("parameter integer M = 3; localparam integer N = M;", "pchain")
    rejected("a localparam derived from a parameter is STILL rejected", s, t,
             "bind at simulation time")

    # ---- [5] the runtime $table_model cap ----------------------------------
    def table(n, tag):
        # reversed knots on y = x^2: unsorted, so the sort network is exercised
        pts = [(float(n - 1 - k), float((n - 1 - k) ** 2)) for k in range(n)]
        body = "".join(f"  xs[{i}]={x}; ys[{i}]={y};\n" for i, (x, y) in enumerate(pts))
        rt = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
              f" real xs[0:{n-1}]; real ys[0:{n-1}];\n analog begin\n" + body +
              '  I(p, n) <+ 1e-3*$table_model(V(p, n), xs, ys, "3L");\n end\nendmodule\n')
        lit = ", ".join(f"{x},{y}" for x, y in pts)
        ct = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
              f" analog I(p, n) <+ 1e-3*$table_model(V(p, n), '{{{lit}}}, \"3L\");\n"
              "endmodule\n")
        return rt, ct, tag

    for n in (65, 100, 256):
        rt, ct, tag = table(n, "t%d" % n)
        d1, rc1, _ = build(rt, tag + "r")
        d2, rc2, _ = build(ct, tag + "l")
        a = sim(d1, "dut", "dut()") if rc1 == 0 else None
        b = sim(d2, "dut", "dut()") if rc2 == 0 else None
        ok = a is not None and b is not None and abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1e-30)
        check(f"runtime == compile-time for {n} unsorted knots, cubic", ok, f"rt={a} ct={b}")

    rt, _, tag = table(257, "t257")
    rejected("beyond the cap is a compile error, not a silent divergence", rt, tag,
             "at most 256 are sorted")

    # The network must be STABLE: de-duplication keeps the FIRST of any repeated
    # abscissa in ORIGINAL order, which is what `pts.dedup_by` does on the
    # compile-time side (Rust's `sort_by` is stable). The old odd-even
    # transposition network was stable for free because it only exchanged
    # neighbours; Batcher's compares elements far apart and can come out with two
    # equal abscissae swapped -- invisible until their ys differ. `vaftabledup`
    # covers this at 4-6 knots; only a table past the old 64-knot cap exercises
    # the merge stages where the reordering actually happens.
    def dup_table(n, tag):
        pts = [(float((n - 1 - k) // 2), float(n - 1 - k)) for k in range(n)]
        body = "".join(f"  xs[{i}]={x}; ys[{i}]={y};\n" for i, (x, y) in enumerate(pts))
        rt = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
              f" real xs[0:{n-1}]; real ys[0:{n-1}];\n analog begin\n" + body +
              '  I(p, n) <+ 1e-3*$table_model(V(p, n), xs, ys, "3L");\n end\nendmodule\n')
        lit = ", ".join(f"{x},{y}" for x, y in pts)
        ct = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
              f" analog I(p, n) <+ 1e-3*$table_model(V(p, n), '{{{lit}}}, \"3L\");\n"
              "endmodule\n")
        return rt, ct, tag

    for n in (70, 200):
        rt, ct, tag = dup_table(n, "d%d" % n)
        d1, rc1, _ = build(rt, tag + "r")
        d2, rc2, _ = build(ct, tag + "l")
        a = sim(d1, "dut", "dut()") if rc1 == 0 else None
        b = sim(d2, "dut", "dut()") if rc2 == 0 else None
        ok = a is not None and b is not None and abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1e-30)
        check(f"the sort stays STABLE at {n} knots with every abscissa repeated", ok,
              f"rt={a} ct={b}")

    # ---- [7] INT_MIN folds with integer semantics ---------------------------
    def ival(expr, tag):
        src = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n integer r;\n"
               f" analog begin r = {expr};\n  I(p, n) <+ 1e-6*r;\n end\nendmodule\n")
        d, rc, out = build(src, tag)
        if rc != 0:
            return "REJECTED"
        v = sim(d, "dut", "dut()")
        return None if v is None else round(-v / 1e-6)

    for i, (expr, want) in enumerate([
            ("(-2147483648)/3", -715827882),      # truncates toward zero, not floors
            ("(-2147483648)/5", -429496729),
            ("(-2147483648)-1", 2147483647),      # wraps, does not saturate
            ("(-2147483648)*2", 0),
            ("(-2147483648)*(-1)", -2147483648),
            ("(-2147483648)%3", -2),
            ("(-2147483648)", -2147483648),
            ("2147483647+1", -2147483648),        # was already right; must stay right
            ("(-100)/3", -33)]):
        got = ival(expr, "iv%d" % i)
        check(f"`{expr}` folds to {want}", got == want, f"got {got}")

    # the one integer operation that genuinely traps must stay rejected
    src = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n integer r;\n"
           " analog begin r = (-2147483648)/(-1);\n  I(p, n) <+ 1e-6*r;\n end\nendmodule\n")
    rejected("`(-2147483648)/(-1)` stays a clean error (it is the one that traps)",
             src, "ivtrap", "overflow")

    for j in os.listdir(HERE):
        if j.startswith("_ic_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
