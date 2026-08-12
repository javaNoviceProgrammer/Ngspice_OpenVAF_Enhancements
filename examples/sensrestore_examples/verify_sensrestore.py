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

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
