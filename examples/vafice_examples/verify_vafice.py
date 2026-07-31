#!/usr/bin/env python3
"""Enhancement-387: three openvaf-r defects found by a compiler bug hunt.

  [1] AN EMPTY PARENTHESISED EXPRESSION CRASHED THE COMPILER.

          analog I(p,n) <+ ();
          -> "OpenVAF encountered a problem and has crashed!"   (exit 101)

      Five lines, no CLI flags, on the shipped release binary. `paren_expr`'s
      loop is guarded by `!p.at(T![')'])`, so for `()` it never ran: nothing was
      parsed and NO DIAGNOSTIC WAS EMITTED. The PAREN_EXPR completed with no
      child, hir_def lowered it to `Expr::Missing`, and `hir/src/body.rs` has no
      arm for that variant -- it fell through to
      `_ => panic!("invalid HIR: {:?}")`.

      The hole was exactly one token wide. Every other malformed expression --
      `{}`, `{1,}`, `a[]`, `? :`, `sqrt()`, `1+` -- was already rejected in the
      parser and never reached lowering. Only `()` (and its nestings `(())`,
      `(( ))`) got through.

  [2] `-DNAME=VALUE` DEFINED A MACRO CALLED `NAME=VALUE`.

      Every `-D` flag became a macro whose name was the WHOLE flag string, so
      `-DEXT=5.5` defined `EXT=5.5` and `` `EXT `` reported "macro '`EXT' has not
      been declared" -- no spelling of the flag could reach it. Now split on the
      first '=', which is what the `-D <MACRO[=VALUE]>` help text promises.

      NOT FIXED, and stated rather than hidden: the VALUE is still not
      substituted. A macro body is a `Vec<ParsedToken>` whose text is resolved by
      SPAN against a real source file, and a value that arrived through argv has
      no backing text. Defining the name is the half that can be done correctly
      in the preprocessor; substituting the value needs the definitions
      materialised as a source file first.

  [3] A BAD `TMPDIR` ABORTED THROUGH AN UNCAUGHT C++ EXCEPTION.

          libc++abi: terminating due to uncaught exception ... filesystem_error
          clang: error: unable to execute command: Abort trap: 6
          error: linking failed (see linker output for details)

      A nonexistent or read-only TMPDIR. The final message blamed "linking" and
      never mentioned TMPDIR, which CI runners and sandboxes routinely set.
      `link()` now checks the directory first -- existence AND writability, since
      a read-only TMPDIR fails the same way -- and names the real cause.

HOW [1] WAS FOUND is worth recording: not by fuzzing the language, but by
following [2]. A valueless `-DEXT` defines a macro with an EMPTY body, so
`1e-3*(`EXT)` expanded to `1e-3*()` -- and that crashed. Two defects, one
reachable only through the other.
"""
import os
import re
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


def compile_va(src, tag, args=()):
    """Returns (returncode, combined output). Never raises on a crash."""
    d = os.path.join(HERE, "_vi_%s" % tag)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "m.va")
    with open(p, "w") as f:
        f.write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    try:
        r = subprocess.run([OPENVAF, p, "-o", os.path.join(d, "m.osdi")] + list(args),
                           capture_output=True, text=True, env=env, timeout=600)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -9, "__TIMEOUT__"


def crashed(out, rc):
    return "encountered a problem and has crashed" in out or rc == 101


