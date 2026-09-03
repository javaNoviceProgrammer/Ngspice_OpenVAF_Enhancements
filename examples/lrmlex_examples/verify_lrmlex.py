#!/usr/bin/env python3
"""Enhancement-515: the lexical layer and compiler directives, audited against
Accellera VAMS-2023 clauses 2 and 10 (and Annex B), then fixed.

What this suite pins, each against the quoted clause:

  * 2.6.1 -- a based literal is "up to three tokens", the unsigned number
    "optionally preceded by white space", and "It shall be legal to macro
    substitute these three tokens". `5 'D 3` is the LRM's own Example 2. All
    of it was rejected at the apostrophe; only the contiguous spelling
    compiled. Now `5 'D 3`, `12'b 0011_0101_0001`, ``SZ'hFF`, `'h 837FF` and
    `8'sh FF` evaluate to 3, 849, 255, 538623 and -1 -- checked at RUN time,
    next to the contiguous forms, so a regression in either direction shows.
  * 2.6.1 -- digits invalid for the base in the white-space form are a located
    error ("based literal has no valid digits for its base"), not a silent 0.
  * 2.6.2 / 2.7 -- `1.` ("at least one digit on each side of the decimal
    point") and a string spanning a raw newline ("contained on a single
    line") are errors now; both compiled in silence before.
  * 2.8.2 / Annex B -- `assert`, `root` and `do` are NOT reserved words, and
    each used to be refused as an identifier. `do` stays contextual, so the
    do-while extension still parses (pinned by dowhile_examples).
  * 2.9 -- an attribute instance "can appear as a suffix to an operator or a
    Verilog-AMS function name in an expression"; that position was a parse
    error. And when the same attribute is written twice, "the last attribute
    value shall be used" -- pinned through the OSDI descriptor text.
  * 10.4 -- "The `undef compiler directive shall have no effect on predefined
    Verilog-AMS macros" (it removed them), and a user macro in the reserved
    `__VAMS_` namespace draws a warning.
  * 10.5 -- `__VAMS_ENABLE__` "shall always be defined". It was not defined at
    all; the LRM's own not_gate example could never take its VAMS branch.
  * 10.6 -- `begin_keywords/`end_keywords exist now: the five version
    specifiers are validated, a 1364-* set warns that the reserved set is not
    narrowed, and a stray `end_keywords warns instead of dying as an
    undeclared macro.
  * `resetall resets the directive state this compiler tracks instead of
    warning "unsupported compiler directive" (the compliance document had
    listed it as supported).
  * 10.7 interaction -- using `__FILE__/`__LINE__ anywhere used to break every
    RELATIVE `include in the compilation ("entity not found"), because the
    source-location rewrite lost the file's directory. srcloc.va pins the
    combination, including the exact `__LINE__ value.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ll_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_file(name):
    osdi = os.path.join(HERE, f"_ll_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_ll_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_ll_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmlex\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def opvar(out, name):
    m = re.search(rf"@n1\[{name}\]\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


HDR = '`include "disciplines.vams"\n'

# ---- the committed module: literals, predefined macros, identifiers --------
print("lrmlex.va (run-time values):")
rc, out, osdi = compile_file("lrmlex.va")
check("[1] lrmlex.va compiles (begin_keywords, `resetall, assert/root/do, "
      "expression-position attributes)", rc == 0, out.strip().splitlines()[-1] if rc else "")
check("[2] `undef of a predefined macro draws the LRM 10.4 warning",
      "no effect on the predefined macro" in out)
if rc == 0:
    sim = run("N1 a 0 mm\nR1 a 0 1k\n.model mm lrmlex()",
              "op\nprint @n1[a] @n1[b] @n1[c] @n1[d] @n1[e]\n"
              "print @n1[f] @n1[g] @n1[h] @n1[i]\nprint @n1[ve] @n1[uk] @n1[xa]\n"
              "print @n1[e2] @n1[e3] @n1[e4] @n1[e5] @n1[opq]",
              "main", osdi)
    for name, want, why in [
        ("a", 3, "5 'D 3 (LRM Example 2)"),
        ("b", 849, "12'b 0011_0101_0001"),
        ("c", 255, "`SZ'hFF (macro-substituted size)"),
        ("d", 538623, "'h 837FF (LRM Example 1)"),
        ("e", -1, "8'sh FF (signed, space before digits)"),
        ("e2", 313257985, "32 'h 12ab_f001 (LRM Example 5; round-4 audit: lexed as a real)"),
        ("e3", 31, "'h 1f (digit + scale letter)"),
        ("e4", 485, "'h 1e5 (digit + exponent shape)"),
        ("e5", 26, "'h 1a (digit + scale letter)"),
        ("opq", 12, "`` pastes op+q into one identifier (19.3.1 via LRM 10.4)"),
        ("f", 255, "contiguous 8'hFF unchanged"),
        ("g", 172, "contiguous 'sb1010_1100 unchanged"),
        ("h", 15, "contiguous 'o17 unchanged"),
        ("i", -1, "contiguous 8'shFF unchanged"),
        ("ve", 1, "__VAMS_ENABLE__ defined (LRM 10.5)"),
        ("uk", 0, "`undef left __VAMS_COMPACT_MODELING__ alone... wait"),
    ]:
        got = opvar(sim, name)
        if name == "uk":
            # uk is 1 when the macro SURVIVED the `undef (ifdef took the branch)
            check("[3] `undef had no effect: __VAMS_COMPACT_MODELING__ still defined",
                  got == 1, f"{got}")
        else:
            check(f"[3] {why} = {want}", got == want, f"{got}")
    got = opvar(sim, "xa")
    check("[4] attribute suffixes on + and * do not change the value (2*3+1)",
          got is not None and abs(got - 7.0) < 1e-12, f"{got}")
    # 2.9: "the last attribute value shall be used" -- read the descriptor text
    dh = run("N1 a 0 mm\nR1 a 0 1k\n.model mm lrmlex()", "op\ndevhelp lrmlex",
             "devh", osdi)
    check("[5] duplicate attribute resolves to the LAST value in the descriptor",
          "last wins" in dh, "devhelp text")
    check("[2b] `\" stringifies a macro argument (19.3.1)", "MOPS1=[hello]" in sim)
    check("[2b] \\`\" places a quote inside the built string",
          'MOPS2=[v is \"v\"]' in sim)

# ---- srcloc + relative include ---------------------------------------------
print("\nsrcloc.va (`__FILE__/`__LINE__ next to a relative `include):")
rc, out, osdi = compile_file("srcloc.va")
check("[6] compiles: the rewrite no longer loses the include directory", rc == 0,
      out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    sim = run("N1 a 0 mm\nR1 a 0 1k\n.model mm srcloc()",
              "op\nprint @n1[lline] @n1[lv] @n1[il] @n1[l2]", "srcloc", osdi)
    check("[7] `__LINE__ is the exact 1-based use line", opvar(sim, "lline") == 14,
          f"{opvar(sim, 'lline')}")
    # LRM 10.7 (round-4 audit): an `include changes the expansions to the
    # included file, and `line declares the following line's number and file
    check("[7b] `__LINE__ inside the included file is ITS line 3",
          opvar(sim, "il") == 3, f"{opvar(sim, 'il')}")
    check("[7b] `__FILE__ inside the include is the include's basename",
          "INCFILE=[incuse.vah]" in sim)
    check("[7b] `__FILE__ in the root file is the root basename",
          "ROOTFILE=[srcloc.va]" in sim)
    check("[7b] `line 200 \"pinned.va\": the next line is 200",
          opvar(sim, "l2") == 200, f"{opvar(sim, 'l2')}")
    check("[7b] `line's declared file replaces `__FILE__",
          "LINEFILE=[pinned.va]" in sim)
    check("[8] the macro defined by the included file arrived", opvar(sim, "lv") == 41,
          f"{opvar(sim, 'lv')}")

# ---- directive diagnostics --------------------------------------------------
print("\ncompiler-directive diagnostics:")
rc, out, _ = compile_src(HDR + '`define __VAMS_MINE 1\n'
                         'module t1(p,n); inout p,n; electrical p,n;\n'
                         'analog I(p,n) <+ 1e-3*V(p,n);\nendmodule\n', "t1")
check("[9] `define in the reserved __VAMS_ namespace warns (LRM 10.4)",
      rc == 0 and "is reserved for a predefined macro" in out)

rc, out, _ = compile_src('`begin_keywords "1364-2005"\n' + HDR +
                         'module t2(p,n); inout p,n; electrical p,n;\n'
                         'analog I(p,n) <+ 1e-3*V(p,n);\nendmodule\n`end_keywords\n', "t2")
check("[10] a valid 1364-* keyword set is accepted with a not-narrowed warning",
      rc == 0 and 'treated as "VAMS-2023"' in out)

rc, out, _ = compile_src('`begin_keywords "PSPICE-9"\n' + HDR +
                         'module t3(p,n); inout p,n; electrical p,n;\n'
                         'analog I(p,n) <+ 1e-3*V(p,n);\nendmodule\n`end_keywords\n', "t3")
check("[11] an unknown version specifier warns and names the valid five",
      rc == 0 and "unknown '`begin_keywords' version specifier" in out)

rc, out, _ = compile_src('`end_keywords\n' + HDR +
                         'module t4(p,n); inout p,n; electrical p,n;\n'
                         'analog I(p,n) <+ 1e-3*V(p,n);\nendmodule\n', "t4")
check("[12] a stray `end_keywords warns instead of dying as an unknown macro",
      rc == 0 and "without a matching" in out)

rc, out, _ = compile_src(HDR + '`resetall\n'
                         'module t5(p,n); inout p,n; electrical p,n;\n'
                         'analog I(p,n) <+ 1e-3*V(p,n);\nendmodule\n', "t5")
check("[13] `resetall is silently honored (no 'unsupported compiler directive')",
      rc == 0 and "unsupported" not in out)

# ---- illegal forms now refused ---------------------------------------------
print("\nillegal lexical forms are located errors now:")
rc, out, _ = compile_src(HDR + 'module t6(p,n); inout p,n; electrical p,n; real x;\n'
                         'analog begin x = 1.; I(p,n) <+ x*1e-3*V(p,n); end\nendmodule\n', "t6")
check("[14] `1.` needs a digit on each side of the decimal point (LRM 2.6.2)",
      rc != 0 and "decimal point" in out)

rc, out, _ = compile_src(HDR + 'module t7(p,n); inout p,n; electrical p,n;\n'
                         'analog begin @(initial_step) $strobe("two\n'
                         'lines"); I(p,n) <+ 1e-3*V(p,n); end\nendmodule\n', "t7")
check("[15] a string spanning a raw newline is an error (LRM 2.7)",
      rc != 0 and "single line" in out)

rc, out, _ = compile_src(HDR + 'module t8(p,n); inout p,n; electrical p,n; integer a;\n'
                         "analog begin a = 4'b 29; I(p,n) <+ a*1e-3*V(p,n); end\nendmodule\n", "t8")
check("[16] white-space based literal with digits illegal for the base is an error",
      rc != 0 and "no valid digits" in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
