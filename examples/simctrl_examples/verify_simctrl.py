#!/usr/bin/env python3
"""
verify_simctrl.py -- verifies Enhancement-55: the simulation-control system
tasks ($finish, $stop, $fatal) honored by ngspice, and $discontinuity(n>=0)
timestep REJECTION, end-to-end through the committed openvaf-r + ngspice.

Defects fixed:
  * $finish was ignored entirely (EVAL_RET_FLAG_FINISH never checked in the
    load path): the transient ran to its full stop time;
  * $stop returned E_PAUSE mid-Newton-iteration, which the integrator treated
    as a step failure -- timestep ground down in a rejection loop instead of
    pausing. Both are now LATCHED per timepoint attempt
    (point_eval_flags, reset on INITJCT/INITPRED/INITTRAN) and honored at the
    ACCEPTED-point boundary: $finish ends the analysis cleanly (firing
    @(final_step) first, per the LRM), $stop pauses resumably. Works in
    transient and DC sweeps;
  * $fatal under an op-dependent condition was silently DELETED: its
    SetRetFlag/print calls take no op-dependent arguments, so the init/eval
    split hoisted them to instance-init, where the op-dependent branch is
    rewritten to its else edge -- the calls sat in an unreachable block and
    were removed from BOTH functions. (The shared post-dominator tree roots
    at the `exit` sink, so the taint propagation never control-tainted the
    fatal arm.) Side-effecting callbacks (SetRetFlag, prints) under
    op-dependent control now stay in eval; E_PANIC from the device load
    aborts the transient instead of being retried as nonconvergence.
    Parameter-only $fatal still validates at SETUP (rejected instance);
  * $discontinuity(n>=0) additionally raises EVAL_RET_FLAG_DISCONT: OSDItrunc
    requests delta/8 while the flag is set (with a 20*CKTdelmin floor), so
    the integrator REJECTS the too-large event step and bisects onto the
    event -- the E-24 sentinel only bounded the NEXT step. Enhancement-759:
    a cross event now lands the step on its crossing with or without the
    announcement, and on that landing the eighth is the step AFTER the
    event (the restart the announcement asks for), not a rejection.

Checks:
  1. tran $finish: Note printed; the run ends AT the requesting point (well
     before tstop); @(final_step) fires at that same point
  2. tran $stop: Note + pause; run ends at the requesting point; no
     timestep-collapse (the STOP event fires only a handful of times)
  3. tran $fatal: "aborting" error + the $fatal message printed; the run
     aborts (last data point < the fatal time + one step)
  4. parameter-only $fatal: instance REJECTED AT SETUP (message printed,
     analysis never runs)
  5. dc sweep $finish: sweep ends at the requesting sweep point (~0.7 V),
     not the .dc stop value (2 V)
  6. $discontinuity A/B twins: both land the event point on the crossing
     (E-759: within 1 ns of 833.33 ns at a 60 ns step; it used to sit on the
     step grid), and the step AFTER the event is >= 4x smaller with the
     announcement than without (E-55's eighth, applied forward on a landing
     into the step); the event time is no later

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
    with open(os.path.join(HERE, "_sc.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_sc.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    # the pause/abort/setup diagnostics go to stderr
    return r.stdout + r.stderr


def tran_deck(model, extra=""):
    return (f"* sc {model}\nVs in 0 DC 0 SIN(0 1 1meg)\nNX in 0 mm\n"
            f".model mm {model}\n.control\nset numdgt=10\n"
            f"pre_osdi simctrl_demo.osdi\ntran 10n 3u\n"
            f"meas tran tend MAX_AT time\n{extra}.endc\n.end\n")


def get(pattern, text, group=1):
    m = re.search(pattern, text)
    return m.group(group) if m else None


def main():
    subprocess.run([OPENVAF, "simctrl_demo.va", "-o", "simctrl_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    print("[1] tran $finish: ends at the requesting point, fires final_step")
    out = run(tran_deck("sfin"))
    t_req = get(r"SC_FIN requested t=(\S+)", out)
    t_fin = get(r"SC_FINAL fired t=(\S+)", out)
    tend = get(r"tend\s*=\s*(\S+)", out)
    check("Note printed", "$finish requested by a Verilog-A device" in out)
    check("run ends at the requesting point (not tstop=3u)",
          t_req and tend and abs(float(tend) - float(t_req)) < 1e-12
          and float(tend) < 1e-6)
    check("@(final_step) fires at the finishing point",
          t_fin and t_req and abs(float(t_fin) - float(t_req)) < 1e-12)

    print("[2] tran $stop: clean resumable pause at the requesting point")
    out = run(tran_deck("sstop"))
    tend = get(r"tend\s*=\s*(\S+)", out)
    check("Note printed", "$stop requested by a Verilog-A device" in out)
    check("pause reported", "pause requested" in out)
    check("run pauses at the event (not tstop)", tend and float(tend) < 1e-6)

    print("[3] tran $fatal: aborts with the message (was silently deleted)")
    out = run(tran_deck("sfatal"))
    tend = get(r"tend\s*=\s*(\S+)", out)
    check("$fatal message printed", "SC_FATAL device limit exceeded" in out)
    check("abort error printed",
          "$fatal raised by a Verilog-A device" in out and "aborting" in out)
    check("transient aborted early", tend is None or float(tend) < 1e-7)

    print("[4] parameter-only $fatal: still validates at setup")
    deck = ("* sc validation\nVs in 0 DC 0.5\nNX in 0 mm\n"
            ".model mm sfatalparam p=-1\n.control\n"
            "pre_osdi simctrl_demo.osdi\nop\n.endc\n.end\n")
    out = run(deck)
    check("validation message printed at setup",
          "SC_BADPARAM p must be nonnegative" in out)
    check("setup rejected (no analysis ran)",
          "setup_instance" in out or "incomplete or empty netlist" in out)

    print("[5] dc sweep $finish: ends the sweep at the requesting point")
    deck = ("* sc dc finish\nVs in 0 DC 0\nNX in 0 mm\n.model mm sfindc\n"
            ".control\nset numdgt=10\npre_osdi simctrl_demo.osdi\n"
            "dc Vs 0 2 0.05\nmeas dc vmax MAX v(in)\n.endc\n.end\n")
    out = run(deck)
    vmax = get(r"vmax\s*=\s*(\S+)", out)
    check("Note printed", "$finish requested by a Verilog-A device" in out)
    check("sweep ended at ~0.7 V (stop value was 2 V)",
          vmax and abs(float(vmax) - 0.7) < 0.051)

    print("[6] $discontinuity(0): the event is landed on, the step after it cut (E-759)")
    dts = {}
    for model in ("snodisc", "sdisc"):
        deck = (f"* sc disc {model}\nVs in 0 DC 0 SIN(0 1 100k)\nRs in a 1k\n"
                f"NX a 0 mm\n.model mm {model}\n.control\nset numdgt=10\n"
                f"pre_osdi simctrl_demo.osdi\ntran 100n 3u\n"
                f"wrdata _sc_{model}.dat v(a)\n.endc\n.end\n")
        run(deck)
        ts, vs = [], []
        for line in open(os.path.join(HERE, f"_sc_{model}.dat")):
            p = line.split()
            if len(p) >= 2:
                ts.append(float(p[0]))
                vs.append(float(p[1]))
        # the event: the first point where the branch current's 1 mA step shows
        k = next((i for i in range(1, len(ts)) if abs(vs[i] - vs[i - 1]) > 0.2), None)
        after = (ts[k + 1] - ts[k]) if k is not None and k + 1 < len(ts) else None
        dts[model] = (ts[k] - ts[k - 1], ts[k], vs[k] - vs[k - 1], after) if k is not None else (None,) * 4
    dt_no, t_no, jump_no, after_no = dts["snodisc"]
    dt_yes, t_yes, jump_yes, after_yes = dts["sdisc"]
    print(f"        without: event at t={t_no} (jump {jump_no}), step after {after_no};"
          f" with: event at t={t_yes} (jump {jump_yes}), step after {after_yes}")
    # V(a) = 0.5 sin(2 pi 100 kHz t) before the event crosses 0.25 V at t = 833.33 ns
    t_cross = 1.0 / 12.0 * 1e-5
    check("E-759: the event point is landed on the crossing without the announcement (within 1 ns)",
          t_no is not None and 0 <= t_no - t_cross < 1e-9)
    check("E-759: ... and with it", t_yes is not None and 0 <= t_yes - t_cross < 1e-9)
    check("the step after the event is >= 4x smaller with the announcement (E-55's eighth, forward)",
          after_no is not None and after_yes is not None and after_yes <= after_no / 4)
    check("event resolved no later", t_yes is not None and t_yes <= t_no + 1e-12)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
