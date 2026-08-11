#!/usr/bin/env python3
"""Enhancement-362: analysis-card sweep parameters must not produce undefined
behaviour, a bad allocation size, or an unbounded loop.

These were found by fuzzing analysis-card parameters against an ASan+UBSan build
(`fuzz_analysis.py` in this directory, which is the campaign harness and is NOT
run by the regression -- it needs a sanitizer build to be worth anything). What
this file does is pin the specific repros so they cannot come back.

WHAT WAS WRONG. Several analyses computed a sweep point count as a double and
cast it to int, then used the result as an ALLOCATION SIZE:

    distoan.c   NoOfPoints        -> DstorAlloc(..., NoOfPoints+2)
    dctran.c    CKTtimeListSize   -> TMALLOC(double, ...), and osdiaccept.c
                                     sizes a buffer from it
    cktsens.c   n                 -> drives the sweep

The expressions go non-finite or out of int range on perfectly ordinary input --
a zero start frequency makes log() diverge, equal endpoints give 0/0, and a step
count of INT_MAX overflows a plain `DnumSteps+1`. Converting any of those to int
is undefined, so the count became whatever the hardware produced. One route
reached the allocator NEGATIVE (ASan: "requested allocation size
0xfffffffffffffff0"). Separately, `.dc` had no bound at all: it advances by a
step and compares against the stop value, so a step below the ULP of the start
never advances and the sweep runs forever.

WHY AN ORDINARY BUILD CANNOT SEE MOST OF THIS. Undefined conversions do not
trap; they yield a plausible number and the run continues. What a normal build
CAN observe is the consequence -- a nonsense request must be refused rather than
run with an invented point count, and a sweep that cannot progress must not hang.
That is what is asserted here.

A NOTE ON WHAT IS *NOT* A BUG. An enormous but finite sweep is slow, not hung,
and the two are indistinguishable from a timeout. `sens ac dec 1000000` over 300
decades measured 0.05 / 0.20 / 1.78 / 17.4 s at 1 / 10 / 100 / 1000 steps --
linear, so it is simply large. Those are deliberately not rejected: only counts
that cannot be represented, and loops that cannot advance, are.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DECK = """sweep guard
V1 in 0 dc 0.65 ac 1 distof1 1 distof2 1
Rs in d 1k
D1 d 0 dm
.model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)
Rl d 0 1meg
.control
option noacct
set numdgt=12
{ctl}
.endc
.end
"""


def run(ctl, tag, timeout=60):
    p = os.path.join(HERE, "_sg_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(DECK.format(ctl=ctl))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    return r.returncode, r.stdout + r.stderr


# Each of these was a distinct sanitizer report or an unbounded loop. None may
# hang, and none may proceed to produce output from an invented point count.
NONSENSE = [
    ("disto, count overflows int",      "disto oct 2147483647 1e6 1e30 -0.5"),
    ("disto, log diverges to -inf",     "disto dec 1000000 1e300 1e-30"),
    ("disto, log diverges to +inf",     "disto oct 2 1e-30 1e300"),
    ("disto, DnumSteps+1 overflows",    "disto lin 2147483647 1e30 1e6 -0.5"),
    ("disto, negative step count",      "disto lin -5 1 1e6 1e-30"),
    ("disto, zero steps per decade",    "disto dec 0 1e4 1e5"),
    ("disto, linear start == stop",     "disto lin 1 1e6 1e6"),
    ("tran, timepoint count overflows", "tran 1e6 1e30 1e6"),
    ("dc, step below the start's ULP",  "dc V1 1 1 1e-30"),
    ("dc, count exceeds int",           "dc V1 0 1 1e-30"),
    ("sens, count overflows int",       "sens v(d) ac dec 2147483647 1e6 -1e6"),
]

# Ordinary sweeps must be completely unaffected -- the guards are only allowed to
# reject what cannot be represented.
NORMAL = [
    ("disto dec",  "disto dec 2 1e4 1e5 0.9\nsetplot disto1\nprint d[0]", r"d\[0\] = (\S+)"),
    ("ac dec",     "ac dec 5 1e4 1e6\nprint vdb(d)[10]",                  r"vdb\(d\)\[10\] = (\S+)"),
    ("dc sweep",   "dc V1 0 1 0.001\nprint v(d)[500]",                    r"v\(d\)\[500\] = (\S+)"),
    ("dc reverse", "dc V1 1 0 -0.1\nprint v(d)[5]",                       r"v\(d\)\[5\] = (\S+)"),
    ("tran",       "tran 5n 2u\nprint v(d)[100]",                         r"v\(d\)\[100\] = (\S+)"),
    ("sens ac",    "sens v(d) ac dec 5 1e4 1e6",                          None),
]


def main():
    hung = [n for i, (n, c) in enumerate(NONSENSE) if run(c, "n%d" % i)[1] == "HANG"]
    check("no nonsense sweep spec hangs", not hung,
          "all %d terminate" % len(NONSENSE) if not hung else "HANG: %s" % hung)

    # A refused sweep must not also emit results computed from a garbage count.
    leaked = []
    for i, (name, ctl) in enumerate(NONSENSE):
        rc, out = run(ctl + "\nsetplot disto1\nprint d[0]", "p%d" % i)
        if out != "HANG" and re.search(r"^d\[0\] = ", out or "", re.M):
            leaked.append(name)
    check("no nonsense sweep spec produces output", not leaked,
          "none of %d emit results" % len(NONSENSE) if not leaked else str(leaked))

    # ...and every ordinary sweep still runs and still produces a finite value.
    bad = []
    for i, (name, ctl, pat) in enumerate(NORMAL):
        rc, out = run(ctl, "g%d" % i)
        if out == "HANG" or rc != 0:
            bad.append("%s rc=%s" % (name, rc))
            continue
        if pat:
            m = re.search(pat, out, re.M)
            # .disto prints a complex value as "re,im", so take the real part
            try:
                v = float(m.group(1).split(",")[0]) if m else None
            except ValueError:
                v = None
            if v is None or v != v or abs(v) == float("inf"):
                bad.append("%s no finite value" % name)
    check("ordinary sweeps are unaffected", not bad,
          "%d analyses run clean" % len(NORMAL) if not bad else str(bad))


    # ---------------------------------------------------------------------
    # Enhancement-431: a `sweep -output` naming something that does not exist
    # used to fill a whole column with zeros -- a clean, plottable, entirely
    # fictional flat line -- behind nothing louder than a `checkvalid` warning.
    # sw_eval_expr() returns 0.0 on failure, which is indistinguishable from an
    # expression that is legitimately zero; Enhancement-385 hit the same thing
    # for knob restore and added the same `ok` out-param.
    print("\nEnhancement-431: a -output that never resolves is reported, not zero-filled")

    def sweepout(ctl, tag):
        rc, out = run(ctl, tag)
        vecs = [l.split(":")[0].strip() for l in out.splitlines()
                if ":" in l and ("real" in l or "notype" in l)]
        return out, vecs

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d)\ndisplay", "o_ok")
    check("[E-431] a real -output is recorded", "v(d)" in vecs, str(vecs))
    check("[E-431] ...and draws no complaint", "never resolved" not in out)

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(nosuch)\ndisplay", "o_bad")
    check("[E-431] a bad -output is reported by name",
          "sweep -output v(nosuch) never resolved" in out,
          out[-160:].replace("\n", " "))
    check("[E-431] ...and its fictional zero column is NOT recorded",
          "v(nosuch)" not in vecs, str(vecs))

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) -output v(nosuch) "
                         "-output i(v1)\ndisplay", "o_mix")
    check("[E-431] a bad -output does not cost the good ones",
          "v(d)" in vecs and "i(v1)" in vecs and "v(nosuch)" not in vecs, str(vecs))

    # a legitimately ZERO output must still be recorded -- the whole point of
    # distinguishing "did not resolve" from "resolved to zero"
    # `v(d)-v(d)` resolves fine and is exactly 0.0 -- the case the old code could
    # not tell apart from a name that does not exist, since both returned 0.0.
    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output zed=v(d)-v(d)\n"
                         "display\nprint zed", "o_zero")
    check("[E-431] an output that legitimately evaluates to ZERO is still recorded",
          "never resolved" not in out and "zed" in " ".join(vecs),
          f"{vecs} {out[-120:]}".replace("\n", " "))

    # ---------------------------------------------------------------------
    # Enhancement-432: `-output` is variadic. The usage line has always read
    # `[-output <expr> ...]`, but only the FIRST token after the flag was read;
    # every one after it fell through to the `unrecognized token` branch and the
    # sweep ran on with a silently shorter output list.
    print("\nEnhancement-432: -output takes every expression up to the next flag")

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) i(v1)\ndisplay",
                         "m_two")
    check("[E-432] a second -output expression is recorded",
          "v(d)" in vecs and "i(v1)" in vecs, str(vecs))
    check("[E-432] ...and is not reported as an unrecognized token",
          "unrecognized token" not in out, out[-160:].replace("\n", " "))

    # the variadic form must agree exactly with the one-flag-each form it replaces
    o1, _ = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) i(v1)\n"
                     "print v(d) i(v1)", "m_var")
    o2, _ = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) -output i(v1)\n"
                     "print v(d) i(v1)", "m_rep")
    nums = lambda s: re.findall(r"-?\d+\.\d+e[-+]\d+", s)
    check("[E-432] variadic and repeated-flag forms give identical data",
          nums(o1) == nums(o2) and len(nums(o1)) >= 6,
          f"{nums(o1)[:3]} vs {nums(o2)[:3]}")

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output vd=v(d) vin=v(in)\ndisplay",
                         "m_named")
    check("[E-432] name=expr works for every element of the list",
          "vd" in vecs and "vin" in vecs, str(vecs))

    # THE reason a bare `-` cannot end the list: a negated expression looks
    # exactly like a flag, and the old single-token form accepted it.
    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output -v(d)\ndisplay", "m_neg")
    check("[E-432] a negated expression is still an expression, not a flag",
          "-v(d)" in vecs, str(vecs))

    # ...so the list is ended by the flags `sweep` actually knows, and each of
    # them must still be parsed as a flag when it follows an output list.
    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) "
                         "-vs @rl[resistance] 1meg 2meg 1meg\ndisplay", "m_vs")
    check("[E-432] -vs ends the list and is honoured as an outer knob",
          sum(1 for v in vecs if v.startswith("v(d)__rl_resistance")) == 2, str(vecs))

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) i(v1) "
                         "-analysis op\ndisplay", "m_an")
    check("[E-432] -analysis ends the list",
          "v(d)" in vecs and "i(v1)" in vecs and "unrecognized token" not in out,
          str(vecs))

    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) i(v1) "
                         "-overlay\ndisplay", "m_ov")
    check("[E-432] -overlay ends the list",
          "v(d)" in vecs and "i(v1)" in vecs and "unrecognized token" not in out,
          str(vecs))

    # a flag directly after `-output` is a missing expression, not an output
    # named `-vs`: the outer knob must still take effect.
    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output "
                         "-vs @rl[resistance] 1meg 2meg 1meg\ndisplay", "m_empty")
    check("[E-432] an empty -output is diagnosed",
          "-output needs an expression" in out, out[-160:].replace("\n", " "))
    check("[E-432] ...and the flag after it is not swallowed as an output",
          any("rl_resistance" in v for v in vecs), str(vecs))

    # Enhancement-267's bus expansion has to survive being a NON-FIRST element:
    # `base[lo:hi]` becomes one output per index, so a three-wide range in second
    # position must produce three separately-named outputs (here they resolve to
    # nothing, which is exactly what makes each expanded name visible).
    out, vecs = sweepout("sweep @rs[resistance] 1k 3k 1k -output v(d) nosuchbus[0:2]\n"
                         "display", "m_bus")
    check("[E-432] a bus range expands from a non-first list position",
          all("nosuchbus[%d] never resolved" % i in out for i in range(3)),
          out[-200:].replace("\n", " "))
    check("[E-432] ...without costing the element before it", "v(d)" in vecs, str(vecs))

    # ---------------------------------------------------------------------
    # Enhancement-432, second half: `outbad[]` was zeroed over the `nout` known
    # at parse time, but with no `-output` at all the outputs are auto-collected
    # INSIDE the point loop, so `nout` was still 0 there and every auto-collected
    # output inherited stack garbage. Enhancement-431 then read that garbage as a
    # resolve failure -- warning about good curves and DELETING the ones whose
    # garbage happened to reach the point count. This is the default invocation,
    # so it needs a deck wide enough for the garbage to land on something.
    print("\nEnhancement-432: auto-collected outputs must not inherit stack garbage")

    wide = ["auto-collect width", "V1 n0 0 dc 1"]
    wide += ["R%d n%d n%d 1k" % (i, i - 1, i) for i in range(1, 25)]
    wide += ["Rend n24 0 1k", ".control", "option noacct",
             "sweep @r1[resistance] 1k 2k 1k -analysis op", "display",
             ".endc", ".end"]
    p = os.path.join(HERE, "_sg_autocollect.cir")
    with open(p, "w") as f:
        f.write("\n".join(wide) + "\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=60, errors="replace")
    out = r.stdout + r.stderr
    got = [l.split(":")[0].strip() for l in out.splitlines()
           if ":" in l and ("real" in l or "notype" in l)]
    missing = [n for n in ("n%d" % i for i in range(25)) if n not in got]
    check("[E-432] a plain sweep records every node it collected",
          not missing, "missing %s" % missing if missing else "25 nodes + scale")
    check("[E-432] ...and reports no resolve failure against them",
          "never resolved" not in out and "did not resolve" not in out,
          out[-200:].replace("\n", " "))

    # ---------------------------------------------------------------------
    # Quoting. ngspice's lexer treats the two quote characters differently and
    # says so in its own comments (parser/lexical.c): `'...'` forms one word
    # WITHOUT the quotes, `"..."` forms one word INCLUDING them, leaving each
    # command to strip the survivors with cp_unquote(). Most of the frontend
    # does; com_sweep.c did not, so `-analysis "tran 1n 20n"` reached the command
    # lookup with its quotes attached and died as `unknown command '"tran..."'`
    # while the single-quoted spelling worked.
    print("\nQuoting: both quote styles reach the command already unquoted")

    def analysis_of(ctl, tag):
        _, out = run(ctl, tag)
        m = re.search(r"analysis '([^']*)'", out)
        return (m.group(1) if m else None), out

    for style, ctl in (("bare",   "-analysis tran 1n 20n"),
                       ("single", "-analysis 'tran 1n 20n'"),
                       ("double", '-analysis "tran 1n 20n"')):
        got, out = analysis_of("sweep @rs[resistance] 1k 2k 1k %s -output v(d)" % ctl,
                               "q_sweep_" + style)
        check("[quote] sweep -analysis, %s-quoted" % style,
              got == "tran 1n 20n" and "unknown command" not in out,
              f"{got!r} {out[-90:]}".replace("\n", " "))

    # the same for -output, where a surviving quote was worse than a hard error:
    # `"v(d)"` recorded a vector literally NAMED with quotes, and `"gain=v(d)"`
    # split at the wrong '=' so the expression never resolved.
    out, vecs = sweepout('sweep @rs[resistance] 1k 3k 1k -output "v(d)"\ndisplay', "q_out")
    check("[quote] -output \"v(d)\" records v(d), not a quoted name",
          "v(d)" in vecs and not any(v.startswith('"') for v in vecs), str(vecs))

    out, vecs = sweepout('sweep @rs[resistance] 1k 3k 1k -output "gain=v(d)"\ndisplay', "q_outn")
    check("[quote] -output \"name=expr\" splits at the right '='",
          "gain" in vecs and "never resolved" not in out, str(vecs))

    # The sibling commands documented with the same `-analysis <cmd>` notation
    # each collected it differently. montecarlo/highsigma stopped at ANY leading
    # '-', so an analysis argument that is legitimately negative ended the list
    # and was then reported as an unexpected token.
    print("\nQuoting: the sibling commands collect -analysis the same way")

    NEG = "disto lin 3 1e5 1e6 -0.5"
    for cmd, tail in (("montecarlo 2", " -spec v(d) -max 9"),
                      ("highsigma 2",  " -metric v(d) -max 9")):
        name = cmd.split()[0]
        got, out = analysis_of(f"{cmd} -analysis {NEG}{tail}", "q_neg_" + name)
        check("[quote] %s -analysis keeps a negative argument" % name,
              got == NEG and "unexpected token" not in out,
              f"{got!r} {out[-90:]}".replace("\n", " "))
        got, out = analysis_of(f'{cmd} -analysis "tran 1n 20n"{tail}', "q_dq_" + name)
        check("[quote] %s -analysis, double-quoted" % name,
              got == "tran 1n 20n" and "unknown command" not in out,
              f"{got!r} {out[-90:]}".replace("\n", " "))

    # wcd copied ONE token, so it alone REQUIRED quoting: `-analysis tran 1n 20n`
    # kept `tran` and then rejected `1n` as an unknown option. It needs a deck
    # with a Gaussian .param actually used by a device, or it stops before the
    # line that echoes the analysis.
    WCD_DECK = "\n".join([
        "wcd quoting", "V1 in 0 dc 1 ac 1", "Rs in d {pg}", "C1 d 0 1n",
        "Rl d 0 1meg", ".param pg=agauss(1000,50,1)", ".control", "option noacct",
        "{ctl}", ".endc", ".end", ""])

    def wcd_analysis(ctl, tag):
        p = os.path.join(HERE, "_sg_%s.cir" % tag)
        with open(p, "w") as f:
            f.write(WCD_DECK.replace("{ctl}", ctl))
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=120, errors="replace")
        out = r.stdout + r.stderr
        m = re.search(r"analysis '([^']*)'", out)
        return (m.group(1) if m else None), out

    for style, ctl in (("bare",   "-analysis tran 1n 20n"),
                       ("single", "-analysis 'tran 1n 20n'"),
                       ("double", '-analysis "tran 1n 20n"')):
        got, out = wcd_analysis("wcd -metric v(d) -max 9 %s -maxiter 1" % ctl,
                                "q_wcd_" + style)
        check("[quote] wcd -analysis collects every token, %s-quoted" % style,
              got == "tran 1n 20n", f"{got!r} {out[-90:]}".replace("\n", " "))

    # ------------------------------------------------------------ E-437 -----
    # A `.temp` card with NO value was applied SILENTLY AS 0 C: strtod("")
    # returns 0.0 and leaves the parse pointer at the start, so the
    # trailing-garbage test that catches `.temp abc` saw a clean parse. The
    # circuit then ran 27 K cold with nothing on stderr. Its own sibling
    # `.options temp=` already refused the same mistake, and of every
    # value-taking dot card `.temp` was the only one whose missing value both
    # went undiagnosed AND could change the answer -- a lone gap, not a class.
    #
    # The divider below carries tc1 on R1, so temperature is visible in v(nb):
    # 27 C reads exactly 0.5, and the silent 0 C read 0.5780 -- 15.6% wrong.
    TEMP_DECK = "\n".join([
        "temp card guard",
        "V1 in 0 dc 1",
        "R1 in nb 1k tc1=0.01",
        "R2 nb 0 1k",
        "{card}",
        ".control",
        "option noacct",
        "set numdgt=12",
        "op",
        "print v(nb)",
        ".endc",
        ".end",
        "",
    ])

    def temp_run(card, tag):
        p = os.path.join(HERE, "_sg_%s.cir" % tag)
        with open(p, "w") as f:
            f.write(TEMP_DECK.replace("{card}", card))
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=60,
                           errors="replace")
        out = r.stdout + r.stderr
        mv = re.search(r"v\(nb\) = (\S+)", out)
        mt = re.search(r"TEMP = ([-\d.]+)", out)
        warned = bool(re.search(r"(?i)^\s*warning", out, re.M))
        return (float(mv.group(1)) if mv else None,
                float(mt.group(1)) if mt else None, warned, out)

    v, t, warned, out = temp_run(".temp", "temp_bare")
    check("[E-437] a `.temp` with no value is diagnosed, not applied as 0 C",
          warned and t == 27.0, f"TEMP={t} warned={warned}")
    check("[E-437] ...and the answer is the 27 C one, not the 0 C one",
          v is not None and abs(v - 0.5) < 1e-9, f"v(nb)={v}")
    check("[E-437] ...with a message naming the actual mistake",
          "carries no temperature value" in out,
          "; ".join(l.strip() for l in out.splitlines()
                    if "arning" in l)[:90])

    # positive control: `.temp` must still SET the temperature. A fix that
    # simply ignored the card would satisfy every check above.
    v125, t125, _, _ = temp_run(".temp 125", "temp_125")
    check("[E-437] a `.temp` WITH a value still sets it (positive control)",
          t125 == 125.0 and v125 is not None and abs(v125 - 0.5) > 1e-3,
          f"TEMP={t125} v(nb)={v125}")
    v27, t27, w27, _ = temp_run(".temp 27", "temp_27")
    check("[E-437] ...and a good value stays quiet",
          t27 == 27.0 and not w27, f"TEMP={t27} warned={w27}")

    # the neighbours this fix must not disturb
    for card, tag in ((".temp abc", "temp_abc"), (".temp 75 125", "temp_multi")):
        vv, tt, ww, _ = temp_run(card, tag)
        check(f"[E-437] `{card}` still warns and keeps 27 C",
              ww and tt == 27.0, f"TEMP={tt} warned={ww}")
    vo, to, _, outo = temp_run(".options temp=", "temp_opt")
    check("[E-437] the sibling `.options temp=` is unchanged",
          to == 27.0 and "equals what" in outo, f"TEMP={to}")

    for junk in os.listdir(HERE):
        if junk.startswith("_sg_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
