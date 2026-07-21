#!/usr/bin/env python3
"""verify_sweepwild.py -- Enhancement-268/-269: wildcard model/instance parameter
knobs.

`@*[param]` (E-268) sets a MODEL parameter on every loaded model that has it, in
place (altermod, no deck re-source); `@#*[param]` and its alias `@*[[param]]`
(E-269) do the same for an INSTANCE parameter across every device instance. This
lets one `sweep` co-vary a shared parameter across many `.model` cards / instances
without the slow `.param` + `reset` idiom.

The demo model `wlmodel` has R = wavelength*scale*1k, where `wavelength` is a MODEL
parameter and `scale` an INSTANCE parameter. Checks:
  [1] `@*[wavelength]` (model wildcard) co-varies BOTH model cards; an unrelated
      model without `wavelength` is untouched.
  [2] the model wildcard reaches `.model` cards INSIDE subcircuits (they flatten to
      per-instantiation model copies).
  [3] `@#*[scale]` (instance wildcard) co-varies EVERY instance.
  [4] the alias `@*[[scale]]` does the same.
  [5] a concrete `@dev1[wavelength]` / `@NX1[scale]` still targets just one.
  [6] `@*[<absent>]` and `@#*[<absent>]` warn and change nothing.

Runs under BOTH linear solvers (the knobs are solver-independent). Exit 0 = pass.
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


def run(body, control):
    deck = ("* wildcard demo\n" + body +
            ".control\nset numdgt=10\n"
            "pre_osdi wlmodel.osdi\npre_osdi plainres.osdi\n"
            f"{control}\n.endc\n.end\n")
    with open(os.path.join(HERE, "_wild.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_wild.cir"], cwd=HERE,
                       capture_output=True, text=True, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def cur(out, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.eE+-]+)", out)
    return abs(float(m.group(1))) if m else None


# plainres.va: a second module with NO wavelength/scale (unrelated device type).
with open(os.path.join(HERE, "plainres.va"), "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module plainres(p, n); inout p, n; electrical p, n;\n"
            " parameter real r = 2000.0; analog V(p,n) <+ I(p,n)*r; endmodule\n")

# Top-level: two wlmodel cards (dev1, dev2) + one plainres. R = wavelength*scale*1k.
FLAT = ("NX1 n1 0 dev1\nNX2 n2 0 dev2\nNX3 n3 0 pr1\n"
        "v1 n1 0 1\nv2 n2 0 1\nv3 n3 0 1\n"
        ".model dev1 wlmodel\n.model dev2 wlmodel\n.model pr1 plainres r=2000\n")

print("Enhancement-268/-269: wildcard model/instance parameter knobs")

if not (compile_va("wlmodel") and compile_va("plainres")):
    check("models compile", False, "openvaf-r failed")
    print(f"\n{passed}/{checks} checks passed")
    raise SystemExit(1)

# [1] model wildcard: @*[wavelength]=4 -> both dev1,dev2 R=4k (i=2.5e-4); pr1 (no
#     wavelength) untouched (r=2000 -> i=5e-4).
out = run(FLAT, "altermod @*[wavelength]=4\nop\nprint i(v1) i(v2) i(v3)")
i1, i2, i3 = cur(out, "i(v1)"), cur(out, "i(v2)"), cur(out, "i(v3)")
check("[1] @*[wavelength] (model wildcard) co-varies both model cards",
      i1 and i2 and abs(i1 - 2.5e-4) < 1e-6 and abs(i2 - 2.5e-4) < 1e-6,
      f"i1={i1} i2={i2} (want 2.5e-4)")
check("[1b] an unrelated model (no `wavelength`) is untouched",
      i3 is not None and abs(i3 - 5.0e-4) < 1e-6, f"i3={i3} (want 5e-4)")

# [2] model wildcard reaches .model cards INSIDE subcircuits.
SUB = (".subckt wlsub a b\nNXs a b devs\n.model devs wlmodel\n.ends\n"
       "X1 n1 0 wlsub\nX2 n2 0 wlsub\nv1 n1 0 1\nv2 n2 0 1\n")
out = run(SUB, "altermod @*[wavelength]=5\nop\nprint i(v1) i(v2)")
i1, i2 = cur(out, "i(v1)"), cur(out, "i(v2)")
check("[2] model wildcard covers `.model` cards inside subcircuits",
      i1 and i2 and abs(i1 - 2.0e-4) < 1e-6 and abs(i2 - 2.0e-4) < 1e-6,
      f"i1={i1} i2={i2} (want 2e-4)")

# [3] instance wildcard @#*[scale]=4 -> every instance scale=4 (R=4k, i=2.5e-4).
out = run(FLAT, "alter @#*[scale]=4\nop\nprint i(v1) i(v2)")
i1, i2 = cur(out, "i(v1)"), cur(out, "i(v2)")
check("[3] @#*[scale] (instance wildcard) co-varies every instance",
      i1 and i2 and abs(i1 - 2.5e-4) < 1e-6 and abs(i2 - 2.5e-4) < 1e-6,
      f"i1={i1} i2={i2} (want 2.5e-4)")

# [4] alias @*[[scale]] behaves identically.
out = run(FLAT, "alter @*[[scale]]=4\nop\nprint i(v1) i(v2)")
i1, i2 = cur(out, "i(v1)"), cur(out, "i(v2)")
check("[4] alias @*[[scale]] co-varies every instance",
      i1 and i2 and abs(i1 - 2.5e-4) < 1e-6 and abs(i2 - 2.5e-4) < 1e-6,
      f"i1={i1} i2={i2} (want 2.5e-4)")

# [5] concrete knobs still target one: @dev1[wavelength] (model) / @NX1[scale] (inst).
out = run(FLAT, "altermod @dev1[wavelength]=10\nalter @NX2[scale]=5\nop\nprint i(v1) i(v2)")
i1, i2 = cur(out, "i(v1)"), cur(out, "i(v2)")
check("[5] concrete @dev1[wavelength] and @NX2[scale] target only their own device",
      i1 and i2 and abs(i1 - 1.0e-4) < 1e-6 and abs(i2 - 2.0e-4) < 1e-6,
      f"i1={i1} (1e-4, dev1 wl=10) i2={i2} (2e-4, NX2 scale=5)")

# [6] no-match wildcards warn and change nothing.
out = run(FLAT, "altermod @*[nope]=1\nalter @#*[nope]=1\nop\nprint i(v1)")
n_model = "no loaded model has parameter" in out.lower()
n_inst = "no loaded instance has parameter" in out.lower()
check("[6] @*[absent] / @#*[absent] warn and change nothing",
      n_model and n_inst and cur(out, "i(v1)") and abs(cur(out, "i(v1)") - 1.0e-3) < 1e-6,
      f"model_warn={n_model} inst_warn={n_inst}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
