#!/usr/bin/env python3
"""verify_wildparam.py -- Enhancement-284: wildcard parameter diagnostics, and the
`sweep` banner's model-vs-instance label.

Verilog-A writes parameter names into the .osdi with their case preserved
(`L_um`), while ngspice lower-cases netlist tokens. That is *not* a problem -- the
OSDI parameter lookup is case-insensitive -- but the old diagnostics made it look
like one:

  * `@*[[L_um]]` is the INSTANCE wildcard. A plain `parameter real L_um` in
    Verilog-A is a MODEL parameter (an instance parameter needs
    `(* type = "instance" *)`), so the instance wildcard correctly matched nothing
    and reported `no loaded instance has parameter 'l_um'` -- lower-cased, and with
    no hint that the parameter exists at the model level. It reads like a
    spelling/case failure.
  * `sweep` labelled every in-place knob `(model param)`, including the instance
    wildcards, because `sw_kind` returns SW_MODEL as a *dispatch* flag.

Fixed: a probe `if_hasparam_wildcard()` lets each wildcard, on finding no match,
check the other level and name the form that would work; and `sw_knobdesc()`
classifies the knob from the name token for the banner.

Passes iff the cross-level hints appear, the labels are right, and matching
wildcards still work. Reported via exit code (0 = pass).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(stem):
    r = subprocess.run([OPENVAF, f"{stem}.va", "-o", f"{stem}.osdi"],
                       cwd=HERE, capture_output=True, text=True, timeout=180)
    return r.returncode == 0 and os.path.exists(os.path.join(HERE, f"{stem}.osdi"))


def run(deck, timeout=90):
    path = os.path.join(HERE, "_wp.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


print("Enhancement-284: wildcard parameter diagnostics + sweep knob label")

ok = build("camel") and build("modelonly")
check("[0] test models compile (camel: mixed-case model+instance params)", ok)
if not ok:
    print("\n0/1 checks passed")
    raise SystemExit(1)

# camel.va : Wavelength = MODEL param, L_um = INSTANCE param (both mixed case)
CAMEL = ("* camel\n.model cm camel Wavelength=1\nn1 a 0 cm L_um=2\nv1 a 0 1\n"
         ".control\npre_osdi camel.osdi\n")
# modelonly.va : L_um is a MODEL parameter only
MODELONLY = ("* modelonly\n.model mo modelonly L_um=2\nn1 a 0 mo\nv1 a 0 1\n"
             ".control\npre_osdi modelonly.osdi\n")

# [1] the reported case: a MODEL param addressed with the INSTANCE wildcard.
rc, out = run(MODELONLY + "alter @*[[L_um]]=4\nquit\n.endc\n.end\n")
lo = out.lower()
check("[1] model param via instance wildcard -> names the model form '@*[l_um]'",
      "no loaded instance has parameter" in lo and "@*[l_um]" in lo
      and "type = \"instance\"" in lo, "")

# [2] the mirror: an INSTANCE param addressed with the MODEL wildcard.
rc, out = run(CAMEL + "alter @*[L_um]=4\nquit\n.endc\n.end\n")
lo = out.lower()
check("[2] instance param via model wildcard -> names '@#*[l_um]'",
      "no loaded model has parameter" in lo and "@#*[l_um]" in lo, "")

# [3] a genuinely absent parameter still gets the plain message (no bogus hint).
rc, out = run(CAMEL + "alter @*[nosuchparam]=1\nquit\n.endc\n.end\n")
lo = out.lower()
check("[3] a truly absent parameter -> plain message, no misleading hint",
      "no loaded model has parameter" in lo and "did you mean" not in lo
      and "@#*[nosuchparam]" not in lo, "")

# [4] sweep labels an INSTANCE wildcard correctly.
rc, out = run(CAMEL + "sweep @*[[L_um]] 1 3 1 -analysis op -output i1=i(v1)\n"
                      "quit\n.endc\n.end\n")
check("[4] sweep labels `@*[[L_um]]` as an instance param (was 'model param')",
      "instance param" in out.lower(), "")

# [5] sweep labels a MODEL wildcard correctly.
rc, out = run(CAMEL + "sweep @*[Wavelength] 1 3 1 -analysis op -output i1=i(v1)\n"
                      "quit\n.endc\n.end\n")
check("[5] sweep labels `@*[Wavelength]` as a model param",
      "model param" in out.lower(), "")

# [6] the matching wildcard still actually sweeps: i = -1/(1*L*1000).
rc, out = run(CAMEL + "sweep @*[[L_um]] 1 3 1 -analysis op -output i1=i(v1)\n"
                      "print i1\nquit\n.endc\n.end\n")
vals = [float(x) for x in re.findall(r"^\s*\d+\s+(-?\d\.\d+e[-+]\d+)", out, re.M)]
ok6 = (len(vals) >= 3 and abs(vals[0] + 1e-3) < 1e-9
       and abs(vals[1] + 5e-4) < 1e-9 and abs(vals[2] + 1.0 / 3e3) < 1e-9)
check("[6] the instance wildcard still sweeps correctly (-1e-3, -5e-4, -3.33e-4)",
      ok6, f"{[round(v, 7) for v in vals[:3]]}")

# [7] case-insensitivity: ALL-CAPS still resolves the mixed-case name.
rc, out = run(CAMEL + "alter @*[[L_UM]]=4\nop\nprint i(v1)\nquit\n.endc\n.end\n")
m = re.search(r"i\(v1\)\s*=\s*(-?\d+\.?\d*[eE][-+]?\d+)", out)
check("[7] ALL-CAPS `@*[[L_UM]]` still matches the mixed-case `L_um`",
      m is not None and abs(float(m.group(1)) + 2.5e-4) < 1e-9,
      f"={m.group(1) if m else '?'}")

# ---------------------------------------------------------------- Enhancement-733
# (D3 of the 2026-09-25 evening hunt) The hint of [2] was printed only when NO
# model took the value. ngspice's built-in resistor has a MODEL parameter `r`
# (its default resistance), so beside `R9 a 0 1k` the same `alter @*[r]=2k`
# set that default, counted one, and said nothing while the OSDI instances,
# whose `r` is an instance parameter, kept theirs.
A = "@"


def val(out, name):
    m = re.search(re.escape(name) + r"\s*=\s*(-?\d+\.?\d*[eE][-+]?\d+)", out)
    return float(m.group(1)) if m else None


ok = build("rinst")
check("[8] rinst compiles (`r` an instance parameter, as on a CMC resistor)", ok)
RB = ("* rinst\n.model rm rinst\nn1 a 0 rm r=1k\nn2 a 0 rm r=1k\nr9 a 0 1k\nv1 a 0 1\n"
      ".control\npre_osdi rinst.osdi\n")
PR = f"op\nprint i(v1) {A}n1[r] {A}n2[r]\nquit\n.endc\n.end\n"
rc, out = run(RB + f"alter {A}*[r]=2k\n" + PR)
check(f"[9] beside a built-in resistor, `alter {A}*[r]=2k` names the instances it could not reach and the form that does (was silent)",
      "model wildcard '" + A + "*[r]' set 1 model" in out and "instance parameter only" in out
      and A + "#*[r]" in out and "rinst" in out, "")
check("[9] ...and the OSDI instances kept their value: 1k, 1k, i(v1) = -3 mA",
      val(out, A + "n1[r]") == 1e3 and val(out, A + "n2[r]") == 1e3
      and val(out, "i(v1)") is not None and abs(val(out, "i(v1)") + 3e-3) < 1e-9, f"{val(out, 'i(v1)')}")
rc, out = run(RB + f"alter {A}#*[r]=2k\n" + PR.replace("quit", f"print {A}r9[resistance]\nquit"))
check("[10] the instance wildcard sets both OSDI instances AND r9 (its `r` is the alias of `resistance`): 2k, 2k, 2k, i(v1) = -1.5 mA, no such line",
      val(out, A + "n1[r]") == 2e3 and val(out, A + "n2[r]") == 2e3 and val(out, A + "r9[resistance]") == 2e3
      and abs((val(out, "i(v1)") or 0) + 1.5e-3) < 1e-9 and "cannot reach" not in out, f"{val(out, 'i(v1)')}")
rc, out = run(RB + f"altermod {A}*[r]=2k\n" + PR)
check(f"[11] `altermod {A}*[r]=2k` is the same wildcard and draws the same line",
      "cannot reach" in out and A + "#*[r]" in out and val(out, A + "n1[r]") == 1e3, "")
RB2 = ("* rinst\n.model rm rinst\nn1 a 0 rm r=1k\nn2 a 0 rm r=1k\nv1 a 0 1\n"
       ".control\npre_osdi rinst.osdi\n")
rc, out = run(RB2 + f"alter {A}*[r]=2k\n" + PR)
check("[12] without the built-in, [2]'s message is unchanged: 'no loaded model has parameter'",
      "no loaded model has parameter 'r'" in out and A + "#*[r]" in out and "cannot reach" not in out, "")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
