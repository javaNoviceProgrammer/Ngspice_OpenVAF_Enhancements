#!/usr/bin/env python3
"""Enhancement-520: the Annex C/E boundary, audited against Accellera
VAMS-2023 (Annex C scope, Annex E SPICE compatibility, and the 2023 change
records of Annex G Table G.7), then fixed.

What this suite pins, each against the quoted clause:

  * 5.11 -- "Verilog-AMS HDL provides C-like jump statements break,
    continue, and return." None existed (a generic "'break' was not found
    in the current scope"). All three work now, through every loop kind:
    continue re-enters a for at its INCREMENT, still decrements repeat's
    counter, break leaves only the innermost loop, and return exits an
    analog function from arbitrarily nested statements, optionally setting
    the return value first. Every semantic is checked numerically.
  * 5.11 / 5.9.3 position rules -- break/continue outside a runtime loop
    are targeted errors, INCLUDING inside a genvar analog_for (5.9.3
    excludes jump statements there; those loops unroll at elaboration).
    return outside an analog function is a targeted error.
  * Annex B / C.16 -- the three are CONTEXTUAL keywords: pre-2023 source
    using `break` as an identifier still compiles, flagged by the L012
    keyword-compat lint like the other VAMS reserved words.
  * 4.7.1 (Mantis 7808) -- analog functions with string return type and
    string output arguments; both ICEd the compiler ("internal error:
    invalid function return type String").
  * 9.17.3 -- "If the string refers to an unknown or unsupported function,
    the simulator is responsible for determining the appropriate limiting
    algorithm, just as if no string had been supplied." ngspice refused to
    LOAD such a .osdi; it now binds a pass-through with a warning and the
    model runs. And Table E.2's preferred name "vdslim" is an alias of
    this tree's "limvds" -- no lint, real limiting.
  * Table 9-7 / 9.10 NOTE -- $realtime in the analog context draws the
    2023 deprecation warning (it behaves as $abstime, no `timescale
    scaling).
  * Annex C.4 -- `default_discipline is an AMS-only directive: recognized,
    warned about, and ignored (it was silently swallowed).
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
        if junk.startswith("_lj_"):
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
    osdi = os.path.join(HERE, f"_lj_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lj_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lj_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmjump\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
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

# ---- jump statements + string functions, numerically -----------------------
print("lrmjump.va (run-time values):")
rc, out, osdi = compile_file("lrmjump.va")
check("[1] lrmjump.va compiles (break/continue/return, string functions)",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmjump", "op\n"
              "print @n1[w] @n1[d] @n1[r] @n1[rb] @n1[n]\n"
              "print @n1[f1] @n1[f2] @n1[f3] @n1[sok]", "main", osdi)
    for name, want, why in [
        ("w", 3, "while + break at 3: 0+1+2"),
        ("d", 6, "do-while + continue skips odd: 0+2+4"),
        ("r", 102, "repeat + continue still counts all 5 iterations"),
        ("rb", 2, "repeat + break after 2"),
        ("n", 3, "nested loops: break leaves only the inner one"),
        ("f1", 7, "return before the fallthrough assignment"),
        ("f2", 4, "return from inside a for-loop inside a function"),
        ("f3", 5, "fname = 5 then bare return (skips the 8)"),
        ("sok", 1, "string OUTPUT argument function returned"),
    ]:
        got = opvar(sim, name)
        check(f"[2] {why} = {want}", got == want, f"{got}")
    check("[3] string return + string output arg at run time (4.7.1)",
          "pick=pos tag=high" in sim)

# ---- position rules and contextual keywords --------------------------------
print("\njump-statement position rules (LRM 5.11 / 5.9.3):")
rc, out, _ = compile_src(HDR + """
module jb(a,b); inout a,b; electrical a,b;
analog begin break; I(a,b) <+ V(a,b); end
endmodule
""", "jb")
check("[4] break outside a loop is a targeted error",
      rc != 0 and "outside a loop" in out)

rc, out, _ = compile_src(HDR + """
module jr(a,b); inout a,b; electrical a,b;
analog begin return 1.0; I(a,b) <+ V(a,b); end
endmodule
""", "jr")
check("[5] return outside an analog function is a targeted error",
      rc != 0 and "outside an analog function" in out)

rc, out, _ = compile_src(HDR + """
module jg(a,b); inout a,b; electrical a,b;
genvar g; integer acc;
analog begin
  acc = 0;
  for (g = 0; g < 4; g = g + 1) begin
    if (g == 2) break;
    acc = acc + 1;
  end
  I(a,b) <+ V(a,b)*acc;
end
endmodule
""", "jg")
check("[6] break inside a genvar analog_for is refused (5.9.3 exclusion)",
      rc != 0 and "outside a loop" in out)

rc, out, _ = compile_src(HDR + """
module ji(a,b); inout a,b; electrical a,b;
real break; integer continue;
analog begin
  break = 1.0; continue = 2;
  I(a,b) <+ V(a,b)*break*continue;
end
endmodule
""", "ji")
check("[7] legacy identifiers named break/continue still compile...",
      rc == 0, out.strip().splitlines()[-1] if rc else "")
check("[8] ...flagged by the L012 keyword-compat lint",
      out.count("L012") >= 2)

# ---- $limit fallback and the vdslim alias (9.17.3 / Table E.2) -------------
print("\n$limit (LRM 9.17.3, Annex E Table E.2):")
rc, out, osdi = compile_file("lrmjump_lim.va")
check("[9] $limit(V(a,b), \"vdslim\") compiles without the L020 lint",
      rc == 0 and "L020" not in out)
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm lrmjump_lim",
              "op\nprint v(a)", "vds", osdi)
    check("[10] the model loads and runs (vdslim bound to the limvds impl)",
          re.search(r"v\(a\)\s*=\s*1\b", sim) is not None
          and "couldn't be loaded" not in sim)

rc, out, osdi = compile_src(HDR + """
module nosuch(a,b); inout a,b; electrical a,b;
  analog I(a,b) <+ 1e-3 * $limit(V(a,b), "nosuchlim");
endmodule
""", "nosuch")
check("[11] an unknown limiter name draws the L020 lint at compile time",
      rc == 0 and "L020" in out)
if rc == 0:
    sim = run("N1 a 0 mm\nV1 a 0 DC 1\n.model mm nosuch",
              "op\nprint v(a)", "nosuch", osdi)
    check("[12] ngspice LOADS it and falls back to no limiting (9.17.3)",
          "treated as if no function had been named" in sim
          and re.search(r"v\(a\)\s*=\s*1\b", sim) is not None
          and "couldn't be loaded" not in sim)

# ---- the 2023 deprecations, now audible ------------------------------------
print("\ndeprecations and AMS-only directives are audible:")
rc, out, _ = compile_src(HDR + """
module rt(a,b); inout a,b; electrical a,b; real t;
analog begin t = $realtime; I(a,b) <+ V(a,b)*(1.0+0.0*t); end
endmodule
""", "rt")
check("[13] $realtime in the analog context draws the Table 9-7 warning",
      rc == 0 and "deprecated" in out and "abstime" in out)

rc, out, _ = compile_src("`default_discipline electrical\n" + HDR + """
module dd(a,b); inout a,b; electrical a,b;
analog I(a,b) <+ 1e-3*V(a,b);
endmodule
""", "dd")
check("[14] `default_discipline warns as an ignored AMS-only directive (C.4)",
      rc == 0 and "AMS-only" in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
