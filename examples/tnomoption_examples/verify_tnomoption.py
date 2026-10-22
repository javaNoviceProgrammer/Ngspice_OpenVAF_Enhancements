#!/usr/bin/env python3
"""Enhancement-914: `.option tnom` reaches compiled models.

F1 of the 2026-09-26 options-and-convergence hunt. A built-in model whose card
gives no `tnom` measures its parameters at the circuit's nominal temperature,
which `.option tnom` sets. The OSDI layer only served it as $simparam("tnom"),
which the industry models do not read: their `tnom` is an ordinary parameter.
`.option tnom=50` moved every built-in and no compiled model, and the
VA-Models BSIM4, which falls back to 25 C when its tnom is not given, ran 1.5 %
off its built-in twin by default.

The simulator now writes its nominal temperature into a compiled model's
ungiven `tnom`, in the parameter's unit, when `.option tnom` is given, or when
the model's own default is the SPICE 27 C (300.15 K) or a "not given" sentinel.
A model with another default keeps it until the option is written.

Each module below copies one model family's pattern; R(T) = r*(1 + tc*(T - tnom))
at T = 27 C, so the current reads the nominal temperature back. A built-in
resistor with tc1 is the twin.

Checks (both solvers):
  [1] the BSIM4 pattern runs at 27 C by default (its 25 C fallback before)
  [2] `.option tnom=50` reaches it, as it reaches the built-in twin
  [3] the card's tnom wins over the option
  [4] the DIODE_CMC pattern keeps its 21 C, and takes the option
  [5] a tnom in Kelvin (300 K by default) takes the option as 323.15 K
  [6] TNOM = 27.0 with units "K" (HiSIM-HV) is read as Celsius
  [7] the EKV pattern's sentinel default takes 27 C (25 C before)
  [8] a value outside the declared range is not written, and a warning says so
  [9] a model without tnom: a note names its TR, only when the option is given
  [10] the option changed between runs, then altermod, then reset
  [11] the VA-Models BSIM4 against the built-in BSIM4 4.8
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

ROOT = os.path.dirname(os.path.dirname(HERE))
BSIM4 = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code", "bsim4", "vacode", "bsim4.va")
MODULES = ["tn27", "tn21", "tnk", "tnkc", "tnsent", "tnrange", "tntr"]

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
        subprocess.run([OPENVAF, m + ".va", "-o", m + ".osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    out = os.path.join(HERE, "bsim4va.osdi")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([OPENVAF, os.path.relpath(BSIM4, HERE), "-o", "bsim4va.osdi"], cwd=HERE,
                   capture_output=True, text=True, timeout=600)
    return all(os.path.exists(os.path.join(HERE, m + ".osdi")) for m in MODULES + ["bsim4va"])


def run(module, param="tnom", opt="", card="", ctl="op\nprint i(v1) i(v2)", tag="t"):
    deck = (f"* tnomoption {tag}\nV1 a 0 1\nN1 a 0 mm\n.model mm {module}({card})\n"
            f"V2 b 0 1\nR2 b 0 1k tc1=0.01\n{opt}\n"
            f".control\npre_osdi {module}.osdi\nset numdgt=12\n{ctl}\nshowmod mm : {param}\n.endc\n.end\n")
    path = os.path.join(HERE, f"_{tag}.cir")
    with open(path, "w") as f:
        f.write(deck)
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], cwd=HERE, capture_output=True,
                       text=True, timeout=120, errors="replace")
    return p.stdout + p.stderr


def vals(out, name):
    return [abs(float(x)) for x in re.findall(rf"^{re.escape(name)} = (\S+)", out, re.M)]


def shown(out, param):
    m = re.findall(rf"^\s*{param}\s+(\S+)\s*$", out, re.M | re.I)
    return float(m[-1]) if m else None


def amps(tn):
    """the current at 27 C through r = 1k with tc = 0.01 measured at tn (Celsius)"""
    return 1.0 / (1e3 * (1 + 0.01 * (27.0 - tn)))


def near(a, b, rel=1e-9):
    return a is not None and b is not None and abs(a - b) <= rel * abs(b)


def first(v):
    return v[0] if v else None


print("Enhancement-914: `.option tnom` reaches compiled models\n")
if not check("compile the seven pattern modules and the VA-Models BSIM4", compile_all()):
    print(f"\n{passed}/{checks} checks passed")
    sys.exit(1)

out = run("tn27", tag="b4none")
i = first(vals(out, "i(v1)"))
check("[1] the BSIM4 pattern runs at the simulator's 27 C by default (was its 25 C fallback, "
      "0.980 mA)", near(i, amps(27)) and shown(out, "tnom") == 27.0, f"{i}")
check("[1] ... as the built-in twin does", near(i, first(vals(out, "i(v2)"))), f"{first(vals(out, 'i(v2)'))}")

out = run("tn27", opt=".option tnom=50", tag="b4opt")
i, ib = first(vals(out, "i(v1)")), first(vals(out, "i(v2)"))
check("[2] `.option tnom=50` reaches the compiled model: 1.2987 mA, the built-in twin's current "
      "(was 0.980 mA, unmoved)", near(i, amps(50)) and near(i, ib) and shown(out, "tnom") == 50.0,
      f"{i} / {ib}")

out = run("tn27", opt=".option tnom=50", card="tnom=40", tag="b4card")
check("[3] a tnom on the card wins over the option", near(first(vals(out, "i(v1)")), amps(40)) and
      shown(out, "tnom") == 40.0, f"{shown(out, 'tnom')}")

out = run("tn21", param="TNOM", tag="cmcnone")
ok1 = near(first(vals(out, "i(v1)")), amps(21)) and shown(out, "tnom") == 21.0
out = run("tn21", param="TNOM", opt=".option tnom=50", tag="cmcopt")
ok2 = near(first(vals(out, "i(v1)")), amps(50)) and shown(out, "tnom") == 50.0
check("[4] the DIODE_CMC pattern keeps its own 21 C by default, and takes `.option tnom=50`",
      ok1 and ok2, f"{ok1} {ok2}")

out = run("tnk", tag="knone")
ok1 = near(first(vals(out, "i(v1)")), 1.0 / (1e3 * (1 + 0.01 * (300.15 - 300.0)))) and \
    shown(out, "tnom") == 300.0
out = run("tnk", opt=".option tnom=50", tag="kopt")
ok2 = near(first(vals(out, "i(v1)")), amps(50)) and near(shown(out, "tnom"), 323.15)
check("[5] a tnom in Kelvin keeps its 300 K by default and takes `.option tnom=50` as 323.15 K",
      ok1 and ok2, f"{ok1} {ok2}")

out = run("tnkc", param="TNOM", opt=".option tnom=50", tag="kc")
check("[6] TNOM = 27.0 declared with units \"K\" (the HiSIM-HV pattern) is read as Celsius: 50, "
      "not 323.15", near(first(vals(out, "i(v1)")), amps(50)) and shown(out, "tnom") == 50.0,
      f"{shown(out, 'tnom')}")

out = run("tnsent", param="TNOM", tag="sent")
check("[7] the EKV pattern's \"not given\" sentinel takes the simulator's 27 C (was its 25 C)",
      near(first(vals(out, "i(v1)")), amps(27)) and shown(out, "tnom") == 27.0, f"{shown(out, 'tnom')}")

out = run("tnrange", param="TNOM", opt=".option tnom=50", tag="range")
check("[8] 50 C outside the declared [22:32]: not written, the model keeps 27, a warning names "
      "the range", near(first(vals(out, "i(v1)")), amps(27)) and
      "the nominal temperature 50 C is outside the range of its 'TNOM' (from [22:32])" in out,
      next((ln for ln in out.splitlines() if "nominal temperature" in ln), "no warning")[:120])

out = run("tntr", param="TR", opt=".option tnom=50", tag="tropt")
ok1 = near(first(vals(out, "i(v1)")), amps(21)) and \
    "Note: model mm: .option tnom does not reach it -- the model has no 'tnom' parameter; its " \
    "reference temperature is 'TR'" in out
out = run("tntr", param="TR", tag="trnone")
ok2 = ".option tnom does not reach it" not in out
check("[9] a model without tnom: a note names its TR when `.option tnom` is given, and none "
      "without the option", ok1 and ok2, f"{ok1} {ok2}")

ctl = ("op\nprint i(v1)\noption tnom=60\nop\nprint i(v1)\naltermod mm tnom=40\nop\nprint i(v1)\n"
       "option tnom=70\nop\nprint i(v1)\nreset\nop\nprint i(v1)")
out = run("tn27", ctl=ctl, tag="seq")
got = vals(out, "i(v1)")
want = [amps(27), amps(60), amps(40), amps(40), amps(70)]
check("[10] 27, then `option tnom=60` at the next run, then `altermod tnom=40`, which a later "
      "`option tnom=70` leaves alone, then `reset` (the card again, the option kept): 70",
      len(got) == 5 and all(near(g, w) for g, w in zip(got, want)),
      " ".join(f"{g:.6e}" for g in got))


def b4(opt="", card=""):
    deck = (f"* tnomoption bsim4\nvdd vdd 0 dc 1.2\nvin in 0 dc 0.6\n"
            f"nm1 out in 0 0 mos_va w=1u l=100n\nm1 outb in 0 0 mos_bi w=1u l=100n\n"
            f"R1 vdd out 20k\nR2 vdd outb 20k\n.model mos_va bsim4va({card})\n"
            f".model mos_bi nmos level=14 version=4.8 {card}\n{opt}\n"
            ".control\npre_osdi bsim4va.osdi\nset numdgt=12\nop\nprint v(out) v(outb)\n.endc\n.end\n")
    path = os.path.join(HERE, "_bsim4.cir")
    with open(path, "w") as f:
        f.write(deck)
    p = subprocess.run([NGSPICE, "-b", "_bsim4.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=120, errors="replace")
    o = p.stdout + p.stderr
    return first(vals(o, "v(out)")), first(vals(o, "v(outb)"))


va, bi = b4()
va27, _ = b4(card="tnom=27")
va50o, bi50o = b4(opt=".option tnom=50")
va50c, bi50c = b4(card="tnom=50")
check("[11] the VA-Models BSIM4 with no tnom runs as with tnom=27 on its card, 4e-5 from the "
      "built-in BSIM4 (was 0.084861 V against 0.083282 V, its 25 C)",
      near(va, va27, 1e-12) and near(va, bi, 1e-4), f"{va} / {bi}")
check("[11] ... and `.option tnom=50` gives it the value tnom=50 on its card gives, as for the "
      "built-in (was 0.084861 V, unmoved)",
      near(va50o, va50c, 1e-12) and near(bi50o, bi50c, 1e-12) and near(va50o, bi50o, 1e-4),
      f"{va50o} / {bi50o}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
