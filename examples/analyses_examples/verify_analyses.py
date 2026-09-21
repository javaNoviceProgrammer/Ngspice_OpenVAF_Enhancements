#!/usr/bin/env python3
"""
verify_analyses.py -- verifies Enhancement-62: ngspice analysis coverage for
Verilog-A (OSDI) devices, end-to-end through the committed openvaf-r +
ngspice.

The probe battery ran every ngspice analysis beyond op/dc/ac/tran/noise
against OSDI devices, comparing with built-in twins (the E-57 technique).
Already exact and pinned here: .tf (transfer function, output/input
impedance), .pz (linear pole exact; the NONLINEAR pz failure is an ngspice
quirk that hits built-in devices identically -- parity, not an OSDI gap),
.sens DC (dV/dR matches the analytic divider derivative) and AC, .dc temp
sweeps ($temperature per point, degC->K exact), alter/altermod, and the
(*type="instance"*) machinery (instance-line r=, print @n1[r], alter).

TWO REAL GAPS were found and fixed in ngspice:

  1. `.dc @inst[param] start stop step` -- the sweep code (dctrcurv.c)
     hardcoded Vsource/Isource/Resistor/temp, so sweeping ANY device
     parameter was impossible ("...is not in the circuit"). A new generic
     PARAM_CODE sweep resolves `@inst[param]` through the device's own
     DEVparam/DEVask tables and refreshes via DEVtemperature (for OSDI
     exactly the alter path: setup_model + setup_instance re-run). Works
     for OSDI instance-kind params AND built-in devices, nests with other
     sweep variables, and restores the original value afterwards.

  2. `.disto` SILENTLY reported zero distortion for OSDI devices: the
     distortion kernel needs per-device Taylor coefficients (DEVdisto),
     which the OSDI ABI cannot provide (first derivatives only), and
     ngspice skipped such devices without a word -- an OSDI diode measured
     0.0 where the identical built-in diode measured 1.8e-6. ngspice now
     prints a prominent warning naming each affected device type.

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


def sweep_rows(log):
    rows = []
    for line in log.splitlines():
        m = re.match(r"\d+\s+([0-9.eE+-]+)\s+(-?[0-9.eE+-]+)", line)
        if m:
            rows.append((float(m.group(1)), float(m.group(2))))
    return rows


out, ok = compile_va("analyses_blocks.va")
if not ok:
    check("blocks compile", False, out.splitlines()[0] if out else "")
    raise SystemExit(1)
out, ok = compile_va("analyses_dio.va")
if not ok:
    check("dio compile", False, out.splitlines()[0] if out else "")
    raise SystemExit(1)

print("[1] .tf with OSDI devices (vs built-in twin in the same deck)")
log = run_deck("_tf.cir", """* tf osdi
.control
pre_osdi analyses_blocks.osdi
.endc
V1 in 0 DC 1
N1 in mid mm1
.model mm1 ores r=1k
N2 mid 0 mm2
.model mm2 ores r=3k
R1 in mid2 1k
R2 mid2 0 3k
.tf v(mid) V1
.control
run
set numdgt=10
print all
.endc
.end
""")
tf = re.search(r"transfer_function = ([0-9.eE+-]+)", log)
zo = re.search(r"output_impedance_at_v\(mid\) = ([0-9.eE+-]+)", log)
zi = re.search(r"input_impedance = ([0-9.eE+-]+)", log)
check("transfer function == 0.75 exactly",
      tf and abs(float(tf.group(1)) - 0.75) < 1e-12)
check("output impedance == 1k||3k == 750 exactly",
      zo and abs(float(zo.group(1)) - 750.0) < 1e-9)
check("input impedance == 4k||4k == 2k exactly (OSDI + builtin dividers)",
      zi and abs(float(zi.group(1)) - 2000.0) < 1e-9)

print("[2] .pz: OSDI RC == built-in RC, pole at -1/(RC)")
poles = {}
for tag, body in (("osdi", """.control
pre_osdi analyses_blocks.osdi
.endc
V1 in 0 DC 0 AC 1
N1 in out mmr
.model mmr ores r=1k
N2 out 0 mmc
.model mmc ocap cap=1n"""),
                  ("builtin", """V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 1n""")):
    log = run_deck("_pz.cir", f"""* pz {tag}
{body}
.pz in 0 out 0 vol pol
.control
run
set numdgt=10
print all
.endc
.end
""")
    m = re.search(r"all = (-?[0-9.eE+-]+),\s*(-?[0-9.eE+-]+)", log)
    poles[tag] = (float(m.group(1)), float(m.group(2))) if m else None
check("OSDI pole == -1e6 rad/s exactly",
      poles["osdi"] is not None and abs(poles["osdi"][0] + 1e6) < 1e-3
      and abs(poles["osdi"][1]) < 1e-6, f"({poles['osdi']})")
check("OSDI pole == built-in pole", poles["osdi"] == poles["builtin"])

print("[3] .sens with OSDI devices (DC exact, AC exact)")
log = run_deck("_sens.cir", """* sens dc osdi
.control
pre_osdi analyses_blocks.osdi
.endc
V1 in 0 DC 1
N1 in mid mm1
.model mm1 ores r=1k
N2 mid 0 mm2
.model mm2 ores r=3k
.sens v(mid)
.control
run
print all
.endc
.end
""")
s1 = re.search(r"n1:r = (-?[0-9.eE+-]+)", log)
s2 = re.search(r"n2:r = (-?[0-9.eE+-]+)", log)
# V = r2/(r1+r2): dV/dr1 = -r2/(r1+r2)^2 = -1.875e-4; dV/dr2 = r1/(r1+r2)^2 = 6.25e-5
check("dV/dr1 == -3k/16M exactly",
      s1 and abs(float(s1.group(1)) + 1.875e-4) < 1e-9, f"({s1.group(1) if s1 else '?'})")
check("dV/dr2 == 1k/16M (numeric perturbation)",
      s2 and abs(float(s2.group(1)) - 6.25e-5) < 1e-9, f"({s2.group(1) if s2 else '?'})")
log = run_deck("_sensac.cir", """* sens ac osdi
.control
pre_osdi analyses_blocks.osdi
.endc
V1 in 0 DC 0 AC 1
N1 in out mmr
.model mmr ores r=1k
N2 out 0 mmc
.model mmc ocap cap=1n
.sens v(out) ac lin 1 159155 159155
.control
run
print all
.endc
.end
""")
m = re.search(r"v1_acmag = ([0-9.eE+-]+),(-?[0-9.eE+-]+)", log)
# at f = 1/(2*pi*RC): H = 1/(1+j) = 0.5 - 0.5j
check("AC sens dV/dacmag == 0.5 - 0.5j (pole frequency)",
      m and abs(float(m.group(1)) - 0.5) < 1e-5 and abs(float(m.group(2)) + 0.5) < 1e-5)

print("[4] .dc temp sweep ($temperature per point, degC->K)")
log = run_deck("_temp.cir", """* temp sweep osdi
.control
pre_osdi analyses_blocks.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm otres r0=1k tc=0.01
.dc temp -25 125 50
.control
run
set numdgt=10
print i(V1)
.endc
.end
""")
rows = sweep_rows(log)
ok_t = len(rows) == 4
for (tc, i_meas) in rows:
    r = 1e3 * (1.0 + 0.01 * ((tc + 273.15) - 300.0))
    ok_t = ok_t and abs(i_meas + 1.0 / r) < 1e-12
check("4 sweep points all match 1/R(T) exactly", ok_t,
      f"({len(rows)} points)")

print("[5] NEW: .dc @inst[param] sweeps (generic instance-parameter sweep)")
log = run_deck("_dcp.cir", """* dc param sweep osdi
.control
pre_osdi analyses_blocks.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm ires
.dc @n1[r] 1k 4k 1k
.control
run
set numdgt=10
print i(V1)
.endc
.end
""")
rows = sweep_rows(log)
ok_s = len(rows) == 4 and all(abs(i + 1.0 / rv) < 1e-12 for rv, i in rows)
check("OSDI @n1[r] 1k..4k: I == 1/R at every point", ok_s, f"({len(rows)} points)")
check("sweep scale named param-sweep", "param-sweep" in log)
log = run_deck("_dcpn.cir", """* nested param sweep
.control
pre_osdi analyses_blocks.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm ires
.dc @n1[r] 1k 2k 1k V1 1 2 1
.control
run
set numdgt=10
print i(V1)
.endc
.end
""")
rows = sweep_rows(log)
want = [(1e3, -1e-3), (2e3, -5e-4), (1e3, -2e-3), (2e3, -1e-3)]
ok_n = len(rows) == 4 and all(abs(a - c) < 1e-6 and abs(b - d) < 1e-12
                              for (a, b), (c, d) in zip(rows, want))
check("nested @n1[r] x V1 (inner level resets)", ok_n, f"({len(rows)} points)")
log = run_deck("_dcpb.cir", """* builtin via generic path
V1 a 0 DC 1
R1 a 0 1k
.dc @r1[resistance] 1k 4k 1k
.control
run
set numdgt=10
print i(V1)
.endc
.end
""")
rows = sweep_rows(log)
ok_b = len(rows) == 4 and all(abs(i + 1.0 / rv) < 1e-12 for rv, i in rows)
check("built-in @r1[resistance] through the same generic path", ok_b)

print("[6] alter / altermod / instance-line / @n1[r] readback")
log = run_deck("_alter.cir", """* alter osdi
.control
pre_osdi analyses_blocks.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm r=2k
.model mm ires
.control
op
set numdgt=10
print i(V1)
print @n1[r]
alter @n1[r] = 4k
op
print i(V1)
altermod @mm[r] = 8k
op
print i(V1)
.endc
.end
""")
vals = re.findall(r"i\(v1\) = (-?[0-9.eE+-]+)", log)
rd = re.search(r"@n1\[r\] = ([0-9.eE+-]+)", log)
check("instance-line r=2k honored", len(vals) >= 1 and abs(float(vals[0]) + 5e-4) < 1e-12)
check("print @n1[r] reads back 2000", rd and abs(float(rd.group(1)) - 2000.0) < 1e-9)
check("alter @n1[r]=4k takes effect", len(vals) >= 2 and abs(float(vals[1]) + 2.5e-4) < 1e-12)
# instance value overrides the model card, so altermod must NOT change n1
check("altermod does not override the given instance value",
      len(vals) >= 3 and abs(float(vals[2]) + 2.5e-4) < 1e-12)

print("[7] .disto and OSDI devices (E-62 warning, E-352 tensors, E-353 $limit)")
log = run_deck("_disto.cir", """* disto osdi
.control
pre_osdi analyses_dio.osdi
.endc
V1 in 0 DC 0.7 AC 1 DISTOF1 0.01
R1 in a 100
N1 a 0 mm
.model mm odio
.disto dec 2 10k 100k
.control
run
print length(v(a))
setplot disto1
print v(a)
.endc
.end
""")
# Enhancement-352 gives OSDI models 2nd/3rd order Taylor tensors, so .disto
# includes their nonlinearities. This model drives its exponential through
# $limit, which Enhancement-352 could not reach -- it differentiated w.r.t. the
# raw voltage read rather than the limited value, so no tensors were emitted and
# the device was reported as contributing nothing. Enhancement-353 folds the
# limited values into the derivative chain, so it now contributes properly.
#
# Both halves matter. The warning must be gone, AND the result must be non-zero:
# a silent zero is the failure mode Enhancement-62 added a warning for, and
# checking only for the absent warning would score exactly that as a pass.
# examples/limitdisto_examples pins the VALUES against the unlimited spelling.
disto_vals = [float(m) for m in
              re.findall(r"^\d+\s+[-\d.e+]+\s+([-\d.e+]+),", log, re.M)]
check("a limiting model is no longer reported as contributing no distortion",
      "contributes no distortion" not in log)
check("a limiting model's distortion is non-zero, not a silent zero",
      bool(disto_vals) and all(abs(v) > 1e-12 for v in disto_vals))
check("analysis still completes (linear part valid)",
      re.search(r"length\(v\(a\)\) = [0-9]", log) is not None)

print("[7] Enhancement-684: which analyses answer analysis(\"ac\") -- the name, the flags, the events")
A = "@"
NAMES = ((A + "n1[is_ac]"), (A + "n1[is_dc]"), (A + "n1[is_static]"), (A + "n1[is_noise]"))
# expected: (name, ac, dc, static, noise, initial event, final event)
EXPECT = (
    ("op",      "op",                          "", "",                                  "dc",    0, 1, 1, 0),
    ("ac",      "ac lin 1 1k 1k",              "", "",                                  "ac",    1, 0, 1, 0),
    ("sp",      "sp lin 1 1k 1k",              "portnum 1 z0 50", "Vp2 a 0 dc 0 portnum 2 z0 50\n", "ac", 1, 0, 1, 0),
    ("pz",      "pz in 0 a 0 vol pz",          "", "",                                  "ac",    1, 0, 1, 0),
    ("disto",   "disto lin 1 1k 1k",           "distof1 0.01", "",                      "ac",    1, 0, 1, 0),
    ("sens ac", "sens v(a) ac lin 1 1k 1k",    "", "",                                  "ac",    1, 0, 1, 0),
    ("tf",      "tf v(a) V1",                  "", "",                                  "dc",    0, 1, 1, 0),
    ("sens dc", "sens v(a)",                   "", "",                                  "dc",    0, 1, 1, 0),
    ("noise",   "noise v(a) V1 lin 2 1k 2k",   "", "",                                  "noise", 0, 0, 1, 1),
)
for tag, an, vsrc, extra, name, e_ac, e_dc, e_st, e_no in EXPECT:
    log = run_deck("_aname.cir", f"""* analysis name {tag}
