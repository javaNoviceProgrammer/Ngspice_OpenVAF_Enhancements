#!/usr/bin/env python3
"""
verify_lrmcorner.py -- verifies Enhancement-59: LRM-corner probe follow-up,
end-to-end through the committed openvaf-r + ngspice.

A 16-corner probe battery over never-exercised Annex-C constructs found four
gaps, all fixed here:
  * event OR lists (`@(cross(...) or cross(...))`, `@(initial_step or
    timer(t))` -- LRM 5.10.3): new `or` keyword token, looped event grammar,
    an `Event::Or` HIR variant, and a `bool_or` fold of the members' fired
    flags at lowering (a raw `ior` on booleans ICEs const-eval).
  * `$realtime` (LRM 9.7.2): new builtin, lowered to the same Abstime
    parameter as `$abstime` (in the analog context they are identical).
  * net concatenation in port connections (`u1({a,c})`, LRM 6.5): the E-5
    elaboration pass expands the concat bit-by-bit onto a vectored port
    (leftmost element = port msb; a whole same-scope bus element contributes
    all its bits in ITS declared order); a bit-count/width mismatch is a
    hard error.
  * recursion diagnostics: a direct self-call used to surface as the
    puzzling "expected a function but found variable" (the function name
    resolves to its return variable); MUTUAL recursion (f1->f2->f1)
    overflowed the compiler stack in the recursive inliner. Both are now
    clean errors; the mutual one names the call cycle.

The 12 corners the battery validated as already-correct are pinned by a
self-checking bitmask module (each corner a distinct power of two, E-37
technique) plus compile-only pins.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src, osdi=None):
    """Compile with bare filenames from within this dir (keeps the .osdi's
    embedded provenance strings machine-portable)."""
    osdi = osdi or os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_deck(name, deck):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr


print("[1] event OR lists (runtime consistency vs single events)")
out, ok = compile_va("evlist_demo.va")
if not ok:
    check("evlist compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_ev.cir", """* event OR list
.control
pre_osdi evlist_demo.osdi
.endc
V1 a 0 SIN(0.5 0.5 1meg)
N1 a c mm
.model mm evdemo
Rc c 0 1m
.tran 2n 1u
.control
run
.endc
.end
""")
    mm = re.search(r"EVLIST n=\s*(-?\d+) n1=\s*(-?\d+) n2=\s*(-?\d+) m=\s*(-?\d+)", log)
    if not mm:
        check("evlist strobe", False, "no EVLIST line")
    else:
        n, n1, n2, m = map(int, mm.groups())
        check("or-list == sum of members", n == n1 + n2 and n1 >= 1 and n2 >= 1,
              f"(n={n}, n1={n1}, n2={n2})")
        check("initial_step or timer fires twice", m == 2, f"(m={m})")

print("[2] $realtime == $abstime through a transient")
out, ok = compile_va("realtime_demo.va")
if not ok:
    check("realtime compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_rt.cir", """* realtime
.control
pre_osdi realtime_demo.osdi
.endc
V1 a 0 SIN(0 1 1meg)
N1 a c mm
.model mm rtdemo
Rc c 0 1k
.tran 2n 1u
.control
run
.endc
.end
""")
    mm = re.search(r"RT dmax=([0-9eE.+-]+)", log)
    check("$realtime tracks $abstime exactly",
          mm is not None and float(mm.group(1)) == 0.0,
          f"(dmax={mm.group(1) if mm else '?'})")

print("[3] port concatenation (two concat forms, exact op current)")
out, ok = compile_va("pconcat_demo.va")
if not ok:
    check("pconcat compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_pc.cir", """* port concat
.control
pre_osdi pconcat_demo.osdi
.endc
V1 a 0 2.0
N1 a c mm
.model mm pcdemo
Rc c 0 1k
.save i(V1)
.op
.control
run
set numdgt=12
print i(V1)
.endc
.end
""")
    mm = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", log)
    # two parallel 1k concat paths (500) + Rc (1k): I = 2/1.5k
    want = -2.0 / 1.5e3
    got = float(mm.group(1)) if mm else float("nan")
    check("I == 2V/1.5k through both concat paths",
          mm is not None and abs(got - want) < 1e-9, f"(I={got:.9g})")

print("[4] recursion diagnostics (clean errors, no crash/hang)")
out, made = compile_va("_rec_direct.va")
check("direct self-call is a clear error",
      not made and "cannot call itself" in out)
out, made = compile_va("_rec_mutual.va")
check("mutual recursion is a clear error (was a stack overflow)",
      not made and "cannot call itself" in out and "f1 -> f2 -> f1" in out)

print("[5] concat width mismatch is a hard error")
out, made = compile_va("_pc_bad.va")
check("2 nets onto a 3-bit port rejected",
      not made and "3 bits wide" in out)

print("[6] corner regression pin (bitmask module, expected score 255)")
out, ok = compile_va("lrmpin_demo.va")
if not ok:
    check("lrmpin compile", False, out.splitlines()[0] if out else "")
else:
    log = run_deck("_pin.cir", """* lrm corner pin
.control
pre_osdi lrmpin_demo.osdi
.endc
V1 a 0 DC 1
NX out a c mm m=8
.model mm lrmpin r=2e3
Rc c 0 1k
Rout out 0 1G
.op
.control
run
set numdgt=12
print v(out)
.endc
.end
""")
    mm = re.search(r"v\(out\)\s*=\s*([0-9.eE+-]+)", log)
    got = float(mm.group(1)) if mm else float("nan")
    check("all 8 pinned corners intact", mm is not None and abs(got - 255.0) < 1e-6,
          f"(score={got:g})")

print("[7] compile-only pins (gnd branch, ddx-flow, above-DC, laplace, int fn outputs)")
out, ok = compile_va("_pin_compile.va")
check("compile pins build", ok and "error" not in out.lower())

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
