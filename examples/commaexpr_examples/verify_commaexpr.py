#!/usr/bin/env python3
"""Enhancement-423: a parenthesised comma list is not an expression.

    r = (1.0, 2.0);        // compiled clean; r == 1.0
    r = (3.0, 2.0, 1.0);   // compiled clean; r == 3.0

`(a, b)` was accepted EVERYWHERE an expression is wanted and silently reduced to
its first element: ordinary expressions, `parameter`/`localparam` defaults,
elements of an array literal, `from`-range bounds, contributions,
access-function arguments, array indices (`a[(0,1)]` -> `a[0]`) and function-call
arguments (`max((1,2),3)` -> 3).

THE DROPPED ELEMENTS WERE NEVER CHECKED AT ALL. Every one of these compiled:

    (1.0, nosuchname)                  an undeclared name
    (1.0, nosuchfunc(3))               an undeclared function
    (1.0, "a string")                  a type error
    (1.0, max(1))                      a builtin with the wrong arity
    (1.0, last_crossing(V(p,n), 7))    an argument Enhancement-420 rejects

while `nosuchname` written alone is rejected, and `(nosuchname, 1.0)` is rejected
too -- confirming that only the first element was ever analysed. So this was not
merely a wrong answer; it was a place errors went to hide.

ROOT CAUSE. `parser/src/grammar/expressions.rs`, `paren_expr`, carried a
tuple-parsing loop over from rust-analyzer, with the giveaway comment still
sitting in it:

    // test tuple_attrs
    // const A: (i64, i64) = (1, #[cfg(test)] 2);

Verilog-A has no tuples. `hir_def/src/body/lower.rs` then does
`ParenExpr(e) => self.collect_opt_expr(e.expr())` -- `e.expr()` is the FIRST
child, so later children never reached the HIR and nothing downstream could see
them.

Enhancement-387's comment sits directly above that loop and lists the malformed
expression forms it enumerated (`{}`, `{1,}`, `a[]`, `? :`, `sqrt()`, `1+`). This
one was missed because it is not malformed *to that loop*. Its aggregate
siblings `{1,2}` and `'{1,2}` were already type-rejected -- the same "handled for
one form, silently not for its sibling" shape this project keeps finding.

WHY IT MATTERS, measured rather than asserted. Compact models are full of long
parenthesised sums split across lines. A comma where a `+` was meant:

    I(p,n) <+ (gm*V(p,n) ,        // meant +
               gds*V(p,n));

takes i(v1) from -5 mA to -1 mA -- a 5x wrong answer, silently. Likewise a
deleted builtin name: `pow(gm,2)` -> `(gm,2)` gives 3 instead of 9. Both are
checked below as numbers, not as diagnostics.

Also fixed: a TRAILING COMMA in a call argument list. `max(1.0, 2.0,)` was
accepted (the loop ended on the `)` and counted two arguments), while the same
trailing comma with one fewer argument, `max(1.0, )`, was caught only later by
the arity check. Both are a clean syntax error now.
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
COMMA = "a parenthesised list is not an expression"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_ce_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def crashed(rc, out):
    """openvaf's panic hook exits 101 with a banner and no backtrace (E-422)."""
    return (rc < 0 or "has crashed" in out or "openvaf-crash" in out or "panicked" in out)


def expr_mod(expr, decls=""):
    return (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n" + decls +
            ' (*desc="r"*) real r;\n analog begin\n  r = ' + expr + ";\n"
            "  I(p, n) <+ 1e-3*V(p, n);\n end\nendmodule\n")


def rejected(label, src, tag, needle=COMMA):
    _, rc, out = build(src, tag)
    ok = rc != 0 and needle in out and not crashed(rc, out)
    check(label, ok, f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:74])


