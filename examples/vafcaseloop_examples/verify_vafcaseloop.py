#!/usr/bin/env python3
"""Enhancement-390: eight defects from a one-hour openvaf-r hunt.

  [1] A `case` INSIDE A `do-while` PRODUCED AN INFINITE LOOP.

      The headline. `lower_case` opened its arms with `ensured_sealed()`, which
      seals the CURRENT block -- and on the first arm that block still belongs to
      the CALLER. When a `case` is the first statement of a `do-while` body, the
      caller's block is the loop's body head, which must stay UNSEALED until the
      back edge is added. Sealing it early completed its phis against the entry
      edge alone, so a variable updated in the loop read back as its pre-loop
      value: `while (k < 3)` folded to a constant true and the optimised MIR came
      out as `block2: jmp block2` -- a literal infinite loop, with the
      contribution block unreachable.

      Two symptoms, decided by what encloses it: on its own the model COMPILED
      CLEAN and hung ngspice forever at the operating point with no diagnostic;
      nested in a `for`/`while`/`repeat` it CRASHED the compiler at
      `mir_opt/dead_code_aggressive.rs:112`.

      This is the Enhancement-375 pattern a third time. The 2026-07-26 binary
      crashed on this construct; Enhancement-363 fixed the panic, and what it
      emitted afterwards looped forever -- worse than the crash it replaced.
      Every block `lower_case` creates is sealed explicitly, so the blanket call
      was never load-bearing.

  [2] AN ANSI FUNCTION ARGUMENT WITH A TYPE BUT NO DIRECTION SILENTLY RETURNED 0.

      `f(real x)` compiled, accepted one argument, and discarded it: the argument
      was neither input nor output, so nothing was copied in and the body read 0.
      `f(3.0)` returned 0 instead of 6. Verilog defaults a function argument to
      `input`, and the separated and combined forms both reject a direction-less
      argument outright -- only the ANSI path could produce one.

  [3] `analog` BLOCKS INSIDE `generate` WERE SILENTLY DISCARDED.

      `generate for (i=0;i<3;i=i+1) begin analog I(p,n) <+ 1e-3; end` contributed
      NOTHING, with zero diagnostics. The generate-block grammar had no case for
      `analog`, so it fell into the catch-all -- and the parse error it raised was
      then swallowed, because elaboration re-renders the generate region from its
      syntax tree. The malformed node rendered to nothing. Generate worked for
      instantiation all along, so only analog blocks vanished.

  [4] `disable <name>` WITH AN UNRESOLVABLE NAME WAS A SILENT NO-OP.

      A typo'd label, a variable name, even the module name: lowering resolved the
      name against the enclosing named blocks and, on a miss, "degraded to a
      no-op" deliberately. The statement did nothing and execution carried on, so
      a loop meant to exit early ran to completion -- a changed answer from a
      spelling mistake.

  [5..7] `$table_model` -- three ways the two data forms disagreed.

      The compile-time forms SORT and DE-DUPLICATE their breakpoints; the runtime
      array form did neither, so identical data gave different answers (descending
      data: 0.5/2.5/5.5 from a literal, -0.5/1.5/2.5 from arrays). A duplicated or
      never-assigned abscissa made a zero-width segment whose slope divided by
      zero, and the NaN surfaced only as "Timestep too small". And the cubic
      control code `"3"` was ignored on the runtime path, which always
      interpolated linearly.

      All three are fixed in kind rather than diagnosed: the runtime table is
      sorted and de-duplicated by an unrolled network, divisions are guarded, and
      the natural cubic spline is solved in MIR by an unrolled Thomas algorithm --
      the knot COUNT is known at compile time even when the knots are not.

  [8] AN UNUSABLE `$table_model` DATA FILE WAS A SILENT ZERO.

      A mistyped filename, an unreadable file, an empty one, a single column of
      numbers: the reader returned an empty table and the device contributed zero,
      with nothing reported. The file is read during lowering, which has no
      diagnostic channel, so the check is made when the report is built -- the
      first point with both the root file and the VFS in hand.

WHAT THE ACCEPT HALF IS GUARDING. [1] changes block sealing, which every model
containing a `case` goes through, and [3] adds a keyword to a grammar. Both are
the kind of change that breaks working models rather than the broken ones, so the
controls below matter more than the reproducers: `case` in every other context,
`if`/`else` where `case` used to fail, and the full compile-time `$table_model`
surface.
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


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag, extra_files=None):
    d = os.path.join(HERE, "_cl_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    for name, content in (extra_files or {}).items():
        open(os.path.join(d, name), "w").write(content)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, r.stdout + r.stderr


def sim(d, vdc="0.0", card="", deck="op\nprint i(v1)", guard=30):
    """Run the model. `None` means the run never finished -- i.e. a hang."""
    open(os.path.join(d, "q.cir"), "w").write(
        "q\n.control\npre_osdi m.osdi\n.endc\n"
        f"V1 a 0 dc {vdc} ac 1\nN1 a 0 mymod\n.model mymod dut({card})\n"
        f".control\noption noacct\nset numdgt=15\n{deck}\n.endc\n.end\n")
    # macOS has no timeout(1); perl's alarm is always present.
    r = subprocess.run(["perl", "-e", "alarm %d; exec @ARGV" % guard, NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    if r.returncode not in (0, 1):
        return None
    m = re.search(r"^(i\(v1\)|mag\(i\(v1\)\))\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    if m is None:
        return None
    v = float(m.group(2))
    return v if m.group(1).startswith("mag") else -v


def loop_model(body, decl=" real x; integer k; integer j;\n"):
    return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n" + decl +
            " analog begin x=0.0; k=0; j=0;\n  " + body + "\n  I(p,n) <+ 1e-3*x;\n end\nendmodule\n")


def main():
    # ---- [1] case inside do-while ------------------------------------------
    CASE = "case (k) 0: x=x+1.0; default: x=x+2.0; endcase"
    for label, body, want in (
        ("do{case}while(k<3)", f"do begin {CASE} k=k+1; end while (k<3);", 5.0),
        ("do{casex}while", "do begin casex (k) 0: x=x+1.0; default: x=x+2.0; endcase k=k+1; end while (k<3);", 5.0),
        ("do{casez}while", "do begin casez (k) 0: x=x+1.0; default: x=x+2.0; endcase k=k+1; end while (k<3);", 5.0),
        ("do{case, no default}while", "do begin case (k) 0: x=x+1.0; endcase k=k+1; end while (k<3);", 1.0),
        ("if{do{case}while}", f"if (j<5) begin do begin {CASE} k=k+1; end while (k<3); end", 5.0),
        ("case{do{case}while}", f"case (j) 0: begin do begin {CASE} k=k+1; end while (k<3); end default: x=x+0.0; endcase", 5.0),
    ):
        d, rc, out = build(loop_model(body), "l" + re.sub(r"\W", "", label)[:12])
        got = sim(d) if rc == 0 else None
        check("no longer hangs: %s" % label,
              got is not None and abs(got / 1e-3 - want) < 1e-9,
              "rc=%s got=%s want=%g" % (rc, None if got is None else got / 1e-3, want))

    # the same construct nested in a LOOP used to crash the compiler outright
    for label, body, want in (
        ("for{do{case}while}", f"for (j=0;j<2;j=j+1) begin k=0; do begin {CASE} k=k+1; end while (k<2); end", 6.0),
        ("while{do{case}while}", f"j=0; while (j<2) begin k=0; do begin {CASE} k=k+1; end while (k<2); j=j+1; end", 6.0),
        ("repeat{do{case}while}", f"repeat (2) begin k=0; do begin {CASE} k=k+1; end while (k<2); end", 6.0),
    ):
        d, rc, out = build(loop_model(body), "c" + re.sub(r"\W", "", label)[:12])
        crashed = "panicked" in out or "encountered a problem" in out
        got = sim(d) if rc == 0 else None
        check("no longer crashes the compiler: %s" % label,
              not crashed and got is not None and abs(got / 1e-3 - want) < 1e-9,
              "crash=%s got=%s want=%g" % (crashed, None if got is None else got / 1e-3, want))

    # ACCEPT: `case` everywhere else must be untouched
    for label, body, want in (
        ("plain case", CASE, 1.0),
        ("while{case}", f"while (k<3) begin {CASE} k=k+1; end", 5.0),
        ("for{case}", f"for (k=0;k<3;k=k+1) begin {CASE} end", 5.0),
        ("nested case", "case (k) 0: case (k) 0: x=x+7.0; default: x=x+1.0; endcase default: x=x+2.0; endcase", 7.0),
        ("case with multiple vals", "case (k) 0,1,2: x=x+3.0; default: x=x+9.0; endcase", 3.0),
        ("do{if/else}while", "do begin if (k==0) x=x+1.0; else x=x+2.0; k=k+1; end while (k<3);", 5.0),
        ("do{plain}while", "do begin x=x+1.0; k=k+1; end while (k<3);", 3.0),
        ("do{case}while(0)", "do begin case (k) 0: x=x+7.0; default: x=x+100.0; endcase k=k+1; end while (0);", 7.0),
    ):
        d, rc, out = build(loop_model(body), "a" + re.sub(r"\W", "", label)[:12])
        got = sim(d) if rc == 0 else None
        check("unchanged: %s" % label,
              got is not None and abs(got / 1e-3 - want) < 1e-9,
              "got=%s want=%g" % (None if got is None else got / 1e-3, want))

    # ---- [2] ANSI argument direction ---------------------------------------
    def fn_model(decl, call):
        return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n real gv;\n " + decl +
                f"\n analog begin gv=0.0;\n  I(p,n) <+ 1e-3*{call};\n end\nendmodule\n")

    for label, decl, call, want in (
        ("f(real x) defaults to input",
         "analog function real f(real x); begin f=x*2.0; end endfunction", "f(3.0)", 6.0),
        ("f(real x, real y)",
         "analog function real f(real x, real y); begin f=x+y; end endfunction", "f(3.0,4.0)", 7.0),
        ("f(input real x) unchanged",
         "analog function real f(input real x); begin f=x*2.0; end endfunction", "f(3.0)", 6.0),
        ("output still writes back",
         "analog function real f(input real x, output real y); begin y=9.0; f=x*2.0; end endfunction",
         "f(3.0,gv)+gv*0.0", 6.0),
    ):
        d, rc, out = build(fn_model(decl, call), "f" + re.sub(r"\W", "", label)[:12])
        got = sim(d) if rc == 0 else None
        check("%s" % label, got is not None and abs(got / 1e-3 - want) < 1e-9,
              "got=%s want=%g" % (None if got is None else got / 1e-3, want))

    # ---- [3] analog inside generate ----------------------------------------
    for label, gen, want in (
        ("generate for x3", " genvar i;\n generate for (i=0;i<3;i=i+1) begin : b\n  analog I(p,n) <+ 1e-3;\n end endgenerate\n", 3e-3),
        ("generate if(1)", " generate if (1) begin : y\n  analog I(p,n) <+ 4e-3;\n end endgenerate\n", 4e-3),
        ("generate if(0) takes else", " generate if (0) begin : y\n  analog I(p,n) <+ 4e-3;\n end endgenerate\n analog I(p,n) <+ 1e-3;\n", 1e-3),
        ("generate + outer analog", " genvar i;\n analog I(p,n) <+ 1e-3;\n generate for (i=0;i<2;i=i+1) begin : b\n  analog I(p,n) <+ 1e-3;\n end endgenerate\n", 3e-3),
    ):
        src = HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n" + gen + "endmodule\n"
        d, rc, out = build(src, "g" + re.sub(r"\W", "", label)[:12])
        got = sim(d) if rc == 0 else None
        check("generate contributes: %s" % label,
              got is not None and abs(got - want) < 1e-12,
              "got=%s want=%g" % (got, want))

    # a syntax error inside a generate's analog block must now be REPORTED
    src = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n genvar i;\n"
           " generate for (i=0;i<2;i=i+1) begin : b\n  analog I(p,n) <+ @@@;\n end endgenerate\n"
           "endmodule\n")
    _, rc, out = build(src, "gerr")
    check("a syntax error inside a generate analog block is reported", rc != 0,
          (out.strip().splitlines() or ["(silent)"])[0][:46])

    # ---- [4] disable with an unresolvable name -----------------------------
    for label, head, dis, should_reject in (
        ("labelled block, disable it", "analog begin : blk", "disable blk", False),
        ("unlabelled block", "analog begin", "disable blk", True),
        ("wrong label", "analog begin : blk", "disable nosuch", True),
        ("a variable name", "analog begin : blk", "disable x", True),
        ("the module name", "analog begin : blk", "disable dut", True),
    ):
        src = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n real x; integer i;\n"
               f" {head}\n  x=0.0; i=0;\n"
               f"  while (i<10) begin x=x+1.0; i=i+1; if (i>=3) {dis}; end\n"
               "  I(p,n) <+ 1e-3*x;\n end\nendmodule\n")
        _, rc, out = build(src, "d" + re.sub(r"\W", "", label)[:12])
        check("disable: %s" % label, (rc != 0) == should_reject,
              "rc=%s %s" % (rc, (out.strip().splitlines() or [""])[0][:38]))

    # ---- [5..7] runtime vs compile-time $table_model ------------------------
    ASC = [(0.0, 0.0), (1.0, 1.0), (2.0, 4.0), (3.0, 9.0)]

    def rt(data, ctrl):
        n = len(data)
        body = "".join(f"  xs[{i}]={x}; ys[{i}]={y};\n" for i, (x, y) in enumerate(data))
        return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
                f" real xs[0:{n-1}]; real ys[0:{n-1}];\n analog begin\n" + body +
                f'  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, ys, "{ctrl}");\n end\nendmodule\n')

    def ct(data, ctrl):
        lit = ", ".join(f"{x},{y}" for x, y in data)
        return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
                f" analog I(p,n) <+ 1e-3*$table_model(V(p,n), '{{{lit}}}, \"{ctrl}\");\nendmodule\n")

    for label, data, ctrl in (
        ("ascending, linear", ASC, "1L"),
        ("DESCENDING, linear", list(reversed(ASC)), "1L"),
        ("ascending, CUBIC", ASC, "3L"),
        ("DESCENDING, cubic", list(reversed(ASC)), "3L"),
        ("clamped (no L)", ASC, "1"),
        ("duplicate x, linear", [(0.0, 0.0), (1.0, 1.0), (1.0, 5.0), (2.0, 4.0)], "1L"),
        ("5 knots, cubic", ASC + [(4.0, 16.0)], "3L"),
    ):
        vals = []
        for src in (rt(data, ctrl), ct(data, ctrl)):
            d, rc, _ = build(src, "t%d" % len(vals) + re.sub(r"\W", "", label)[:10])
            vals.append(None if rc else [sim(d, vdc=v) for v in ("-0.5", "0.5", "1.5", "2.5", "3.5")])
        # Compared to a relative tolerance, not bit-for-bit: the runtime path
        # DIVIDES where the compile-time path folds the same coefficient to a
        # constant (`1/(6h)` vs `x/(6h)`), so the cubic can land a ULP or two
        # apart. That is float arithmetic, not a difference in the answer -- the
        # defect this guards against moved values by 100%, not by 1e-16.
        ok = vals[0] is not None and vals[1] is not None and len(vals[0]) == len(vals[1])
        if ok:
            for a, b in zip(vals[0], vals[1]):
                if a is None or b is None or abs(a - b) > 1e-12 * max(abs(a), abs(b), 1e-30):
                    ok = False
                    break
        check("runtime and compile-time agree: %s" % label, ok,
              "rt=%s ct=%s" % (vals[0], vals[1]))

    # a never-assigned table (all zeros) must not produce NaN and kill the run
    src = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n real xs[0:2]; real ys[0:2];\n"
           " analog begin\n  ys[0]=0.0; ys[1]=1.0; ys[2]=4.0;\n"
           '  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, ys, "1L");\n end\nendmodule\n')
    d, rc, _ = build(src, "tnan")
    check("an unassigned runtime table yields a finite result, not NaN",
          rc == 0 and sim(d, vdc="0.5") is not None)

    # ---- [8] the data file ---------------------------------------------------
    GOOD = "0.0 0.0\n1.0 1.0\n2.0 4.0\n"
    for label, fname, content, should_reject in (
        ("a valid two-column file", "t.dat", GOOD, False),
        ("a commented file", "t.dat", "# hdr\n0.0 0.0\n// c\n1.0 1.0\n", False),
        ("a missing file", "nope.dat", None, True),
        ("a file of prose", "t.dat", "this is not a table\n@@@\n", True),
        ("an empty file", "t.dat", "", True),
        ("a single column", "t.dat", "1.0\n2.0\n3.0\n", True),
    ):
        extra = {} if content is None else {fname if content is not None else "x": content}
        src = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
               f' analog I(p,n) <+ 1e-3*$table_model(V(p,n), "{fname}", "1L");\nendmodule\n')
        _, rc, out = build(src, "F" + re.sub(r"\W", "", label)[:12], extra)
        check("table file: %s" % label, (rc != 0) == should_reject,
              "rc=%s %s" % (rc, (out.strip().splitlines() or [""])[0][:40]))

    for j in os.listdir(HERE):
        if j.startswith("_cl_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