.control
pre_osdi analyses_blocks.osdi
.endc
V1 in 0 dc 1 ac 1 {vsrc}
N1 in a am r=1k
.model am aname
R2 a 0 1k
C1 a 0 1n
{extra}.control
{an}
print {' '.join(NAMES)}
.endc
.end
""")
    vals = []
    for nm in NAMES:
        m = re.search(re.escape(nm) + r"\s*=\s*([-\d.eE+]+)", log)
        vals.append(int(float(m.group(1))) if m else None)
    names = set(re.findall(r"AN_NAME (\w+)", log))
    ev = re.findall(r"AN_EV (\w+)", log)
    want_init = "initial_" + ("ac" if e_ac else "dc") if name != "noise" else None
    want_final = "final_" + name
    ok = (vals == [e_ac, e_dc, e_st, e_no] and names == {name}
          and (want_init is None or (want_init in ev and ("initial_ac" if want_init == "initial_dc" else "initial_dc") not in ev))
          and ev.count(want_final) == 1 and all(e == want_final or e.startswith("initial_") for e in ev))
    check(f"{tag}: analysis_name '{name}', flags ac/dc/static/noise = {e_ac}{e_dc}{e_st}{e_no}, "
          f"initial_step/final_step qualified by that name", ok,
          f"(got {vals}, names {sorted(names)}, events {ev})")

print("[8] Enhancement-689: a model's analysis(\"ic\") initial condition under tran ... uic")
NOTE = "Note: uic: a Verilog-A analysis(\"ic\") initial condition seeds "


def uic_run(tag, body, prints, uic="uic"):
    log = run_deck("_uic.cir", f"""* uic ic {tag}
