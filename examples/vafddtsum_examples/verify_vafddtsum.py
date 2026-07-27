#!/usr/bin/env python3
"""Enhancement-332: summing >=3 `ddt()` terms silently dropped charge.

`I(a,b) <+ ddt(V) + ddt(V) + ddt(V)` is a 3 F capacitor. The shipped compiler
produced 1 F, with no diagnostic.

ROOT CAUSE was not in `ddt` handling at all but in TRAVERSAL ORDER.
`create_dimension` replays the instructions that consume an analog operator's
result, and its `(None, Some(x)) => Some(x)` arms mean "the unmapped operand does
not depend on the dimension" -- sound only in a topological order.
`Postorder::populate` pushes every use of the operator result onto its stack up
front, marking each visited ON PUSH, so when one use feeds another the
earlier-pushed one is popped and emitted FIRST. For `(t+t)+t` the consumer was
replayed before the `t+t` it depends on, that operand looked unmapped, and the
2 F term was DROPPED rather than added -- leaving 1 F.

  [1] N summed `ddt` terms give exactly N farads, for N = 1..6   (was: 1 for N>=3)
  [2] the same result via a `generate` loop -- legal, idiomatic code
  [3] TRANSIENT agrees with AC, so this is real charge and not an AC-path artifact
  [4] an analog operator in a loop is rejected the same way for EVERY loop form
      (`repeat` used to slip through and compile to a wrong charge)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

TWO_PI = 6.283185307179586
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(path, osdi):
    r = subprocess.run([OPENVAF, path, "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr


def run_deck(deck_name, text, pattern):
    path = os.path.join(HERE, deck_name)
    with open(path, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", deck_name], cwd=HERE,
                           capture_output=True, text=True, timeout=180)
        m = re.search(pattern, r.stdout + r.stderr)
        return float(m.group(1)) if m else None
    finally:
        if os.path.exists(path):
            os.remove(path)


def cap_ac(module, osdi):
    """Effective capacitance from an AC probe: |I| = 2*pi*f*C at f = 1 Hz, V = 1."""
    val = run_deck("_ac.cir",
                   f"ddtsum ac\nV1 a 0 dc 0 ac 1\nN1 a 0 m\n.model m {module}\n"
                   f".control\npre_osdi {osdi}\nac lin 1 1 1\nprint mag(i(v1))\n"
                   ".endc\n.end\n",
                   r"mag\(i\(v1\)\)\s*=\s*([-\d.eE+]+)")
    return None if val is None else val / TWO_PI


def cap_tran(module, osdi):
    """Effective capacitance from a 1 V/s ramp: I = C dV/dt = C."""
    val = run_deck("_tr.cir",
                   f"ddtsum tran\nV1 a 0 pwl(0 0 10 10)\nN1 a 0 m\n.model m {module}\n"
                   f".control\npre_osdi {osdi}\ntran 0.01 1\n"
                   "meas tran ii find i(v1) at=0.5\n.endc\n.end\n",
                   r"ii\s*=\s*([-\d.eE+]+)")
    return None if val is None else -val


def main():
    # [1] N summed ddt terms must give exactly N farads
    bad = []
    for n in range(1, 7):
        name = f"_sum{n}"
        src = os.path.join(HERE, name + ".va")
        with open(src, "w") as f:
            f.write('`include "disciplines.vams"\n'
                    f"module {name}(a,b); inout a,b; electrical a,b;\n"
                    "  analog begin I(a,b) <+ "
                    + " + ".join(["ddt(V(a,b))"] * n) + "; end\nendmodule\n")
        osdi = name + ".osdi"
        rc, _ = compile_va(src, osdi)
        c = cap_ac(name, osdi) if rc == 0 else None
        if c is None or abs(c - n) > 1e-5:
            bad.append(f"N={n}: {c}")
        for p in (src, os.path.join(HERE, osdi)):
            if os.path.exists(p):
                os.remove(p)
    check("N summed ddt terms give exactly N farads (N=1..6)", not bad,
          "; ".join(bad) if bad else "")

    # [2] the committed 3-term model, and [3] transient must agree with AC
    rc, out = compile_va(os.path.join(HERE, "ddtsum.va"), "ddtsum.osdi")
    if rc != 0:
        check("3 summed ddt terms = 3 F", False, f"compile rc={rc}")
        check("transient agrees with AC", False, "compile failed")
    else:
        ac = cap_ac("ddtsum", "ddtsum.osdi")
        tr = cap_tran("ddtsum", "ddtsum.osdi")
        check("3 summed ddt terms = 3 F (AC)",
              ac is not None and abs(ac - 3.0) < 1e-5, f"C={ac}")
        check("transient agrees with AC -- real charge, not an AC artifact",
              tr is not None and abs(tr - 3.0) < 1e-3, f"C_tran={tr}")
        os.remove(os.path.join(HERE, "ddtsum.osdi"))

    # [2b] the same thing through a generate loop: legal, idiomatic code
    rc, out = compile_va(os.path.join(HERE, "ddtsum_generate.va"), "ddtsum_generate.osdi")
    if rc != 0:
        check("generate-unrolled ddt sum = 3 F", False, f"compile rc={rc}")
    else:
        c = cap_ac("ddtsum_generate", "ddtsum_generate.osdi")
        check("generate-unrolled ddt sum = 3 F (legal idiomatic code)",
              c is not None and abs(c - 3.0) < 1e-5, f"C={c}")
        os.remove(os.path.join(HERE, "ddtsum_generate.osdi"))

    # [4] every loop form rejects an analog operator alike
    forms = {
        "for": "for (i=0;i<3;i=i+1) s = s + ddt(V(a,b));",
        "while": "i=0; while (i<3) begin s = s + ddt(V(a,b)); i=i+1; end",
        "repeat": "repeat (3) s = s + ddt(V(a,b));",
    }
    wrong = []
    for kind, body in forms.items():
        name = f"_lp_{kind}"
        src = os.path.join(HERE, name + ".va")
        with open(src, "w") as f:
            f.write('`include "disciplines.vams"\n'
                    f"module {name}(a,b); inout a,b; electrical a,b;\n"
                    "  real s; integer i;\n"
                    f"  analog begin s=0.0; i=0; {body} I(a,b) <+ s; end\nendmodule\n")
        rc, out = compile_va(src, name + ".osdi")
        if rc != 65 or "not allowed in loops" not in out or "4.5.1" not in out:
            wrong.append(f"{kind}: rc={rc}")
        for p in (src, os.path.join(HERE, name + ".osdi")):
            if os.path.exists(p):
                os.remove(p)
    check("for/while/repeat all reject an analog operator, citing LRM 4.5.1",
          not wrong, "; ".join(wrong) if wrong else "")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
