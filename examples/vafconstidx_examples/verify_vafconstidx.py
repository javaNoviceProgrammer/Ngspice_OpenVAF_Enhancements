#!/usr/bin/env python3
"""Enhancement-393: a `localparam` may index a bus, not merely size one.

A `localparam` is fixed at elaboration -- the LRM forbids overriding one
externally -- and this compiler already accepted it as a constant nearly
everywhere: array bounds, bus widths, parameter defaults, `repeat` counts, and
(since Enhancement-392) `generate` bounds. A **bit-select index** was the
exception:

    localparam integer K = 3;
    electrical [0:5] n;
    ... V(b, n[K]) ...      // error: bus bit-select index must be a constant

The same gap rejected a plain constant expression of literals, `n[2+1]`, because
the index folder recognised only a bare literal (optionally negated).

THREE PLACES RESOLVE A BIT-SELECT, and all three had to change, because two of
them run BEFORE name resolution and so could not ask for a parameter's value at
all:

  [1] an index in the analog body (`hir_ty`'s inference) -- the common case;
  [2] a BRANCH ENDPOINT, `branch (n[K], n[0])`, folded while the item tree is
      built, long before any name is resolved;
  [3] a PORT CONNECTION, `kid c(.p(bus[K]))`, which the instantiation elaborator
      resolves by synthesizing the textual name `bus[K]` and looking it up.

[1] is fixed semantically, by resolving the localparam and continuing the fold
inside that parameter's own body. [2] and [3] are fixed in the textual
declaration pre-pass that already folds parameter-dependent *widths*
(Enhancement-91/92), which is the only place early enough to serve them.

WHICH NAMES MAY BE FOLDED IS THE WHOLE QUESTION, and both halves answer it the
same way. Only what is fixed before the OSDI descriptor exists:

  * a `localparam`, and a localparam built from other localparams;
  * a `parameter` that Enhancement-92 froze into one because it shaped a
    declaration width -- indexing the very bus that parameter sized is then
    consistent by construction.

A plain `parameter` is refused, and so is a localparam whose value is built from
one: a parameter binds at simulation time, and baking its default into a node
selection would silently ignore an override from the model card. The semantic
folder gets this right structurally -- folding such a localparam requires folding
the parameter, which it will not do, so the whole chain fails.

WHAT THE ACCEPT HALF IS GUARDING. A genuine RUNTIME index into a variable array
(`arr[i]`, `i` a variable) must stay dynamic, a runtime index into a vectored NET
must stay an error (its bits are distinct simulator unknowns), and an oversized
literal must stay a bad *constant* rather than becoming a runtime index.

THE NUMERIC ORACLE. Compiling is not the claim -- selecting the RIGHT element is.
Every accept case below is simulated and compared against the literal spelling of
the same index, over a resistor ladder where tapping the wrong node gives a
different current.
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

# A 3 x 1k ladder across bus bits 0..3. Tapping bit k puts k resistors in the
# loop, so the operating-point current names the bit that was selected:
#   k=1 -> -1e-3, k=2 -> -5e-4, k=3 -> -3.333e-4
LADDER = ("  V(a, n[0]) <+ 0.0;\n"
          "  I(n[0],n[1]) <+ V(n[0],n[1])/1000;\n"
          "  I(n[1],n[2]) <+ V(n[1],n[2])/1000;\n"
          "  I(n[2],n[3]) <+ V(n[2],n[3])/1000;\n")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_ci_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def sim(d):
    open(os.path.join(d, "q.cir"), "w").write(
        "q\n.control\npre_osdi m.osdi\n.endc\n"
        "V1 a 0 dc 1\nN1 a 0 m\n.model m m()\n"
        ".control\noption noacct\nset numdgt=12\nop\nprint i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 30; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    return None if m is None else float(m.group(1))


def rejected(label, src, tag, needle):
    _, rc, out = build(src, tag)
    check(label, rc != 0 and needle in out and "panicked" not in out,
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:76])


def tap(label, decls, index, tag, want):
    """Tap the ladder at `index`; the current must match the literal spelling."""
    src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
           f" {decls}\n electrical [0:3] n;\n analog begin\n" + LADDER +
           f"  V(b, n[{index}]) <+ 0.0;\n end\nendmodule\n")
    d, rc, out = build(src, tag)
    got = sim(d) if rc == 0 else None
    check(label, got is not None and abs(got - want) < 1e-12,
          f"rc={rc} i(v1)={got} want={want} " + (out.strip().splitlines() or [""])[0][:40])


def main():
    # ---- [1] an index in the analog body -----------------------------------
    tap("literal n[3] (the reference)", "", "3", "lit3", -1.0 / 3000)
    tap("n[K], K a localparam", "localparam integer K = 3;", "K", "lpk", -1.0 / 3000)
    tap("n[K+1], an expression over a localparam",
        "localparam integer K = 2;", "K+1", "lpk1", -1.0 / 3000)
    tap("n[M], M built from another localparam",
        "localparam integer K = 1; localparam integer M = K + 2;", "M", "lpm", -1.0 / 3000)
    tap("n[K*3], multiplication", "localparam integer K = 1;", "K*3", "lpmul", -1.0 / 3000)
    tap("n[K/2], division", "localparam integer K = 6;", "K/2", "lpdiv", -1.0 / 3000)
    tap("n[2+1], a plain literal expression (also rejected before)",
        "", "2+1", "lit21", -1.0 / 3000)
    tap("n[7/2], literal division truncating toward zero", "", "7/2", "lit72", -1.0 / 3000)
    tap("a DIFFERENT localparam value selects a different bit (K=2)",
        "localparam integer K = 2;", "K", "lpk2", -5.0e-4)

    # E-92 composition: a parameter that sizes the bus is already frozen to a
    # localparam, so it may index that same bus.
    src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
           " parameter integer N = 3;\n electrical [0:N] n;\n analog begin\n" + LADDER +
           "  V(b, n[N]) <+ 0.0;\n end\nendmodule\n")
    d, rc, _ = build(src, "e92")
    got = sim(d) if rc == 0 else None
    check("n[N] where N also sizes `electrical [0:N]` (frozen by E-92)",
          got is not None and abs(got + 1.0 / 3000) < 1e-12, f"rc={rc} i(v1)={got}")

    # ---- [2] a branch endpoint ---------------------------------------------
    def branch_tap(label, decls, rng, index, tag, want):
        src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
               f" {decls}\n electrical {rng} n;\n"
               f" branch (n[{index}], n[0]) br;\n analog begin\n" + LADDER +
               "  I(br) <+ V(br)/1000;\n  V(b, n[3]) <+ 0.0;\n end\nendmodule\n")
        d, rc, out = build(src, tag)
        got = sim(d) if rc == 0 else None
        check(label, got is not None and abs(got - want) < 1e-12,
              f"rc={rc} i(v1)={got} want={want} " + (out.strip().splitlines() or [""])[0][:40])

    # 3k ladder in parallel with the 1k branch = 750R
    branch_tap("branch (n[3], n[0]) literal (the reference)",
               "", "[0:3]", "3", "br3", -1.0 / 750)
    branch_tap("branch (n[K], n[0]), K a localparam",
               "localparam integer K = 3;", "[0:3]", "K", "brk", -1.0 / 750)
    branch_tap("branch (n[N], n[0]) where N also sizes the bus",
               "parameter integer N = 3;", "[0:N]", "N", "brn", -1.0 / 750)

    # ---- [3] a port connection ---------------------------------------------
    src = (HDR + "module kid(p, n);\n inout p, n; electrical p, n;\n"
           " analog I(p, n) <+ V(p, n)/1000;\nendmodule\n"
           "module m(a, b);\n inout a, b; electrical a, b;\n"
           " localparam integer K = 3;\n electrical [0:3] n;\n"
           " kid c(.p(n[K]), .n(n[0]));\n analog begin\n" + LADDER +
           "  V(b, n[3]) <+ 0.0;\n end\nendmodule\n")
    d, rc, out = build(src, "port")
    got = sim(d) if rc == 0 else None
    check("a port connection `.p(n[K])` resolves to the same bit",
          got is not None and abs(got + 1.0 / 750) < 1e-12,
          f"rc={rc} i(v1)={got} " + (out.strip().splitlines() or [""])[0][:40])

    # ---- other array kinds --------------------------------------------------
    def val(label, decls, body, tag, want):
        src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
               f" {decls}\n analog begin\n{body}\n end\nendmodule\n")
        d, rc, out = build(src, tag)
        got = sim(d) if rc == 0 else None
        check(label, got is not None and abs(got - want) < 1e-12,
              f"rc={rc} i(v1)={got} want={want} " + (out.strip().splitlines() or [""])[0][:40])

    val("a variable array read arr[K]",
        "localparam integer K = 3; real arr[0:5];",
        "  arr[0]=10.0; arr[1]=20.0; arr[2]=30.0; arr[3]=40.0; arr[4]=50.0; arr[5]=60.0;\n"
        "  I(a,b) <+ arr[K]*1e-3;", "arrk", -0.04)
    val("a variable array WRITE arr[K] lands in the same element",
        "localparam integer K = 3; real arr[0:5];",
        "  arr[0]=0; arr[1]=0; arr[2]=0; arr[3]=0; arr[4]=0; arr[5]=0;\n"
        "  arr[K] = 40.0;\n  I(a,b) <+ arr[3]*1e-3;", "arrw", -0.04)
    val("a parameter array pa[K]",
        "parameter real pa[0:5] = '{10.0,20.0,30.0,40.0,50.0,60.0}; localparam integer K = 3;",
        "  I(a,b) <+ pa[K]*1e-3;", "park", -0.04)
    val("a 2-D array m2[K-2][K]",
        "localparam integer K = 3; real m2[0:2][0:3];",
        "  m2[1][3] = 40.0;\n  I(a,b) <+ m2[K-2][K]*1e-3;", "m2k", -0.04)

    # ======================= REJECT HALF ====================================
    # A `parameter` binds at simulation time. Folding its default into a node
    # selection would silently ignore an override from the model card.
    body_p = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
              " parameter integer P = 3;\n electrical [0:3] n;\n analog begin\n" + LADDER +
              "  V(b, n[P]) <+ 0.0;\n end\nendmodule\n")
    rejected("a plain `parameter` index is STILL rejected", body_p, "rp",
             "bit-select index must be a constant")

    body_l = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
              " parameter integer P = 3;\n localparam integer L = P;\n"
              " electrical [0:3] n;\n analog begin\n" + LADDER +
              "  V(b, n[L]) <+ 0.0;\n end\nendmodule\n")
    rejected("a localparam DERIVED FROM a parameter is STILL rejected", body_l, "rl",
             "bit-select index must be a constant")

    src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
           " parameter integer P = 3;\n electrical [0:3] n;\n"
           " branch (n[P], n[0]) br;\n analog begin\n" + LADDER +
           "  I(br) <+ V(br)/1000;\n  V(b, n[3]) <+ 0.0;\n end\nendmodule\n")
    rejected("a plain `parameter` BRANCH endpoint is STILL rejected", src, "rbr",
             "bit-select index is not a constant")

    # out of range is reported as out of range, not as "not a constant"
    src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
           " localparam integer K = 9;\n electrical [0:3] n;\n analog begin\n" + LADDER +
           "  V(b, n[K]) <+ 0.0;\n end\nendmodule\n")
    rejected("an out-of-range localparam index says OUT OF RANGE", src, "roor",
             "out of range")

    # ======================= ACCEPT HALF ====================================
    # A genuine runtime index must stay dynamic.
    val("a RUNTIME index arr[i] still works (i a variable)",
        "real arr[0:5]; integer i;",
        "  for (i=0; i<6; i=i+1) arr[i] = i*10.0;\n  i = 4;\n  I(a,b) <+ arr[i]*1e-3;",
        "dyn", -0.04)

    # ...and a runtime index into a vectored NET must stay an error: its bits are
    # distinct simulator unknowns, so there is nothing to select at runtime.
    src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
           " electrical [0:3] n;\n integer i;\n analog begin\n  i = 2;\n" + LADDER +
           "  V(b, n[i]) <+ 0.0;\n end\nendmodule\n")
    rejected("a runtime index into a vectored NET is still an error", src, "netdyn",
             "bit-select index must be a constant")

    # an oversized literal is a bad CONSTANT, not a runtime index
    src = (HDR + "module m(a, b);\n inout a, b; electrical a, b;\n"
           " electrical [0:3] n;\n analog begin\n" + LADDER +
           "  V(b, n[99999999999999]) <+ 0.0;\n end\nendmodule\n")
    rejected("an oversized literal index stays a bad constant", src, "big",
             "bit-select index must be a constant")

    for j in os.listdir(HERE):
        if j.startswith("_ci_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
