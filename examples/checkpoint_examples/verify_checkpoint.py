#!/usr/bin/env python3
"""
verify_checkpoint.py -- Enhancement-131: transient checkpoint / restart.

Two new interactive commands let a (long) transient run be saved to disk and
later resumed -- possibly in a fresh ngspice process:

    savestate <file>    dump the current transient state of the active circuit
    loadstate <file>    restore it into the (identically built) circuit and
                        continue the .tran defined in the deck

The saved state is the full integration state the in-memory `resume` relies on:
the solution vector (CKTrhsOld), the device state history (CKTstates[]), the
current time / step / order and the pending breakpoints.  On reload the circuit
is rebuilt, the state poured back in, and DCtran() continues -- opening a fresh
output plot (there is no live plot to relink across a reload).

Each check runs an UNINTERRUPTED reference tran (0 -> T2), then a split run:
part 1 (0 -> T1) + savestate, then -- in a SEPARATE ngspice process -- loadstate
and continue to T2.  The resumed waveform must match the reference at the end
(exact, to the printed precision) and at an interior sample time.

It is a front-end + transient-core command, independent of the enhancement it
verifies; checkpoint/restart is Sparse-solver only (KLU is rejected), so this is
run once under the default solver.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_ck"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def last_val(out, name):
    m = re.search(rf"(?im)^\s*{re.escape(name)}[^\n=]*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def meas_val(out, name):
    m = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def scenario(label, body, t1, t2, tmid, pre="", osdi_tol=None, uic=""):
    """Reference vs (savestate @ t1 -> fresh loadstate -> continue to t2)."""
    ckpt = os.path.join(HERE, "_ck.state")
    if os.path.exists(ckpt):
        os.remove(ckpt)
    ctrl = (pre + "\n") if pre else ""
    u = (" " + uic) if uic else ""

    ref = run(f"* {label} reference\n{body}\n.tran {t2[0]} {t2[1]}{u}\n.control\n{ctrl}run\n"
              f"meas tran vmid FIND v(out) AT={tmid}\n"
              f"let vend = v(out)[length(v(out))-1]\nprint vend\n.endc\n.end\n", "_ref")
    p1 = run(f"* {label} part1\n{body}\n.tran {t1[0]} {t1[1]}{u}\n.control\n{ctrl}run\n"
             f"savestate {ckpt}\n.endc\n.end\n", "_p1")
    p2 = run(f"* {label} restart\n{body}\n.tran {t2[0]} {t2[1]}{u}\n.control\n{ctrl}"
             f"loadstate {ckpt}\n"
             f"meas tran vmid FIND v(out) AT={tmid}\n"
             f"let vend = v(out)[length(v(out))-1]\nprint vend\n.endc\n.end\n", "_p2")
    if os.path.exists(ckpt):
        os.remove(ckpt)

    saved = "Checkpoint written" in p1
    restored = "Restored checkpoint" in p2
    r_end, p_end = last_val(ref, "vend"), last_val(p2, "vend")
    r_mid, p_mid = meas_val(ref, "vmid"), meas_val(p2, "vmid")

    check(f"{label}: savestate wrote a checkpoint", saved)
    check(f"{label}: loadstate resumed the run", restored)

    def close(a, b, tol):
        return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))

    # built-in devices reproduce the run to full precision; OSDI carries a little
    # instance-internal state, so allow a small tolerance there.
    end_tol = osdi_tol if osdi_tol else 1e-6
    mid_tol = osdi_tol if osdi_tol else 2e-4        # interior point uses meas interpolation
    check(f"{label}: resumed end value matches reference (ref={r_end}, got={p_end})",
          close(p_end, r_end, end_tol), f"{p_end} vs {r_end}")
    check(f"{label}: resumed interior value matches reference (ref={r_mid}, got={p_mid})",
          close(p_mid, r_mid, mid_tol), f"{p_mid} vs {r_mid}")


print("Enhancement-131: transient checkpoint / restart")

# [1] Linear RC low-pass charging from 0 (uic) -- resumed run is bit-identical.
scenario("RC step",
         "V1 in 0 dc 1\nR1 in out 1k\nC1 out 0 1u",
         ("1u", "1m"), ("1u", "2m"), "1.5m", uic="uic")

# [2] PULSE source -- exercises breakpoint save/restore + source re-scheduling.
scenario("RC pulse",
         "V1 in 0 PULSE(0 1 0 10u 10u 180u 400u)\nR1 in mid 2k\nC1 mid 0 47n\n"
         "R2 mid out 1k\nC2 out 0 100n",
         ("2u", "1.3m"), ("2u", "3m"), "2.1m")

# [3] Nonlinear built-in diode rectifier, sine drive.
scenario("Diode rect",
         "V1 in 0 SIN(0 5 1k)\nD1 in out DMOD\nR1 out 0 10k\nC1 out 0 100n\n"
         ".model DMOD D(IS=1e-14 N=1.6 RS=10)",
         ("2u", "1.7m"), ("2u", "4m"), "2.5m")

# [4] OSDI / Verilog-A compiled diode (reactive + nonlinear).
osdi = os.path.join(HERE, "ckdiode.osdi")
cr = subprocess.run([OPENVAF, os.path.join(HERE, "ckdiode.va"), "-o", osdi],
                    capture_output=True, text=True, timeout=120)
if os.path.exists(osdi):
    scenario("OSDI diode",
             "V1 in 0 SIN(0 3 1k)\nN1 in out dmod\nR1 out 0 10k\nC1 out 0 100n\n"
             ".model dmod ckdiode is=1e-14 n=1.6",
             ("2u", "1.7m"), ("2u", "4m"), "2.5m",
             pre=f"pre_osdi {osdi}", osdi_tol=1e-3)
    os.remove(osdi)
else:
    check("OSDI diode: compiled ckdiode.va", False, cr.stderr.strip()[:80])

# [5] Same-session save + reload (no separate process).
ckpt = os.path.join(HERE, "_ss.state")
if os.path.exists(ckpt):
    os.remove(ckpt)
ss = run("* same session\nV1 in 0 dc 1\nR1 in out 1k\nC1 out 0 1u\n"
         ".tran 1u 2m uic\n.control\ntran 1u 1m uic\n"
         f"savestate {ckpt}\nloadstate {ckpt}\n"
         "let vend = v(out)[length(v(out))-1]\nprint vend\n.endc\n.end\n", "_ss")
if os.path.exists(ckpt):
    os.remove(ckpt)
vend_ss = last_val(ss, "vend")
# RC to 2ms with tau=1ms -> 1-exp(-2) = 0.864665
check(f"same-session save+load reaches 1-exp(-2)=0.8647 (got {vend_ss})",
      vend_ss is not None and abs(vend_ss - (1 - math.exp(-2))) < 1e-4, str(vend_ss))

# [6] Robustness: a checkpoint restored into a DIFFERENT circuit is rejected.
ckpt = os.path.join(HERE, "_mm.state")
if os.path.exists(ckpt):
    os.remove(ckpt)
run("* mm p1\nV1 in 0 dc 1\nR1 in out 1k\nC1 out 0 1u\n.tran 1u 1m\n.control\nrun\n"
    f"savestate {ckpt}\n.endc\n.end\n", "_mmp1")
mm = run("* mm p2 (extra node)\nV1 in 0 dc 1\nR1 in mid 1k\nR9 mid out 1k\nC1 out 0 1u\n"
         f".tran 1u 2m\n.control\nloadstate {ckpt}\n.endc\n.end\n", "_mmp2")
if os.path.exists(ckpt):
    os.remove(ckpt)
check("mismatched circuit is rejected (not crashed)", "does not match" in mm, mm[-120:])

# [7] Robustness: KLU solver is rejected with a clear message.
ckpt = os.path.join(HERE, "_klu.state")
if os.path.exists(ckpt):
    os.remove(ckpt)
klu = run("* klu\nV1 in 0 dc 1\nR1 in out 1k\nC1 out 0 1u\n.option klu\n.tran 1u 1m\n"
          f".control\nrun\nsavestate {ckpt}\n.endc\n.end\n", "_klu")
wrote = os.path.exists(ckpt)
if wrote:
    os.remove(ckpt)
check("KLU solver rejected with a clear message (no crash, no file)",
      ("only supported with the default Sparse" in klu) and not wrote)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
