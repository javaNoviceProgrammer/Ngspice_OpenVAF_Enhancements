#!/usr/bin/env python3
"""Enhancement-421: five things from a round-27 hunt, three of them the same
mistake reported through one door and not the other.

  [1] AN `exclude` THAT COVERS THE WHOLE `from` RANGE MADE THE PARAMETER
      UNSETTABLE, IN SILENCE.

          parameter real x = 1.0 from [0:10] exclude [0:10];

      compiled clean. Every value a netlist supplies is then rejected --
      "Parameter x is out of bounds!" and the analysis aborts -- while the
      default still reads, because Enhancement-56 exempts defaults from range
      checking by design. The parameter is unsettable and the declaration, which
      is where the mistake is, said nothing.

      That is EXACTLY the end state Enhancement-399 already reports for
      `from [3:1]`. It checked `from` and never looked at `exclude`, so the same
      defect spelled the other way went straight through. This is the round-12
      lesson -- when auditing validation, enumerate EVERY way to spell the thing
      -- applied to every way of spelling an empty range.

      Reached by plausible routes, not just the exact-cover one: an exclude
      WIDER than the range it guards (`from [1:2] exclude [0:10]`, a copy-paste),
      and two excludes that happen to tile it.

  [2] AN INVERTED `exclude` INTERVAL EXCLUDED NOTHING, IN SILENCE.

          parameter real x = 1.0 from [0:10] exclude [3:1];

      The author wrote "keep 1 through 3 out" with the bounds the wrong way
      round. Nothing is excluded and nothing is said, so every value in the band
      the declaration appears to forbid is accepted. `from [3:1]` with those same
      bounds is a compile error.

      This is the more insidious of the two: [1] fails loudly at run time, [2]
      never fails at all -- it just silently permits what the model meant to
      forbid.

  [3] `$simparam` NAMES WERE NEVER CHECKED, AND THEY ARE THE ONLY SIBLING WHOSE
      BAD NAME IS FATAL.

      The severity ordering was exactly inverted:

        analysis("nosuch")            warned (L021)  -> branch merely dead
        $limit(.., "nosuchlim", ..)   warned (L020)  -> load merely refused
        ac_stim("nosuch")             warned (L021)  -> source merely inactive
        $simparam("nosuchknob")       SILENT         -> EVAL_RET_FLAG_FATAL,
        $simparam$str("nosuchstr")    SILENT            the analysis DIES

      The three that warned degrade benignly; the two that said nothing are the
      only ones that kill the run.

      THE NAME LIST IS NGSPICE'S, NOT THE LRM'S, and that distinction is the
      whole point. ngspice serves 14 numeric names and 2 string ones
      (`src/osdi/osdiload.c`). The LRM names `minr`, `imelt`, `shrink`, `imax`,
      `rthresh` -- ngspice serves NONE of them, so a model using one dies. For
      `$simparam$str` the two sets do not intersect at all: the LRM says `cwd`,
      `module`, `instance`, `path`; ngspice serves `analysis_name` and
      `simulator`. Validating against the LRM's list would have warned on the
      names that work and stayed silent on the ones that abort.

      `$simparam(name, default)` is deliberately NOT warned. Returning the
      default for a name this simulator does not serve is precisely what that
      form is for, and is how a model stays portable. `$simparam$str` has no such
      form, so every unresolvable name there is fatal.

  [4] TWO `default` ARMS IN ONE CASE STATEMENT WERE ACCEPTED.

      IEEE 1364-2005 9.5: "use of multiple default statements in one case
      statement shall be illegal". The behaviour was never wrong -- the first
      `default` runs -- which is why it is worth saying: the second arm is
      unreachable code that looks like it does something.

  [5] TWO GARBLED DIAGNOSTIC STRINGS. L015's help said "para-ma-eters" and
      closed a double quote with an apostrophe; a type error read "typed mismatch
      invalid function arguments", two sentences run together with a typo in the
      first.

A checker that rejects too much is worse than one that rejects nothing. Roughly
half of what follows is the ACCEPT half, and the boundary cases are the point:
`exclude (0:10)` against `from [0:10]` leaves exactly the two endpoints settable
and must still compile.
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
    d = os.path.join(HERE, "_rg_%s" % tag)
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
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:76])


def clean(label, src, tag):
    """Compiles AND says nothing -- a spurious warning is a failure too."""
    _, rc, out = build(src, tag)
    noisy = [l for l in out.splitlines() if l.startswith(("error", "warning"))]
    check(label, rc == 0 and not noisy, f"rc={rc} " + (noisy or [""])[0][:70])


def warns(label, src, tag, needle):
    """A LINT: the model must still BUILD, and the text must be there."""
    _, rc, out = build(src, tag)
    check(label, rc == 0 and needle in out,
          f"rc={rc} " + (out.strip().splitlines() or ["no output"])[0][:76])


def pmod(decl, extra=""):
    return (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n" + extra + decl +
            " analog I(p, n) <+ 1e-3*x*V(p, n);\nendmodule\n")


def amod(body, decls=""):
    return (HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
            ' (*desc="r"*) real r;\n' + decls +
            " analog begin\n  r = 0;\n" + body + "  I(p, n) <+ 1e-3*V(p, n);\n end\nendmodule\n")


def setp(d, val):
    """Supply x from a .model card and read it back; None when rejected."""
    open(os.path.join(d, "q.cir"), "w").write(
        f"* setp\nV1 a 0 dc 1\nN1 a 0 dut\n.model dut dut(x={val})\n"
        ".control\npre_osdi m.osdi\noption noacct\nset numdgt=12\nop\n"
        "print i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 40; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    out = r.stdout + r.stderr
    if "out of bounds" in out:
        return None
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", out, re.M)
    return None if m is None else float(m.group(1))


def main():
    # =====================================================================
    print("\n[1] an `exclude` that covers the whole `from` range")
    COVER = "excludes every value its range allows"
    for tag, decl, note in [
        ("exact",  " parameter real x = 1.0 from [0:10] exclude [0:10];", "exact cover"),
        ("tile",   " parameter real x = 1.0 from [0:10] exclude [0:5] exclude [5:10];",
                   "two excludes tile it"),
        ("wider",  " parameter real x = 1.0 from [1:2] exclude [0:10];",
                   "exclude WIDER than the range -- the copy-paste"),
        ("openopen", " parameter real x = 1.0 from (0:10) exclude (0:10);", "open against open"),
        ("closedopen", " parameter real x = 1.0 from (0:10) exclude [0:10];",
                   "a closed exclude swallows an open range"),
        ("point",  " parameter real x = 3.0 from [3:3] exclude 3;",
                   "a single-point range, excluded by a point"),
        ("int",    " parameter integer x = 1 from [0:10] exclude [0:10];", "integer parameter"),
    ]:
        rejected(f"{note} is rejected", pmod(decl), "c_" + tag, COVER)

    # ---- accept half: the boundaries are the whole point -----------------
    clean("an excluded point leaves the rest settable",
          pmod(" parameter real x = 1.0 from [0:10] exclude 0;"), "ok_pt")
    clean("an excluded sub-interval",
          pmod(" parameter real x = 1.0 from [0:10] exclude (2:3);"), "ok_sub")
    clean("two disjoint excluded points",
          pmod(" parameter real x = 1.0 from [0:10] exclude 2 exclude 4;"), "ok_2pt")
    clean("two excludes that leave a GAP between them",
          pmod(" parameter real x = 1.0 from [0:10] exclude [0:5] exclude [6:10];"), "ok_gap")
    clean("an OPEN exclude leaves both endpoints settable",
          pmod(" parameter real x = 0.0 from [0:10] exclude (0:10);"), "ok_open")
    clean("`exclude [0:10)` leaves exactly the upper endpoint",
          pmod(" parameter real x = 10.0 from [0:10] exclude [0:10);"), "ok_hi")
    clean("`exclude (0:10]` leaves exactly the lower endpoint",
          pmod(" parameter real x = 0.0 from [0:10] exclude (0:10];"), "ok_lo")
    clean("an exclude entirely outside the range",
          pmod(" parameter real x = 1.0 from [0:10] exclude 99;"), "ok_out")
    clean("`exclude` with no `from` at all",
          pmod(" parameter real x = 1.0 exclude 0;"), "ok_nofrom")
    # Enhancement-455: `inf` now FOLDS as a bound, so this case is answerable and
    # is answered. It was pinned as clean here only because the folder had no
    # case for the `inf` token -- the label said so ("`inf` does not fold") -- and
    # that limitation also let every reversed range spelled with `inf` through
    # (`from (inf:0)` was accepted and then enforced nothing at all). Excluding
    # `[0:inf)` from `[0:inf)` leaves no settable value, which is exactly what
    # this check exists to report. Partial excludes over an infinite range are
    # unaffected and still compile -- pinned directly below.
    rejected("`exclude` covering an UNBOUNDED range is now reported (E-455)",
             pmod(" parameter real x = 1.0 from [0:inf) exclude [0:inf);"), "ok_inf",
             "excludes every value its range allows")
    clean("...while a PARTIAL exclude over an unbounded range still compiles",
          pmod(" parameter real x = 9.0 from [0:inf) exclude [0:5];"), "ok_inf_part")
    clean("...and an unbounded range with no exclude is untouched",
          pmod(" parameter real x = 1.0 from [0:inf);"), "ok_inf_plain")
    clean("a RUNTIME bound makes the question unanswerable, so nothing is said",
          pmod(" parameter real x = 1.0 from [0:10] exclude [0:y];",
               extra=" parameter real y = 5.0;\n"), "ok_rt")
    clean("two `from` clauses are a union and are skipped",
          pmod(" parameter real x = 1.0 from [0:1] from [2:3] exclude [0:3];"), "ok_2from")
    # SCOPE BOUNDARY, pinned deliberately: the sweep is real-valued, so points
    # cannot tile an interval. On an INTEGER parameter `exclude 0/1/2` over
    # [0:2] really is a full cover and is NOT reported. Under-reporting is the
    # safe direction and the evidence was real-valued; recorded so the gap is
    # known rather than accidental.
    clean("SCOPE: points over an integer range are not treated as a cover",
          pmod(" parameter integer x = 1 from [0:2] exclude 0 exclude 1 exclude 2;"), "ok_ipt")

    # ---- and the boundary must be real, not just quiet -------------------
    d, rc, _ = build(pmod(" parameter real x = 0.0 from [0:10] exclude (0:10);"), "bnd")
    if rc == 0:
        lo, mid, hi = setp(d, "0"), setp(d, "5"), setp(d, "10")
        check("`from [0:10] exclude (0:10)` really does keep both endpoints settable",
              lo is not None and hi is not None and mid is None,
              f"x=0 -> {lo}, x=5 -> {mid} (must be rejected), x=10 -> {hi}")

    # =====================================================================
    print("\n[2] an inverted / degenerate `exclude` excludes nothing")
    EMPTY = "excludes nothing"
    for tag, decl, note in [
        ("inv",   " parameter real x = 1.0 from [0:10] exclude [3:1];", "inverted closed"),
        ("invo",  " parameter real x = 1.0 from [0:10] exclude (3:1);", "inverted open"),
        ("degen", " parameter real x = 1.0 from [0:10] exclude (1:1);", "degenerate open"),
        ("half",  " parameter real x = 1.0 from [0:10] exclude [1:1);", "half-open degenerate"),
        ("nofrom"," parameter real x = 1.0 exclude [3:1];",             "with no from clause"),
    ]:
        rejected(f"{note} is rejected", pmod(decl), "e_" + tag, EMPTY)
    clean("`exclude [1:1]` -- both bounds closed -- is a legitimate point exclusion",
          pmod(" parameter real x = 0.0 from [0:10] exclude [1:1];"), "ok_pt11")
    # the `from` half must be untouched
    rejected("`from [3:1]` is still rejected as before (E-399)",
             pmod(" parameter real x = 1.0 from [3:1];"), "e_from", "no value can satisfy")

    # =====================================================================
    print("\n[3] $simparam / $simparam$str names")
    L025 = "which this simulator does not provide"
    for name in ("gmin", "reltol", "abstol", "vntol", "tnom", "scale", "iteration",
                 "abstime", "epsmin", "gdev", "iniLim", "sourceScaleFactor",
                 "simulatorVersion", "simulatorSubversion"):
        clean(f'$simparam("{name}") -- ngspice serves it -- is silent',
              amod(f'  r = $simparam("{name}");\n'), "sp_" + name.lower())
    for name in ("minr", "imelt", "shrink", "imax", "rthresh"):
        warns(f'$simparam("{name}") warns -- an LRM name ngspice does NOT serve',
              amod(f'  r = $simparam("{name}");\n'), "spb_" + name, L025)
    warns("a plain typo warns", amod('  r = $simparam("nosuchknob");\n'), "sp_typo", L025)
    warns("the diagnostic says an unresolvable name is FATAL, not zero",
          amod('  r = $simparam("nosuchknob");\n'), "sp_fatal", "FATAL at run time")
    warns("and it points at the two-argument form",
          amod('  r = $simparam("nosuchknob");\n'), "sp_help", "<default>")
    clean("the TWO-ARGUMENT form is silent -- that is what it is for",
          amod('  r = $simparam("nosuchknob", 1.5);\n'), "sp_dflt")
    clean("two-argument form with an LRM-only name is silent too",
          amod('  r = $simparam("minr", 1.0);\n'), "sp_dflt2")
    clean("a plusarg-channel name is left alone",
          amod('  r = $simparam("$test$plusargs$foo", 0.0);\n'), "sp_pa")
    # E-527 (kernel audit): analysis_type and cwd joined the served set.
    for name in ("analysis_name", "analysis_type", "cwd", "simulator"):
        clean(f'$simparam$str("{name}") -- ngspice serves it -- is silent',
              amod(f'  $display("%s", $simparam$str("{name}"));\n'), "ss_" + name)
    for name in ("module", "instance", "path"):
        warns(f'$simparam$str("{name}") warns -- LRM name with no instance identity '
              f'in the channel',
              amod(f'  $display("%s", $simparam$str("{name}"));\n'), "ssb_" + name, L025)

    # the lint must be a LINT: allowable, and deniable
    d, rc, out = build(amod('  r = $simparam("nosuchknob");\n'), "sp_lint")
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi"),
                        "-A", "unknown_simparam"], capture_output=True, text=True,
                       env=env, cwd=d, timeout=900)
    check("`-A unknown_simparam` silences it (it is a lint, not an error)",
          r.returncode == 0 and "L025" not in (r.stdout + r.stderr),
          (r.stdout + r.stderr).strip().splitlines()[:1])
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi"),
                        "-E", "unknown_simparam"], capture_output=True, text=True,
                       env=env, cwd=d, timeout=900)
    check("`-E unknown_simparam` makes it an error", r.returncode != 0,
          f"rc={r.returncode}")

    # the runtime consequence the diagnostic claims, measured
    d, rc, _ = build(amod('  r = $simparam("nosuchknob");\n'), "sp_run")
    open(os.path.join(d, "q.cir"), "w").write(
        "* fatal\nV1 a 0 dc 1\nN1 a 0 dut\n.model dut dut()\n"
        ".control\npre_osdi m.osdi\noption noacct\nop\nprint i(v1)\n.endc\n.end\n")
    r = subprocess.run(["perl", "-e", "alarm 40; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    out = r.stdout + r.stderr
    check("an unresolvable $simparam really is FATAL at run time, not merely zero",
          "unknown $simparam" in out and "aborted" in out.lower(),
          [l.strip() for l in out.splitlines() if "simparam" in l][:1])

    # =====================================================================
    print("\n[4] more than one `default` arm in a case statement")
    DUP = "more than one `default` arm"
    rejected("two `default` arms are rejected",
             amod("  case (7)\n   1: r=1;\n   default: r=5;\n   default: r=6;\n  endcase\n"),
             "cd2", DUP)
    rejected("three `default` arms are rejected",
             amod("  case (7)\n   default: r=5;\n   default: r=6;\n   default: r=7;\n  endcase\n"),
             "cd3", DUP)
    rejected("casez is checked too",
             amod("  casez (4'b1011)\n   4'b10?1: r=7;\n   default: r=1;\n"
                  "   default: r=2;\n  endcase\n"), "cdz", DUP)
    clean("ONE default still compiles",
          amod("  case (7)\n   1: r=1;\n   default: r=5;\n  endcase\n"), "cd1")
    clean("no default at all still compiles",
          amod("  case (7)\n   1: r=1;\n  endcase\n"), "cd0")
    clean("a duplicate case ITEM is legal in Verilog and stays accepted",
          amod("  case (1)\n   1: r=10;\n   1: r=20;\n   default: r=0;\n  endcase\n"), "cdi")
    clean("one default in each of TWO case statements",
          amod("  case (1)\n   default: r=1;\n  endcase\n"
               "  case (2)\n   default: r=2;\n  endcase\n"), "cdtwo")

    # =====================================================================
    print("\n[5] the two garbled diagnostic strings")
    _, rc, out = build(HDR + "module dut(p, n);\n inout p, n; electrical p, n;\n"
                       ' parameter real q = $simparam("gmin", 0.0);\n'
                       " analog I(p, n) <+ q*V(p, n);\nendmodule\n", "s1")
    check("L015's help spells `parameters` and closes its quotes",
          'parameters like "gmin" or "sourceScaleFactor"' in out,
          [l.strip() for l in out.splitlines() if "help:" in l][:1])
    check("...and the old spelling is gone", "paramaeters" not in out and "gmin'" not in out)
    _, rc, out = build(amod("  r = $simprobe(p, n);\n"), "s2")
    check("the argument-type error reads as one sentence",
          "type mismatch: invalid function arguments" in out,
          [l.strip() for l in out.splitlines() if l.startswith("error")][:1])

    for j in os.listdir(HERE):
        if j.startswith("_rg_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
