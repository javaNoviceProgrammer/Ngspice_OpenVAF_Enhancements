#!/usr/bin/env python3
"""Enhancement-517: data types and parameters, audited against Accellera
VAMS-2023 clauses 3.1-3.5, then fixed.

What this suite pins, each against the quoted clause:

  * 3.2.1 -- "Units and descriptions specified for block-level variables
    shall be ignored by the simulator." A desc variable inside a named block
    was exported as an OSDI operating-point variable under its bare name
    (two blocks with the same-named variable produced duplicate opvars).
    Module-scope opvars still work; block-scope ones are gone.
  * 3.3 -- "A string literal can be assigned to a string or an integral
    type. If their size differs, the literal is right justified and either
    truncated on the left or zero filled on the left." Was a hard type
    error; now 'A'=65, 'AB'=0x4142, 'ABCDE' keeps its last four bytes. A
    string VALUE still cannot be assigned to an integral type.
  * 3.4.4/3.4.8 -- a whole array parameter is overridable at instantiation
    with an assignment pattern, 1-D and multi-dimensional, "the sizes shall
    match" (wrong size and scalar-to-array are targeted errors). Was
    rejected as "names no parameter".
  * 3.4.7 -- "it shall be an error to specify an override for a parameter by
    its original name and one or more aliases". ngspice warned and let one
    value silently win; both the .model card and the instance line are
    errors now. And "the alias_identifier shall not occur anywhere else in
    the module" -- referencing the alias in module equations is a targeted
    compile error (was silently resolved to the target's value).
  * 3.4.1 (documented deviation) -- an untyped parameter's type freezes from
    its default; a non-integral netlist value rounded into an integer
    parameter now draws a warning on both the .model and the instance paths.
  * 2.7 follow-up -- backslash-newline inside a string literal is a line
    continuation contributing NOTHING (BSIM4 splits $strobe messages this
    way; the old unescaper kept the newline, cutting messages mid-sentence).
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
        if junk.startswith("_ld_"):
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
    osdi = os.path.join(HERE, f"_ld_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_ld_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_ld_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmdata\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
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

# ---- the committed module: string-literal ints, opvar scope, continuation --
print("lrmdata.va (run-time values):")
rc, out, osdi = compile_file("lrmdata.va")
check("[1] lrmdata.va compiles", rc == 0,
      out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmdata", "op\n"
              "print @n1[i0] @n1[i1] @n1[i2] @n1[i3] @n1[gmod]\n"
              "print @n1[gblk]", "main", osdi)
    for name, want, why in [
        ("i0", 65, "decl-init integer i0 = \"A\" (LRM 3.3)"),
        ("i1", 65, "'A' packs to 65"),
        ("i2", 16706, "'AB' packs to 0x4142"),
        ("i3", 1111704645, "'ABCDE' truncated on the left to 0x42434445"),
        ("gmod", 3, "module-scope desc variable is an opvar (3.2.1)"),
    ]:
        got = opvar(sim, name)
        check(f"[2] {why} = {want}", got == want, f"{got}")
    check("[3] block-scope desc variable is NOT an opvar (3.2.1)",
          opvar(sim, "gblk") is None and "no such parameter gblk" in sim)
    check("[4] backslash-newline is a line continuation (one joined line)",
          "part one and part two as ONE line" in sim)
    for tag, want, why in [
        ("REPVAR", "HiHiHi", "nonconstant count {cnt{\"Hi\"}} (LRM 3.3's own example)"),
        ("REPPAR", "cdcdcd", "parameter count {rp{\"cd\"}}"),
        ("REPZERO", "", "zero count yields the empty string"),
        ("REPUNIT", "ab-ab-", "multi-operand unit {cnt-1{\"ab\",\"-\"}}"),
    ]:
        check(f"[4b] string replication, {why}", f"{tag}=[{want}]" in sim,
              next((l for l in sim.splitlines() if tag in l), "no line"))

# ---- whole-array override at instantiation (3.4.4 / 3.4.8) -----------------
print("\nwhole-array parameter overrides at instantiation:")
rc, out, osdi = compile_file("lrmdata_hier.va")
check("[5] lrmdata_hier.va compiles (1-D and multi-D array pattern overrides)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmdata_top",
              "op\nprint i(V1)", "h1", osdi)
    m = re.search(r"i\(v1\)\s*=\s*([-+0-9.eE]+)", sim, re.I)
    got = float(m.group(1)) if m else None
    check("[6] 1-D override '{9,8,7} lands element-wise (i = -987 A)",
          got is not None and abs(got + 987.0) < 1e-6, f"{got}")
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmdata_topmd",
              "op\nprint i(V1)", "h2", osdi)
    m = re.search(r"i\(v1\)\s*=\s*([-+0-9.eE]+)", sim, re.I)
    got = float(m.group(1)) if m else None
    check("[7] multi-D override '{'{9,8,7},'{6,5,4}} lands (i = -976400 A)",
          got is not None and abs(got + 976400.0) < 1e-3, f"{got}")

rc, out, _ = compile_src(HDR + """
module szbad(a,b); inout a,b; electrical a,b;
  parameter real cf[0:2] = '{1.0,2.0,3.0};
  analog I(a,b) <+ V(a,b)*cf[0];
