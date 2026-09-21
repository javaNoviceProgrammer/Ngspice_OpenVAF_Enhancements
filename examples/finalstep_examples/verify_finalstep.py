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
  7. (E-677) ac/noise: the final_step evaluation runs on the bias point
  8. (E-683, hunt F2 of 2026-09-21) final_step fires once at the end of pz,
     tf, sens (dc and ac), disto and sp, at the bias point; a counter
     assigned in the block reads 1 afterwards under ac and noise too (the
     E-412 snapshot is kept only for an evaluation with no bias point); an op
     after an ac, at a new bias, sees the new bias (the capture does not go
     stale)

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
        m = re.search(r"FS_OP V=(\S+) tl=(\S+)", line)
        if m:
            events.append(("op_read", float(m.group(1)), float(m.group(2))))
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

    # Enhancement-677 (hunt F6 of 2026-09-19): after an ac or a noise sweep
    # CKTrhsOld holds the small-signal solution at the last frequency, and the
    # final_step evaluation ran on it: V(p,n) read 1 (the unit AC source's
    # response) at a 0.2 V bias, and last_crossing() read 0 -- a valid time --
    # where LRM 4.5.10 requires a negative value before any crossing. The
    # evaluation runs on the bias point the analysis linearised around.
    print("[7] ac/noise: the final_step evaluation runs on the operating point")
    for name, an in (("op (control)", "op"), ("ac", "ac dec 2 1k 10k"),
                     ("noise", "noise v(in) V1 dec 2 1k 10k")):
        deck = (f"* fs {name}\nV1 in 0 DC 0.2 AC 1\nN1 in 0 mop\n.model mop fsop\n"
                f".control\npre_osdi finalstep_demo.osdi\n{an}\n.endc\n.end\n")
        ev = run(deck)
        rd = [e for e in ev if e[0] == "op_read"]
        check(f"{name}: final sees the bias V=0.2 and last_crossing's negative sentinel",
              len(rd) == 1 and abs(rd[0][1] - 0.2) < 1e-9 and rd[0][2] < 0)

    # Enhancement-683 (hunt F2 of 2026-09-21): pz, tf, sens, disto and sp did
    # not call the OSDI final step at all, and under ac/noise the E-412
    # snapshot discarded what the @(final_step) body assigned. Every analysis
    # fires it once, at the bias point, and the assignments stay.
    print("[8] final_step at the end of every analysis, its writes kept")
    OPV = "@" + "n1[cf]"
    FSCNT = ("* fs cnt {name}\nV1 in 0 DC 0.2 AC 1 {vsrc}\nN1 in 0 mcnt\n.model mcnt fscnt\n"
             "R1 in a 1k\nR2 a 0 1k\nC1 a 0 1n\n{extra}"
             ".control\npre_osdi finalstep_demo.osdi\n{an}\nprint " + OPV + "\n.endc\n.end\n")

    def run_cnt(name, an, vsrc="", extra=""):
        with open(os.path.join(HERE, "_fs.cir"), "w") as fh:
            fh.write(FSCNT.format(name=name, an=an, vsrc=vsrc, extra=extra))
        out = subprocess.run([NGSPICE, "-b", "_fs.cir"], cwd=HERE,
                             capture_output=True, text=True, timeout=120).stdout
        fired = re.findall(r"FS_CNT cf=(\d+) V=(\S+)", out)
        m = re.search(re.escape(OPV) + r"\s*=\s*(\S+)", out)
        return fired, (float(m.group(1)) if m else None)

    # The sp deck's ports carry their z0 = 50 ohm: in series with the 0.2 V
    # port, as a shunt at the second port on node a. The bias at `in` is then
    # 0.2 * RL / (RL + 50) with RL = 1k || (1k + 1k || 50) = 511.6 ohm.
    rl = 1.0 / (1.0 / 1e3 + 1.0 / (1e3 + 1.0 / (1.0 / 1e3 + 1.0 / 50.0)))
    v_sp = 0.2 * rl / (rl + 50.0)
    for name, an, vsrc, extra, vbias in (
            ("pz", "pz in 0 a 0 vol pz", "", "", 0.2),
            ("tf", "tf v(a) V1", "", "", 0.2),
            ("sens (dc)", "sens v(a)", "", "", 0.2),
            ("sens (ac)", "sens v(a) ac lin 2 1k 2k", "", "", 0.2),
            ("disto", "disto lin 1 1k 1k", "distof1 0.01", "", 0.2),
            ("sp", "sp lin 2 1k 2k", "portnum 1 z0 50", "V2 a 0 DC 0 portnum 2 z0 50\n", v_sp)):
        fired, cf = run_cnt(name, an, vsrc, extra)
        check(f"{name}: final fires exactly once, at the bias V={vbias:.4g}, and the counter reads 1 afterwards",
              len(fired) == 1 and fired[0][0] == "1" and abs(float(fired[0][1]) - vbias) < 1e-6 and cf == 1)
    for name, an in (("ac", "ac dec 2 1k 10k"), ("noise", "noise v(a) V1 dec 2 1k 10k")):
        fired, cf = run_cnt(name, an)
        check(f"{name}: the counter assigned in final_step reads 1 afterwards (was 0: the snapshot discarded it)",
              len(fired) == 1 and abs(float(fired[0][1]) - 0.2) < 1e-9 and cf == 1)
    fired, cf = run_cnt("op after ac", "ac dec 2 1k 10k\nalter V1 dc=0.4\nop")
    check("an op after an ac, at a new bias: final sees the new bias V=0.4 (the capture does not go stale)",
          len(fired) == 2 and abs(float(fired[0][1]) - 0.2) < 1e-9 and abs(float(fired[1][1]) - 0.4) < 1e-9 and cf == 1)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
