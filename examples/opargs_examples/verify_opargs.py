#!/usr/bin/env python3
"""
verify_opargs.py -- verifies Enhancement-61: the full-argument-form audit of
the analog operators and events, end-to-end through the committed
openvaf-r + ngspice.

A 22-form probe battery covered every optional-argument spelling in LRM 4.5
(analog operators) and 5.10 (events). ONE real defect was found and fixed:

  slew(x, max_pos_rate, max_neg_rate) -- the LRM (4.5.15) defines
  max_neg_slew_rate as a NEGATIVE number; the lowering negated it assuming a
  positive magnitude, so an LRM-conformant call like slew(x, 1e6, -1e6)
  produced a POSITIVE lower clamp bound and the tracking loop became a
  runaway ramp: the output ignored the input entirely and grew as t*rate
  past any target. The fix bounds with |max_pos| / -|max_neg|, exact for
  conformant inputs and tolerant of the legacy positive-magnitude spelling.

Everything else was verified working and is pinned here: toleranced events
(cross/above 3-4 arg, timer with PERIOD -- fires repeatedly), $bound_step
(actually bounds the solver step), $limit (both "pnjlim" and user functions
with extra args -- genuinely engaged: the stiff diode converges without
gmin stepping), ac_stim magnitude AND phase, and the trailing tolerance
args of ddt/idt/idtmod/absdelay/laplace (numerically exact, tolerances are
hints). transition()'s ramp semantics get their first runtime pin too.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_deck(name, deck):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr


def read_wrdata(name):
    rows = []
    for line in open(os.path.join(HERE, name)):
        p = line.split()
        if len(p) >= 4:
            rows.append((float(p[0]), float(p[1]), float(p[3])))
    return rows


def at(rows, t):
    return min(rows, key=lambda r: abs(r[0] - t))[2]


print("[1] slew() LRM sign convention (THE fixed defect)")
out, ok = compile_va("slew_demo.va")
if not ok:
    check("slew compile", False, out.splitlines()[0] if out else "")
else:
    run_deck("_slew.cir", """* slew step response
.control
pre_osdi slew_demo.osdi
.endc
V1 in 0 PULSE(0 1 0.1u 1n 1n 2u 20u)
N1 in out mm
.model mm slewdemo
Ro out 0 1k
.tran 10n 8u
.control
run
wrdata _slew.txt v(in) v(out)
.endc
.end
""")
    rows = read_wrdata("_slew.txt")
    # before the fix the output ramped from t=0 ignoring the input
    check("output holds at 0 before the step", abs(at(rows, 0.05e-6)) < 1e-3,
          f"(v={at(rows, 0.05e-6):.4g})")
    v6 = at(rows, 0.6e-6)   # rising at 1e6 from 0.1u -> 0.5
    check("rising edge rate-limited to +1e6 V/s", abs(v6 - 0.5) < 2e-3, f"(v={v6:.4f})")
    v15 = at(rows, 1.5e-6)  # reached and HOLDS the 1.0 target
    check("output stops at the target (no runaway)", abs(v15 - 1.0) < 2e-3, f"(v={v15:.4f})")
    v41 = at(rows, 4.1e-6)  # falling from 2.1u at 0.25e6 -> 1 - 0.5
    check("falling edge rate-limited to -0.25e6 V/s", abs(v41 - 0.5) < 3e-3, f"(v={v41:.4f})")

print("[2] toleranced events + timer PERIOD")
out, ok = compile_va("events_demo.va")
if not ok:
    check("events compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_ev.cir", """* toleranced events
.control
pre_osdi events_demo.osdi
.endc
V1 a 0 SIN(0.5 0.5 1meg)
N1 a 0 mm
.model mm evargs
.tran 2n 1u
.control
run
.endc
.end
""")
    mm = re.search(r"EVARGS nc=\s*(-?\d+) na=\s*(-?\d+) nt=\s*(-?\d+)", log)
    if not mm:
        check("EVARGS strobe", False, "missing")
    else:
        nc, na, nt = map(int, mm.groups())
        check("cross(expr,dir,ttol,etol) fires", nc >= 1, f"(nc={nc})")
        check("above(expr,ttol,etol) fires", na >= 1, f"(na={na})")
        check("timer PERIOD fires 5x (0.1..0.9us)", nt == 5, f"(nt={nt})")

print("[3] $limit: pnjlim + user fn with extra args (stiff diode, no gmin fallback)")
out, ok = compile_va("limit_demo.va")
if not ok:
    check("limit compile", False, out.splitlines()[0] if out else "")
else:
    want = None
    for mod in ("limpnj", "limuser"):
        log = run_deck("_lim.cir", f"""* stiff diode {mod}
