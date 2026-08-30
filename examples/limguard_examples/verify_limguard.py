#!/usr/bin/env python3
"""Enhancement-396: ten defects from a one-hour hunt aimed at openvaf-r.

One is a hard crash, two are silent wrong answers, and the rest are input that
was accepted and then degraded quietly at run time.

  [1] $limit WITH ANY UNRESOLVABLE NAME OR ARITY SEGFAULTED THE SIMULATOR.

      Source that compiled clean killed ngspice with **zero output**. ngspice
      resolves the name against a fixed table at load time -- pnjlim (2 extra
      args), fetlim (1), limitlog (1), limvds (0) -- and on a mismatch it
      printed "ignoring..." and left `func_ptr` NULL. The compiled model then
      CALLED that pointer. The warning never reached anyone either: it went to
      stdout and was destroyed, unflushed, by the crash it was warning about.

      `fetlim` takes 1 extra argument here and 2 in the LRM (`vto, vgst`), so
      writing the LRM spelling was one of the ways to crash.

      There is no safe way to continue -- the call site is already compiled to
      an indirect call -- so an unresolvable entry is now a hard load failure
      naming the function, both arities and the supported set, on stderr. The
      compiler additionally raises the `unknown_limit_function` lint at build
      time, when the model is still in front of its author. That is a lint and
      not an error because the set is simulator-defined.

  [2] AND [3] A COLLISION WARNING THAT FIRED ON ALMOST THE WHOLE INDUSTRY
      CORPUS, FOR AN ARRANGEMENT THAT IS DELIBERATE.

      Enhancement-335 warns when two OSDI parameters fold to one lowercased
      SPICE keyword, because one of them then becomes unreachable from a deck.
      It compared KEYWORDS only -- and a model that declares one of the names
      the loader also provides has TWO entries under that keyword by design:
      `osdi_create_registry_entry` ROUTES its built-in to the model's own
      parameter (`dtemp` sets `dt = param_id`, `m` sets `has_m`, `temp`
      suppresses the loader's entry). Both entries address the same parameter
      id and nothing is unreachable.

      `dtemp` is a conventional CMC instance parameter, so the warning fired for
      PSP 103/104, MEXTRAM 504/505, VBIC, BSIM-BULK/CMG/IMG/SOI, HiSIM 2/HV/SOI/
      SOTB, L-UTSOI, EKV, MVSG, ASM-HEMT, JUNCAP200, r2/r3_cmc -- **69 warnings
      across the corpus**, none of them a real problem, and each one worded as
      "declared more than once differing only in case" when the two spellings
      are identical and there is no second declaration to find.

      Comparing parameter IDS is what separates the two situations. The corpus
      now emits **5** warnings, all of them genuine `GAIN`/`gain`-style clashes
      between parameters with different ids.

      WITHDRAWN, and recorded because the mistake is instructive: this was first
      reported as "a model parameter named `m` silently defeats Enhancement-394's
      subcircuit multiplier", on the evidence that a model declaring `m` gave 1x
      under `X1 ... m=3`. That probe declared `m` and never USED it. A real CMC
      model declares `m` AND scales its own output by it, which is exactly why
      `has_m` exists -- and then `X1 ... m=3` scales correctly, as the accept
      half below pins at 1x, 3x and 5x. The multiplier is DELIVERED through the
      model's parameter, not defeated by it.

  [4] $table_model DATA FILES ACCEPTED NON-FINITE VALUES.

      `abc` was rejected but `nan`, `inf` and an overflowing exponent such as
      1e400 parsed straight through and poisoned the WHOLE table -- every query,
      including points that should interpolate between valid rows, returned NaN.
      A missing-data marker is exactly how measured data files spell one, which
      is precisely when the diagnostic is wanted.

  [5] @(timer) WITH A DEGENERATE PERIOD FIRED ON EVERY EVALUATION.

      Over a 10 us transient a 1 us timer gives 10 events. A period of zero, a
      negative period and a denormal one all gave **120** -- one per timestep.
      So a period computed as `1/freq` with `freq = 0` silently turned a sampler
      into a per-iteration event.

  [6] $bound_step WAS UNVALIDATED.

      Zero and denormal aborted the analysis with a "Timestep too small" that
      named neither the model nor the call; **negative silently forced the
      minimum timestep everywhere** -- 10001 output rows against 108.

  [7] noise_table SHAPE WAS UNVALIDATED.

      An empty or single-entry array made the device contribute NO NOISE AT ALL;
      an odd length dropped the unpaired entry; and a NEGATIVE noise power was
      accepted and produced the same spectrum as its positive twin, so the sign
      was quietly discarded.

  [8] OUT-OF-RANGE ARRAY INDEXING -- fixed for every compile-time-constant
      index (literal, negative, write target, localparam). See the scope note
      at the end for the runtime-index case.

  [9] A BUS PORT'S TWO RANGES COULD DISAGREE.

      `inout [0:2] b;` beside `electrical [0:4] b;` was accepted; the direction
      range won and the net's other two bits were discarded, so the module had
      fewer terminals than its own source said.

 [10] A FAMILY OF UNVALIDATED CONSTANT ARGUMENTS: a `@(cross)` direction that
      is not -1/0/+1, negative `transition` delay/rise/fall, a non-positive
      `slew` rate, a zero or negative `idtmod` modulus, a negative `absdelay`
      delay, and a delay exceeding the declared maximum.

SCOPE BOUNDARY, stated rather than hidden: an out-of-range array index computed
at RUN TIME is still masked rather than diagnosed. It is memory-SAFE -- verified
with a canary below: reads fold to element 0, writes are discarded, nothing
around the array is touched, for indices from -100 to 10^6. Diagnosing it would
mean a bounds check on every array access in the inner evaluation loop of every
compact model, which is a real cost to catch a mistake the constant-index checks
already catch in the form models actually write.

Every check below is paired: the reject half pins the defect, and the accept
half pins that legitimate input still compiles and still gives the same number.
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


def build(src, tag, extra=None):
    d = os.path.join(HERE, "_op_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    for name, content in (extra or {}).items():
        open(os.path.join(d, name), "w").write(content)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def run(d, deck, guard=45):
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def deck(net="N1 a 0 mm", card="dut()", body="op\nprint i(v1)", src="V1 a 0 dc 1", extra=""):
    return ("p\n.control\npre_osdi m.osdi\n.endc\n" + src + "\n" + net + "\n"
            ".model mm " + card + "\n" + extra +
            "\n.control\noption noacct\nset numdgt=12\n" + body + "\n.endc\n.end\n")


def cur(out):
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", out, re.M)
    return float(m.group(1)) if m else None


def opvar(out, name):
    m = re.search(rf"@\S*n1\[{re.escape(name)}\]\s*=\s*(\S+)", out)
    return float(m.group(1)) if m else None


def mod(body, decl="", ports="p,n", nets="electrical p,n;"):
    return (HDR + f"module dut({ports});\n inout {ports}; {nets}\n{decl}\n"
            f" analog begin {body} end\nendmodule\n")


def main():
    # ================================================== [1] the $limit crash
    print("\n  -- [1] $limit with an unresolvable name or arity --")
    LIMITERS = [
        ("pnjlim with 2 extra args", '$limit(V(p,n),"pnjlim",0.025,0.6)', True),
        ("fetlim with 1 extra arg", '$limit(V(p,n),"fetlim",1.0)', True),
        ("limitlog with 1 extra arg", '$limit(V(p,n),"limitlog",1.0)', True),
        ("limvds with 0 extra args", '$limit(V(p,n),"limvds")', True),
        ("no limiter at all", '$limit(V(p,n))', True),
        ("fetlim with the LRM's 2 args", '$limit(V(p,n),"fetlim",1.0,0.5)', False),
        ("an unknown limiter name", '$limit(V(p,n),"nosuchlimiter",1.0)', False),
        ("an empty limiter name", '$limit(V(p,n),"")', False),
        ("pnjlim with the wrong arity", '$limit(V(p,n),"pnjlim",0.025)', False),
    ]
    for label, call, resolvable in LIMITERS:
        d, rc, out = build(mod(f"I(p,n) <+ {call}*1e-3;"), "lim")
        # the compiler always accepts it; the lint fires only when unresolvable
        linted = "does not provide" in out
        check(f"{label}: compiles" + ("" if resolvable else " and is linted"),
              rc == 0 and linted != resolvable, f"rc={rc} lint={linted}")
        rcs, o = run(d, deck())
        if resolvable:
            check(f"{label}: simulates", rcs == 0 and cur(o) is not None, f"rc={rcs}")
        else:
            # the crash was rc = -11 (SIGSEGV) with zero bytes of output
            check(f"{label}: refuses to load instead of crashing",
                  rcs > 0 and "$limit" in o, f"rc={rcs}")
            check(f"{label}: the error names the supported set",
                  "pnjlim" in o and "fetlim" in o, "")

    # ============================================ [2]/[3] parameter collisions
    print("\n  -- [2]/[3] built-in parameter collisions --")

    # A CMC-style model: declares `m` AND scales by it, which is what `has_m`
    # exists for. The subcircuit multiplier must arrive through that parameter.
    CMC = HDR + """module dut(p,n);
 inout p,n; electrical p,n;
 (*type="instance"*) parameter real m = 1.0;
 (*type="instance"*) parameter real dtemp = 0.0;
 analog begin I(p,n) <+ m*V(p,n)*1e-3; end
