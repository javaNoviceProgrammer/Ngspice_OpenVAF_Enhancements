#!/usr/bin/env python3
"""Enhancement-420: six openvaf-r defects from a round-26 hunt, all of one shape.

Every one of them was ACCEPTED BY THE COMPILER AND THEN SILENTLY DEGENERATE. No
crash, no hang, no diagnostic -- the model built, the simulation ran, and the
answer was either wrong or the construct simply did nothing. That is the worst
failure mode this project keeps finding, because there is no symptom to search
for: the author reads source that says one thing and gets behaviour that says
another.

  [1] `laplace_nd(V(a,b), '{1.0}, '{0.0})` -- AN IDENTICALLY ZERO DENOMINATOR.

      The transfer function is 1/0. It compiled clean; at run time the operating
      point failed with

          Transient op failed, timestep too small

      which names neither the model nor the call. The author debugs the netlist.

      Only a COEFFICIENT list is checked, and only when every element folds to a
      literal zero. An all-zero ROOT list (`laplace_np`, `laplace_zp`, `zi_np`,
      `zi_zp`) means poles at the origin -- a pure integrator, perfectly
      legitimate -- and so does a single leading zero, `'{0.0, 1.0}` being the
      denominator `s`. The accept half below pins all of those down.

  [2] `zi_nd(V(a,b), '{1.0}, '{1.0}, 0.0, 0.0)` -- A ZERO SAMPLING PERIOD.

      T is what the whole z-domain filter is defined against. With T = 0 the
      model compiled, ran, and returned the INPUT UNCHANGED: y = 1.0 for a unit
      input. A filter that is not a filter, reported nowhere.

  [3] `last_crossing(V(a,b) - 0.5, 7)` -- A DIRECTION THAT IS NOT A DIRECTION.

      The LRM defines exactly three: +1 rising, -1 falling, 0 either. `7` was
      accepted and behaved as 0, returning the same 5.0e-07 the `either` form
      does. A direction is a spelled-out constant in every real model, so the
      typo is catchable at compile time.

  [4] `$discontinuity(-3)` -- A DEGREE THAT NAMES NOTHING.

      The degree is the order of the derivative that jumps: 0 the value, 1 the
      slope. Below that exactly one value means anything, and it is -1: the
      LRM's marker for a limiting discontinuity inside a `$limit` function.
      Everything under -1 was silently treated as an ordinary non-negative
      degree.

      THE FIRST VERSION OF THIS CHECK WAS `require_non_negative` AND IT WAS
      WRONG. `$discontinuity(-1)` appears verbatim in the LRM's own page-261
      `spicepnjlim` diode, and `lower_builtin` routes it to `LimDiscontinuity`
      -- it is implemented, not tolerated. examples/lrm_examples compiles that
      page and caught the over-reach on the first regression sweep. The check
      shipped here rejects only what is below -1, which is what the evidence
      supports.

  [5] `2 ** -1` WITH TWO INTEGER OPERANDS GAVE 1. THE STANDARD SAYS 0.

      The substantive one. `**` was typed real unconditionally, so both operands
      were promoted to float, `llvm.pow.f64` ran, and the real result was
      rounded back AWAY FROM ZERO wherever an integer was wanted. IEEE
      1364-2005 Table 5-6 defines integer `**` exactly: for |base| > 1 and a
      negative exponent the result is 0. openvaf returned 1 -- off by a whole
      unit, from source that compiled clean.

      `**` is now an integer expression when both operands are integers (the
      standard: the result is real only if either operand is real), and the
      lowering implements Table 5-6. A signature change alone would have left
      the same float `pow` sitting behind an integer type; that trap is on
      record from E-376, where `$dist_*` needed the lowering ficast too.

      The differential turned up a SECOND case the hunt had not reported:
      `0 ** -1` returned 2147483647. That is `llvm.lround` of an infinity --
      floating-point `pow(0, -1)` is inf, and rounding an infinity into an i32
      is undefined. Table 5-6 calls `0 ** negative` `'x`, which is 0 in an
      integer context. The fix clamps the exponent the float path sees, so the
      infinity is never produced rather than merely never used.

  [6] `ac_stim("nosuch", 1.0, 0.0)` GOT NO DIAGNOSTIC AT ALL.

      The project's recurring shape: handled for one construct, silently not for
      its sibling. `analysis("nosuch")` has warned since E-399 (L021) and
      `$limit(.., "nosuchlimit", ..)` since E-396 (L020). All three name
      something that can never match. ngspice gates the stimulus on
      `strcmp(src->analysis, "ac")` in osdiacld.c, so an unmatchable name leaves
      the source PERMANENTLY INACTIVE -- and the runtime half of this script
      measures exactly that, rather than taking the diagnostic's word for it.

      A warning, not an error, for the same reason L020 and L021 are: the set of
      analysis names is simulator-defined and another OSDI consumer may match
      more.

A checker that rejects too much is worse than one that rejects nothing, because
it breaks working models. Half of what follows is the ACCEPT half.
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


def build(src, tag):
    d = os.path.join(HERE, "_dg_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def rejected(label, src, tag, needle):
    _, rc, out = build(src, tag)
    check(label, rc != 0 and needle in out and "panicked" not in out,
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:78])


def accepted(label, src, tag):
    _, rc, out = build(src, tag)
    ok = rc == 0 and "error" not in out
    check(label, ok, f"rc={rc} " + (out.strip().splitlines() or [""])[0][:70])
    return ok


def warned(label, src, tag, needle):
    """A LINT: the model must still BUILD, and the text must be there."""
    _, rc, out = build(src, tag)
    check(label, rc == 0 and needle in out,
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:78])


def unwarned(label, src, tag, needle):
    _, rc, out = build(src, tag)
    check(label, rc == 0 and needle not in out,
          f"rc={rc} " + (out.strip().splitlines() or [""])[0][:70])


def dut(body, decls="", card_params=""):
    return (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
            + decls + " analog begin\n" + body + " end\nendmodule\n")


def opvars(d, names):
    """Run an operating point and read back a list of opvars by name."""
    lines = "\n".join(f"echo {k} = $&@n1[{k}]" for k in names)
    open(os.path.join(d, "q.cir"), "w").write(
        "* opvar readback\nV1 a 0 dc 1\nN1 a 0 dut\n.model dut dut()\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=12\nop\n"
        + lines + "\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    txt = r.stdout + r.stderr
    got = {}
    for k in names:
        m = re.search(r"^%s = (\S+)" % re.escape(k), txt, re.M)
        got[k] = None if m is None else float(m.group(1))
    return got


def ac_mag(d, model="dut"):
    """One-point .ac; returns |v(out)| for a model driven only by its ac_stim.

    Same shape as acstim_examples/_a.cir: a ONE-terminal voltage source, so a
    live stimulus of magnitude 1 reads back as exactly 1.0 and a dead one as
    exactly 0.0 -- no divider, no tolerance to argue about.
    """
    open(os.path.join(d, "a.cir"), "w").write(
        f"* ac_stim activity\nNDUT out {model}\n.model {model} {model}()\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=12\n"
        "ac lin 1 1k 1k\nprint mag(v(out))\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "a.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    m = re.search(r"^mag\(v\(out\)\)\s*=\s*(\S+)", r.stdout + r.stderr, re.M)
    return None if m is None else float(m.group(1))


def main():
    # =====================================================================
    # [1] laplace: an identically zero DENOMINATOR
    # =====================================================================
    print("\n[1] laplace_* -- an identically zero denominator")
    ZERO_DEN = "is identically zero"
    rejected("laplace_nd with denominator '{0.0} is rejected",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{0.0});\n"), "l_nd0", ZERO_DEN)
    rejected("a LONGER all-zero denominator is rejected too",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{0.0, 0.0, 0.0});\n"),
             "l_nd000", ZERO_DEN)
    rejected("written as integer zeros, still rejected",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{0, 0});\n"), "l_ndi", ZERO_DEN)
    rejected("negative zero is zero",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{-0.0});\n"), "l_ndnz", ZERO_DEN)
    rejected("laplace_zd (denominator is also COEFFICIENTS) is rejected",
             dut(" I(p, n) <+ laplace_zd(V(p, n), '{1.0}, '{0.0, 0.0});\n"),
             "l_zd0", ZERO_DEN)
    rejected("zi_nd with an all-zero denominator is rejected",
             dut(" I(p, n) <+ zi_nd(V(p, n), '{1.0}, '{0.0}, 1e-9, 0.0);\n"),
             "z_nd0", ZERO_DEN)

    # ---- accept half: every legitimate denominator must still build ------
    accepted("an ordinary first-order denominator",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{1.0, 1e-6});\n"), "l_ok1")
    accepted("a LEADING zero is a pure integrator, not a degenerate filter",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{0.0, 1.0});\n"), "l_ok2")
    accepted("an all-zero POLE list means poles at the origin -- legitimate",
             dut(" I(p, n) <+ laplace_np(V(p, n), '{1.0}, '{0.0, 0.0});\n"), "l_ok3")
    accepted("laplace_zp with all-zero poles",
             dut(" I(p, n) <+ laplace_zp(V(p, n), '{1.0}, '{0.0, 0.0});\n"), "l_ok4")
    accepted("zi_np with an all-zero POLE list",
             dut(" I(p, n) <+ zi_np(V(p, n), '{1.0}, '{0.0}, 1e-9, 0.0);\n"), "l_ok5")
    accepted("a RUNTIME denominator element is left alone (nothing is folded)",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{1.0}, '{z});\n",
                 decls=" parameter real z = 0.0;\n"), "l_ok6")
    accepted("a CONCATENATION still compiles -- laplace lowers it correctly (E-399)",
             dut(" I(p, n) <+ laplace_nd(V(p, n), {1.0}, {1.0, 1e-6});\n"), "l_ok7")
    accepted("an EMPTY numerator (H = 0) still compiles (E-405)",
             dut(" I(p, n) <+ laplace_nd(V(p, n), '{}, '{1.0});\n"), "l_ok8")

    # =====================================================================
    # [2] zi_*: the sampling period
    # =====================================================================
    print("\n[2] zi_* -- the sampling period")
    PERIOD = "the sampling period must be greater than zero"
    for tag, form in [("nd", "zi_nd(V(p, n), '{1.0}, '{1.0}, 0.0, 0.0)"),
                      ("np", "zi_np(V(p, n), '{1.0}, '{1.0}, 0.0, 0.0)"),
                      ("zd", "zi_zd(V(p, n), '{1.0}, '{1.0}, 0.0, 0.0)"),
                      ("zp", "zi_zp(V(p, n), '{1.0}, '{1.0}, 0.0, 0.0)")]:
        rejected(f"zi_{tag} with T = 0 is rejected",
                 dut(f" I(p, n) <+ {form};\n"), "t0_" + tag, PERIOD)
    rejected("a NEGATIVE sampling period is rejected",
             dut(" I(p, n) <+ zi_nd(V(p, n), '{1.0}, '{1.0}, -1e-9, 0.0);\n"),
             "tneg", PERIOD)
    accepted("a positive literal period",
             dut(" I(p, n) <+ zi_nd(V(p, n), '{1.0}, '{1.0}, 1e-9, 0.0);\n"), "t_ok1")
    accepted("a RUNTIME period is left alone",
             dut(" I(p, n) <+ zi_nd(V(p, n), '{1.0}, '{1.0}, ts, 0.0);\n",
                 decls=" parameter real ts = 1e-9;\n"), "t_ok2")
    accepted("the 6-argument form with a positive period",
             dut(" I(p, n) <+ zi_nd(V(p, n), '{1.0}, '{1.0}, 1e-9, 0.0, 1e-12);\n"),
             "t_ok3")

    # =====================================================================
    # [3] last_crossing: the direction
    # =====================================================================
    print("\n[3] last_crossing -- the direction")
    DIRN = "it must be +1 (rising), -1 (falling) or 0 (either)"
    LC = " r = last_crossing(V(p, n) - 0.5, %s);\n I(p, n) <+ 1e-3*V(p, n) + 0.0*r;\n"
    for bad in ("7", "2", "-2", "-7", "100"):
        rejected(f"last_crossing direction {bad} is rejected",
                 dut(LC % bad, decls=" real r;\n"), "lc%s" % bad.replace("-", "m"), DIRN)
    for good in ("1", "-1", "0", "+1"):
        accepted(f"direction {good} is accepted",
                 dut(LC % good, decls=" real r;\n"), "lcok%s" % good.replace("-", "m")
                 .replace("+", "p"))
    accepted("the one-argument form (no direction at all) is accepted",
             dut(" r = last_crossing(V(p, n) - 0.5);\n I(p, n) <+ 1e-3*V(p, n) + 0.0*r;\n",
                 decls=" real r;\n"), "lcnone")
    accepted("a RUNTIME direction is left alone",
             dut(LC % "d", decls=" real r;\n parameter integer d = 1;\n"), "lcrt")

    # =====================================================================
    # [4] $discontinuity: the degree
    # =====================================================================
    print("\n[4] $discontinuity -- the degree")
    DEG = "nothing below -1 names a discontinuity"
    for bad in ("-2", "-3", "-10"):
        rejected(f"$discontinuity({bad}) is rejected",
                 dut(f" $discontinuity({bad});\n I(p, n) <+ 1e-3*V(p, n);\n"),
                 "dg%s" % bad.replace("-", "m"), DEG)
    for good in ("0", "1", "3"):
        accepted(f"$discontinuity({good}) is accepted",
                 dut(f" $discontinuity({good});\n I(p, n) <+ 1e-3*V(p, n);\n"),
                 "dgok%s" % good)
    accepted("a bare `$discontinuity;` is accepted (degree 0, E-395)",
             dut(" $discontinuity;\n I(p, n) <+ 1e-3*V(p, n);\n"), "dgbare")
    accepted("$discontinuity(-1) is accepted -- the LRM's limiting marker",
             dut(" $discontinuity(-1);\n I(p, n) <+ 1e-3*V(p, n);\n"), "dgm1")

    # the LRM's own page-261 shape: -1 inside a $limit function. This is the
    # exact construct the first version of the check broke.
    LIMSRC = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
              " analog function real lim1;\n  input vn, vo;\n  real vn, vo, v;\n"
              "  begin\n   v = vn;\n   if (v > 0.7) begin\n    v = 0.7;\n"
              "    $discontinuity(-1);\n   end\n   lim1 = v;\n  end\n endfunction\n"
              " analog I(p, n) <+ 1e-3*$limit(V(p, n), lim1);\nendmodule\n")
    accepted("the LRM p.261 shape -- $discontinuity(-1) inside a $limit function",
             LIMSRC, "dglim")

    # =====================================================================
    # [5] integer ** -- IEEE 1364-2005 Table 5-6
    # =====================================================================
    print("\n[5] `**` with two integer operands -- Table 5-6")
    # (expression, expected integer result). `-1 ** -3` is (-1) ** (-3): unary
    # minus binds tighter than `**`, which round-26 verified is already correct.
    TABLE = [
        ("2 ** -1", 0),          # |base| > 1, negative exponent -> 0. WAS 1.
        ("2 ** -3", 0),
        ("7 ** -2", 0),
        ("-3 ** -2", 0),         # base < -1
        ("1 ** -5", 1),          # base 1 -> always 1
        ("1 ** -6", 1),
        ("-1 ** -3", -1),        # base -1, odd exponent
        ("-1 ** -4", 1),         # base -1, even exponent
        ("-1 ** 3", -1),
        ("-1 ** 4", 1),
        ("0 ** -1", 0),          # 'x in Table 5-6 -> 0 as an integer. WAS 2147483647.
        ("0 ** -7", 0),
        ("0 ** 0", 1),           # any base ** 0 -> 1
        ("2 ** 0", 1),
        ("-5 ** 0", 1),
        ("0 ** 3", 0),
        ("2 ** 10", 1024),       # the ordinary path must not move
        ("3 ** 5", 243),
        ("-2 ** 3", -8),
        ("-2 ** 4", 16),
    ]
    names = ["v%d" % i for i in range(len(TABLE))]
    decls = "".join(f' (*desc="{e}"*) integer {k};\n' for k, (e, _) in zip(names, TABLE))
    body = "".join(f"  {k} = {e};\n" for k, (e, _) in zip(names, TABLE))
    d, rc, out = build(dut(body + "  I(p, n) <+ 1e-3*V(p, n);\n", decls=decls), "pow")
    if check("the Table 5-6 probe model builds", rc == 0,
             (out.strip().splitlines() or [""])[0][:70]):
        pass
    got = opvars(d, names) if rc == 0 else {k: None for k in names}
    for k, (expr, want) in zip(names, TABLE):
        v = got[k]
        check(f"`{expr}` == {want}", v is not None and int(round(v)) == want,
              f"got {v}")

    # the REAL path must not have moved: if either operand is real the result is
    # real, and 2.0 ** -1 is 0.5, not 0.
    RTABLE = [("2.0 ** -1.0", 0.5), ("2.0 ** -1", 0.5), ("2 ** -1.0", 0.5),
              ("2.0 ** 0.5", 1.4142135623730951), ("9.0 ** 0.5", 3.0)]
    rnames = ["r%d" % i for i in range(len(RTABLE))]
    decls = "".join(f' (*desc="{e}"*) real {k};\n' for k, (e, _) in zip(rnames, RTABLE))
    body = "".join(f"  {k} = {e};\n" for k, (e, _) in zip(rnames, RTABLE))
    d, rc, _ = build(dut(body + "  I(p, n) <+ 1e-3*V(p, n);\n", decls=decls), "rpow")
    got = opvars(d, rnames) if rc == 0 else {k: None for k in rnames}
    for k, (expr, want) in zip(rnames, RTABLE):
        v = got[k]
        # `echo $&@n1[..]` prints six significant digits whatever numdgt says,
        # so the tolerance is the PRINTER's, not the arithmetic's.
        check(f"`{expr}` == {want} (a real operand keeps the real result)",
              v is not None and abs(v - want) <= 1e-5 * max(abs(want), 1.0), f"got {v}")

    # a RUNTIME integer exponent must follow the same table, not just literals
    RT = [(2, -1, 0), (2, 3, 8), (-1, -3, -1), (-1, -4, 1), (1, -9, 1), (0, -1, 0),
          (5, 0, 1), (-2, 5, -32)]
    rtn = ["q%d" % i for i in range(len(RT))]
    decls = ("".join(f" (*desc=\"q{i}\"*) integer {k};\n" for i, k in enumerate(rtn))
             + "".join(f" parameter integer b{i} = {b};\n parameter integer e{i} = {e};\n"
                       for i, (b, e, _) in enumerate(RT)))
    body = "".join(f"  {k} = b{i} ** e{i};\n" for i, k in enumerate(rtn))
    d, rc, _ = build(dut(body + "  I(p, n) <+ 1e-3*V(p, n);\n", decls=decls), "rtpow")
    got = opvars(d, rtn) if rc == 0 else {k: None for k in rtn}
    for k, (b, e, want) in zip(rtn, RT):
        v = got[k]
        check(f"runtime `{b} ** {e}` == {want}",
              v is not None and int(round(v)) == want, f"got {v}")

    # CONST CONTEXTS and the one further consequence of the type change.
    #
    # `**` becoming integer-typed also changes what an expression CONTAINING it
    # does: `1 / (2 ** 3)` was 0.125 and is now 0. That is the same change, not a
    # side effect -- `1 / 8` with two integer operands has always truncated to 0
    # here, so `**` was the one arithmetic operator escaping integer arithmetic.
    # It is the only way an existing model can change answer, so it is pinned
    # BOTH ways rather than left to be discovered.
    CTX = [
        ("pn", "integer", "pn", 0, " parameter integer pn = 2 ** -1;\n"),
        ("pr", "real", "pr", 8.0, " parameter real pr = 2 ** 3;\n"),
        ("lp", "integer", "lp", 81, " localparam integer lp = 3 ** 4;\n"),
        ("dv", "real", "1/(2 ** 3)", 0.0, ""),      # integer division, as `1/8` is
        ("rv", "real", "1.0/(2 ** 3)", 0.125, ""),  # a real numerator keeps it real
    ]
    decls = "".join(d for _, _, _, _, d in CTX) + "".join(
        f' (*desc="{k}"*) {t} o_{k};\n' for k, t, _, _, _ in CTX)
    body = "".join(f"  o_{k} = {e};\n" for k, _, e, _, _ in CTX)
    d, rc, _ = build(dut(body + "  I(p, n) <+ 1e-3*V(p, n);\n", decls=decls), "ctx")
    got = opvars(d, ["o_" + k for k, _, _, _, _ in CTX]) if rc == 0 else {}
    for k, _, expr, want, _ in CTX:
        v = got.get("o_" + k)
        check(f"`{expr}` == {want} (constant context / integer division)",
              v is not None and abs(v - want) <= 1e-9, f"got {v}")

    # an analog function taking its operands as runtime integer arguments
    FN = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
          ' (*desc="f"*) integer o_f;\n'
          " analog function integer ipw;\n  input x, y;\n  integer x, y;\n"
          "  ipw = x ** y;\n endfunction\n"
          " analog begin\n  o_f = ipw(2, -1);\n  I(p, n) <+ 1e-3*V(p, n);\n"
          " end\nendmodule\n")
    d, rc, _ = build(FN, "fnpow")
    v = opvars(d, ["o_f"])["o_f"] if rc == 0 else None
    check("inside an analog function, `2 ** -1` is 0 too",
          v is not None and int(round(v)) == 0, f"got {v}")

    # =====================================================================
    # [6] ac_stim: an analysis name that can never match
    # =====================================================================
    print("\n[6] ac_stim -- an unmatchable analysis name")
    L021 = "which no analysis can ever match"
    warned("ac_stim(\"nosuch\", ..) warns (L021), and still BUILDS",
           dut(' I(p, n) <+ 1e-3*V(p, n) + ac_stim("nosuch", 1.0, 0.0);\n'),
           "acbad", L021)
    warned("the diagnostic says the stimulus is PERMANENTLY INACTIVE",
           dut(' I(p, n) <+ 1e-3*V(p, n) + ac_stim("nosuch", 1.0, 0.0);\n'),
           "acbad2", "permanently inactive")
    warned("the one-argument form warns too",
           dut(' I(p, n) <+ 1e-3*V(p, n) + ac_stim("nosuch");\n'), "acbad3", L021)
    # The check is exactly `analysis()`'s: a name OUTSIDE the seven the simulator
    # can ever match. It deliberately does NOT insist on "ac". ngspice's own gate
    # is `strcmp(src->analysis, "ac")`, so `ac_stim("tran")` is inactive there
    # too -- but the LRM lets a stimulus name any analysis, and another OSDI
    # consumer may honour more than ngspice does. Narrowing to what can never
    # match anywhere is the claim the evidence supports; see Enhancement-420.md.
    unwarned('ac_stim("tran") is silent -- a matchable name, narrowly scoped check',
             dut(' I(p, n) <+ 1e-3*V(p, n) + ac_stim("tran", 1.0, 0.0);\n'),
             "actran", L021)
    unwarned('ac_stim("ac", ..) is silent',
             dut(' I(p, n) <+ 1e-3*V(p, n) + ac_stim("ac", 1.0, 0.0);\n'), "acok", L021)
    unwarned("the no-argument form ac_stim() is silent",
             dut(' I(p, n) <+ 1e-3*V(p, n) + ac_stim();\n'), "acok2", L021)
    unwarned("analysis() itself is unchanged -- a known name stays silent",
             dut(' if (analysis("ac")) I(p, n) <+ 1e-3*V(p, n);\n'
                 ' else I(p, n) <+ 2e-3*V(p, n);\n'), "anok", L021)

    # THE RUNTIME HALF. The diagnostic claims the source is permanently
    # inactive; measure it rather than believe it. A model whose ONLY current is
    # its ac_stim, into 1G, gives |v(out)| = 1e9 * mag when the source is live
    # and exactly 0 when it is not.
    def stim(name):
        return (HDR + "module dut(out);\n inout out; electrical out;\n"
                f' analog V(out) <+ ac_stim("{name}", 1.0, 0.0);\nendmodule\n')

    d, rc, _ = build(stim("ac"), "aclive")
    live = ac_mag(d) if rc == 0 else None
    check("ac_stim(\"ac\") really does drive the node in .ac",
          live is not None and abs(live - 1.0) < 1e-9, f"mag(v(out))={live}")
    d, rc, _ = build(stim("nosuch"), "acdead")
    dead = ac_mag(d) if rc == 0 else None
    check("ac_stim(\"nosuch\") drives EXACTLY NOTHING -- the warning is right",
          dead is not None and dead == 0.0, f"mag(v(out))={dead}")

    for j in os.listdir(HERE):
        if j.startswith("_dg_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
