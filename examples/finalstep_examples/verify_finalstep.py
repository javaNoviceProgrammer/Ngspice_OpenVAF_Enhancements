#!/usr/bin/env python3
"""
verify_finalstep.py -- verifies Enhancement-53: @(final_step) firing at the
end of each analysis, and analysis-phase lists on step events, end-to-end
through the committed openvaf-r + ngspice.

Two defects fixed:
  * @(final_step) never fired: E-7 implemented @(initial_step) via a one-shot
    EVAL_FLAG_IS_INITIAL_STEP but left final_step as a documented fail-safe
    no-op (firing needs "the analysis is over" knowledge the eval loop doesn't
    have). Now the analyses (dctran.c, dcop.c, dctrcurv.c, acan.c) call a new
    OSDIfinalStep() once on successful completion: one dedicated eval() per
    OSDI instance with EVAL_FLAG_IS_FINAL_STEP (1<<21) set, computed at the
    converged final solution; its results are not loaded into the matrix/RHS.
  * analysis-phase lists (`@(initial_step("tran","ac"))`, LRM 5.10.2) were
    silently dropped: the AST/HIR always carried `phases`, but
    lower_event_control ignored them (the recurring scaffolded-but-unwired
    pattern). They now AND the step flag with the same per-name
    CallBackKind::Analysis matcher analysis() uses (E-30), OR-ed across names.

Checks (parsing the tagged $strobe lines from ngspice stdout):
  1. tran 2u (two full 1 MHz sine periods): `final` fires exactly once, at
     t=2e-6, with V = 1.0 (sin(4*pi)=0) exactly; `final_tran` fires;
     `final_ac`/`final_dc` do NOT; `initial_tran` + the multi-phase
     `initial_ac_tran` fire; `initial_ac` does NOT
  2. op: single point = both first and last -> `initial`, `initial_dc`,
     `final`, `final_dc` fire once each; tran/ac-qualified events do NOT
  3. ac sweep: `final` + `final_ac` fire exactly once; `initial_ac` and the
     multi-phase list fire; `final_tran`/`final_dc` do NOT
  4. dc sweep (0->2V): `final` fires exactly once with V = 2.0 (the last
     sweep point); `final_dc` fires; `final_tran`/`final_ac` do NOT
  5. noise sweep: `initial` and `final` fire exactly once each;
     tran/dc-qualified events do NOT
  6. peak tracking (the LRM's classic use case): a variable accumulated
     across the whole tran is reported once at final_step: vpeak = 1.5
     (offset 1 V + amplitude 0.5 V), tol 1%%

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def run(deck):
    with open(os.path.join(HERE, "_fs.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_fs.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    events = []
    for line in out.splitlines():
        m = re.search(r"FS_LOG (\w+)\s+t=(\S+)(?:\s+V=(\S+))?", line)
        if m:
            events.append((m.group(1), float(m.group(2)),
                           float(m.group(3)) if m.group(3) else None))
        m = re.search(r"FS_PEAK vpeak=(\S+)", line)
        if m:
            events.append(("vpeak", float(m.group(1)), None))
    return events


def main():
    subprocess.run([OPENVAF, "finalstep_demo.va", "-o", "finalstep_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    def count(events, tag):
        return sum(1 for e in events if e[0] == tag)

    print("[1] tran: final_step once at tstop, phase filters honored")
    deck = ("* fs tran\nV1 in 0 DC 1 SIN(1 0.5 1meg)\nN1 in 0 mlog\n"
            ".model mlog fslog\n.control\npre_osdi finalstep_demo.osdi\n"
            "tran 10n 2u\n.endc\n.end\n")
    ev = run(deck)
    fin = [e for e in ev if e[0] == "final"]
    check("final fires exactly once", len(fin) == 1)
    check("final at t=2e-6", len(fin) == 1 and abs(fin[0][1] - 2e-6) < 1e-12)
    check("final sees converged V(tstop)=1.0",
          len(fin) == 1 and abs(fin[0][2] - 1.0) < 1e-6)
    check("final_tran fires once", count(ev, "final_tran") == 1)
    check("final_ac silent", count(ev, "final_ac") == 0)
    check("final_dc silent", count(ev, "final_dc") == 0)
    check("initial fires once", count(ev, "initial") == 1)
    check("initial_tran fires", count(ev, "initial_tran") == 1)
    check("initial_ac silent in tran", count(ev, "initial_ac") == 0)
    check("multi-phase (ac,tran) fires in tran", count(ev, "initial_actran") == 1)

    print("[2] op: single point is both first and last")
    deck = ("* fs op\nV1 in 0 DC 1\nN1 in 0 mlog\n.model mlog fslog\n"
            ".control\npre_osdi finalstep_demo.osdi\nop\n.endc\n.end\n")
    ev = run(deck)
    check("initial + final fire once each",
          count(ev, "initial") == 1 and count(ev, "final") == 1)
    check("initial_dc + final_dc fire",
          count(ev, "initial_dc") == 1 and count(ev, "final_dc") == 1)
    check("tran/ac-qualified silent",
          count(ev, "initial_tran") + count(ev, "final_tran")
          + count(ev, "initial_ac") + count(ev, "final_ac") == 0)

    print("[3] ac: final_step once after the frequency sweep")
    deck = ("* fs ac\nV1 in 0 DC 1 AC 1\nN1 in 0 mlog\n.model mlog fslog\n"
            ".control\npre_osdi finalstep_demo.osdi\nac dec 10 1k 1meg\n"
            ".endc\n.end\n")
    ev = run(deck)
    check("final + final_ac fire once each",
          count(ev, "final") == 1 and count(ev, "final_ac") == 1)
    check("initial_ac + multi-phase fire",
          count(ev, "initial_ac") == 1 and count(ev, "initial_actran") == 1)
    check("tran/dc-qualified final silent",
          count(ev, "final_tran") + count(ev, "final_dc") == 0)

    print("[4] dc sweep: final_step once at the last sweep point")
    deck = ("* fs dc\nV1 in 0 DC 0\nN1 in 0 mlog\n.model mlog fslog\n"
            ".control\npre_osdi finalstep_demo.osdi\ndc V1 0 2 0.1\n"
            ".endc\n.end\n")
    ev = run(deck)
    fin = [e for e in ev if e[0] == "final"]
    check("final fires exactly once", len(fin) == 1)
    check("final sees the last sweep point V=2.0",
          len(fin) == 1 and abs(fin[0][2] - 2.0) < 1e-6)
    check("final_dc fires, tran/ac silent",
          count(ev, "final_dc") == 1
          and count(ev, "final_tran") + count(ev, "final_ac") == 0)

    print("[5] noise: final_step once after the noise sweep")
    deck = ("* fs noise\nV1 in 0 DC 1 AC 1\nN1 in 0 mlog\nR1 in out 1k\n"
            "C1 out 0 1n\n.model mlog fslog\n.control\n"
            "pre_osdi finalstep_demo.osdi\nnoise v(out) V1 dec 5 1k 100k\n"
            ".endc\n.end\n")
    ev = run(deck)
    check("initial + final fire once each",
          count(ev, "initial") == 1 and count(ev, "final") == 1)
    check("tran/dc-qualified silent",
          count(ev, "final_tran") + count(ev, "final_dc") == 0)

    print("[6] the classic use case: peak tracked all run, reported once at the end")
    deck = ("* fs peak\nV1 in 0 DC 1 SIN(1 0.5 1meg)\nN1 in 0 mpk\n"
            ".model mpk fspeak\n.control\npre_osdi finalstep_demo.osdi\n"
            "tran 5n 2u\n.endc\n.end\n")
    ev = run(deck)
    pk = [e for e in ev if e[0] == "vpeak"]
    check("vpeak reported exactly once", len(pk) == 1)
    check("vpeak = 1.5 (offset + amplitude), 1% tol",
          len(pk) == 1 and abs(pk[0][1] - 1.5) < 0.015)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