endmodule
"""
    d, rc, out = build(CMC, "cmc")
    check("a CMC-style model (own `m` and `dtemp`) compiles", rc == 0,
          out.strip().splitlines()[:1])
    if rc == 0:
        for mult, want in [("", -1e-3), (" m=3", -3e-3), (" m=5", -5e-3)]:
            rcs, o = run(d, ("p\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\n"
                             f"X1 a 0 s{mult}\n.subckt s p n\nN1 p n mm\n"
                             ".model mm dut()\n.ends\n"
                             ".control\noption noacct\nset numdgt=12\nop\n"
                             "print i(v1)\n.endc\n.end\n"))
            check(f"E-394's multiplier arrives through the model's own `m`: X1{mult or ' (none)'}",
                  cur(o) is not None and abs(cur(o) - want) < 1e-12, f"{cur(o)}")
        rcs, o = run(d, deck())
        check("and declaring `m`/`dtemp` produces NO warning (the loader routes them)",
              not [ln for ln in o.splitlines() if ln.startswith("Warning")],
              [ln.strip()[:60] for ln in o.splitlines() if ln.startswith("Warning")][:1])

    for name in ("temp", "dt"):
        d, rc, out = build(mod("I(p,n) <+ V(p,n)*1e-3;",
                               decl=f' (*type="instance"*) parameter real {name} = 1.0;'),
                           "route_" + name)
        rcs, o = run(d, deck())
        check(f"declaring '{name}' produces no warning either",
              rc == 0 and not [ln for ln in o.splitlines() if ln.startswith("Warning")],
              [ln.strip()[:60] for ln in o.splitlines() if ln.startswith("Warning")][:1])

    # the genuine E-335 clash must still be reported
    d, rc, out = build(mod("I(p,n) <+ V(p,n)*1e-3*GAIN*gain;",
                           decl=' (*type="instance"*) parameter real GAIN = 1.0;\n'
                                ' (*type="instance"*) parameter real gain = 2.0;'), "case")
    rcs, o = run(d, deck())
    check("a real case collision between DIFFERENT parameters is still reported",
          "differing only in case" in o,
          [ln.strip()[:60] for ln in o.splitlines() if ln.startswith("Warning")][:1])

    # ================================================== [4] table data files
    print("\n  -- [4] non-finite values in a $table_model data file --")
    TBL = mod('y = $table_model(V(p,n), "t.tbl", "1L"); I(p,n) <+ V(p,n)*1e-3;',
              decl=' (* desc="y" *) real y;')
    for label, content, ok in [
        ("a well-formed table", "0.0 0.0\n1.0 2.0\n2.0 4.0\n3.0 6.0\n", True),
        ("comments and blank lines", "# g\n0.0 0.0\n\n1.0 2.0\n2.0 4.0\n", True),
        ("a nan abscissa", "0.0 0.0\nnan 2.0\n2.0 4.0\n", False),
        ("an inf ordinate", "0.0 0.0\n1.0 inf\n2.0 4.0\n", False),
        ("-infinity", "0.0 0.0\n1.0 -infinity\n2.0 4.0\n", False),
        ("an overflowing exponent 1e400", "0.0 0.0\n1.0 1e400\n2.0 4.0\n", False),
    ]:
        _d, rc2, o2 = build(TBL, "tbl", extra={"t.tbl": content})
        check(f"{label} is {'accepted' if ok else 'rejected'}", (rc2 == 0) == ok,
              (o2.strip().splitlines() or [""])[0][:52])

    # ---- [5] a degenerate period must fire ONCE, not once per evaluation ----
    # This is the invariant finding [5] actually cared about: a period of zero
    # used to give 120 events over a 10 us run, one per timestep.
    for lbl, per, want in [("period 0", "0", 1), ("period -1us", "-1e-6", 1),
                           ("period 1us", "1e-6", 11), ("no period", None, 1)]:
        ev = f"@(timer(0, {per}))" if per is not None else "@(timer(0))"
        d, rc, _ = build(mod(f'{ev} $strobe("TK"); I(p,n) <+ V(p,n)*1e-3;'), "tk")
        if rc != 0:
            check(f"[E-445] timer {lbl} compiles", False, f"rc={rc}")
            continue
        _, out = run(d, deck(body="tran 1u 10u"))
        n = len(re.findall("TK", out))
        check(f"[E-445] timer {lbl} fires {want}x, not once per timestep",
              n == want, f"fired {n}x")

    # ---- the LRM's trailing `enable`, on all three monitored events ----
    # LRM 5.10.3: cross/above/timer each end in an optional `enable`, and the
    # event is live only while it is non-zero. It used to be counted as a
    # SURPLUS argument and rejected, so an event could not be gated at all --
    # and wrapping the event's BODY in an `if` is not the same thing, because
    # the event still fires and still drags the timestep to its schedule.
    #
    # The gate is applied to the FIRED flag, not to the event's own state, so a
    # disabled event keeps its schedule instead of restarting. Both halves are
    # pinned: the timer fires on the SAME grid it would have used ungated, and a
    # crossing that happens while disabled is not replayed when the enable
    # returns -- only crossings that occur while enabled fire, per 5.10.3.2.
    print("\n  -- LRM 5.10.3 `enable` on @(cross)/@(above)/@(timer) --")
    for lbl, ev, want in [
        ("@(timer) enable 1", "timer(1e-6, 2e-6, 0, 1)", True),
        ("@(timer) enable 0", "timer(1e-6, 2e-6, 0, 0)", False),
        ("@(timer) enable 7 (any non-zero)", "timer(1e-6, 2e-6, 0, 7)", True),
        ("@(timer) enable -1 (any non-zero)", "timer(1e-6, 2e-6, 0, -1)", True),
        ("@(above) enable 1", "above(V(p,n)-0.5, 1e-9, 1e-6, 1)", True),
        ("@(above) enable 0", "above(V(p,n)-0.5, 1e-9, 1e-6, 0)", False),
        ("@(cross) enable 1", "cross(V(p,n)-0.5, 0, 1e-9, 1e-6, 1)", True),
        ("@(cross) enable 0", "cross(V(p,n)-0.5, 0, 1e-9, 1e-6, 0)", False),
    ]:
        d, rc, o2 = build(mod(f'@({ev}) $strobe("TK"); I(p,n) <+ V(p,n)*1e-3;'), "en")
        if rc != 0:
            check(f"{lbl} compiles", False, (o2.strip().splitlines() or [""])[0][:52])
            continue
        _, out = run(d, deck(src="V1 a 0 PWL(0 0 10u 2)",
                             body="tran 0.25u 10u", card="dut()"))
        n = len(re.findall("TK", out))
        check(f"{lbl} -> the event {'fires' if want else 'stays silent'}",
              (n > 0) == want, f"fired {n}x")

    # a runtime enable, decided by a .model parameter rather than a literal
    for lbl, ev in [("@(timer)", "timer(1e-6, 2e-6, 0, en)"),
                    ("@(above)", "above(V(p,n)-0.5, 1e-9, 1e-6, en)"),
                    ("@(cross)", "cross(V(p,n)-0.5, 0, 1e-9, 1e-6, en)")]:
        d, rc, o2 = build(mod(f'@({ev}) $strobe("TK"); I(p,n) <+ V(p,n)*1e-3;',
                              decl=" parameter integer en = 1;"), "enp")
        if rc != 0:
            check(f"{lbl} with a parameter enable compiles", False,
                  (o2.strip().splitlines() or [""])[0][:52])
            continue
        got = []
        for val in ("1", "0"):
            _, out = run(d, deck(src="V1 a 0 PWL(0 0 10u 2)", body="tran 0.25u 10u",
                                 card=f"dut() en={val}"))
            got.append(len(re.findall("TK", out)))
        check(f"{lbl} enable from a .model parameter: en=1 fires, en=0 silent",
              got[0] > 0 and got[1] == 0, f"en=1 -> {got[0]}x, en=0 -> {got[1]}x")

    # a TIME-VARYING enable: the gate rises at 4us, and the timer must resume on
    # its original 1us grid rather than restarting from the moment it went live
    GATE = "electrical p,n,g;"
    src = (HDR + "module dut(p,n,g);\n inout p,n; input g; " + GATE + "\n"
           ' analog begin @(timer(0, 1e-6, 0, V(g) > 0.5)) $strobe("TK %g", $abstime);\n'
           "  I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n")
    d, rc, o2 = build(src, "engate")
    if rc != 0:
        check("a time-varying enable compiles", False,
              (o2.strip().splitlines() or [""])[0][:52])
    else:
        _, out = run(d, deck(net="N1 a 0 g mm", src="V1 a 0 PWL(0 0 10u 2)",
                             extra="Vg g 0 PWL(0 0 3.99u 0 4.01u 1 10u 1)",
                             body="tran 0.2u 10u"))
        ts = [float(x) for x in re.findall(r"TK (\S+)", out)]
        check("a timer gated by a signal fires only while the signal is high",
              len(ts) > 0 and all(t > 3.99e-6 for t in ts), f"{len(ts)} fires: {ts[:3]}")
        check("and resumes on its ORIGINAL 1us grid, it does not restart",
              len(ts) > 0 and all(abs(t / 1e-6 - round(t / 1e-6)) < 1e-3 for t in ts),
              f"{[round(t*1e6, 3) for t in ts]}")

    # a crossing that happens while DISABLED is not replayed on re-enable.
    # v(a) ramps 0->2 over 10us, so V(p,n)-0.5 crosses zero once, near 2.5us.
    for lbl, gate, want in [
        ("enabled only after the crossing", "PWL(0 0 6.99u 0 7.01u 1 10u 1)", 0),
        ("enabled only before the crossing", "PWL(0 1 0.99u 1 1.01u 0 10u 0)", 0),
        ("enabled across the crossing", "PWL(0 0 0.99u 0 1.01u 1 10u 1)", 1),
    ]:
        src = (HDR + "module dut(p,n,g);\n inout p,n; input g; electrical p,n,g;\n"
               ' analog begin @(cross(V(p,n)-0.5, 0, 1e-9, 1e-6, V(g) > 0.5))'
               ' $strobe("TK");\n  I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n')
        d, rc, o2 = build(src, "encr")
        if rc != 0:
            check(f"@(cross) {lbl} compiles", False,
                  (o2.strip().splitlines() or [""])[0][:52])
            continue
        _, out = run(d, deck(net="N1 a 0 g mm", src="V1 a 0 PWL(0 0 10u 2)",
                             extra=f"Vg g 0 {gate}", body="tran 0.2u 10u"))
        n = len(re.findall("TK", out))
        check(f"@(cross) {lbl} -> {want} event(s)", n == want, f"fired {n}x")

    # an event LIST must respect EACH member's own enable. `@(a or b)` is one
    # Event::Or whose members hold the enables, so a type rule written against
    # the event's own variants saw only the Or and typed every member's enable
    # as a real -- which cast it int-to-real and then merged it with an i1. That
    # survived lowering intact and hung LLVM's type legalizer at codegen, so
    # every one of these forms crashed or spun the compiler.  The counts below
    # are exact, because "it compiles" would not have caught the gate being
    # applied to the wrong member.
    for lbl, ev, want in [
        ("timer(en=1) or cross", "timer(1e-6,2e-6,0,1) or cross(V(p,n)-0.5,0)", 6),
        ("timer(en=0) or cross -> the cross alone",
         "timer(1e-6,2e-6,0,0) or cross(V(p,n)-0.5,0)", 1),
        ("timer or cross(en=0) -> the timer alone",
         "timer(1e-6,2e-6) or cross(V(p,n)-0.5,0,1e-9,1e-6,0)", 5),
        ("both gated off -> nothing fires",
         "timer(1e-6,2e-6,0,0) or cross(V(p,n)-0.5,0,1e-9,1e-6,0)", 0),
        ("initial_step or timer(en=0) -> initial_step alone",
         "initial_step or timer(1e-6,2e-6,0,0)", 1),
        ("three members, the middle one gated off",
         "initial_step or timer(1e-6,2e-6,0,0) or above(V(p,n)-0.5,1e-9,1e-6,1)", 2),
    ]:
        d, rc, o2 = build(mod(f'@({ev}) $strobe("TK"); I(p,n) <+ V(p,n)*1e-3;'), "enor")
        if rc != 0:
            check(f"or-list: {lbl} compiles", False,
                  (o2.strip().splitlines() or [""])[0][:52])
            continue
        _, out = run(d, deck(src="V1 a 0 PWL(0 0 10u 2)", body="tran 0.25u 10u"))
        n = len(re.findall("TK", out))
        check(f"or-list: {lbl} -> {want} event(s)", n == want, f"fired {n}x")

    # one argument PAST the LRM arity is still refused, for each event
    for lbl, ev in [("@(timer) 5 args", "timer(1e-6, 2e-6, 0, 1, 9)"),
                    ("@(above) 5 args", "above(V(p,n)-0.5, 1e-9, 1e-6, 1, 9)"),
                    ("@(cross) 6 args", "cross(V(p,n)-0.5, 0, 1e-9, 1e-6, 1, 9)")]:
        _d, rc2, o2 = build(mod(f"@({ev}) I(p,n) <+ V(p,n)*1e-3;"), "ensur")
        check(f"{lbl} is still rejected as surplus", rc2 != 0 and rc2 != 101,
              (o2.strip().splitlines() or [""])[0][:52])

    # ================================================== [5]/[6]/[10] constants
    print("\n  -- [5] @(timer), [6] $bound_step, [10] operator arguments --")
    ARG_CASES = [
        # A NON-POSITIVE PERIOD IS LEGAL, and now fires exactly ONCE.
        # LRM 5.10.3.3: "If the period expression evaluates to a value less than
        # or equal to 0.0, the timer shall trigger only once at the specified
        # start_time." Finding [5] was that such a period fired on EVERY
        # evaluation (120 events over a 10 us run); refusing it at compile time
        # cured that, but also refused the way a one-shot is written when the
        # period is COMPUTED rather than omitted -- while `@(timer(t0))`, the same
        # request spelled differently, was accepted and did exactly that. The
        # lowering now routes a non-positive period to the same fire-once path, so
        # finding [5]'s invariant is kept by the firing COUNT pinned below rather
        # than by a compile error.
        ("@(timer) period 0", " integer c;", "@(timer(0, 0)) c = c+1;", True),
        ("@(timer) period negative", " integer c;", "@(timer(0, -1e-6)) c = c+1;", True),
        ("@(timer) start negative", " integer c;", "@(timer(-1.0, 1e-6)) c = c+1;", False),
        ("@(timer) period 1us", " integer c;", "@(timer(0, 1e-6)) c = c+1;", True),
        ("@(timer) with only a start", " integer c;", "@(timer(0)) c = c+1;", True),
        ("@(timer) period from a runtime expr", " integer c;",
         "@(timer(0, abs(V(p,n))*1e-6)) c = c+1;", True),
        ("$bound_step(0)", "", "$bound_step(0.0);", False),
        ("$bound_step(-1e-7)", "", "$bound_step(-1e-7);", False),
        ("$bound_step(1e-7)", "", "$bound_step(1e-7);", True),
        ("$bound_step from a runtime expr", "", "$bound_step(abs(V(p,n))*1e-7);", True),
        ("@(cross) direction 7", " integer c;", "@(cross(V(p,n)-0.5, 7)) c = c+1;", False),
        ("@(cross) direction -3", " integer c;", "@(cross(V(p,n)-0.5, -3)) c = c+1;", False),
        ("@(cross) direction +1", " integer c;", "@(cross(V(p,n)-0.5, +1)) c = c+1;", True),
        ("@(cross) direction 0", " integer c;", "@(cross(V(p,n)-0.5, 0)) c = c+1;", True),
        ("transition negative delay", "",
         "I(p,n) <+ transition(V(p,n), -1e-6, 1e-9, 1e-9)*0.0;", False),
        ("transition negative rise", "",
         "I(p,n) <+ transition(V(p,n), 0.0, -1e-9, 1e-9)*0.0;", False),
        ("transition all non-negative", "",
         "I(p,n) <+ transition(V(p,n), 0.0, 1e-9, 1e-9)*0.0;", True),
        ("slew non-positive rise rate", "", "I(p,n) <+ slew(V(p,n), -1e6, -1e6)*0.0;", False),
        ("slew non-negative fall rate", "", "I(p,n) <+ slew(V(p,n), 1e6, 1e6)*0.0;", False),
        ("slew with the right signs", "", "I(p,n) <+ slew(V(p,n), 1e6, -1e6)*0.0;", True),
        ("idtmod modulus 0", "", "I(p,n) <+ idtmod(V(p,n), 0.0, 0.0, 0.0)*0.0;", False),
        ("idtmod modulus negative", "", "I(p,n) <+ idtmod(V(p,n), 0.0, -1.0, 0.0)*0.0;", False),
        ("idtmod modulus positive", "", "I(p,n) <+ idtmod(V(p,n), 0.0, 1.0, 0.0)*0.0;", True),
        ("absdelay negative delay", "", "I(p,n) <+ absdelay(V(p,n), -1e-6)*0.0;", False),
        # Enhancement-514: NOT rejected any more. LRM 4.5.7 DEFINES what happens
        # -- "If td becomes greater than maxdelay, maxdelay will be used as a
        # substitute for td" -- so refusing the model rejected a conformant
        # program. It warns instead, and the substitution happens; the warning is
        # asserted separately in examples/lrmops_examples/.
        ("absdelay delay > maxdelay", "", "I(p,n) <+ absdelay(V(p,n), 1e-3, 1e-9)*0.0;", True),
        ("absdelay delay <= maxdelay", "", "I(p,n) <+ absdelay(V(p,n), 1e-7, 1e-6)*0.0;", True),
    ]
    for label, decl, body, ok in ARG_CASES:
        _d, rc2, o2 = build(mod(body + " I(p,n) <+ V(p,n)*1e-3;", decl=decl), "arg")
        check(f"{label} is {'accepted' if ok else 'rejected'}", (rc2 == 0) == ok,
              (o2.strip().splitlines() or [""])[0][:52])

    # ================================================== [7] noise_table
    print("\n  -- [7] noise_table shape --")
    for label, arr, ok in [
        ("a well-formed (f, p) list", "'{1.0, 1e-18, 1e9, 1e-18}", True),
        ("an empty array", "'{}", False),
        ("a single entry", "'{1.0}", False),
        ("an odd length", "'{1.0, 1e-18, 1e9}", False),
        ("a negative noise power", "'{1.0, -1e-18, 1e9, 1e-18}", False),
        ("a negative frequency", "'{-1.0, 1e-18, 1e9, 1e-18}", False),
    ]:
        _d, rc2, o2 = build(mod(f'I(p,n) <+ V(p,n)*1e-3 + noise_table({arr}, "nt");'), "nt")
        check(f"noise_table with {label} is {'accepted' if ok else 'rejected'}",
              (rc2 == 0) == ok, (o2.strip().splitlines() or [""])[0][:52])

    # ================================================== [8] array indexing
    print("\n  -- [8] out-of-range array indexing --")
    for label, decl, body, ok in [
        ("a literal read past the end", " real arr[0:2];",
         "arr[0]=1.0; I(p,n) <+ V(p,n)*1e-3*arr[5];", False),
        ("a literal negative index", " real arr[0:2];",
         "arr[0]=1.0; I(p,n) <+ V(p,n)*1e-3*arr[-1];", False),
        ("a literal write past the end", " real arr[0:2];",
         "arr[5]=1.0; I(p,n) <+ V(p,n)*1e-3*arr[0];", False),
        ("a localparam index past the end",
         " localparam integer K = 5;\n real arr[0:2];",
         "arr[0]=1.0; I(p,n) <+ V(p,n)*1e-3*arr[K];", False),
        ("an in-range literal index", " real arr[0:2];",
         "arr[2]=2.0; I(p,n) <+ V(p,n)*1e-3*arr[2];", True),
    ]:
        _d, rc2, o2 = build(mod(body, decl=decl), "idx")
        check(f"{label} is {'accepted' if ok else 'rejected'}", (rc2 == 0) == ok,
              (o2.strip().splitlines() or [""])[0][:52])

    # the runtime-index boundary: masked, but provably memory-safe
    SAFE = HDR + """module dut(p,n);
 inout p,n; electrical p,n;
 parameter integer idx = 0;
 (* desc="canary" *) real canary;
 (* desc="a0" *) real a0;
 (* desc="a2" *) real a2;
 real arr[0:2];
 integer i;
 analog begin
   canary = 42.0;
   arr[0] = 10.0; arr[1] = 20.0; arr[2] = 30.0;
   i = idx;
   arr[i] = -999.0;
   a0 = arr[0]; a2 = arr[2];
   I(p,n) <+ V(p,n)*1e-3;
 end
