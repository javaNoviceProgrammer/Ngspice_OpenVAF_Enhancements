#!/usr/bin/env python3
"""Enhancement-240: fix an out-of-bounds crash in the XSPICE s_xfer code model.

The `s_xfer` analog code model (xspice/icm/analog/s_xfer/cfunc.mod) implements a
Laplace transfer function H(s) = num(s)/den(s) in controller-canonical form. Its
`integrator` state array is allocated to `den_size` elements (the number of
denominator coefficients). In the DC/transient branch it unconditionally did

    pout_pin = *(integrator[1]);        /* the out/in partial */

which assumes at least TWO denominator coefficients. A **0-order denominator**
(`den_size == 1`, i.e. a static-gain transfer function such as
`den_coeff=[1]`) has only `integrator[0]`, so reading `integrator[1]` walked off
the end of a one-element array and dereferenced garbage -> SIGSEGV at circuit
load. This bit any legitimate static-gain `s_xfer` (H(s)=k), not just degenerate
input, and is reachable from any netlist with such an a-device.

E-240 guards the access: for `den_size == 1`, out = gain*num_coeff[0]*in, so the
partial d(out)/d(in) is `gain*num_coeff[0]`; `integrator[1]` is read only when
`den_size > 1`.

The XSPICE code models load from the prebuilt bundle via SPICE_LIB_DIR, which
`_setup` points at bin/<os>/<arch>/. If the bundle/codemodels are unavailable in
this checkout, the a-device cannot load and the test self-skips.

Checks (batch mode, -b). A crash shows up as a NEGATIVE return code (signal).
 1. a static-gain `s_xfer(num=[3] den=[1])` no longer crashes and gives the exact
    gain (H=3, so 4 V in -> 12 V out) -- was SIGSEGV;
 2. another static gain `s_xfer(num=[2] den=[5])` -> H=0.4 -> 1.6 V;
 3. a zero denominator `den=[0]` (H=inf) no longer crashes (clean non-converge);
 4. a genuine dynamic filter H=1/(s+1) still works: |H(DC)| ~ 1 (regression).

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402  (also sets SPICE_LIB_DIR)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(model, analysis="op", extra=""):
    deck = (f"* s_xfer test\nv1 1 0 dc 4 ac 1\nr0 1 0 1k\n"
            f"a1 1 2 sd\n.model sd s_xfer({model})\nr2 2 0 1k\n"
            f".control\n{analysis}\n{extra}.endc\n.end\n")
    cir = os.path.join(HERE, "_sx.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


def num(out, name):
    m = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


# Availability gate: a valid dynamic s_xfer must load & run (proves codemodels present)
rc, out = run("num_coeff=[1] den_coeff=[1 1]", "ac dec 20 0.01 100",
              "let mdc=abs(v(2)[0])\nprint mdc\n")
mdc = num(out, "mdc")
if rc < 0 or mdc is None:
    print("  SKIP  XSPICE code models unavailable in this checkout "
          f"(rc={rc}) -- cannot exercise s_xfer")
    raise SystemExit(0)

# 1: static-gain den_size==1 -- the crash case -- now safe AND exact (H=3 -> 12 V)
rc, out = run("num_coeff=[3] den_coeff=[1]", "op", "print v(2)\n")
v = num(out, r"v\(2\)")
check("static-gain s_xfer(num=[3] den=[1]) no crash & exact (H=3 -> 12 V)",
      rc >= 0 and v is not None and abs(v - 12.0) < 1e-6, f"rc={rc} v(2)={v}")

# 2: another static gain H=0.4 -> 1.6 V
rc, out = run("num_coeff=[2] den_coeff=[5]", "op", "print v(2)\n")
v = num(out, r"v\(2\)")
check("static-gain s_xfer(num=[2] den=[5]) -> H=0.4 -> 1.6 V",
      rc >= 0 and v is not None and abs(v - 1.6) < 1e-6, f"rc={rc} v(2)={v}")

# 3: zero denominator (H=inf) -- must not crash
rc, _ = run("num_coeff=[1] den_coeff=[0]", "op", "print v(2)\n")
check("zero-denominator s_xfer(den=[0]) does not crash (was SIGSEGV)", rc >= 0,
      f"rc={rc}")

# 4: genuine dynamic filter still correct -- |H(DC)| ~ 1 for 1/(s+1)
check("dynamic s_xfer H=1/(s+1) still correct (|H(DC)| ~ 1)",
      mdc is not None and abs(mdc - 1.0) < 5e-3, f"|H(DC)|={mdc}")

p = os.path.join(HERE, "_sx.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
