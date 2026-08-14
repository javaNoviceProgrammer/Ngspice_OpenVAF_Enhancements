#!/usr/bin/env python3
"""Enhancement-457: `'{ n{expr} }` -- replication inside an assignment pattern.

The LRM uses it in its own initializer examples, commenting that "all elements
are initialized to 0.0 using an assignment pattern and replication operator":

    real distort[0:2][0:2] = '{ 3{ '{3{0.0}}}};

Every such form was rejected at PARSE time -- "unexpected token '{'; expected
','" -- because the pattern parser read a plain comma-separated list, took the
count as an element and met `{` where it wanted a separator. The replication that
always worked, `{4{0}}`, is the CONCATENATION operator: a different construct one
apostrophe away, which LRM 4.2.13 explicitly warns is easily confused with this
one.

Three places walked a `'{...}` literal -- the leaf COUNT checked against the
declared size, and the two per-element extractors (array variables, array
parameters) -- and each counted a replication as ONE leaf. They now share a
single walker, so the count and the elements cannot disagree: a pattern that
expanded to the right length but the wrong contents would pass a size check and
still be wrong, which is why every array here carries distinct, checkable values
rather than a single repeated 0.0.

A count that will not fold, is negative, or is implausibly large leaves the
element unexpanded, so it reads as one leaf and the ordinary length-mismatch
diagnostic reports it -- never a silently mis-sized array.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
WORK = tempfile.gettempdir()
OSDI = os.path.join(WORK, "_pr.osdi")
H = '`include "disciplines.vams"\n'
M = "module m(a,b); inout a,b; electrical a,b;\n"
T = " analog I(a,b) <+ V(a,b)*1e-3;\nendmodule\n"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(text, tag):
    src = os.path.join(WORK, f"_pr_{tag}.va")
    with open(src, "w") as f:
        f.write(text)
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(WORK, f"_pr_{tag}.osdi")],
                       capture_output=True, text=True, timeout=300, cwd=WORK,
                       stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr)


def expect(label, decl, accept):
    rc, out = compile_src(H + M + decl + T, re.sub(r"\W", "", label)[:12])
    ok = (rc == 0) if accept else (rc != 0)
    crashed = rc == 101 or "has crashed" in out
    first = [l for l in out.splitlines() if "error" in l.lower()]
    check(label, ok and not crashed, (first[0][:60] if first and not ok else f"rc={rc}") if not ok else "")


print("Enhancement-457: replication inside an assignment pattern\n")

print("the LRM's own initializer examples compile")
expect("[E-457] real distort[0:2][0:2] = '{ 3{ '{3{0.0}}}}",
       " real distort[0:2][0:2] = '{ 3{ '{3{0.0}}}};\n", True)
expect("[E-457] string flags[0:2][0:2] = '{ 3{ '{3{\" \"}}}}",
       " string flags[0:2][0:2] = '{ 3{ '{3{\" \"}}}};\n", True)

print("\nthe ordinary forms")
for label, decl in [
    ("'{4{0.0}} into a [0:3] parameter", " parameter real p[0:3] = '{4{0.0}};\n"),
    ("'{ 4{0} } with spaces", " parameter real p[0:3] = '{ 4{0} };\n"),
    ("an integer array '{4{7}}", " parameter integer p[0:3] = '{4{7}};\n"),
    ("literals either side: '{1.0, 2{3.0}, 4.0}", " parameter real p[0:3] = '{1.0, 2{3.0}, 4.0};\n"),
    ("a replication of two elements: '{2{1.0,2.0}}", " parameter real p[0:3] = '{2{1.0,2.0}};\n"),
    ("an array VARIABLE initializer '{4{1.5}}", " real r[0:3] = '{4{1.5}};\n"),
    ("a string array '{3{\"x\"}}", " parameter string p[0:2] = '{3{\"x\"}};\n"),
]:
    expect(f"[E-457] {label}", decl, True)

print("\nthe existing spellings are untouched (controls)")
for label, decl in [
    ("a spelled-out pattern", " parameter real p[0:3] = '{0.0,0.0,0.0,0.0};\n"),
    ("a nested 2-D pattern", " parameter real c[0:2][0:2] = "
     "'{'{0.0,0.1,0.1},'{0.1,0.0,0.1},'{0.1,0.1,0.0}};\n"),
    ("a single-element pattern", " parameter real p[0:0] = '{1.0};\n"),
]:
    expect(f"[E-457] {label}", decl, True)
rc, out = compile_src(
    H + M + ' string s;\n analog begin s = {4{"a"}}; I(a,b) <+ V(a,b)*1e-3; end\nendmodule\n', "cc")
check("[E-457] the `{n{...}}` CONCATENATION operator still works", rc == 0, f"rc={rc}")

print("\na wrong or unusable count is still reported, never silently mis-sized")
for label, decl in [
    ("too few: '{3{0.0}} into [0:3]", " parameter real p[0:3] = '{3{0.0}};\n"),
    ("too many: '{5{0.0}} into [0:3]", " parameter real p[0:3] = '{5{0.0}};\n"),
    ("a zero count", " parameter real p[0:3] = '{0{0.0}};\n"),
    ("a negative count", " parameter real p[0:3] = '{-1{0.0}};\n"),
    ("an implausibly large count", " parameter real p[0:3] = '{99999999{0.0}};\n"),
    ("a non-constant count", " parameter integer n = 4;\n parameter real p[0:3] = '{n{0.0}};\n"),
]:
    expect(f"[E-457] {label} is refused", decl, False)

# ------------------------------------------------------------- the VALUES ---
print("\nthe expansion carries the right values, not merely the right length")
r = subprocess.run([OPENVAF, os.path.join(HERE, "patternrep.va"), "-o", OSDI],
                   capture_output=True, text=True, timeout=600, cwd=HERE)
if check("[E-457] patternrep.va compiles", r.returncode == 0 and os.path.isfile(OSDI),
         (r.stdout + r.stderr).strip().splitlines()[0][:60] if r.returncode else ""):
    deck = os.path.join(WORK, "_pr.cir")
    with open(deck, "w") as f:
        f.write(f"""* patternrep