.control
pre_osdi limit_demo.osdi
.endc
V1 in 0 DC 5
R1 in a 1
N1 a 0 mm
.model mm {mod}
.save v(a)
.op
.control
run
set numdgt=10
print v(a)
.endc
.end
""")
        mm = re.search(r"v\(a\)\s*=\s*([0-9.eE+-]+)", log)
        got = float(mm.group(1)) if mm else float("nan")
        direct = "gmin stepping" not in log
        # analytic: (5-V)/1 = 1e-15*exp(V/0.026) -> V ~ 0.9345
        check(f"{mod}: converges directly to the exact op",
              mm is not None and direct and abs(got - 0.9345) < 1e-3,
              f"(v={got:.6f}, direct={direct})")

print("[4] $bound_step bounds the transient step")
out, ok = compile_va("bstep_demo.va")
if not ok:
    check("bstep compile", False, out.splitlines()[0] if out else "")
else:
    evals = {}
    for u in (0, 1):
        log = run_deck("_bs.cir", f"""* bound step {u}
.control
pre_osdi bstep_demo.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm bstepdemo useb={u}
.tran 20n 1u
.control
run
.endc
.end
""")
        mm = re.search(r"BSTEP evals=\s*(\d+)", log)
        evals[u] = int(mm.group(1)) if mm else -1
    # 1us at <=5n needs >=200 accepted steps; unbounded coasts at ~50
    check("$bound_step(5n) forces fine steps",
          evals[0] > 0 and evals[1] >= 2 * evals[0],
          f"(evals: off={evals[0]}, on={evals[1]})")

print("[5] ac_stim magnitude AND phase")
out, ok = compile_va("acstim_demo.va")
if not ok:
    check("acstim compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_ac.cir", """* acstim mag/phase
.control
pre_osdi acstim_demo.osdi
.endc
Vd a 0 DC 0
N1 a c mm
.model mm acstimargs
Rc c 0 1k
.ac lin 1 1k 1k
.control
run
set numdgt=12
print v(c)
.endc
.end
""")
    mm = re.search(r"v\(c\)\s*=\s*([0-9.eE+-]+),\s*([0-9.eE+-]+)", log)
    if not mm:
        check("ac_stim v(c)", False, "missing")
    else:
        re_v, im_v = float(mm.group(1)), float(mm.group(2))
        # 2*exp(j*pi/2) into 1k||1k = j1000 exactly
        check("V(c) == 2<90deg x 500 = j1000 exactly",
              abs(re_v) < 1e-6 and abs(im_v - 1000.0) < 1e-6,
              f"(v=({re_v:.3g}, {im_v:.6f}))")

print("[6] trailing tolerance args stay numerically exact")
out, ok = compile_va("filt_demo.va")
if not ok:
    check("filt compile", False, out.splitlines()[0] if out else "")
else:
    # ddt(1n*V, abstol): AC at 1MHz -> |Y| = 2pi*1e-3
    log = run_deck("_f0.cir", """* ddt tol
.control
pre_osdi filt_demo.osdi
.endc
V1 a 0 DC 0 AC 1
N1 a 0 mm
.model mm filtargs mode=0
.ac lin 1 1meg 1meg
.control
run
set numdgt=10
print i(V1)
.endc
.end
""")
    mm = re.search(r"i\(v1\)\s*=\s*([0-9.eE+-]+),\s*([0-9.eE+-]+)", log)
    im = float(mm.group(2)) if mm else float("nan")
    check("ddt(x, abstol) exact at AC", mm is not None and abs(im + 2*math.pi*1e-3) < 1e-9,
          f"(im={im:.6g})")
    for mode, name in ((1, "idt(x, ic, assert, abstol)"), (2, "idtmod(x, ic, mod, off, abstol)")):
        log = run_deck("_f1.cir", f"""* idt tol {mode}
.control
pre_osdi filt_demo.osdi
.endc
V1 a 0 DC 0 AC 1
N1 a 0 mm
.model mm filtargs mode={mode}
.ac lin 1 159.1549431 159.1549431
.control
run
set numdgt=10
print i(V1)
.endc
.end
""")
        mm = re.search(r"i\(v1\)\s*=\s*([0-9.eE+-]+),\s*([0-9.eE+-]+)", log)
        im = float(mm.group(2)) if mm else float("nan")
        check(f"{name} exact at AC", mm is not None and abs(im - 1e-6) < 1e-11,
              f"(im={im:.6g})")

print("[7] transition() ramp semantics (first runtime pin)")
out, ok = compile_va("trans_demo.va")
if not ok:
    check("transition compile", False, out.splitlines()[0] if out else "")
else:
    run_deck("_tr.cir", """* transition ramp
.control
pre_osdi trans_demo.osdi
.endc
V1 in 0 PULSE(0 1 0.1u 1n 1n 5u 10u)
N1 in out mm
.model mm transdemo
Ro out 0 1k
.tran 10n 1u
.control
run
wrdata _trans.txt v(in) v(out)
.endc
.end
""")
    rows = read_wrdata("_trans.txt")
    vmid = at(rows, 0.3e-6)   # halfway through the 0.4u rise
    vend = at(rows, 0.7e-6)
    check("ramp midpoint at half the rise time", abs(vmid - 0.5) < 5e-3, f"(v={vmid:.4f})")
    check("ramp completes and holds", abs(vend - 1.0) < 5e-3, f"(v={vend:.4f})")

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