.control
pre_osdi analyses_blocks.osdi
.endc
.model mc uicic
.model mv vpot
Vin in 0 dc 1
{body}
.control
tran 0.1u 0.3u {uic}
print {prints}
.endc
.end
""")
    vals = {}
    for m in re.finditer(r"^(\S+) = (-?[\d.]+e[-+]\d+)", log, re.M):
        vals[m.group(1)] = float(m.group(2))
    return log, vals


def near(a, b, tol=1e-3):
    return a is not None and abs(a - b) <= tol


log, v = uic_run("ground", "R1 in a 1k\nN1 a 0 mc c=1n ic=0.5", "v(a)[0] v(a)[1] " + A + "n1[nic]")
check("a branch to ground: v(a) starts at 0.5 under uic (was 3e-5, the parameter dead), the Note names v(a) = 0.5",
      near(v.get("v(a)[0]"), 0.5) and near(v.get("v(a)[1]"), 0.5) and (NOTE + "v(a) = 0.5") in log
      and (v.get(A + "n1[nic]") or 0) >= 1, f"{v} {log[-200:]}")
log, v = uic_run("builtin", "R1 in a 1k\nN1 a 0 mc c=1n ic=0.5\nR2 in b 1k\nC2 b 0 1n ic=0.5",
                 "v(a)[0] v(b)[0] v(a)[2] v(b)[2]")
check("beside the built-in capacitor's ic=0.5: the two trajectories agree to 1e-6 at the first and third points",
      all(v.get(k) is not None for k in ("v(a)[0]", "v(b)[0]", "v(a)[2]", "v(b)[2]"))
      and abs(v["v(a)[0]"] - v["v(b)[0]"]) < 1e-6 and abs(v["v(a)[2]"] - v["v(b)[2]"]) < 1e-6
      and near(v["v(b)[0]"], 0.5), f"{v}")
log, v = uic_run("icwins", "R1 in a 1k\nN1 a 0 mc c=1n ic=0.5\n.ic v(a)=0.3", "v(a)[0]")
check("a .ic on the node holds it: v(a) starts at 0.3, the model's 0.5 is reported as not applied (its node is held)",
      near(v.get("v(a)[0]"), 0.3) and NOTE not in log
      and "Warning: uic: the analysis(\"ic\") initial condition n1 places on V(p,n) is not applied: every node it "
          "constrains is ground or held by a .ic" in log, f"{v} {log[-300:]}")
log, v = uic_run("floating", "R1 in x 1k\nN1 x y mc c=1n ic=0.5\nRy y 0 1k", "v(x)[0] v(y)[0]")
check("a floating branch: the difference is split (v(x) = 0.25, v(y) = -0.25 in the Note) and the first point "
      "holds v(x)-v(y) = 0.5",
      (NOTE + "v(x) = 0.25, v(y) = -0.25") in log and v.get("v(x)[0]") is not None and v.get("v(y)[0]") is not None
      and near(v["v(x)[0]"] - v["v(y)[0]"], 0.5), f"{v} {log[-300:]}")
log, v = uic_run("source", "N2 s 0 mv vdc=1\nR1 s a 1k\nC1 a 0 1n", "v(s)[0] v(a)[0]")
check("an unconditional V(p,n) <+ vdc is the device's equation, not an initial condition: not seeded (no Note), "
      "the source's node is at 1 V from the first step as a built-in source is",
      NOTE not in log and near(v.get("v(s)[0]"), 1.0) and "Warning: uic" not in log, f"{v} {log[-200:]}")
log, v = uic_run("capgetic", "R1 in a 1k\nN1 a 0 mc c=1n ic=0.5\nC3 a 0 1n", "v(a)[0]")
check("a built-in capacitor without ic= on the seeded node takes its initial voltage from the seeded value (CAPgetic "
      "re-run): v(a) starts at 0.5, not pulled back to 0",
      near(v.get("v(a)[0]"), 0.5) and (NOTE + "v(a) = 0.5") in log, f"{v} {log[-200:]}")
log, v = uic_run("nouic", "R1 in a 1k\nN1 a 0 mc c=1n ic=0.5", "v(a)[0] v(a)[1]", uic="")
check("without uic nothing changes: the transient operating point applies the ic branch, v(a) = 0.5 at t = 0, no Note",
      near(v.get("v(a)[0]"), 0.5) and NOTE not in log, f"{v}")

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
