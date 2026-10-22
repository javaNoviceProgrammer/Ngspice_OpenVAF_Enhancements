#!/usr/bin/env python3
"""Enhancement-916: a subcircuit's multiplier reaches a compiled model that owns `m`.

F7 and F8 of the 2026-09-26 options-and-convergence hunt. A subcircuit called
with `m=` had ` m={m}` appended to every device line inside it (E-394), and on
an N line that `m` landed on whatever the compiled device calls `m`:
  - F7: a diode whose grading coefficient is `m` (every SPICE-derived
    Verilog-A diode) refused the line -- "unknown parameter (m): it is a model
    parameter of this device" -- on a line the user wrote no parameter on, and
    `_mfactor=` on the inner line was refused as a second spelling;
  - F8: a module with an instance parameter `m` of its own had it overwritten
    by the multiplier and was not multiplied, in silence (0.502 mA where two
    devices draw 1.002 mA).

The expansion now appends the multiplier to an N line as `_subckt_m=`, and the
parser multiplies it into the device's own multiplier (`_mfactor` on a compiled
device) once it knows the device: the multiplier the line or the card gives,
times the subcircuit's. An `m=` the user wrote stays what the model says it is.

Checks (both solvers):
  [1] a compiled diode owning `m` in a subcircuit called with m=2: runs, and
      equals the built-in diode in the same subcircuit
  [2] ... with `_mfactor=3` on its line: six diodes
  [3] a module with its own instance parameter `m`, in m=2: multiplied
  [4] ... with `m=3` written on its line: the parameter stays 3, still doubled
  [5] a resistor module (its `m` is the multiplier) with m=3 inside m=2: 6x
  [6] nested subcircuits 2 x 3 x 5: 30x
  [7] a card's `_mfactor=3` default inside m=2: 6x
  [8] m=0 and m=-1 on the X line: one note, one warning, as on a plain line
  [9] the built-in resistor and a subcircuit that declares `m` itself: as before
  [10] the small-signal response is multiplied too
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

MODULES = ["vadiode", "mmode", "cres"]
A = "@"                     # device-parameter vectors, built so no line holds a bare one
PRE = "\n".join(f"pre_osdi {m}.osdi" for m in MODULES)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_all():
    for m in MODULES:
        out = os.path.join(HERE, m + ".osdi")
        if os.path.exists(out):
            os.remove(out)
        subprocess.run([OPENVAF, m + ".va", "-o", m + ".osdi"], cwd=HERE, capture_output=True,
                       text=True, timeout=300)
    return all(os.path.exists(os.path.join(HERE, m + ".osdi")) for m in MODULES)


def run(body, ctl="op\nprint i(v1)", tag="t"):
    deck = (f"* subcktmfactor {tag}\n{body}\n.model dva vadiode(is_=1e-14 n=1.2 m=0.4)\n"
            ".model dbi d(is=1e-14 n=1.2 m=0.4)\n.model mm mmode\n.model rr cres(r=1k)\n"
            f".control\n{PRE}\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    with open(os.path.join(HERE, f"_{tag}.cir"), "w") as f:
        f.write(deck)
    p = subprocess.run([NGSPICE, "-b", f"_{tag}.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=120, errors="replace")
    return p.stdout + p.stderr


def vals(out, name):
    return [abs(float(x)) for x in re.findall(rf"^{re.escape(name)} = (\S+)", out, re.M)]


def first(v):
    return v[0] if v else None


def near(a, b, rel=1e-9):
    return a is not None and b is not None and abs(a - b) <= rel * abs(b)


def cell(inner, x="m=2", tag="t", ctl="op\nprint i(v1)"):
    return run(f".subckt cell p n\n{inner}\n.ends\nV1 a 0 dc 0.5\nX1 a 0 cell {x}", ctl, tag)


print("Enhancement-916: a subcircuit's multiplier reaches a compiled model that owns `m`\n")
if not check("compile the diode, the module owning `m` and the resistor", compile_all()):
    print(f"\n{passed}/{checks} checks passed")
    sys.exit(1)

body = (".subckt dsub p n\nnd1 p n dva\n.ends\n.subckt bsub p n\nd1 p n dbi\n.ends\n"
        "V1 in 0 dc 1\nR1 in a 1k\nX1 a 0 dsub m=2\nV2 in2 0 dc 1\nR2 in2 b 1k\nX2 b 0 bsub m=2")
out = run(body, "op\nprint v(a) v(b)", "diode")
va, vb = first(vals(out, "v(a)")), first(vals(out, "v(b)"))
check("[1] a compiled diode whose grading coefficient is `m`, in a subcircuit called with m=2, "
      "runs and gives the built-in diode's point (was refused: unknown parameter (m))",
      near(va, vb, 1e-5) and "unknown parameter" not in out, f"{va} / {vb}")
one = first(vals(run(".subckt bsub p n\nd1 p n dbi\n.ends\nV1 in 0 dc 1\nR1 in a 1k\nX1 a 0 bsub",
                     "op\nprint v(a)", "diode1"), "v(a)"))
check("[1] ... and the multiplier is applied: 2 diodes sit lower than 1", va is not None and
      one is not None and va < one - 0.01, f"{va} < {one}")

out = run(body.replace("nd1 p n dva", "nd1 p n dva _mfactor=3").replace("d1 p n dbi", "d1 p n dbi m=3"),
          "op\nprint v(a) v(b)", "diode6")
va, vb = first(vals(out, "v(a)")), first(vals(out, "v(b)"))
check("[2] ... with `_mfactor=3` on its line: six diodes, as the built-in's m=3 inside m=2 (was "
      "refused as a second spelling of the multiplier)", near(va, vb, 1e-5), f"{va} / {vb}")

i = first(vals(cell("nx1 p n mm", tag="own"), "i(v1)"))
check("[3] a module with an instance parameter `m` of its own, in m=2: two devices, 1.002 mA "
      "(was 0.502 mA: its m set to 2 and no multiplier)", near(i, 2 * (0.5e-3 + 1e-6)), f"{i}")
out = cell("nx1 p n mm m=3", tag="own3", ctl="op\nprint i(v1) " + A + "n.x1.nx1[m]")
i = first(vals(out, "i(v1)"))
check("[4] ... with `m=3` written on its line: the parameter stays 3 and the device is still "
      "doubled, 1.006 mA", near(i, 2 * (0.5e-3 + 3e-6)) and first(vals(out, A + "n.x1.nx1[m]")) == 3.0,
      f"{i} m={first(vals(out, A + 'n.x1.nx1[m]'))}")

i = first(vals(cell("n1 p n rr m=3", tag="res3"), "i(v1)"))
check("[5] a resistor module, whose `m` is the multiplier, with m=3 inside m=2: 6x (E-394)",
      near(i, 3e-3), f"{i}")

body = (".subckt l3 p n\nn1 p n rr m=5\n.ends\n.subckt l2 p n\nX3 p n l3 m=3\n.ends\n"
        "V1 a 0 dc 0.5\nX1 a 0 l2 m=2")
i = first(vals(run(body, tag="nest"), "i(v1)"))
check("[6] nested subcircuits 2 x 3 x 5 around the compiled resistor: 30x", near(i, 15e-3), f"{i}")

body = (".subckt cell p n\nn1 p n rr3\n.ends\n.model rr3 cres(r=1k _mfactor=3)\n"
        "V1 a 0 dc 0.5\nX1 a 0 cell m=2\nn2 a 0 rr3")
out = run(body, "op\nprint i(v1) " + A + "n2[i] " + A + "n.x1.n1[i]", "card")
check("[7] a `.model` card's `_mfactor=3` default, inside m=2: 6x there, 3x at the top level",
      near(first(vals(out, A + "n.x1.n1[i]")), 3e-3) and near(first(vals(out, A + "n2[i]")), 1.5e-3),
      f"{first(vals(out, A + 'n.x1.n1[i]'))} / {first(vals(out, A + 'n2[i]'))}")

out0 = cell("n1 p n rr", "m=0", "zero")
outn = cell("n1 p n rr", "m=-1", "neg")
check("[8] m=0 on the X line: the instance is disabled with one note; m=-1: one warning, the "
      "multiplier kept", out0.count("m=0 disables the instance") == 1 and
      first(vals(out0, "i(v1)")) == 0.0 and outn.count("multiplier m=-1 is negative") == 1 and
      near(first(vals(outn, "i(v1)")), 0.5e-3), f"{first(vals(out0, 'i(v1)'))} {first(vals(outn, 'i(v1)'))}")

ib = first(vals(cell("R1 p n 1k", tag="builtin"), "i(v1)"))
body = ".subckt cell p n m=1\nn1 p n rr m={m}\n.ends\nV1 a 0 dc 0.5\nX1 a 0 cell m=2"
idecl = first(vals(run(body, tag="decl"), "i(v1)"))
check("[9] a built-in resistor in m=2 is doubled, and a subcircuit that declares `m` itself binds "
      "it once (E-394)", near(ib, 1e-3) and near(idecl, 1e-3), f"{ib} / {idecl}")

out = run(".subckt cell p n\nnx1 p n mm\n.ends\nV1 a 0 dc 0.5 ac 1\nX1 a 0 cell m=2",
          "ac lin 1 1k 1k\nprint mag(i(v1))", "ac")
check("[10] the small-signal current of the module owning `m` in m=2 is two devices' (2 mS)",
      near(first(vals(out, "mag(i(v1))")), 2e-3), f"{first(vals(out, 'mag(i(v1))'))}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