def opvar(d, name="r"):
    open(os.path.join(d, "q.cir"), "w").write(
        "* probe\nV1 a 0 dc 1\nN1 a 0 dut\n.model dut dut()\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=12\nop\n"
        f"echo {name} = $&@n1[{name}]\nprint i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 40; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    txt = r.stdout + r.stderr
    m = re.search(r"^%s = (\S+)" % name, txt, re.M)
    i = re.search(r"^i\(v1\)\s*=\s*(\S+)", txt, re.M)
    return (float(m.group(1)) if m else None, float(i.group(1)) if i else None)


def accepted(label, expr, want, decls=""):
    """Compiles clean AND still computes the right number."""
    d, rc, out = build(expr_mod(expr, decls), "ok_" + re.sub(r"\W", "", expr)[:10])
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    if rc != 0 or noisy:
        check(label, False, f"rc={rc} " + (noisy or [""])[0][:66]); return
    got, _ = opvar(d)
    check(label, got is not None and abs(got - want) < 1e-9, f"{expr} -> {got}, want {want}")


def main():
    # =====================================================================
    print("\n[1] the comma list is rejected wherever it used to be accepted")
    for expr in ["(1.0, 2.0)", "(1.0, 2.0, 3.0)", "((1.0, 2.0))", "(1.0, 2.0)*10.0",
                 "max((1.0, 2.0), 3.0)", "(1.0,)", "((1.0, 2.0) > 0.5) ? 7.0 : 8.0"]:
        rejected(f"`{expr}` is rejected", expr_mod(expr), "r" + re.sub(r"\W", "", expr)[:10])

    print("\n[2] and in every OTHER position it reached")
    for tag, decl, use, note in [
        ("dflt", " parameter real q = (7.0, 8.0);", "q", "a parameter default"),
        ("lp",   " localparam real q = (7.0, 8.0);", "q", "a localparam"),
        ("arr",  " parameter real q[0:1] = '{(7.0,8.0), 2.0};", "q[0]",
                 "an element of an array literal"),
        ("idx",  " real a[0:3];", "a[(0,1)]", "an array index"),
        ("rng",  " parameter real q = 1.0 from [(0.0,1.0):10];", "q", "a from-range bound"),
    ]:
        src = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n" + decl +
               '\n (*desc="r"*) real r;\n analog begin\n  r = ' + use + ";\n"
               "  I(p, n) <+ 1e-3*V(p, n);\n end\nendmodule\n")
        rejected(f"{note}", src, "p_" + tag)
    rejected("a comma list scaling a contribution",
             HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
             " analog I(p, n) <+ (1e-3, 5e-3)*V(p, n);\nendmodule\n", "p_contrib")
    rejected("a comma list as an access-function argument",
             HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
             " analog I(p, n) <+ 1e-3*V((p, n));\nendmodule\n", "p_access")

    print("\n[3] the errors that used to HIDE in a dropped element are reported")
    # Each of these compiled clean before. What is asserted is that the file is
    # now REJECTED -- whether by the comma diagnostic or by the error that was
    # hiding, both of which are real problems the author needs to see.
    for tag, expr, note in [
        ("undef",  "(1.0, nosuchname)",                  "an undeclared name"),
        ("undef2", "(1.0, nosuchfunc(3))",               "an undeclared function"),
        ("type",   '(1.0, "a string")',                  "a type error"),
        ("arity",  "(1.0, max(1))",                      "a builtin with the wrong arity"),
        ("e420",   "(1.0, last_crossing(V(p,n), 7))",    "an argument E-420 rejects"),
    ]:
        _, rc, out = build(expr_mod(expr), "h_" + tag)
        check(f"{note} hidden in a dropped element no longer compiles",
              rc != 0 and not crashed(rc, out),
              f"rc={rc} " + (out.strip().splitlines() or [""])[0][:66])
    # the control: the same name alone was always rejected
    rejected("the control -- the same name alone -- is still rejected",
             expr_mod("nosuchname"), "h_ctl", "not found in the current scope")

    print("\n[4] ACCEPT half -- ordinary parentheses must be untouched")
    accepted("a plain parenthesised expression", "(1.0)", 1.0)
    accepted("a parenthesised sum", "(1.0+2.0)", 3.0)
    accepted("nested parentheses", "((1.0+2.0)*3.0)", 9.0)
    accepted("two parenthesised factors", "(1.0)*(2.0)", 2.0)
    accepted("a unary minus in parentheses", "(-1.0)", -1.0)
    accepted("a parenthesised condition of a ternary", "(1.0 > 0.5) ? 7.0 : 8.0", 7.0)
    accepted("a two-argument builtin", "max(1.0, 2.0)", 2.0)
    accepted("a two-argument builtin, nested", "pow(2.0, 3.0)", 8.0)
    # the two-argument $simparam: E-421 deliberately does not warn on this form,
    # and a name ngspice does not serve falls back to the default
    accepted("a two-argument system function",
             '$simparam("nosuchknob", 2.5)', 2.5)
    accepted("a parenthesised expression spanning lines",
             "(1.0 +\n       2.0)", 3.0)
    accepted("an array literal still takes commas", "q[1]", 2.0,
             decls=" parameter real q[0:1] = '{1.0, 2.0};\n")
    accepted("a function call with a parenthesised argument", "max((1.0+3.0), 2.0)", 4.0)

    print("\n[5] the realistic mistake, measured as a NUMBER")
    GOOD = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
            " parameter real gm = 1e-3;\n parameter real gds = 4e-3;\n"
            " analog begin\n  I(p, n) <+ (gm*V(p, n) +\n"
            "              gds*V(p, n));\n end\nendmodule\n")
    d, rc, out = build(GOOD, "m_good")
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    _, i = opvar(d) if rc == 0 else (None, None)
    check("the intended sum (with `+`) compiles and gives -5 mA",
          rc == 0 and not noisy and i is not None and abs(i + 5e-3) < 1e-12,
          f"rc={rc} i(v1)={i}")
    rejected("the same sum with a `,` where the `+` was meant is now rejected "
             "(it used to give -1 mA, a 5x wrong answer)",
             GOOD.replace("gm*V(p, n) +", "gm*V(p, n) ,"), "m_bad")
    rejected("a deleted builtin name -- `pow(gm,2)` written `(gm,2)` -- is rejected "
             "(it used to give 3 instead of 9)",
             HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
             " parameter real gm = 3.0;\n"
             ' (*desc="r"*) real r;\n analog begin\n  r = (gm, 2);\n'
             "  I(p, n) <+ 1e-3*V(p, n);\n end\nendmodule\n", "m_pow")

    print("\n[6] a trailing comma in a call argument list")
    for expr, note in [("max(1.0, 2.0,)", "two arguments and a trailing comma"),
                       ("max(1.0, )", "one argument and a trailing comma"),
                       ("pow(2.0, 3.0,)", "another builtin")]:
        _, rc, out = build(expr_mod(expr), "tc_" + re.sub(r"\W", "", expr)[:10])
        check(f"`{expr}` ({note}) is rejected", rc != 0 and not crashed(rc, out),
              f"rc={rc} " + (out.strip().splitlines() or [""])[0][:66])
    accepted("...and a call with no trailing comma still works", "max(1.0, 2.0)", 2.0)

    print("\n[7] the sibling aggregate forms are unchanged")
    rejected("a concatenation used as a real is still a TYPE error, not a syntax one",
             expr_mod("{1.0, 2.0}"), "s_cat", "type mismatch")
    rejected("an array literal used as a real is still a type error",
             expr_mod("'{1.0, 2.0}"), "s_arr", "type mismatch")

    for j in os.listdir(HERE):
        if j.startswith("_ce_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