endmodule
module szbad_top(a,b); inout a,b; electrical a,b;
  szbad #(.cf('{9.0, 8.0})) l1(a,b);
endmodule
""", "szbad")
check("[8] wrong element count is an error naming both sizes (3.4.4)",
      rc != 0 and "supplies 2 element(s)" in out and "has 3" in out)

rc, out, _ = compile_src(HDR + """
module scbad(a,b); inout a,b; electrical a,b;
  parameter real cf[0:2] = '{1.0,2.0,3.0};
  analog I(a,b) <+ V(a,b)*cf[0];
endmodule
module scbad_top(a,b); inout a,b; electrical a,b;
  scbad #(.cf(3.14)) l1(a,b);
endmodule
""", "scbad")
check("[9] a scalar override of an array parameter asks for a pattern",
      rc != 0 and "assignment pattern" in out)

# ---- aliasparam rules (3.4.7) ----------------------------------------------
print("\naliasparam (LRM 3.4.7):")
ALIAS = HDR + """
module ldalias(a,b); inout a,b; electrical a,b;
  parameter real dtemp = 0.0;
  aliasparam trise = dtemp;
  analog I(a,b) <+ V(a,b)*(1.0 + dtemp)*1e-3;
endmodule
"""
rc, out, osdi = compile_src(ALIAS, "alias")
check("[10] aliasparam module compiles", rc == 0)
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm ldalias(trise=5 dtemp=5)",
              "op\nprint i(V1)", "al1", osdi)
    check("[11] original name AND alias on one .model card is an ERROR",
          "same parameter (aliasparam)" in sim and "LRM 3.4.7" in sim
          and re.search(r"i\(v1\)", sim, re.I) is None)

rc, out, _ = compile_src(HDR + """
module aluse(a,b); inout a,b; electrical a,b;
  parameter real dtemp = 0.0;
  aliasparam trise = dtemp;
  analog I(a,b) <+ V(a,b)*(1.0 + trise);
endmodule
""", "aluse")
check("[12] referencing the alias inside the module body is a compile error",
      rc != 0 and "alias" in out and "3.4.7" in out)

# ---- untyped-parameter round warning (3.4.1 deviation, made audible) -------
print("\nlossy integer rounding warns (both netlist paths):")
rc, out, osdi = compile_file("lrmdata.va")
if rc == 0:
    sim = run("N1 a 0 mm sel=2.5\nV1 a 0 DC 1\n.model mm lrmdata(ip=2.5)",
              "op\nprint i(V1)", "round", osdi)
    check("[13] .model card: non-integral value into integer param warns",
          re.search(r"\.model mm: parameter \(ip\).*rounded", sim) is not None)
    check("[14] instance line: non-integral value into integer param warns",
          re.search(r"n1: parameter \(sel\).*rounded", sim) is not None)
    sim = run("N1 a 0 mm sel=2\nV1 a 0 DC 1\n.model mm lrmdata(ip=2)",
              "op\nprint i(V1)", "round2", osdi)
    check("[15] integral values draw no rounding warning",
          "rounded to the nearest integer" not in sim)

# ---- still-refused forms ---------------------------------------------------
print("\nstill refused, as the LRM requires:")
rc, out, _ = compile_src(HDR + """
module sv(a,b); inout a,b; electrical a,b;
  string s; integer i;
  analog begin s = "A"; i = s; I(a,b) <+ V(a,b)*i; end
endmodule
""", "strval")
check("[16] a string VALUE assigned to an integer stays a type error (3.3)",
      rc != 0 and ("mismatch" in out or "string" in out))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
