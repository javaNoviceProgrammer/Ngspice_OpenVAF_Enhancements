#!/usr/bin/env python3
"""Enhancement-327: `ddx` unknowns that do not lower to a bare MIR `Param`.

`LoweringCtx::nodes` can return a `Param` (a forward-oriented probe), an `fneg`
INSTRUCTION (a reverse-oriented probe such as `V(b,a)`, or one whose high side is
ground), or `F_ZERO` (a probe of ground only). `ddx` lowering unwrapped a `Param`
unconditionally, so the latter two panicked with "Value is not a parameter" --
crashing the SHIPPED compiler on legal input.

Both shapes have an unambiguous derivative, so the fix makes them COMPILE rather
than error:
  * `V(b,a)` is the same branch with the opposite reference direction, so
    `d f / d V(b,a) == -( d f / d V(a,b) )`;
  * ground is not an unknown of the DAE system, so `d f / d V(gnd) == 0`.

Compiling is not enough -- the derivative has to be RIGHT, so every check below is
numeric against the closed form. Each module differentiates `V^2` (exact
derivative `2V`) at V = 3, scaled by 1 mS.

  [1] the model compiles at all          (pre-fix: compiler panic, no .osdi)
  [2] forward  ddx(V^2, V(a,b)) == 2V     -> i = -6 mA
  [3] reverse  ddx(V^2, V(b,a)) == -2V    -> i = +6 mA, the EXACT negative
  [4] ground   ddx(V^2, V(gnd)) == 0      -> only the 1e-9 leak remains
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


def main():
    osdi = os.path.join(HERE, "ddxunknown.osdi")
    if os.path.exists(osdi):
        os.remove(osdi)
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, "ddxunknown.va"), "-o", osdi],
                           capture_output=True, text=True, timeout=120)
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = "HANG", ""
    sig = next((l for l in out.splitlines() if "panicked at" in l), "")
    check("reverse-oriented / ground `ddx` unknowns compile", rc == 0 and os.path.exists(osdi),
          f"rc={rc} {sig[:60]}")
    if rc != 0:
        print(f"\nFAILURES: {passed}/{checks} passed")
        sys.exit(1)

    deck = os.path.join(HERE, "_ddx.cir")
    with open(deck, "w") as f:
        f.write("ddx unknown orientation\n"
                "V1 n1 0 dc 3\nNf n1 0 fmod\n"
                "V2 n2 0 dc 3\nNr n2 0 rmod\n"
                "V3 n3 0 dc 3\nNg n3 0 gmod\n"
                ".model fmod ddx_fwd\n.model rmod ddx_rev\n.model gmod ddx_gnd\n"
                ".control\npre_osdi ddxunknown.osdi\nop\n"
                "print i(v1) i(v2) i(v3)\n.endc\n.end\n")
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], cwd=HERE,
                            capture_output=True, text=True, timeout=120)
        out = rr.stdout + rr.stderr
    finally:
        if os.path.exists(deck):
            os.remove(deck)

    def val(name):
        m = re.search(rf"{re.escape(name)}\s*=\s*([-\d.eE+]+)", out)
        return float(m.group(1)) if m else None

    ifwd, irev, ignd = val("i(v1)"), val("i(v2)"), val("i(v3)")

    # d/dV (V^2) = 2V = 6 at V=3; scaled by 1 mS; source current is the negative
    check("forward ddx(V^2, V(a,b)) = 2V (i = -6 mA)",
          ifwd is not None and abs(ifwd - (-6.0e-3)) < 1e-9, str(ifwd))
    check("reverse ddx(V^2, V(b,a)) is the EXACT negative (i = +6 mA)",
          irev is not None and ifwd is not None and abs(irev + ifwd) < 1e-15,
          f"{irev} vs -({ifwd})")
    # only the explicit 1e-9*V leak may remain: 1e-9 * 3 = 3e-9
    check("ground unknown ddx(V^2, V(gnd)) contributes exactly 0",
          ignd is not None and abs(ignd - (-3.0e-9)) < 1e-15, str(ignd))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
