#!/usr/bin/env python3
"""verify_vafdeadop.py -- Enhancement-307: a `ddt` with no contributions crashed openvaf-r.

`sim_back/topology/lineralize.rs` asserted that an analog operator reaching the
linearizer with an empty contribution list could only be noise:

    assert!(noise, "ddt should have been deadcode eliminated")

That does not hold. A `ddt` whose result never reaches a contribution can survive dead-code
elimination, and because this was a plain `assert!` -- not `debug_assert!` -- it fired in the
SHIPPED build: "OpenVAF encountered a problem and has crashed!".

Found by grammar-based fuzzing aimed at the middle/back end (5 independent seeds out of
3000 hit the identical assert), then delta-debugged. Ablation showed the trigger needs all
of: the `ddt`, a current probe on a declared branch (a probe-only branch), an if/else, and
a case -- in a module with no contributions at all.

The fix takes the `Evaluation::Dead` path the function already returns for the noise case:
no contributions means the operator's value reaches no device equation, so its result is
replaced with zero and pending uses are retargeted.

Checks here:
  1. the reproducer compiles (it crashed the compiler before);
  2. the model it produces actually loads into ngspice;
  3. a NORMAL ddt -- one that does contribute -- is numerically unchanged, checked against
     the closed form, since the fix touches the Dead path.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    osdi = os.path.join(HERE, name.replace(".va", ".osdi"))
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi],
                           capture_output=True, text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if "has crashed" in out or "panicked at" in out:
        return False, "COMPILER CRASH"
    if r.returncode != 0:
        return False, f"exit {r.returncode}"
    return os.path.exists(osdi), "compiled"


def ngspice(deck, name):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


def val(out, vec):
    m = re.search(rf"^{re.escape(vec)}\s*=\s*([-\d.eE+]+)", out, re.M | re.I)
    return float(m.group(1)) if m else None


print("Enhancement-307: a ddt with no contributions crashed the compiler")

# --- 1: the reproducer must compile -----------------------------------------
ok, verdict = compile_va("deadop_repro.va")
check("dead-ddt reproducer compiles (was a compiler crash)", ok, verdict)

# --- 2: and the model it produced must load ---------------------------------
if ok:
    # The reproducer contributes NOTHING, so it is an inert device and its node
    # floats -- an `op` legitimately cannot solve it. What matters is that the
    # produced .osdi is a well-formed loadable module, so check `pre_osdi` itself.
    out = ngspice("""* the .osdi built from the reproducer must be loadable
r1 a 0 1k
v1 a 0 dc 1
.control
pre_osdi deadop_repro.osdi
op
print v(a)
.endc
.end
""", "_load.cir")
    low = out.lower()
    check("the resulting .osdi loads (pre_osdi accepts it)",
          val(out, "v(a)") is not None
          and not any(k in low for k in ("could not", "cannot open", "not loaded",
                                         "error loading", "osdi error")),
          f"v(a)={val(out,'v(a)')}")

# --- 3: a NORMAL ddt is numerically unchanged -------------------------------
# I = C*ddt(V) is a capacitor, so |Z| = 1/(2*pi*f*C) exactly.
with open(os.path.join(HERE, "livecap.va"), "w") as fh:
    fh.write("""// a ddt that DOES contribute -- must be unaffected by the Dead-path fix
`include "disciplines.vams"
module livecap(p, n);
   inout p, n;
   electrical p, n;
   parameter real c = 1e-9;
   analog begin
      I(p,n) <+ c*ddt(V(p,n));
   end
endmodule
""")
ok2, verdict2 = compile_va("livecap.va")
check("a contributing ddt still compiles", ok2, verdict2)
if ok2:
    F, C = 1e5, 1e-9
    # r1 gives the node a DC reference (a lone capacitor + current source floats and
    # is singular); at 100 kHz the 1nF cap is 1591 ohm, so the 1G resistor is negligible
    # and |Z| -> 1/(2 pi f C).
    out = ngspice(f"""* a ddt capacitor must still give |Z| = 1/(2 pi f C)
i1 0 p ac 1
n1 p 0 cm
r1 p 0 1g
.model cm livecap c={C}
.control
pre_osdi livecap.osdi
ac lin 1 {F} {F}
print mag(v(p))
.endc
.end
""", "_cap.cir")
    want = 1.0 / (2 * math.pi * F * C)
    got = val(out, "mag(v(p))")
    rel = abs(got - want) / want if got is not None else 1.0
    check("contributing ddt: |Z| = 1/(2 pi f C) unchanged",
          got is not None and rel < 1e-4,
          f"got {got if got is None else format(got,'.6g')} want {want:.6g}")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
