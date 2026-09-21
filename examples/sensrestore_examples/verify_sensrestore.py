#!/usr/bin/env python3
"""Enhancement-440: `sens` must leave the circuit exactly as it found it.

`sens` computes each sensitivity by perturbing a parameter, reloading, and
writing the original value back. That restores the NUMBER but not the model's
"given" state: every device setter marks its parameter as supplied, and no
device API offers an un-set. For a model whose behaviour is selected by whether
a parameter was GIVEN rather than by its value, the model is left permanently
reinterpreted -- and every later analysis in the session silently solves a
different circuit.

The BJT is the sharp case. `ibe`/`ibc` default to 0 and ungiven, and bjttemp.c
keys off `BJTBEsatCurGiven && BJTBCsatCurGiven`: ungiven, the junction
saturation currents fall back to `is`; given, they are taken literally. `sens`
made them given with the value 0, leaving BJTBEtSatCur = 0 -- a transistor with
no saturation current at all.

Measured before the fix, with no diagnostic of any kind:

    op                 -> 4.432965241196   (matches the analytic 5 - 10k*Ic)
    sens v(nb)
    op                 -> 4.999999907      12.8% wrong -- the transistor is dead
    dc, and every later op, likewise

A differential pair came back 101% wrong. The error did not shrink when reltol
was tightened from 1e-3 to 1e-12, which is what distinguishes leftover state
from a Newton-path difference, and only `reset` cleared it.

The fix snapshots every model struct before the perturbation loop and restores
it afterwards, then re-runs CKTtemp() so each instance's derived values are
rebuilt from the restored models.

This suite pins the split closed and -- just as importantly -- pins that `sens`
still WORKS, since a fix that quietly disabled the analysis would also pass a
before/after comparison.

Enhancement-682 (N2 of the 2026-09-21 hunt): `sens` over a deck with current
sources printed "GET ERROR: Isource:I:i1 -> param r (27)" and "... td (28)"
twice per source per sweep. E-447 had declared the voltage-source-only pwl
options `r` and `td` on the current source so the card could refuse them by
name, but declared them IOP -- askable -- with no ask case behind them, and the
sweep asks every settable, askable real parameter. They are IP now (settable,
not askable), as the voltage source declares its own. Five checks at the end:
no ask error over two current sources, the source's own sensitivities still
reported, `show` without the two rows, the card refusal kept, and a sweep over
seventeen device types with no ask or set error at all.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

# Remove the generated decks at process exit rather than at the end of main.
# check_both_solvers pins a solver by editing each deck and registers an atexit
# handler that writes the ORIGINAL text back -- which RE-CREATES any deck the
# script deleted before exiting. atexit runs handlers last-registered-first, so
# registering here, before the first deck is written, puts this one last.
import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_sr_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, timeout=180):
    deck = (f"sensrestore {tag}\n{body}\n.control\noption noacct\nset numdgt=12\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_sr_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.stdout + r.stderr


def probes(out, node):
    """Every printed value of v(<node>), in order."""
    return re.findall(r"v\(" + re.escape(node) + r"\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)",
                      out, re.I)


# ---------------------------------------------------------------------------
# The circuits. Ic = is*exp(Vbe/Vt) = 1e-16*exp(0.7/0.02585) ~ 5.67e-5 A, so
# v(nb) = 5 - 10k*Ic ~ 4.43 V. A BJT that has lost its saturation current
# instead sits at Vcc.
# ---------------------------------------------------------------------------
BJT = """Vcc vcc 0 dc 5
Vb b 0 dc 0.7
Q1 nb b 0 qm
R1 vcc nb 10k
.model qm npn(is=1e-16 bf=100)"""

DIFFPAIR = """Vcc vcc 0 dc 5
Vee ee 0 dc -5
Vi b1 0 dc 0.01
Rc vcc nb 10k
Q1 nb b1 e qm
Q2 c2 0 e qm
Rc2 vcc c2 10k
Re e ee 10k
.model qm npn(is=1e-16 bf=100)"""

print("Enhancement-440: sens must not alter the circuit it measures\n")

print("a BJT operating point survives a sens")
out = run(BJT, "op\nprint v(nb)\nsens v(nb)\nop\nprint v(nb)", "bjt")
v = probes(out, "nb")
check("[E-440] the op before sens is the analytic value",
      len(v) >= 1 and abs(float(v[0]) - 4.432965241196) < 1e-6,
      f"v(nb)={v[0] if v else None}")
check("[E-440] the op after sens is UNCHANGED",
      len(v) >= 2 and v[0] == v[1], f"{v}")

print("\nit stays put -- the old damage was sticky and cured only by reset")
out = run(BJT, "op\nprint v(nb)\nsens v(nb)\nop\nprint v(nb)\nop\nprint v(nb)\n"
               "op\nprint v(nb)", "sticky")
v = probes(out, "nb")
check("[E-440] three further ops all agree with the first",
      len(v) >= 4 and len(set(v)) == 1, f"{v}")

# sens BEFORE any other analysis was corrupted too, so the damage was not a
# stale warm-start guess left by the preceding op.
out = run(BJT, "sens v(nb)\nop\nprint v(nb)", "first")
v = probes(out, "nb")
check("[E-440] a sens run FIRST leaves a correct op behind",
      len(v) >= 1 and abs(float(v[0]) - 4.432965241196) < 1e-6,
      f"v(nb)={v[0] if v else None}")

print("\nthe differential pair -- the worst case measured (101% wrong)")
out = run(DIFFPAIR, "op\nprint v(nb)\nsens v(nb)\nop\nprint v(nb)", "diffpair")
v = probes(out, "nb")
check("[E-440] diffpair op is unchanged by sens",
      len(v) >= 2 and v[0] == v[1], f"{v}")

print("\nlater analyses, not just op, must see the restored circuit")
out = run(BJT, "op\nprint v(nb)\nsens v(nb)\ndc Vb 0.7 0.7 0.1\nprint v(nb)", "dc")
v = probes(out, "nb")
check("[E-440] a dc sweep after sens agrees with the op before it",
      len(v) >= 2 and abs(float(v[0]) - float(v[1])) < 1e-9, f"{v}")

print("\ntightening reltol must not be what fixes it "
      "(a tolerance artifact would shrink; leftover state does not)")
for rt in ("1e-3", "1e-9", "1e-12"):
    out = run(BJT, f"option reltol={rt}\nop\nprint v(nb)\nsens v(nb)\n"
                   f"op\nprint v(nb)", "rt" + rt.replace("-", ""))
    v = probes(out, "nb")
    check(f"[E-440] identical before/after at reltol={rt}",
          len(v) >= 2 and v[0] == v[1], f"{v}")

print("\nCONTROLS -- devices that never had the defect must be untouched")
CONTROLS = [
    ("diode", "V1 in 0 dc 0.8\nR1 in nb 1k\nD1 nb 0 dm\n.model dm d(is=1e-14)"),
    ("MOS", "Vdd vdd 0 dc 5\nVg g 0 dc 2\nM1 nb g 0 0 nm w=2u l=1u\n"
            "R1 vdd nb 20k\n.model nm nmos(level=1 vto=1 kp=100u)"),
    ("JFET", "Vdd vdd 0 dc 5\nVg g 0 dc -0.5\nJ1 nb g 0 jm\nR1 vdd nb 10k\n"
             ".model jm njf(vto=-2 beta=1m)"),
    ("resistive divider", "V1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k"),
]
for name, body in CONTROLS:
    out = run(body, "op\nprint v(nb)\nsens v(nb)\nop\nprint v(nb)",
              "c" + name.split()[0])
    v = probes(out, "nb")
    check(f"[E-440] {name}: op unchanged across sens",
          len(v) >= 2 and v[0] == v[1], f"{v}")

print("\nand sens ITSELF must still work -- a fix that disabled it would also "
      "pass the checks above")
out = run(BJT, "sens v(nb)\nprint all", "works")
rows = [ln for ln in out.splitlines() if re.search(r"q1[:.]|qm[:.]", ln, re.I)]
check("[E-440] sens still reports per-parameter sensitivities",
      len(rows) > 20, f"{len(rows)} device rows")
# A resistive divider has an exact, checkable sensitivity. With
# v(nb) = R2/(R1+R2) and R1 = R2 = 1k, dv/dR2 = R1/(R1+R2)^2 = +2.5e-4 V/ohm and
# dv/dR1 = -R2/(R1+R2)^2 = -2.5e-4. Checking BOTH pins the sign convention as
# well as the magnitude, so a fix that restored the models but broke the
# perturbation itself would be caught here.
out = run("V1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k",
          "set numdgt=10\nsens v(nb)\nprint all", "exact")
for res, want in (("r1", -2.5e-4), ("r2", +2.5e-4)):
    m = re.search(r"^\s*" + res + r"\s*=\s*([-\d.eE+]+)\s*$", out, re.M | re.I)
    check(f"[E-440] {res} sensitivity is still numerically right "
          f"(analytic {want:+.1e} V/ohm)",
          bool(m) and abs(float(m.group(1)) - want) < 1e-8,
          f"{res} = {m.group(1) if m else 'not found'}")

print("\nEnhancement-682: the sweep over a current source is quiet, and still measures it")
ISRC = "I1 0 nb dc 1m\nI2 0 nb dc 0.5m\nR1 nb 0 1k"
out = run(ISRC, "sens v(nb)\nprint all\nshow i1\nalter i1 r=1\nalter i1 td=2", "isrc")
check("[E-682] no 'GET ERROR' over two current sources (was four lines per sweep)",
      "GET ERROR" not in out and "SET ERROR" not in out, out[-300:])
m = re.search(r"^\s*i1\s*=\s*([-\d.eE+]+)\s*$", out, re.M | re.I)
check("[E-682] the source's own sensitivity is still reported: dv(nb)/dI1 = R1 = 1000",
      bool(m) and abs(float(m.group(1)) - 1000.0) < 1e-3, f"i1 = {m.group(1) if m else 'not found'}")
shown = out.split("Isource: Independent current source", 1)[-1] if "Isource:" in out else ""
check("[E-682] show i1 lists neither r nor td (they cannot be asked: nothing is stored)",
      "Isource:" in out and not re.search(r"^\s+(r|td)\s", shown, re.M), shown[:400])
check("[E-682] the card refusal of E-447 stands: alter i1 r= and td= name the reason",
      out.count("is not supported for current sources") == 2, out[-400:])
SWEEP = ("vin in 0 dc 1 ac 1\niin 0 a dc 1m\nr1 in a 1k\nc1 a 0 1n\nl1 a b 1u\nr2 b 0 1k\nd1 b 0 dd\n"
         ".model dd d(is=1e-14)\nq1 c bb 0 qq\n.model qq npn(is=1e-15 bf=100)\nrc in c 1k\nvb bb 0 dc 0.7\n"
         "m1 dr g 0 0 mm l=1u w=10u\n.model mm nmos(level=1 vto=0.5 kp=1e-4)\nvg g 0 dc 1\nrd in dr 1k\n"
         "j1 jd jg 0 jj\n.model jj njf(vto=-1 beta=1e-4)\nrj in jd 1k\nvjg jg 0 dc -0.5\n"
         "e1 e 0 a 0 2\nre e 0 1k\ng1 0 gg a 0 1m\nrg gg 0 1k\nf1 0 ff vin 1\nrf ff 0 1k\nh1 h 0 vin 100\nrh h 0 1k\n"
         "b1 bb2 0 v=v(a)*2\nrb bb2 0 1k\ns1 sa 0 a 0 sw\n.model sw sw(vt=0.5 ron=1 roff=1meg)\nrs in sa 1k\n"
         "k1 l1 l2 0.5\nl2 kk 0 1u\nrk kk 0 1k")
out = run(SWEEP, "sens v(a)\nsens v(a) ac lin 1 1k 1k\nprint r1 iin", "sweep")
check("[E-682] a DC and an AC sens over seventeen device types: no ask or set error, r1 and iin reported",
      "GET ERROR" not in out and "SET ERROR" not in out
      and re.search(r"^\s*r1\s*=", out, re.M) and re.search(r"^\s*iin\s*=", out, re.M), out[-400:])

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
