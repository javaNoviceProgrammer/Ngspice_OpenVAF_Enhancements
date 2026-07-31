#!/usr/bin/env python3
"""Enhancement-389: the four openvaf-r items that were still open.

  [1] A LOOP WHOSE CONTROL VARIABLE IS WRITTEN BUT NEVER CHANGES.

      Enhancement-375 rejects a loop that provably cannot finish, because such a
      model has no correct object code -- it can never complete one evaluation.
      It asked whether the condition's variables are WRITTEN, which is not the
      same question as whether they can CHANGE:

          for (k = 0; k < 10; k = k + 0) ...   // writes k, never changes it

      compiled cleanly, emitted a valid `.osdi`, and then hung ngspice at the
      operating point with no diagnostic at all -- precisely the outcome E-375
      exists to prevent, reached by a different shape. A write that provably
      leaves the value alone is no longer counted as progress.

      Deliberately NOT rejected: `k = k - 1`, which looks just as wrong but
      TERMINATES by 32-bit wrap after ~2^31 iterations. This analysis is sound in
      the reject direction, so "pathologically slow" must still compile.

  [2] ANSI-STYLE ANALOG FUNCTION ARGUMENTS.

      Only the separated form was accepted:

          analog function real f; input x; real x; ...

      Both the combined declaration `input real x;` and the ANSI header
      `analog function real f(input real x);` were parse errors. Both are now
      accepted, and the type is really applied -- an `integer` argument declared
      either way rejects a real literal exactly as the separated form does.

  [3] `$table_model` WITH RUNTIME ARRAY DATA (LRM p274).

      The data had to be a compile-time literal or a data file; array *variables*
      filled in by the body were rejected with "requires a bit-select [i]". A
      runtime table now lowers to the same interpolation shape as the
      compile-time one, so `mir_autodiff` differentiates it identically -- the
      small-signal conductance is exact, not a finite difference.

  [4] THE TWO QUARANTINED SOURCEGEN TESTS (Enhancement-379).

      Covered by the workspace suite rather than here: `cargo test --workspace`
      goes from 207 passed / 158 ignored to 209 passed / 156 ignored.

WHAT THE ACCEPT HALF IS GUARDING. [1] makes a compile-time check stricter, which
is the direction that can break working models: every loop shape that terminates
must still compile. [3] adds a second lowering path for `$table_model`, so the
compile-time forms must be re-proved unchanged.
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


def build(src, tag, args=()):
    d = os.path.join(HERE, "_oi_%s" % tag)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")]
                       + list(args), capture_output=True, text=True, env=env, timeout=900)
    return d, r.returncode, r.stdout + r.stderr


def sim(d, card="", analysis="op\nprint i(v1)", vdc="0", guard=25):
    """Run the compiled model; None means the run did not finish (a hang)."""
    open(os.path.join(d, "q.cir"), "w").write(
        "q\n.control\npre_osdi m.osdi\n.endc\n"
        "V1 a 0 dc %s ac 1\nN1 a 0 mymod\n.model mymod dut %s\n"
        ".control\noption noacct\nset numdgt=12\n%s\n.endc\n.end\n" % (vdc, card, analysis))
    try:
        # macOS has no timeout(1); perl's alarm is always present.
        r = subprocess.run(["perl", "-e", "alarm %d; exec @ARGV" % guard,
                            NGSPICE, "-b", "q.cir"], cwd=d,
                           capture_output=True, text=True, errors="replace")
    except Exception:
        return None
    if r.returncode not in (0, 1):
        return None
    m = re.search(r"^(i\(v1\)|mag\(i\(v1\)\))\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    if m is None:
        return None
    val = float(m.group(2))
    # i(v1) flows into the source, so a device current is its negation; a
    # MAGNITUDE is already non-negative and must not be flipped.
    return val if m.group(1).startswith("mag") else -val


def loop_model(body):
    return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n real x; integer k;\n"
            " analog begin\n  x = 0.0; k = 0;\n  %s\n  I(p,n) <+ 1e-3*x;\n end\nendmodule\n" % body)


def main():
    # ---- [1] the non-terminating loops E-375 missed ------------------------
    for label, body in (
        ("k = k + 0", "for (k = 0; k < 10; k = k + 0) x = x + 1.0;"),
        ("k = k", "for (k = 0; k < 10; k = k) x = x + 1.0;"),
        ("k = 0 + k", "for (k = 0; k < 10; k = 0 + k) x = x + 1.0;"),
        ("k = k - 0", "for (k = 0; k < 10; k = k - 0) x = x + 1.0;"),
        ("k = k * 1", "for (k = 0; k < 10; k = k * 1) x = x + 1.0;"),
        ("k = k + 0 in the body", "while (k < 10) begin x = x + 1.0; k = k + 0; end"),
    ):
        d, rc, out = build(loop_model(body), "l" + re.sub(r"\W", "", label))
        check("rejected: a loop whose control var never changes (%s)" % label,
              rc != 0 and "loop condition" in out,
              (out.strip().splitlines() or ["(silent)"])[0][:52])

    # ======================= ACCEPT HALF ====================================
    # Making a compile-time check stricter can only break working models, so the
    # loops that DO finish matter more than the ones that do not.
    for label, body, want in (
        ("k = k + 1", "for (k = 0; k < 10; k = k + 1) x = x + 1.0;", 10.0),
        ("k = k * 2", "for (k = 1; k < 10; k = k * 2) x = x + 1.0;", 4.0),
        ("k = k + 1 in the body", "while (k < 10) begin x = x + 1.0; k = k + 1; end", 10.0),
        ("no-op then real progress",
         "for (k = 0; k < 10; k = k + 0) begin x = x + 1.0; k = k + 1; end", 10.0),
        ("repeat", "repeat (3) x = x + 1.0;", 3.0),
        ("while (0)", "while (0) x = x + 1.0;", 0.0),
    ):
        d, rc, out = build(loop_model(body), "a" + re.sub(r"\W", "", label))
        got = sim(d) if rc == 0 else None
        check("still compiles and runs: %s" % label,
              got is not None and abs(got / 1e-3 - want) < 1e-9,
              "rc=%s got=%s want=%g" % (rc, got, want))

    # `k = k - 1` terminates by 32-bit wrap -- slow, but NOT infinite, so
    # rejecting it would be wrong.
    d, rc, _ = build(loop_model("for (k = 0; k < 10; k = k - 1) x = x + 1.0;"), "wrap")
    check("a loop that wraps to termination is NOT rejected", rc == 0)

    # ---- [2] ANSI / combined function arguments ----------------------------
    def fn_model(decl):
        return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n %s\n"
                " analog I(p,n) <+ 1e-3*f(3.0);\nendmodule\n" % decl)

    for label, decl in (
        ("separated  input x; real x;",
         "analog function real f; input x; real x; begin f = x*2.0; end endfunction"),
        ("combined   input real x;",
         "analog function real f; input real x; begin f = x*2.0; end endfunction"),
        ("ANSI       f(input real x)",
         "analog function real f(input real x); begin f = x*2.0; end endfunction"),
        ("ANSI       f(input x)   (defaults to real)",
         "analog function real f(input x); begin f = x*2.0; end endfunction"),
    ):
        d, rc, out = build(fn_model(decl), "f" + re.sub(r"\W", "", label)[:14])
        got = sim(d) if rc == 0 else None
        check("%s -> f(3.0) = 6" % label,
              got is not None and abs(got / 1e-3 - 6.0) < 1e-9,
              "rc=%s got=%s" % (rc, got))

    # the declared type is really APPLIED, not just parsed and dropped
    for label, decl in (
        ("combined", "analog function real f; input integer x; begin f = x*2.0; end endfunction"),
        ("ANSI", "analog function real f(input integer x); begin f = x*2.0; end endfunction"),
    ):
        _, rc, out = build(fn_model(decl), "ti" + label)
        check("%s: an integer argument rejects a real literal" % label,
              rc != 0 and "expected integer" in out,
              (out.strip().splitlines() or [""])[0][:46])

    # ---- [3] $table_model with runtime arrays ------------------------------
    # ys depends on a model-card parameter, so the table CANNOT be folded at
    # compile time -- this is genuinely the runtime path.
    rt = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
          " parameter real scale = 1.0;\n real xs[0:3]; real ys[0:3];\n"
          " analog begin\n"
          "  xs[0]=0.0; xs[1]=1.0; xs[2]=2.0; xs[3]=3.0;\n"
          "  ys[0]=0.0; ys[1]=scale*1.0; ys[2]=scale*4.0; ys[3]=scale*9.0;\n"
          "  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, ys, \"1L\");\n"
          " end\nendmodule\n")
    d_rt, rc, out = build(rt, "tmrt")
    check("$table_model accepts runtime array data", rc == 0,
          (out.strip().splitlines() or [""])[0][:52])

    if rc == 0:
        for vdc, scale, want in (("0.5", 1.0, 0.5), ("1.5", 1.0, 2.5),
                                 ("2.5", 1.0, 6.5), ("1.5", 2.0, 5.0)):
            got = sim(d_rt, card="scale=%g" % scale, vdc=vdc)
            check("runtime table interpolates at V=%s, scale=%g" % (vdc, scale),
                  got is not None and abs(got / 1e-3 - want) < 1e-9,
                  "got=%s want=%g" % (got, want))

        # The Jacobian must be the analytic segment slope, not a difference: on
        # [1,2] the slope is (4-1)/(2-1) = 3.
        g = sim(d_rt, card="scale=1.0", vdc="1.5",
                analysis="op\nac lin 1 1 1\nprint mag(i(v1))")
        check("the runtime table's small-signal conductance is exact",
              g is not None and abs(g / 1e-3 - 3.0) < 1e-9, "dI/dV = %s" % g)

    # ACCEPT: the compile-time forms are untouched by the new path
    ct = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
          " analog I(p,n) <+ 1e-3*$table_model(V(p,n),"
          " '{0.0,0.0, 1.0,1.0, 2.0,4.0, 3.0,9.0}, \"1L\");\nendmodule\n")
    d_ct, rc, _ = build(ct, "tmct")
    got = sim(d_ct, vdc="1.5") if rc == 0 else None
    check("the compile-time inline table still interpolates",
          got is not None and abs(got / 1e-3 - 2.5) < 1e-9, "got=%s want=2.5" % got)
    g = sim(d_ct, vdc="1.5", analysis="op\nac lin 1 1 1\nprint mag(i(v1))") if rc == 0 else None
    check("...and agrees with the runtime table's conductance",
          g is not None and abs(g / 1e-3 - 3.0) < 1e-9, "dI/dV = %s" % g)

    # a non-array second data argument is still a type error, not a 1-point table
    _, rc, out = build(
        HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n real xs[0:1];\n"
        " analog begin\n  xs[0]=0.0; xs[1]=1.0;\n"
        "  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, 1.0);\n end\nendmodule\n", "tmbad")
    check("a scalar where the table values belong is still an error", rc != 0,
          (out.strip().splitlines() or ["(accepted!)"])[0][:46])

    for j in os.listdir(HERE):
        if j.startswith("_oi_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
