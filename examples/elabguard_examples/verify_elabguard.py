#!/usr/bin/env python3
"""verify_elabguard.py -- Enhancement-414: the elaboration passes, and the
declaration-level silences beside them.

THE HEADLINE, and the only one of these that changed an answer. An analog `genvar`
for-loop is unrolled TEXTUALLY, so the unroller has to find where one statement
ends. It recognised two shapes: a `begin`..`end` block, and "everything through the
next top-level `;`". Every other statement was cut at the first `;` inside it and
the remainder was spliced in AFTER the generated block. Usually that produced a
parse error pointing at `endmodule`, but for

    if (d > 0.5)
        for (i = 0; i < 2; i = i + 1)
            if (cc > 0.5) x = x + 1.0;
            else          x = x + 10.0;

the orphaned `else` re-attached to the ENCLOSING `if`. The module compiled with
rc=0 and no diagnostic, and computed a different program: three of the four
(d, cc) combinations came out wrong. `dangle_int` -- the identical source with an
`integer` index, which is not unrolled -- is the oracle.

THE SECOND CORRECTNESS FIX was found while fixing a crash. Enhancement-92 freezes a
parameter that shapes a declaration WIDTH into a localparam. The pass looked for
`[lo:hi]` groups mentioning a parameter, and a parameter's `from [lo:hi]` VALUE
constraint is spelled with the same brackets -- so `bb = 4 from [aa:8]` marked `aa`
structural and froze it. `.model .. (aa=5)` was then accepted and did nothing at
all. When the range mentioned its own parameter (`from [p:8]`) the freeze rewrote
text the range fold had already claimed, and the two overlapping rewrites panicked
the compiler.

WHAT IS DELIBERATELY NOT CHANGED HERE: a parameter's DEFAULT is still not range
checked. Enhancement-56 exempted it because CMC-standard models declare a default
outside the range as the "feature disabled" state (FBH-HBT's `Fb = 0.0 from
(0.0:inf)`), and enforcing it rejected stock models at setup. Ranges bind supplied
values, which paramrange_examples covers.

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
TMP = tempfile.gettempdir()


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(src_path, osdi, cwd=None):
    r = subprocess.run([OPENVAF, src_path, "-o", osdi], capture_output=True, text=True,
                       timeout=600, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def compile_text(name, text):
    """Compile a generated source; kept out of examples/ so the tree stays clean."""
    p = os.path.join(TMP, f"eg_{name}.va")
    with open(p, "w") as fh:
        fh.write(text)
    return compile_va(p, os.path.join(TMP, f"eg_{name}.osdi"))


def crashed(rc, log):
    # a signal is a NEGATIVE returncode; 101 is a Rust panic
    return rc == 101 or rc < 0 or "has crashed" in log


def run(name, deck, ctrl, osdi):
    p = os.path.join(TMP, f"eg_{name}.cir")
    with open(p, "w") as fh:
        fh.write(f"* elabguard {name}\n{deck}\n.control\npre_osdi {osdi}\n"
                 f"set numdgt=12\n{ctrl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=300)
    return "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "TEMP =" not in l)


def num(out, expr):
    m = re.findall(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


HDR = '`include "disciplines.vams"\n'


def mod(decls, body="I(a,c) <+ 1e-3*V(a,c);"):
    return (HDR + "module t(a,c); inout a,c; electrical a,c;\nreal x;\n" + decls
            + "\nanalog begin\n" + body + "\nend\nendmodule\n")


def main():
    print("Enhancement-414: elaboration passes and declaration-level silences\n")

    # ---------------------------------------------------------------- unroll
    print("  every statement shape as an unbraced genvar-loop body")
    osdi = os.path.join(TMP, "eg_unroll.osdi")
    rc, log = compile_va(os.path.join(HERE, "elab_unroll.va"), osdi)
    if not check("elab_unroll.va compiles", rc == 0 and os.path.exists(osdi),
                 "; ".join(log.strip().splitlines()[:2])):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    out = run("shapes", "v1 a 0 dc 1\nn1 a 0 mm\n.model mm shapes()", "op\n"
              + "\n".join(f"print @n1[{k}]" for k in
                          ("s_case", "s_ifb", "s_ifelse", "s_while", "s_repeat",
                           "s_for", "s_named", "s_nest")), osdi)
    # case: i=0 ->1, i=1 ->10, i=2 ->default 100        = 111
    # if/begin: 2 iterations x (1+2)                    = 6
    # if/else: i=0 ->1, i=1 ->10, i=2 ->1               = 12
    # while: 0 ->1 ->1.5, ->2.5 ->3.0, then 3.0 < 3.0 is false  = 3.0
    #        (the second unrolled copy finds the guard already false)
    # repeat: 2 x 3                                     = 6
    # nested integer for: 2 x 3                         = 6
    # named block: 1 + 4 + 9                            = 14
    # nested genvar: 2 x 3                              = 6
    for k, want in (("s_case", 111.0), ("s_ifb", 6.0), ("s_ifelse", 12.0),
                    ("s_while", 3.0), ("s_repeat", 6.0), ("s_for", 6.0),
                    ("s_named", 14.0), ("s_nest", 6.0)):
        got = num(out, f"@n1[{k}]")
        check(f"{k} = {want}", got is not None and abs(got - want) < 1e-9, f"got {got}")

    print("\n  the dangling `else`: unrolled must equal the integer-loop oracle")
    for d, cc, want in ((1.0, 1.0, 2.0), (1.0, 0.0, 20.0),
                        (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)):
        gv = num(run(f"dg{d}{cc}", f"v1 a 0 dc 1\nn1 a 0 mm\n"
                     f".model mm dangle_gv(d={d} cc={cc})", "op\nprint @n1[x]", osdi),
                 "@n1[x]")
        it = num(run(f"di{d}{cc}", f"v1 a 0 dc 1\nn1 a 0 mm\n"
                     f".model mm dangle_int(d={d} cc={cc})", "op\nprint @n1[x]", osdi),
                 "@n1[x]")
        check(f"d={d} cc={cc}: genvar {gv} == integer {it} == {want}",
              gv is not None and it is not None and gv == it and abs(gv - want) < 1e-9)

    print("\n  a named block inside the loop no longer collides with its own copies")
    check("`begin : blk` with a local declaration compiles",
          "already declared" not in log, log[:60])

    # ---------------------------------------------------------------- freeze
    print("\n  a parameter named in another parameter's `from` range stays settable")
    osdi_f = os.path.join(TMP, "eg_freeze.osdi")
    rc, log = compile_va(os.path.join(HERE, "elab_freeze.va"), osdi_f)
    check("elab_freeze.va compiles", rc == 0, "; ".join(log.strip().splitlines()[:1]))
    for knob, want_aa, want_i in (("", 2.0, -0.002), ("aa=5", 5.0, -0.005)):
        out = run("frz" + (knob or "def").replace("=", ""),
                  f"v1 a 0 dc 1\nn1 a 0 mm\n.model mm freeze({knob})",
                  "op\nprint @n1[seen_aa] i(v1)", osdi_f)
        check(f".model mm freeze({knob or '<defaults>'}) -> aa = {want_aa}",
              num(out, "@n1[seen_aa]") == want_aa
              and abs((num(out, "i(v1)") or 0) - want_i) < 1e-8,
              f"aa={num(out, '@n1[seen_aa]')} i={num(out, 'i(v1)')}")
    rc, log = compile_text("selfrange", mod("parameter integer p = 4 from [p:8];"))
    check("a range that mentions its own parameter does not crash the compiler",
          not crashed(rc, log), f"rc={rc}")
    check("...and is reported", rc != 0 and "references itself" in log,
          "; ".join(l for l in log.splitlines() if "error" in l)[:70])

    # ------------------------------------------------------------ alias cycles
    print("\n  an aliasparam cycle is an error, not a crash dump")
    for name, decls in (("self", "aliasparam pp = pp;"),
                        ("mutual", "aliasparam pp = qq;\naliasparam qq = pp;"),
                        ("three", "aliasparam q1 = q2;\naliasparam q2 = q3;\n"
                                  "aliasparam q3 = q1;")):
        rc, log = compile_text("alias_" + name, mod(decls))
        check(f"aliasparam {name}-cycle: no crash", not crashed(rc, log), f"rc={rc}")
        check(f"aliasparam {name}-cycle: reported",
              rc != 0 and "closes on itself" in log,
              "; ".join(l for l in log.splitlines() if "error" in l)[:64])
    rc, log = compile_text("alias_ok", mod("parameter real p = 1.0;\n"
                                           "aliasparam q1 = p;\naliasparam q2 = q1;"))
    check("a legitimate alias chain still compiles", rc == 0,
          "; ".join(log.strip().splitlines()[:1]))

    # ------------------------------------------------------------- self params
    print("\n  a declaration that reads itself")
    for name, decls, use in (("param", "parameter real p = p;", "p"),
                             ("localparam", "localparam real ls = ls + 1;", "ls"),
                             ("scaled", "localparam real l2 = l2*3 + 7;", "l2")):
        rc, log = compile_text("self_" + name,
                               mod(decls, f"I(a,c) <+ {use}*1e-3*V(a,c);"))
        check(f"self-referential {name} is reported",
              rc != 0 and "references itself" in log, f"rc={rc}")
    rc, log = compile_text("fwd", mod("parameter real q = 2.0;\nparameter real p = q;",
                                      "I(a,c) <+ p*1e-3*V(a,c);"))
    check("a backward reference still compiles", rc == 0)

    # ------------------------------------------------------------------ noise
    print("\n  a noise_table data file is validated, and an empty one contributed NOTHING")
    osdi_n = os.path.join(TMP, "eg_noise.osdi")
    rc, log = compile_va(os.path.join(HERE, "elab_noise.va"), osdi_n, cwd=HERE)
    check("elab_noise.va (usable file) compiles", rc == 0,
          "; ".join(log.strip().splitlines()[:1]))
    if rc == 0:
        deck = "v1 in 0 dc 0 ac 1\nr1 in a 1\nn1 a 0 mm\n.model mm %s()"
        ctrl = "noise v(a) v1 lin 1 1k 1k\nprint onoise_spectrum"
        with_noise = num(run("nzf", deck % "noisefile", ctrl, osdi_n), "onoise_spectrum")
        without = num(run("nzn", deck % "nonoise", ctrl, osdi_n), "onoise_spectrum")
        check("the file's noise actually reaches the spectrum",
              with_noise is not None and without is not None and with_noise > 2 * without,
              f"{with_noise} vs {without} with no source")
    bad = os.path.join(TMP, "eg_bad_noise.tbl")
    open(bad, "w").write("hello world\nnot numbers\n")
    for name, arg, why in (("missing", '"nosuchfile.tbl"', "a mistyped name"),
                           ("garbage", f'"{bad}"', "a file with no numbers")):
        rc, log = compile_text("nzbad_" + name,
                               HDR + "module t(a,c); inout a,c; electrical a,c;\n"
                               "analog begin I(a,c) <+ 1e-3*V(a,c);\n"
                               f"I(a,c) <+ noise_table({arg}); end\nendmodule\n")
        check(f"{why} is reported", rc != 0 and "as noise_table data" in log, f"rc={rc}")
    for fn in ("white_noise(-1e-16)", "flicker_noise(-1e-16, 1.0)"):
        rc, log = compile_text("nzneg_" + fn[:6],
                               HDR + "module t(a,c); inout a,c; electrical a,c;\n"
                               "analog begin I(a,c) <+ 1e-3*V(a,c);\n"
                               f"I(a,c) <+ {fn}; end\nendmodule\n")
        check(f"a negative power in {fn.split('(')[0]} is reported",
              rc != 0 and "must not be negative" in log, f"rc={rc}")
    rc, log = compile_text("nzrt", HDR + "module t(a,c); inout a,c; electrical a,c;\n"
                           "parameter real p = 1e-16;\n"
                           "analog begin I(a,c) <+ 1e-3*V(a,c);\n"
                           "I(a,c) <+ white_noise(p*abs(V(a,c))); end\nendmodule\n")
    check("a run-time noise power is left alone", rc == 0)

    # --------------------------------------------------------- branch (a,a)
    print("\n  a branch whose two endpoints are the same node")
    rc, log = compile_text("degen", mod("branch (a,a) br;",
                                        "I(br) <+ 1e-3*V(a,c);\nI(a,c) <+ 1e-9*V(a,c);"))
    check("branch (a,a) compiles but warns", rc == 0 and "L024" in log,
          "; ".join(l for l in log.splitlines() if "warning" in l)[:70])
    rc, log = compile_text("degen_ok", mod("branch (a,c) br;", "I(br) <+ 1e-3*V(br);"))
    check("a normal branch is silent", rc == 0 and "L024" not in log)

    # ------------------------------------------------------------ diagnostics
    print("\n  diagnostics that contradicted the compiler's own acceptance")
    rc, log = compile_text("arity_ad", mod("", "x = absdelay(V(a,c),1e-6,1e-5,3);\n"
                                               "I(a,c) <+ 1e-3*V(a,c)*x;"))
    check("absdelay with 4 args says 'at most 3' (3 are legal)",
          "at most 3 arguments" in log, "; ".join(
              l for l in log.splitlines() if "argument count" in l)[:64])
    rc, log = compile_text("arity_idt", mod("", "x = idt(V(a,c),1.0,V(a,c)>2.0,1e-9,5);\n"
                                                "I(a,c) <+ 1e-3*V(a,c)*x;"))
    check("idt with 5 args says 'at most 4' (4 are legal)", "at most 4 arguments" in log)
    rc, log = compile_text("elabnote",
                           HDR + "module t(a,c);\ninout a,c; electrical a,c;\nreal x;\n"
                           "genvar i;\nanalog begin\n x = 0.0;\n"
                           " for (i=0;i<2;i=i+1) x = x + i;\n"
                           " I(a,c) <+ 1e-3*V(a,c)*nosuchname;\nend\nendmodule\n")
    check("a diagnostic in an elaborated buffer says so",
          "elaborated copy of the source" in log,
          "; ".join(l for l in log.splitlines() if "note" in l)[:60])
    r = subprocess.run([OPENVAF, "--version"], capture_output=True, text=True, timeout=60)
    check("--version reports a version, not 'unknown'",
          "unknown" not in r.stdout.lower(), r.stdout.strip())

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
