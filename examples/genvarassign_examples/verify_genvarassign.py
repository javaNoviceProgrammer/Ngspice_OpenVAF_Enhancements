#!/usr/bin/env python3
"""Enhancement-638: an assignment to a genvar inside its own loop is refused
before the loop is unrolled, and the message names the mistake.

`for (i=0;i<3;i=i+1) begin i = i + 1; ... end` used to be unrolled like any
other use of `i`: the assignment became `0 = 0 + 1` in the generated copy and
the parser reported `unexpected token integer; expected ';', '@', 'begin',
...` there, once per copy, with the user's mistake never named. A nested loop
that reuses the genvar as its own loop variable got the same treatment.

Checks:
  [1]  `i = i + 1;` in a begin/end body: refused, the statement quoted, no generated-copy parse error
  [2]  `i = 7;` as the loop's single statement: refused the same way
  [3]  a nested `for (i = ...)` reusing the genvar: refused as reuse
  [4]  legal loops still compile and compute: `i == j` comparisons, `k = i`, `a[i] = i`, nested genvars
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="genvarassign_")
HDR = '`include "disciplines.vams"\n'
M = "module m(p,n); inout p,n; electrical p,n;\n"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def op(tag):
    deck = os.path.join(WORK, f"{tag}.cir")
    with open(deck, "w") as f:
        f.write(f"* genvarassign {tag}\nv1 a 0 1\nn1 a 0 mm\n.model mm m\n.control\nset noinit\npre_osdi {tag}.osdi\nop\nprint i(v1)\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", p.stdout + p.stderr, re.M)
    return float(m.group(1)) if m else None


print("Enhancement-638: an assignment to a genvar inside its own loop is refused\n")

ok, msg = compile_src(M + "genvar i; real s; analog begin s = 0; for (i=0;i<3;i=i+1) begin i = i + 1; s = s + 1; end I(p,n) <+ s*1e-3; end endmodule\n", "c1")
check("[1] `i = i + 1;` inside the body is refused, the statement quoted, the genvar's rule stated -- not the parser's `0 = 0 + 1` in a generated copy",
      (not ok) and "`i` is assigned inside its own loop body (`i = i + 1;`)" in msg
      and "takes its values from the loop header only" in msg
      and "unexpected token integer" not in msg and "__generated" not in msg, msg[-250:])

ok, msg = compile_src(M + "genvar i; real s; analog begin s = 0; for (i=0;i<3;i=i+1) i = 7; I(p,n) <+ s*1e-3; end endmodule\n", "c2")
check("[2] `i = 7;` as the loop's single statement is refused the same way",
      (not ok) and "`i` is assigned inside its own loop body (`i = 7;`)" in msg and "unexpected token" not in msg, msg[-250:])

ok, msg = compile_src(M + "genvar i; real s; analog begin s = 0; for (i=0;i<3;i=i+1) begin for (i=0;i<2;i=i+1) s = s + 1; end I(p,n) <+ s*1e-3; end endmodule\n", "c3")
check("[3] a nested `for (i = ...)` reusing the genvar is refused as reuse, with the advice to nest with a different genvar",
      (not ok) and "a loop nested inside it uses `i` as its own loop variable" in msg and "nest with a different genvar" in msg, msg[-250:])

r = {}
ok, msg = compile_src(M + "genvar i, j; real s; analog begin s = 0; for (i=0;i<3;i=i+1) for (j=0;j<=i;j=j+1) s = s + (i == j ? 1 : 0); I(p,n) <+ s*1e-3; end endmodule\n", "c4a")
r["i == j, nested genvars"] = ok and abs(op("c4a") + 3e-3) < 1e-9
ok, msg = compile_src(M + "genvar i; real s; integer k; analog begin s = 0; for (i=0;i<3;i=i+1) begin k = i; s = s + k; if (i == 1) s = s + 1; end I(p,n) <+ s*1e-3; end endmodule\n", "c4b")
r["k = i"] = ok and abs(op("c4b") + 4e-3) < 1e-9
ok, msg = compile_src(M + "genvar i; real s, a[0:2]; analog begin s = 0; for (i=0;i<3;i=i+1) begin a[i] = i; s = s + a[i]; end I(p,n) <+ s*1e-3; end endmodule\n", "c4c")
r["a[i] = i"] = ok and abs(op("c4c") + 3e-3) < 1e-9
check("[4] legal loops compile and compute: `i == j` over nested genvars (3), `k = i` with a comparison (4), `a[i] = i` (3)",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
