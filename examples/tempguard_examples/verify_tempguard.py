#!/usr/bin/env python3
"""Enhancement-815 (F24 of the 2026-10-08 ngspice + OSDI hunt): an instance
temperature at or below absolute zero is refused on every route, and the model
never sees one.

The instance line refused `temp=-300` and `dtemp=-400` (Enhancement-467), and
OSDIsetup refused a composed temperature at or below 0 K (Enhancement-426). But:
  - `alter n1 dtemp=-400` (or `dt=`, `temp=-300`, `@n1[dtemp]=`) was stored;
    OSDIsetup then printed "the offset is ignored" while OSDItemp -- which runs
    at every analysis after the first and at every sweep point -- composed the
    temperature again with no guard and handed the model -99.85 K. A resistor
    model's current reversed. A built-in took the value without a word.
  - `dt=-400` on the line, the same knob's other spelling, was not refused.
  - `dc @n1[dtemp] -400 0 200` ran its first point at -99.85 K, silently, and
    the `sweep` command over the same range solved that point at -99.85 K too.
  - a valid offset that a later ambient makes unphysical (`dtemp=-290`, then
    `set temp=-10`) was announced as ignored and reached the model.

  [1] the instance line: dtemp, dt and temp below 0 K refused, the model at the
      circuit temperature
  [2] alter: dtemp, dt, temp and @n1[dtemp]= refused, the previous value kept
      (and reported), the model at the circuit temperature
  [3] a physical value through alter or a sweep still applies
  [4] a built-in resistor: alter refused the same way
  [5] a .dc sweep of an instance temperature knob through 0 K is refused (its
      last point decides, not a stop it never reaches); the `sweep` command
      records a point whose value `alter` refused as NaN, not under the
      previous value
  [6] the ambient makes a valid offset unphysical: the model runs at the circuit
      temperature, said once, back to the offset when the ambient allows
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="tempguard_")
checks = passed = 0

# a resistance with a temperature coefficient: negative below 200.15 K, so a
# negative absolute temperature shows in the current as well as in the strobe
VA = """`include "disciplines.vams"
module tm(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
analog begin
  I(a,b) <+ V(a,b)/(r*(1 + 0.01*($temperature - 300.15)));
  if (analysis("static")) $strobe("TEMP T=%.4f", $temperature);
end
endmodule
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


va = os.path.join(WORK, "tm.va")
with open(va, "w") as f:
    f.write(VA)
r = subprocess.run([VAF, va, "-o", os.path.join(WORK, "tm.osdi")],
                   capture_output=True, text=True, errors="replace")
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(inst, ctl, tag, extra=""):
    """combined stdout+stderr of a deck with the module (and a built-in r1)"""
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* tempguard {tag}\n.control\npre_osdi tm.osdi\n.endc\n{extra}"
                f"v1 1 0 1\nn1 1 0 tmm {inst}\n.model tmm tm\n"
                f"v2 2 0 1\nr1 2 0 1k tc1=0.01\n"
                f".control\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, errors="replace")
    return p.stdout + p.stderr


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r" = (\S+)", out, re.M)
    return float(m.group(1).rstrip(",")) if m else None


def temps(out):
    return [float(t) for t in re.findall(r"TEMP T=(\S+)", out)]


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


print("Enhancement-815: no route hands a model a temperature at or below absolute zero\n")

# ------------------------------------------------------------- [1] ---
print("[1] the instance line")
for inst, word in (("dtemp=-400", "dtemp = -400 C puts the device at -373 C"),
                   ("dt=-400", "dt = -400 C puts the device at -373 C"),
                   ("temp=-300", "temp = -300 C is at or below absolute zero")):
    out = run(inst, "op\nprint i(v1)", "line_" + inst.split("=")[0])
    check(f"[1] `n1 ... {inst}`: refused by name, the model at 300.15 K, i(v1) = -1 mA",
          word in out and "absolute zero" in out and temps(out) and min(temps(out)) == 300.15
          and near(val(out, "i(v1)"), -1e-3), f"{temps(out)} {val(out, 'i(v1)')} {out[-400:]}")

# ------------------------------------------------------------- [2] ---
print("[2] alter")
for cmd, word, rb in (("alter n1 dtemp=-400", "dtemp = -400 C puts the device at -373 C", "@n1[dtemp]"),
                      ("alter n1 dt=-400", "dt = -400 C puts the device at -373 C", "@n1[dtemp]"),
                      ("alter n1 temp=-300", "temp = -300 C is at or below absolute zero", "@n1[temp]"),
                      ("alter @n1[dtemp]=-400", "dtemp = -400 C puts the device at -373 C", "@n1[dtemp]")):
    out = run("", f"{cmd}\nop\nprint i(v1)\nprint {rb}", "alter_" + str(checks))
    keep = 27.0 if rb == "@n1[temp]" else 0.0
    check(f"[2] `{cmd}`: not applied ({rb} stays {keep:g}), the model at 300.15 K, i(v1) = -1 mA",
          word in out and "not applied" in out and temps(out) and min(temps(out)) == 300.15
          and near(val(out, "i(v1)"), -1e-3) and val(out, rb) == keep,
          f"{temps(out)} {val(out, 'i(v1)')} {val(out, rb)} {out[-400:]}")

# ------------------------------------------------------------- [3] ---
print("[3] a physical value still applies")
out = run("", "alter n1 dtemp=-200\nop\nprint i(v1) @n1[dtemp]", "alter_ok")
check("[3] `alter n1 dtemp=-200`: the model at 100.15 K (i(v1) = +1 mA), no warning",
      temps(out) == [100.15] and near(val(out, "i(v1)"), 1e-3) and val(out, "@n1[dtemp]") == -200
      and "absolute zero" not in out, f"{temps(out)} {val(out, 'i(v1)')} {out[-300:]}")
out = run("", "dc @n1[dtemp] -250 0 125\nprint i(v1)", "dc_ok")
check("[3] `dc @n1[dtemp] -250 0 125`: three points at 50.15, 175.15 and 300.15 K",
      temps(out)[:3] == [50.15, 175.15, 300.15] and "absolute zero" not in out,
      f"{temps(out)} {out[-300:]}")

# ------------------------------------------------------------- [4] ---
print("[4] a built-in resistor")
out = run("", "alter r1 dtemp=-400\nalter r1 temp=-300\nop\nprint i(v2) @r1[dtemp]", "builtin")
check("[4] `alter r1 dtemp=-400` and `temp=-300`: both not applied, i(v2) = -1 mA",
      "r1: dtemp = -400 C puts the device at -373 C" in out
      and "r1: temp = -300 C is at or below absolute zero" in out
      and near(val(out, "i(v2)"), -1e-3) and val(out, "@r1[dtemp]") == 0,
      f"{val(out, 'i(v2)')} {out[-400:]}")

# ------------------------------------------------------------- [5] ---
print("[5] a .dc sweep of an instance temperature knob")
for sweep, who in (("dc @n1[dtemp] -400 0 200", "n1"), ("dc @n1[temp] -300 27 100", "n1"),
                   ("dc @r1[dtemp] -400 0 200", "r1")):
    out = run("", f"{sweep}\nprint i(v1)", "dc_" + str(checks))
    check(f"[5] `{sweep}`: refused, nothing evaluated below 0 K",
          f"puts {who} at" in out and "absolute zero" in out
          and all(t > 0 for t in temps(out)) and "TEMP T=-" not in out,
          f"{temps(out)} {out[-400:]}")
out = run("", "dc @n1[dtemp] -60 -320 -120\nprint i(v1)", "dc_short")
check("[5] `dc @n1[dtemp] -60 -320 -120`: the stop is below 0 K but the last point (-300, "
      "0.15 K) is not -- it runs, at 240.15, 120.15 and 0.15 K",
      temps(out)[:3] == [240.15, 120.15, 0.15] and "absolute zero" not in out,
      f"{temps(out)} {out[-300:]}")
out = run("", "sweep @n1[dtemp] -400 0 200 -output i(v1)\nprint i(v1)", "sweepcmd")
rows = re.findall(r"^\d+\t(\S+)\t?$", out, re.M)
check("[5] the `sweep` command over -400 .. 0: the refused point is recorded as NaN and said "
      "so, the other two are real (+1 mA at 100.15 K, -1 mA at 300.15 K)",
      rows == ["nan", "1.000000e-03", "-1.00000e-03"]
      and "1 of 3 point could not be set" in out and "TEMP T=-" not in out,
      f"{rows} {out[-500:]}")

# ------------------------------------------------------------- [6] ---
print("[6] the ambient makes a valid offset unphysical")
out = run("dtemp=-290", "op\nset temp=-10\nop\nop\nset temp=27\nop", "ambient")
t = temps(out)
warn = out.count("puts the device at -300 C")
check("[6] `dtemp=-290`, `set temp=-10`: the model at the circuit's 263.15 K, not -26.85 K",
      t == [10.15, 263.15, 263.15, 10.15], f"{t}")
check("[6] said once for two analyses, naming the offset, the circuit and the device temperature",
      warn == 1 and "dtemp = -290 C with the circuit at -10 C" in out, f"{warn} {out[-500:]}")
out = run("dtemp=-280", "dc temp 27 -13 -10", "ambient_dc")
t = temps(out)
check("[6] `dc temp 27 -13 -10` under dtemp=-280: 20.15, 10.15, 0.15 K, then the circuit's "
      "270.15 and 260.15 K, said once",
      [round(x, 2) for x in t[:5]] == [20.15, 10.15, 0.15, 270.15, 260.15]
      and out.count("at or below absolute zero") == 1, f"{t} {out[-500:]}")

print(f"\n    {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
