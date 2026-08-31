#!/usr/bin/env python3
"""Enhancement-518: expressions and math, audited against Accellera VAMS-2023
clauses 4.1-4.4, then fixed.

What this suite pins, each against the quoted clause:

  * 4.4 / Table 4-16 -- "V(n1,n1) ... Error", "I(n1,n1) ... Error", "the
    operands of an expression shall be unique to define a valid branch".
    V(a,a) compiled with NO diagnostic and silently read 0; both forms are
    located errors now. The carve-out that keeps real models working: a
    hierarchy-FLATTENED instantiation legally ties two formal terminals to
    one node (a diode-connected transistor -- the LRM's own ECP oscillator
    does it), and those elaborated accesses keep the old defined semantics.
  * 4.2.4 -- "It shall be an error to pass zero (0) as the second argument
    to the modulus operator." A literal zero was already a compile error; a
    DECK-supplied zero silently produced NaN and a generic convergence
    failure. It aborts with a named OSDI(fatal) now, integer and real paths
    both -- while a genuinely runtime divisor stays unguarded (the LLVM
    lowering pins it to the defined 0 instead of UB that SIGFPEs on x86).
  * 4.2.11 -- the shift distance is "always treated as an unsigned number"
    with no upper bound, so 1<<32 is legal and equals 0. It was a hard
    error while the identical runtime expression already computed 0; now a
    warning plus the LRM value, compile-time and runtime paths agreeing.
    <<</>>> are kept as a flagged extension (the LRM bars them from analog
    blocks; >>> is the only spelling of a sign-extending shift).
  * 4.2.6 -- ===/!== ("limited support in the analog block"): they lex now
    and carry ==/!= semantics, exact in a 2-state analog world. They died
    with a parse error that never named the operator.
  * INT_MIN/-1 wraps to INT_MIN (2's complement) instead of LLVM UB.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_le_"):
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


def compile_file(name):
    osdi = os.path.join(HERE, f"_le_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_le_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_le_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmexpr\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def opvar(out, name):
    m = re.search(rf"@n1\[{name}\]\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


HDR = '`include "disciplines.vams"\n'

# ---- the committed module: every corner value at run time ------------------
print("lrmexpr.va (run-time values):")
rc, out, osdi = compile_file("lrmexpr.va")
check("[1] lrmexpr.va compiles (shift corners now warnings, not errors)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
check("[2] out-of-range literal shift draws the new warning",
      "shifts every bit out" in out)
check("[3] <<</>>> draw the analog-block extension warning (LRM 4.2.11)",
      "openvaf extension" in out)
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmexpr", "op\n"
              "print @n1[s1] @n1[s2] @n1[s3] @n1[c1] @n1[c2] @n1[a1]\n"
              "print @n1[a2] @n1[m1] @n1[d1] @n1[d2] @n1[d3] @n1[m3]",
              "main", osdi)
    for name, want, why in [
        ("s1", 0, "1<<32 = 0 (distance unsigned, 4.2.11)"),
        ("s2", -1, "-8>>>34 = -1 (sign fill past the width)"),
        ("s3", 0, "1<<sh with sh=40: runtime path agrees"),
        ("c1", 2, "(3===3)+(3!==4) = 2 (case equality as 2-state ==)"),
        ("c2", 1, "2.5===2.5 = 1"),
        ("a1", -4, "-8>>>1 = -4 (arithmetic right shift)"),
        ("a2", -16, "-8<<<1 = -16 (identical to <<)"),
        ("m1", 1, "10%9 untouched"),
        ("d1", 1, "10/9 untouched"),
        ("d2", -2147483648, "INT_MIN/-1 wraps (no UB, no SIGFPE)"),
        ("d3", 0, "7/(param-derived 0) is the defined 0"),
        ("m3", 0, "7%(runtime 0) is the defined 0, not a fatal"),
    ]:
        got = opvar(sim, name)
        check(f"[4] {why}", got == want, f"{got}")

# ---- same-node access is an error (Table 4-16) -----------------------------
print("\nsame-node branch access (LRM 4.4, Table 4-16):")
rc, out, _ = compile_src(HDR + """
module vaa(a,b); inout a,b; electrical a,b; real x;
analog begin x = V(a,a); V(b) <+ x + V(a); end
endmodule
""", "vaa")
check("[5] V(a,a) is a located error", rc != 0 and "same net" in out)

rc, out, _ = compile_src(HDR + """
module iaa(a,b); inout a,b; electrical a,b; real x;
analog begin x = I(a,a); V(b) <+ x; end
endmodule
""", "iaa")
check("[6] I(a,a) is a located error", rc != 0 and "same net" in out)

# the flattening carve-out: a diode-connected instantiation stays legal
rc, out, _ = compile_src(HDR + """
module bjtish(c, b, e);
  inout c, b, e; electrical c, b, e;
  analog begin
    I(b, e) <+ 1e-6*(limexp(V(b, e)/$vt) - 1);
    I(c, e) <+ 1e-4*(limexp(V(b, e)/$vt) - 1);
    I(c, b) <+ 1e-9*V(c, b);
  end
endmodule
module diodeconn(a, gnd_);
  inout a, gnd_; electrical a, gnd_;
  bjtish q1 (a, a, gnd_);   // collector tied to base: V(c,b) becomes V(a,a)
endmodule
""", "dconn")
check("[7] a diode-connected instantiation still compiles (flattening carve-out)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")

rc, out, _ = compile_src(HDR + """
module brdegen(a,b); inout a,b; electrical a,b;
  branch (a, a) bad;
  branch (a, b) good;
  analog I(good) <+ 1e-3*V(good);
endmodule
""", "brdegen")
check("[8] a NAMED degenerate branch declaration stays a warning (E-414)",
      rc == 0 and "warning" in out)

# ---- modulus by a deck-supplied zero (4.2.4) -------------------------------
print("\nmodulus by zero (LRM 4.2.4):")
rc, out, osdi = compile_src(HDR + """
module modz(o5, o6);
  inout o5, o6; electrical o5, o6;
  parameter integer z = 0;
  parameter real rz = 0.0;
  analog begin
    V(o5) <+ 10 % z;
    V(o6) <+ 10.0 % rz;
  end
endmodule
""", "modz")
check("[9] a parameter-zero divisor still compiles (value is deck-overridable)",
      rc == 0)
if rc == 0:
    sim = run("N1 o5 o6 mm\n.model mm modz", "op\nprint v(o5)", "modz", osdi)
    check("[10] deck-supplied zero aborts with a fatal naming % and LRM 4.2.4",
          "modulus divisor" in sim and "LRM 4.2.4" in sim
          and "OSDI(fatal)" in sim)
    sim = run("N1 o5 o6 mm\n.model mm modz(z=3 rz=3.0)",
              "op\nprint v(o5) v(o6)", "modok", osdi)
    check("[11] a nonzero override runs (10%3 = 1 V on o5)",
          re.search(r"v\(o5\)\s*=\s*1\b", sim) is not None
          and "OSDI(fatal)" not in sim)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
