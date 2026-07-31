#!/usr/bin/env python3
"""Enhancement-388: the two items Enhancement-387 left open.

  [1] `-D` VALUES ARE NOW SUBSTITUTED.

      E-387 fixed the NAME (`-DK=5.5` had defined a macro literally called
      `K=5.5`) but left the VALUE unimplemented, because `-D` flags were
      synthesised straight into `Macro { body: vec![], .. }` and a macro body is
      a `Vec<ParsedToken>` whose text resolves BY SPAN against a real source
      file -- a value that arrived through argv has no backing text, so no body
      could be built for it.

      The fix removes that synthesis entirely. The flags are written into a
      virtual source file as ordinary directives

          `define K 5.5

      which the preprocessor parses exactly as if the user had typed them, spans
      and all. `-DK=5.5` now substitutes 5.5, and a bare `-DK` expands to `1` --
      which is what `-D <MACRO[=VALUE]>` has always promised for an omitted
      value, and what it did not do.

  [2] THE EXPRESSION-DEPTH GUARD SAYS WHAT IT MEANS.

      Enhancement-148 bounds expression depth so a pathologically deep
      expression is rejected instead of overflowing the recursive-descent
      parser. It reported that through the ordinary "unexpected token" path, so
      a 999-term operator chain came back as

          error: unexpected token identifier; expected '(', ''{', '{', ...

      -- a complaint about a token that is perfectly valid, with no hint that a
      depth limit exists. The preprocessor's own recursion guard has always said
      what happened ("nests too deeply (a file that includes itself?)"); the
      parser now does too, with a help note naming the limit.

WHAT THE ACCEPT HALF IS REALLY GUARDING. [1] moves EVERY `-D` flag onto a new
code path, and `STANDARD_FLAGS` -- `__OPENVAF__`, `__VAMS__`,
`__VAMS_COMPACT_MODELING__` -- travel that same path. Compact models branch on
those, so a fix that defined the user's flags but dropped the standard ones would
break real models while every `-D` test still passed.
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
    d = os.path.join(HERE, "_vd_%s" % tag)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")]
                       + list(args), capture_output=True, text=True, env=env, timeout=600)
    return d, r.returncode, r.stdout + r.stderr


def current(d):
    """Run the compiled model at 0 V and return the contributed current / 1e-3."""
    open(os.path.join(d, "q.cir"), "w").write(
        "q\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 0\nN1 a 0 mymod\n"
        ".model mymod dut\n.control\noption noacct\nset numdgt=15\nop\n"
        "print i(v1)\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "q.cir"], cwd=d, capture_output=True,
                       text=True, timeout=300, errors="replace")
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    return None if m is None else -float(m.group(1)) / 1e-3


USE_K = HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n analog I(p,n) <+ 1e-3*(`K);\nendmodule\n"


def main():
    # ---- [1] -D values ------------------------------------------------------
    for flag, want in (("-DK=5.5", 5.5), ("-DK=42", 42.0), ("-DK=1e-3", 1e-3),
                       ("-DK=-2.25", -2.25), ("-DK=(2.0+3.0)", 5.0)):
        d, rc, out = build(USE_K, "v" + re.sub(r"\W", "", flag), [flag])
        got = current(d) if rc == 0 else None
        check("%s substitutes its value" % flag,
              got is not None and abs(got - want) <= 1e-12 * max(abs(want), 1e-12),
              "got %s (want %g)" % (got, want))

    # the documented default: "If the value is omitted '1' is used"
    d, rc, out = build(USE_K, "bare", ["-DK"])
    got = current(d) if rc == 0 else None
    check("a valueless -DK expands to 1, as documented",
          got is not None and abs(got - 1.0) < 1e-12, "got %s" % got)

    # ---- [2] the depth diagnostic ------------------------------------------
    deep = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
            " parameter real k = 1.0;\n analog I(p,n) <+ 1e-6*(%s);\nendmodule\n"
            % "\n   + ".join(["k"] * 1200))
    _, rc, out = build(deep, "deep")
    check("an over-deep expression says it nests too deeply",
          rc != 0 and "nests too deeply" in out,
          (out.strip().splitlines() or ["(no output)"])[0][:64])
    check("...and the help note names the limit",
          "1000" in out and "intermediate variables" in out)

    # ======================= ACCEPT HALF ====================================
    # STANDARD_FLAGS travel the same new path as the user's -D flags. A fix that
    # defined the user's and dropped these would pass every test above.
    for flag in ("__OPENVAF__", "__VAMS__", "__VAMS_COMPACT_MODELING__"):
        src = (HDR + "`ifdef %s\n`define V 7.0\n`else\n`define V 1.0\n`endif\n"
               "module dut(p,n);\n inout p,n; electrical p,n;\n"
               " analog I(p,n) <+ 1e-3*(`V);\nendmodule\n" % flag)
        d, rc, _ = build(src, "std" + flag.strip("_").lower())
        got = current(d) if rc == 0 else None
        check("`ifdef %s is still defined" % flag,
              got is not None and abs(got - 7.0) < 1e-12, "got %s" % got)

    # `ifdef must see a user flag in both spellings
    for flag in ("-DFOO", "-DFOO=9"):
        src = (HDR + "`ifdef FOO\n`define V 3.0\n`else\n`define V 1.0\n`endif\n"
               "module dut(p,n);\n inout p,n; electrical p,n;\n"
               " analog I(p,n) <+ 1e-3*(`V);\nendmodule\n")
        d, rc, _ = build(src, "if" + re.sub(r"\W", "", flag), [flag])
        got = current(d) if rc == 0 else None
        check("`ifdef sees %s" % flag, got is not None and abs(got - 3.0) < 1e-12,
              "got %s" % got)

    # a model with NO -D flags must be untouched, and a source `define must still
    # win/behave -- the preamble is skipped entirely when it is empty
    src = (HDR + "`define V 4.5\nmodule dut(p,n);\n inout p,n; electrical p,n;\n"
           " analog I(p,n) <+ 1e-3*(`V);\nendmodule\n")
    d, rc, _ = build(src, "nodefs")
    got = current(d) if rc == 0 else None
    check("a compile with no -D flags is unaffected",
          got is not None and abs(got - 4.5) < 1e-12, "got %s" % got)

    # an undefined macro must still be an error, not silently empty
    _, rc, out = build(USE_K, "undef")
    check("an undefined macro is still reported",
          rc != 0 and "has not been declared" in out,
          (out.strip().splitlines() or [""])[0][:60])

    # the depth LIMIT itself must not move: 998 terms still compile
    ok_deep = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n"
               " parameter real k = 1.0;\n analog I(p,n) <+ 1e-6*(%s);\nendmodule\n"
               % "\n   + ".join(["k"] * 998))
    _, rc, out = build(ok_deep, "ok998")
    check("998 terms still compile (the limit is unchanged)", rc == 0,
          (out.strip().splitlines() or [""])[0][:50])

    for j in os.listdir(HERE):
        if j.startswith("_vd_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
