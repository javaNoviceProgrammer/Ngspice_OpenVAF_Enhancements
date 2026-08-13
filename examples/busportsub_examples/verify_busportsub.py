#!/usr/bin/env python3
"""verify_busportsub.py -- a Verilog-A bus port driven through a subcircuit.

A worked, realistic example of Enhancement-444's `.option autobus` reaching
inside a `.subckt` (Enhancement-449). `va_res.va` is an ordinary two-terminal
resistor whose two pins are declared as one bus port:

    inout [0:1] p ;
    V(p[0],p[1]) <+ R_ohm * I(p[0],p[1]) ;

so the model has terminals `p[0]` and `p[1]`. The subcircuit wraps it and the
device line inside connects the WHOLE bus by its base name:

    .subckt mysub q[0] q[1]        .subckt mysub2 q[0:1]
    N1 q va_res                    N1 q va_res
    .ends                          .ends

Both decks build the same divider -- two 1 kOhm instances in series from V1 to
ground -- so `v(b)` must be exactly half of `v(a)` at every sweep point, which is
an analytic answer no mis-binding can produce by accident.

The two `.subckt` lines are the same interface spelled two ways: per-bit ports
and a range. `q[0:1]` is the tidier form. What does NOT work is a bare `q` in
the PORT LIST -- the `.subckt` line is parsed long before any model is known, so
nothing there can tell that `q` is two bits wide; that case is pinned below as
the error it produces.

Exhaustive checks of the underlying mechanism live in `subbus_examples`; this
directory is the end-user shape.
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

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_bp_"):
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


def ngrun(deck_name, timeout=120):
    r = subprocess.run([NGSPICE, "-b", deck_name], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def write(name, text):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(text)
    return name


def sweep(out):
    """the (v-sweep, v(a), v(b)) rows of the dc print"""
    return [tuple(float(x) for x in m)
            for m in re.findall(
                r"^\s*\d+\s+(-?[\d.]+e[-+]\d+)\s+(-?[\d.]+e[-+]\d+)\s+"
                r"(-?[\d.]+e[-+]\d+)", out, re.M)]


print("A Verilog-A bus port driven through a subcircuit\n")

r = subprocess.run([OPENVAF, "va_res.va", "-o", "va_res.osdi"], cwd=HERE,
                   capture_output=True, text=True)
check("[E-449] va_res.va compiles", r.returncode == 0 and
      os.path.isfile(os.path.join(HERE, "va_res.osdi")), r.stderr.strip()[:60])

# ------------------------------------------------------- the two spellings ---
print("\nthe committed decks")
rows = {}
for deck, how in (("mycircuit.cir", "per-bit ports  `.subckt mysub q[0] q[1]`"),
                  ("mycircuit2.cir", "a range        `.subckt mysub2 q[0:1]`")):
    rc, out = ngrun(deck)
    rows[deck] = sweep(out)
    check(f"[E-449] {deck} runs -- {how}",
          rc == 0 and len(rows[deck]) == 11, f"rc={rc} {len(rows[deck])} rows")

for deck in ("mycircuit.cir", "mycircuit2.cir"):
    ok = rows[deck] and all(
        abs(vb - va / 2.0) <= 1e-9 * max(1.0, abs(va)) and abs(va - sw) <= 1e-9
        for sw, va, vb in rows[deck])
    check(f"[E-449] {deck}: v(b) is exactly half of v(a) at all 11 points", ok,
          f"{rows[deck][1] if rows[deck] else ''}")

check("[E-449] both spellings give BIT-IDENTICAL results",
      rows["mycircuit.cir"] == rows["mycircuit2.cir"] and rows["mycircuit.cir"])

# ------------------------------------------------------------- the controls ---
# What the option is actually doing: without it, the bare `q` on the device line
# is not expanded, the instance is left short, and E-402 says so.
print("\nwhat the option is doing")
base = open(os.path.join(HERE, "mycircuit2.cir")).read()
write("_bp_nooption.cir", base.replace(".option autobus", "* no autobus here"))
rc, out = ngrun("_bp_nooption.cir")
check("[E-449] without `.option autobus` the bus is NOT bound by name",
      "are not connected" in out or "not connected" in out)

# A bare name in the PORT LIST cannot work: the .subckt line is parsed before any
# model is known, so `q` there is one scalar port and the two-node instantiation
# is simply a port-count mismatch. Pinned as the diagnostic it produces.
write("_bp_barelist.subckt",
      ".subckt _bp_bare q\n.model va_res va_res R_ohm=1k\nN1 q va_res\n.ends\n")
write("_bp_barelist.cir",
      base.replace("./mysub2.subckt", "./_bp_barelist.subckt")
          .replace("X1 a b mysub2", "X1 a b _bp_bare")
          .replace("X2 b 0 mysub2", "X2 b 0 _bp_bare"))
rc, out = ngrun("_bp_barelist.cir")
check("[E-449] a BARE name in the .subckt port list is a port-count error",
      "Too many parameters" in out, f"rc={rc}")

# The bus base may also be passed through a SCALAR port -- a different interface,
# in which the caller supplies one name and the bits appear in ITS scope.
write("_bp_scalar.subckt",
      ".subckt _bp_scalar q\n.model va_res va_res R_ohm=1k\nN1 q va_res\n.ends\n")
write("_bp_scalar.cir",
      ".title bus base through a scalar port\n"
      ".option autobus\n.include ./_bp_scalar.subckt\n"
      "V1 z[0] 0 DC 1.0\nX1 z _bp_scalar\nRload z[1] 0 1k\n"
      ".control\npre_osdi ./va_res.osdi\nop\nprint v(z[0]) v(z[1])\n.endc\n.end\n")
rc, out = ngrun("_bp_scalar.cir")
v = dict(re.findall(r"v\(([^)]+)\)\s*=\s*(-?[\d.]+e[-+]\d+)", out, re.I))
check("[E-449] a SCALAR port passes the bus base to the caller's scope",
      rc == 0 and v.get("z[0]") is not None and
      abs(float(v.get("z[1]", "nan")) - 0.5) <= 1e-9, f"{v}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