endmodule
"""
    d, rc, out = build(SAFE, "safe")
    check("the runtime-index probe compiles", rc == 0, out.strip().splitlines()[:1])
    if rc == 0:
        allsafe = True
        for i in (3, 5, 100, -1, -100, 1000000):
            rcs, o = run(d, deck(card=f"dut(idx={i})",
                                 body="op\nprint @n1[canary] @n1[a0] @n1[a2]"))
            ok = (rcs == 0 and opvar(o, "canary") == 42.0
                  and opvar(o, "a0") == 10.0 and opvar(o, "a2") == 30.0)
            allsafe &= ok
        check("a runtime out-of-range index is memory-safe (canary and array intact)",
              allsafe, "indices 3, 5, 100, -1, -100, 1000000")

    # ================================================== [9] bus port ranges
    print("\n  -- [9] a bus port's two ranges --")
    for label, ports, nets, ok in [
        ("port [0:2] against net [0:4]", "inout [0:2] b; inout n;",
         "electrical [0:4] b; electrical n;", False),
        ("port [0:4] against net [0:2]", "inout [0:4] b; inout n;",
         "electrical [0:2] b; electrical n;", False),
        ("port [2:0] against net [0:2]", "inout [2:0] b; inout n;",
         "electrical [0:2] b; electrical n;", False),
        ("matching [0:2]", "inout [0:2] b; inout n;",
         "electrical [0:2] b; electrical n;", True),
        ("matching descending [2:0]", "inout [2:0] b; inout n;",
         "electrical [2:0] b; electrical n;", True),
    ]:
        src = (HDR + f"module dut(b,n);\n {ports} {nets}\n"
               " analog I(b[0],n) <+ V(b[0],n)*1e-3;\nendmodule\n")
        _d, rc2, o2 = build(src, "bus")
        check(f"{label} is {'accepted' if ok else 'rejected'}", (rc2 == 0) == ok,
              (o2.strip().splitlines() or [""])[0][:52])

    # a scalar-port model must be entirely unaffected
    _d, rc2, o2 = build(mod("I(p,n) <+ V(p,n)*1e-3;"), "scalar")
    rcs, o = run(_d, deck())
    check("a scalar-port model still compiles and gives -1.0e-03",
          rc2 == 0 and cur(o) is not None and abs(cur(o) + 1e-3) < 1e-12, f"{cur(o)}")

    for j in os.listdir(HERE):
        if j.startswith("_op_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    return 0 if passed == checks else 1


sys.exit(main())
