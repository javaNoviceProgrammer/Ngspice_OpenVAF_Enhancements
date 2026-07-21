#!/usr/bin/env python3
"""verify_sweepwild.py -- Enhancement-268: the wildcard model-parameter knob
`@*[param]`.

Multiple `.model` cards can share a model-parameter NAME (e.g. two Verilog-A
models both with a `wavelength` parameter). `sweep`'s existing model knob
`@<model>[param]` targets ONE model, and the `.param` idiom re-sources the whole
deck at every point (slow). The new wildcard knob `@*[param]` sets `param` on
EVERY loaded model that has it, IN PLACE (altermod, no deck re-source) -- so one
`sweep @*[wavelength] ...` co-varies all such models, fast.

Two `.model` cards of `wlmodel` (R = wavelength*1k) plus one unrelated model
(`plainres`, no `wavelength`) share the circuit. Checks:
  [1] `sweep @*[wavelength]` co-varies BOTH wlmodel devices (i1 == i2 == 1/(wl*1k)).
  [2] the unrelated model (no `wavelength`) is untouched by the wildcard.
  [3] a concrete `@dev1[wavelength]` still targets ONLY dev1 (no regression).
  [4] `@*[<absent param>]` warns and changes nothing.

Runs under BOTH linear solvers (the knob is solver-independent). Exit 0 = pass.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE           # noqa: E402
from _setup import check_both_solvers as _cbs; _cbs(__file__)  # noqa: E402  both solvers

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(stem):
    r = subprocess.run([OPENVAF, f"{stem}.va", "-o", f"{stem}.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0


def run(control):
    """Run a .control block against the two-wlmodel + plainres circuit."""
    deck = (
        "* wildcard model-param demo\n"
        "NX1 n1 0 dev1\nNX2 n2 0 dev2\nNX3 n3 0 pr1\n"
        "v1 n1 0 1\nv2 n2 0 1\nv3 n3 0 1\n"
        ".model dev1 wlmodel wavelength=1\n"
        ".model dev2 wlmodel wavelength=1\n"
        ".model pr1 plainres r=2000\n"
        ".control\nset numdgt=10\n"
        "pre_osdi wlmodel.osdi\npre_osdi plainres.osdi\n"
        f"{control}\n.endc\n.end\n")
    with open(os.path.join(HERE, "_wild.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_wild.cir"], cwd=HERE,
                       capture_output=True, text=True, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def val(out, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.eE+-]+)", out)
    return float(m.group(1)) if m else None


# plainres.va is a second module (no `wavelength`) written on the fly.
with open(os.path.join(HERE, "plainres.va"), "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module plainres(p, n); inout p, n; electrical p, n;\n"
            " parameter real r = 2000.0; analog V(p,n) <+ I(p,n)*r; endmodule\n")

print("Enhancement-268: wildcard model-parameter knob @*[param]")

if not (compile_va("wlmodel") and compile_va("plainres")):
    check("models compile", False, "openvaf-r failed")
    print(f"\n{passed}/{checks} checks passed")
    raise SystemExit(1)

# [1] sweep @*[wavelength]: both wlmodel devices co-vary. i = 1/(wl*1k).
#     print the last-point currents; wl runs 1,2,4 -> i = 1e-3, 5e-4, 2.5e-4.
out = run("sweep @*[wavelength] 1 4 1 -output i1=i(v1) -output i2=i(v2) -output i3=i(v3)\n"
          "* the wildcard altermod is in place, so the models sit at wl=4; a fresh\n"
          "* op reads the node currents at that value (no reset happened)\n"
          "op\nprint i(v1) i(v2) i(v3)")
i1, i2, i3 = val(out, "i(v1)"), val(out, "i(v2)"), val(out, "i(v3)")
# after the sweep the models sit at wl=4 -> i1=i2=1/(4k)=2.5e-4 (sign per source)
both = (i1 is not None and i2 is not None
        and abs(abs(i1) - 2.5e-4) < 1e-6 and abs(abs(i2) - 2.5e-4) < 1e-6)
check("[1] sweep @*[wavelength] co-varies BOTH wlmodel devices",
      both, f"i1={i1} i2={i2} (want |i|=2.5e-4)")

# [2] the unrelated plainres (no wavelength) is untouched: i3 = 1/2000 = 5e-4.
check("[2] a model without `wavelength` is untouched by @*[wavelength]",
      i3 is not None and abs(abs(i3) - 5.0e-4) < 1e-6, f"i3={i3} (want |i|=5e-4)")

# [3] a concrete @dev1[wavelength] targets ONLY dev1.
out = run("altermod @dev1[wavelength]=10\nop\nprint i(v1) i(v2)")
i1, i2 = val(out, "i(v1)"), val(out, "i(v2)")
check("[3] concrete @dev1[wavelength]=10 targets only dev1 (no regression)",
      i1 is not None and i2 is not None
      and abs(abs(i1) - 1.0e-4) < 1e-6 and abs(abs(i2) - 1.0e-3) < 1e-6,
      f"i1={i1} (|i|=1e-4) i2={i2} (|i|=1e-3, unchanged)")

# [4] @*[<absent>] warns, changes nothing.
out = run("altermod @*[nosuchparam]=1\nop\nprint i(v1)")
check("[4] @*[absent param] warns and changes nothing",
      "no loaded model has parameter" in out.lower(),
      "warning present" if "no loaded model" in out.lower() else "no warning")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