V1 in 0 dc 1
Rs in mid 1k
N1 mid 0 mm
.model mm patternrep
.control
pre_osdi {OSDI}
op
print @n1[q] @n1[mx] @n1[p] @n1[g] @n1[v]
.endc
.end
""")
    out = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True,
                         timeout=300, stdin=subprocess.DEVNULL)
    txt = out.stdout + out.stderr

    # NOTE: the opvar is `mx`, not `m` -- every ngspice instance already has an
    # `m` MULTIPLIER parameter, so `@n1[m]` reads that (1.0) instead of the
    # model variable, and this check silently measured the multiplier.
    def rd(n):
        mm = re.search(rf"@n1\[{n}\]\s*=\s*(-?[\d.eE+-]+)", txt)
        return float(mm.group(1)) if mm else None

    for name, want, note in [
        ("q", 5.0, "'{4{2.5}}      -> quad[0]+quad[3]"),
        ("mx", 6.0, "'{1.0,2{3.0},4.0} -> mixed[1]+mixed[2]"),
        ("p", 6.0, "'{2{1.0,2.0}}  -> all four summed"),
        ("g", 1.0, "'{3{'{3{0.5}}}} -> grid[0][0]+grid[2][2]"),
        ("v", 3.0, "'{4{1.5}}      -> vals[0]+vals[3]"),
    ]:
        got = rd(name)
        check(f"[E-457] {note} = {want}", got is not None and abs(got - want) < 1e-12, f"got {got}")

for junk in os.listdir(WORK):
    if junk.startswith("_pr"):
        try:
            os.remove(os.path.join(WORK, junk))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