def main():
    # ---- [1] the ICE, and the whole family around it -----------------------
    FORMS = ["()", "(())", "(( ))", "1e-3*()", "1e-3*(())", "-()", "1e-3+()", "sqrt(())"]
    bad = []
    for i, form in enumerate(FORMS):
        rc, out = compile_va(
            HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
            " analog I(p,n) <+ %s;\nendmodule\n" % form, "e%d" % i)
        if crashed(out, rc):
            bad.append(form)
    check("no empty-parenthesis form crashes the compiler",
          not bad, "%d crashed: %s" % (len(bad), " ".join(bad)) if bad else
          "%d forms, all rejected cleanly" % len(FORMS))

    # a crash is not the only wrong outcome -- silently ACCEPTING `()` would be
    # just as bad, so require a real diagnostic
    rc, out = compile_va(HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
                         " analog I(p,n) <+ ();\nendmodule\n", "diag")
    check("`()` is reported as a syntax error, not accepted",
          rc != 0 and re.search(r"^error", out, re.M) and not crashed(out, rc),
          (out.strip().splitlines() or ["(no output)"])[0][:70])

    # ---- [2] -D names ------------------------------------------------------
    USE = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
           " analog I(p,n) <+ V(p,n)*1e-3 `EXT ;\nendmodule\n")
    rc, out = compile_va(USE, "dval", ["-DEXT=5.5"])
    check("-DNAME=VALUE defines a macro named NAME",
          rc == 0, (out.strip().splitlines() or [""])[0][:70])
    rc, out = compile_va(USE, "dbare", ["-DEXT"])
    check("-DNAME (no value) also defines it", rc == 0,
          (out.strip().splitlines() or [""])[0][:70])

    # `ifdef must see it under both spellings
    IFD = (HDR + "`ifdef EXT\n`define V 8.0\n`else\n`define V 1.0\n`endif\n"
           "module dut(p,n);\n inout p,n; electrical p,n;\n"
           " analog I(p,n) <+ 1e-3*(`V);\nendmodule\n")
    for spelling, tag in (("-DEXT", "if1"), ("-DEXT=5.5", "if2")):
        d = os.path.join(HERE, "_vi_%s" % tag)
        rc, out = compile_va(IFD, tag, [spelling])
        ok = rc == 0
        if ok:
            deck = os.path.join(d, "q.cir")
            open(deck, "w").write(
                "q\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 0\nN1 a 0 mymod\n"
                ".model mymod dut\n.control\noption noacct\nset numdgt=12\nop\n"
                "print i(v1)\n.endc\n.end\n")
            r = subprocess.run([NGSPICE, "-b", "q.cir"], cwd=d, capture_output=True,
                               text=True, timeout=300, errors="replace")
            m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
            ok = m is not None and abs(-float(m.group(1)) / 1e-3 - 8.0) < 1e-9
        check("`ifdef sees the macro from %s (takes the 8.0 branch)" % spelling, ok)

    # ---- [3] TMPDIR --------------------------------------------------------
    OK_VA = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
             " analog I(p,n) <+ V(p,n)*1e-3;\nendmodule\n")
    d = os.path.join(HERE, "_vi_tmp")
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "m.va")
    open(src, "w").write(OK_VA)
    missing = os.path.join(d, "definitely_not_here")
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=missing)
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, timeout=600)
    out = r.stdout + r.stderr
    check("a nonexistent TMPDIR is reported by name, not as an abort",
          "TMPDIR" in out and "uncaught exception" not in out and "Abort trap" not in out,
          (out.strip().splitlines() or ["(no output)"])[0][:70])

    # read-only TMPDIR fails through a different errno and must also be named
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR="/")
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, timeout=600)
    out = r.stdout + r.stderr
    check("a read-only TMPDIR is reported by name too",
          "TMPDIR" in out and "uncaught exception" not in out,
          (out.strip().splitlines() or ["(no output)"])[0][:70])

    # ======================= ACCEPT HALF ====================================
    # The parser change touches every parenthesised expression in every model,
    # so ordinary parentheses are exactly what a careless fix would break.
    rc, out = compile_va(
        HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
        " parameter real r0 = 1000.0;\n"
        " analog I(p,n) <+ ((V(p,n)) / (r0)) + (((1.0)))*0.0;\nendmodule\n", "acc1")
    check("nested ordinary parentheses still compile", rc == 0,
          (out.strip().splitlines() or [""])[0][:60])

    # a valid model must still produce the right number end-to-end
    d = os.path.join(HERE, "_vi_acc2")
    rc, out = compile_va(
        HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
        " analog I(p,n) <+ (V(p,n))*(1e-3);\nendmodule\n", "acc2")
    ok = rc == 0
    if ok:
        open(os.path.join(d, "q.cir"), "w").write(
            "q\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 2.0\nN1 a 0 mymod\n"
            ".model mymod dut\n.control\noption noacct\nset numdgt=14\nop\n"
            "print i(v1)\n.endc\n.end\n")
        r = subprocess.run([NGSPICE, "-b", "q.cir"], cwd=d, capture_output=True,
                           text=True, timeout=300, errors="replace")
        m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
        ok = m is not None and abs(-float(m.group(1)) - 2.0e-3) < 1e-15
    check("a parenthesised model still computes correctly (2 V / 1 kOhm = 2 mA)", ok)

    # a normal compile must not be disturbed by the TMPDIR probe
    rc, out = compile_va(OK_VA, "acc3")
    check("an ordinary compile with a valid TMPDIR still succeeds", rc == 0,
          (out.strip().splitlines() or [""])[0][:60])

    import shutil
    for j in os.listdir(HERE):
        if j.startswith("_vi_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
