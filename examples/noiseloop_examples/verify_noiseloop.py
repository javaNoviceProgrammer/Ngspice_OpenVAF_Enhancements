#!/usr/bin/env python3
"""Enhancement-424: a noise source inside a run-time loop contributed nothing.

    for (k = 0; k < 1; k = k + 1)
        I(p, n) <+ white_noise(4e-21);     // contributed exactly nothing

`onoise_total` came back BIT-IDENTICAL to a model with no noise source in it.
And not "registered but zero": the device registered NO SOURCE AT ALL. Printing
the per-source vectors in the `noise2` plot shows `onoise_total_n1_unnamed0` for
the working spelling and no `n1` source whatsoever for the loop one -- which is
what turned this from "the number looks wrong" into a diagnosis.

It affected `white_noise`, `flicker_noise`, `noise_table` and `noise_table_log`,
in `for`, `while` and `repeat` alike, and `ac_stim` with them -- that rides the
same small-signal pipeline (Enhancement-51) and went from mag 500 to 0. It was
silent even under `-E all`, so it was not a suppressed lint.

WHY REJECTING IT IS THE RIGHT FIX, rather than making it work. Every OTHER
member of this family was already an error here:

    error: analog operator 'ddt' is not allowed in loops

`ddt`, `idt`, `absdelay`, `transition` and `laplace_*` are all rejected inside a
loop (LRM 4.5.1). The noise builtins are simply not in `is_analog_operator()`,
so they fell past that check and were discarded further down instead of being
reported. The sibling behaviour already decided this question; noise was the
family member nobody had joined up.

The restriction is LOOP-ONLY, and deliberately so. A noise source inside an
`if`, an `else` or a `case` is legitimate -- gating noise on a mode flag is
ordinary compact-model practice -- and works correctly today. That is why this
uses its own `is_small_signal_source()` predicate instead of being folded into
`is_analog_operator()`, which also drives the conditional and main-block checks.

A `generate` loop keeps working, and is the answer for a model that wants
per-finger or per-segment noise: it unrolls at elaboration, so it creates one
source per iteration. That is checked below as a NUMBER -- two iterations give
two sources and about twice the noise power.

ONE BEHAVIOUR CHANGE WORTH NAMING. Assigning a noise source to a variable inside
a loop and contributing outside it --

    for (k = 0; k < 1; k = k + 1) t = white_noise(4e-21);
    I(p, n) <+ t;

-- used to WORK (it contributed correctly). It is rejected now. That is not an
over-reach: `t = ddt(...)`, `t = idt(...)` and `t = laplace_nd(...)` in exactly
that position are ALREADY rejected, so the restriction has always been on the
call site being inside a loop, not on how the result is used. Rejecting the
noise spelling makes it consistent; leaving it would have kept one member of the
family behaving differently from all the others, which is how this defect
started.

Also fixed: `$finish(n)` and `$stop(n)` accepted any n. IEEE 1364-2005 17.1.2
gives the argument exactly three meanings -- 0, 1 and 2 select how much
diagnostic information the simulator prints. `$finish(3)`, `$finish(99)`,
`$finish(-1)` and `$stop(7)` select nothing at all.
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
LOOP = "creates a small-signal source, which is not allowed in loops"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_nl_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def crashed(rc, out):
    return rc < 0 or "has crashed" in out or "openvaf-crash" in out or "panicked" in out


def mod(body, decls="", params=" parameter real g = 1e-3;\n"):
    return (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n" + params + decls +
            " analog begin\n" + body + " end\nendmodule\n")


def noise(d):
    """Integrated output noise AND the per-source vectors the device registered.

    The deck needs all four of: a frequency RANGE (a single-frequency `noise`
    run produces no total at all), an output node that is NOT the source node
    (measuring at the source shorts the noise), the trailing pts_per_summary
    argument, and `setplot noise2`. `print all` is what shows WHICH sources
    exist -- the difference between "registered and zero" and "never created".
    """
    open(os.path.join(d, "q.cir"), "w").write(
        "* noise\nV1 in 0 dc 0 ac 1\nN1 in out dut\nRL out 0 1k\n.model dut dut()\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=12\n"
        "noise v(out) v1 dec 20 1k 1meg 1\nsetplot noise2\nprint onoise_total\n"
        "print all\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    txt = r.stdout + r.stderr
    m = re.search(r"^onoise_total\s*=\s*(\S+)", txt, re.M)
    srcs = sorted(set(re.findall(r"onoise_total_n1[a-z0-9_]*", txt)))
    return (float(m.group(1)) if m else None), srcs


def rejected(label, src, tag, needle=LOOP):
    _, rc, out = build(src, tag)
    ok = rc != 0 and needle in out and not crashed(rc, out)
    check(label, ok, f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:72])


def clean(label, src, tag):
    _, rc, out = build(src, tag)
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    check(label, rc == 0 and not noisy, f"rc={rc} " + (noisy or [""])[0][:70])


K = " integer k;\n"
G = "  I(p, n) <+ g*V(p, n);\n"


def main():
    # =====================================================================
    print("\n[1] every small-signal source, in every run-time loop")
    for fn, call in [("white_noise", "white_noise(4e-21)"),
                     ("flicker_noise", "flicker_noise(4e-21, 1.0)"),
                     ("noise_table", "noise_table('{1.0,4e-21, 1e9,4e-21})"),
                     ("noise_table_log", "noise_table_log('{1.0,4e-21, 1e9,4e-21})"),
                     ("ac_stim", 'ac_stim("ac", 1.0, 0.0)')]:
        rejected(f"{fn} in a `for` loop is rejected",
                 mod(G + f"  for (k=0;k<1;k=k+1) I(p, n) <+ {call};\n", K), "a_" + fn)
    rejected("white_noise in a `while` loop",
             mod(G + "  k=0;\n  while (k<1) begin I(p,n) <+ white_noise(4e-21); k=k+1; end\n", K),
             "l_while")
    rejected("white_noise in a `repeat` loop",
             mod(G + "  repeat (1) I(p,n) <+ white_noise(4e-21);\n"), "l_repeat")
    rejected("nested inside an `if` inside a loop",
             mod(G + "  for (k=0;k<1;k=k+1) begin\n   if (g>0) I(p,n) <+ white_noise(4e-21);\n  end\n", K),
             "l_nest")
    rejected("a doubly nested loop",
             mod(G + "  for (k=0;k<1;k=k+1) for (j=0;j<1;j=j+1) I(p,n) <+ white_noise(4e-21);\n",
                 " integer k; integer j;\n"), "l_deep")
    # the behaviour change, named in the docstring
    rejected("assigned to a VARIABLE inside a loop -- this used to work, and is "
             "rejected for consistency with `t = ddt(..)`",
             mod(G + "  t=0;\n  for (k=0;k<1;k=k+1) t = white_noise(4e-21);\n  I(p,n) <+ t;\n",
                 " integer k; real t;\n"), "l_var")
    # the sibling that decided the question
    rejected("...and `t = ddt(..)` in that same position is still rejected as before",
             mod(G + "  t=0;\n  for (k=0;k<1;k=k+1) t = ddt(V(p,n));\n  I(p,n) <+ 1e-9*t;\n",
                 " integer k; real t;\n"), "l_ddt", "analog operator 'ddt' is not allowed in loops")

    # =====================================================================
    print("\n[2] ACCEPT half -- every legitimate placement still compiles")
    clean("a plain contribution", mod(G + "  I(p,n) <+ white_noise(4e-21);\n"), "k_plain")
    clean("inside begin..end", mod(G + "  begin I(p,n) <+ white_noise(4e-21); end\n"), "k_begin")
    clean("inside an if", mod(G + "  if (g>0) I(p,n) <+ white_noise(4e-21);\n"), "k_if")
    clean("inside an else",
          mod(G + "  if (g<0) I(p,n) <+ white_noise(1e-30);\n  else I(p,n) <+ white_noise(4e-21);\n"),
          "k_else")
    clean("inside a case",
          mod(G + "  case (1)\n   1: I(p,n) <+ white_noise(4e-21);\n   default: ;\n  endcase\n"),
          "k_case")
    clean("ac_stim inside an if", mod(G + '  if (g>0) I(p,n) <+ ac_stim("ac",1.0,0.0);\n'), "k_acst")
    clean("flicker_noise inside an if",
          mod(G + "  if (g>0) I(p,n) <+ flicker_noise(4e-21,1.0);\n"), "k_flick")
    clean("an ordinary contribution in a loop (the control)",
          mod(G + "  for (k=0;k<2;k=k+1) I(p,n) <+ g*V(p,n);\n", K), "k_ctl")
    clean("a noise source assigned to a variable OUTSIDE any loop",
          mod(G + "  t = white_noise(4e-21);\n  I(p,n) <+ t;\n", " real t;\n"), "k_var")

    # =====================================================================
    print("\n[3] the accept half, measured as NUMBERS")
    d, rc, _ = build(mod(G), "m_floor")
    floor, fsrc = noise(d)
    check("a model with no noise source has no `n1` source and a resistor-only floor",
          floor is not None and not [s for s in fsrc if s.startswith("onoise_total_n1_")],
          f"total={floor} sources={fsrc}")
    d, rc, _ = build(mod(G + "  I(p,n) <+ white_noise(4e-21);\n"), "m_one")
    one, osrc = noise(d)
    check("a plain noise source registers one source and rises above the floor",
          one is not None and floor is not None and one > floor * 2
          and any(s.startswith("onoise_total_n1_") for s in osrc),
          f"total={one} sources={osrc}")
    d, rc, _ = build(mod(G + "  if (g>0) I(p,n) <+ white_noise(4e-21);\n"), "m_if")
    cond, _ = noise(d)
    check("the conditional spelling gives the SAME total as the plain one",
          cond is not None and one is not None and abs(cond - one) <= 1e-9 * abs(one),
          f"if={cond} plain={one}")

    # the genvar answer, which is what a per-finger model should write
    GEN = (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
           " parameter real g = 1e-3;\n genvar k;\n"
           " analog I(p, n) <+ g*V(p, n);\n"
           " generate for (k=0;k<2;k=k+1) begin : gb\n"
           "  analog I(p,n) <+ white_noise(4e-21);\n end endgenerate\nendmodule\n")
    d, rc, out = build(GEN, "m_gen")
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    gtot, gsrc = noise(d) if rc == 0 else (None, [])
    check("a GENVAR loop compiles clean and creates ONE SOURCE PER ITERATION",
          rc == 0 and not noisy and len([s for s in gsrc if s.startswith("onoise_total_n1_")]) == 2,
          f"rc={rc} sources={gsrc}")
    # `onoise_total` is an RMS voltage, so two equal uncorrelated sources add in
    # POWER, not in amplitude: subtract the resistor floor's power, then compare.
    # (Comparing the RMS values directly gives a ratio of 1.44 and reads like a
    # defect -- it is the assertion that is wrong, not the compiler.)
    if None not in (gtot, one, floor):
        p1 = one * one - floor * floor
        pg = gtot * gtot - floor * floor
        check("...and two sources carry exactly twice the noise POWER of one",
              abs(pg / p1 - 2.0) <= 1e-9, f"ratio={pg / p1:.12f} (want 2.0)")
    else:
        check("...and two sources carry exactly twice the noise POWER of one", False,
              f"genvar={gtot} one={one} floor={floor}")

    # =====================================================================
    print("\n[4] $finish / $stop diagnostic level")
    LVL = "the diagnostic level"
    for code in ("3", "99", "-1"):
        rejected(f"$finish({code}) is rejected", mod(f"  $finish({code});\n" + G),
                 "q_" + code.replace("-", "m"), LVL)
    rejected("$stop(7) is rejected", mod("  $stop(7);\n" + G), "q_s7", LVL)
    for code in ("0", "1", "2"):
        clean(f"$finish({code}) is accepted", mod(f"  $finish({code});\n" + G), "qo_" + code)
    clean("$stop(2) is accepted", mod("  $stop(2);\n" + G), "qo_s2")
    clean("$finish with no argument at all", mod("  $finish;\n" + G), "qo_none")
    clean("$stop with no argument", mod("  $stop;\n" + G), "qo_snone")
    clean("a RUNTIME argument is unanswerable, so nothing is said",
          mod("  $finish(k);\n" + G, K), "qo_rt")

    for j in os.listdir(HERE):
        if j.startswith("_nl_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
