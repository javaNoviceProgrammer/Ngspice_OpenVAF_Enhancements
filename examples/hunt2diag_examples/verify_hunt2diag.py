#!/usr/bin/env python3
"""Enhancement-588: five compiler-side findings of the 2026-09-07 hunt, resolved.

  F5  `I(<a[1]>)`, a port-branch probe on a bus element, was a parse error
      ("expected '>'"); it now names the bus element like every other
      bit-select, in expressions and in `branch (<a[1]>) b;` declarations.
  F6  a module parameter named `m`, `temp`, `dtemp` or `dt` took over
      ngspice's reserved instance parameter of that name silently; lint L029
      (`reserved_parameter_name`, warn) now says so, case-insensitively.
  F7a a discrete-set range read "range from 1 from 2 from 4" in ngspice's
      out-of-bounds message; the bounds text now keeps the set: "from {1, 2, 4}".
  F7f `noise_table` with two entries at the same frequency compiled and held
      the first power everywhere; it is refused. An unsorted table stays legal.
  F7h `case (s) endcase` with no items compiled; it is a syntax error.

Checks (compile-only unless noted):
  [1] I(<a[1]>) reads the element's current in a running deck; a branch on a
      bus element compiles; an out-of-range element is still refused
  [2] L029 for m, temp, dtemp, dt and for `M`; not for mm, temperature, dtemp2
  [3] the range text: "from {1, 2, 4}" and "from {0.5, 1.0, 2.0}" in the ngspice
      message; an interval range is unchanged "(0:inf)"
  [4] a duplicated noise_table frequency is an error naming the frequency; an
      unsorted table and noise_table_log are accepted; the odd-length and
      negative-power errors of E-396 still fire
  [5] an empty case is a syntax error at the endcase; default-first, nested and
      single-item cases compile
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
WORK = tempfile.mkdtemp(prefix="hunt2diag_")
HDR = '`include "disciplines.vams"\n'


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


def run(deck, ctl, osdi, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hunt2diag {tag}\n{deck}\n.control\nset noinit\npre_osdi {osdi}.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


print("Enhancement-588: hunt findings F5, F6, F7a, F7f, F7h\n")

# ------------------------------------------------------------- [1] ---
ok, msg = compile_src("""module bus(a, c);
  inout [0:2] a; inout c; electrical [0:2] a; electrical c;
  branch (<a[2]>) pb2;
  (* desc="I(<a[1]>)" *) real o_ip1;
  (* desc="I(pb2)" *) real o_ip2;
  genvar i;
  analog begin
    for (i = 0; i <= 2; i = i + 1) I(a[i], c) <+ 1e-3 * (i + 1) * V(a[i], c);
    o_ip1 = I(<a[1]>);
    o_ip2 = I(pb2);
  end
endmodule
""", "bus")
check("[1] I(<a[1]>) and branch (<a[2]>) compile", ok, msg.strip().splitlines()[0] if not ok else "")
if ok:
    out = run("V0 x0 0 dc 1\nV1 x1 0 dc 2\nV2 x2 0 dc 3\nN1 x0 x1 x2 0 mm\n.model mm bus",
              'op\necho "R: ip1=$&@n1[o_ip1] ip2=$&@n1[o_ip2]"', "bus", "busrun")
    m = re.search(r"(?m)^R: (.*)$", out)
    check("[1] the port probes read the element currents: I(<a[1]>) = 2 mS x 2 V = 4 mA, I(<a[2]>) = 9 mA",
          m is not None and m.group(1) == "ip1=0.004 ip2=0.009", m.group(1) if m else out[-200:])
ok, msg = compile_src("""module bus2(a, c);
  inout [0:1] a; inout c; electrical [0:1] a; electrical c;
  analog begin I(a[0], c) <+ V(a[0], c); I(a[1], c) <+ V(a[1], c) + 0.0 * I(<a[5]>); end
endmodule
""", "bus2")
check("[1] an out-of-range element <a[5]> is still refused", not ok and ("a[5]" in msg or "not found" in msg or "range" in msg),
      msg.strip().splitlines()[0] if msg.strip() else "")

# ------------------------------------------------------------- [2] ---
def lint_names(src, tag):
    ok, msg = compile_src(src, tag)
    return ok, re.findall(r"warning\[L029\]: parameter name '(\w+)'", msg)
ok, names = lint_names("""module rp(p, n); inout p, n; electrical p, n;
  (* type="instance" *) parameter real m = 1.0;
  (* type="instance" *) parameter real temp = 27.0;
  parameter real dtemp = 0.0;
  parameter real dt = 0.0;
  parameter real M2 = 1.0;
  analog I(p,n) <+ (m + temp + dtemp + dt + M2) * 0.0 + V(p,n);
endmodule
""", "rp")
check("[2] L029 names m, temp, dtemp and dt (warn; the module still compiles)",
      ok and names == ["m", "temp", "dtemp", "dt"], f"{ok} {names}")
ok, names = lint_names("""module rp2(p, n); inout p, n; electrical p, n;
  parameter real M = 2.0;
  parameter real mm = 1.0;
  parameter real temperature = 300.0;
  parameter real dtemp2 = 0.0;
  analog I(p,n) <+ (M + mm + temperature + dtemp2) * 0.0 + V(p,n);
endmodule
""", "rp2")
check("[2] case-insensitive: `M` is named; mm, temperature, dtemp2 are not",
      ok and names == ["M"], f"{ok} {names}")

# ------------------------------------------------------------- [3] ---
ok, msg = compile_src("""module ds(p, n); inout p, n; electrical p, n;
  parameter integer n1 = 1 from {1, 2, 4};
  parameter real rset = 1.0 from {0.5, 1.0, 2.0};
  parameter real g = 1e-3 from (0:inf);
  analog I(p,n) <+ g * n1 * rset * V(p,n);
endmodule
""", "ds")
check("[3] the discrete-set module compiles", ok)
if ok:
    o1 = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm ds n1=3", "op", "ds", "ds1")
    o2 = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm ds rset=1.5", "op", "ds", "ds2")
    o3 = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm ds g=0", "op", "ds", "ds3")
    # Enhancement-601: an integer's refusal shows its value like a real's
    check("[3] the out-of-bounds message keeps the set: '(value 3; range from {1, 2, 4})'",
          "Parameter n1 of 'mm' is out of bounds (value 3; range from {1, 2, 4})!" in o1,
          [l for l in o1.splitlines() if "out of bounds" in l][:1])
    check("[3] a real set: '(value 1.5; range from {0.5, 1.0, 2.0})'",
          "out of bounds (value 1.5; range from {0.5, 1.0, 2.0})!" in o2,
          [l for l in o2.splitlines() if "out of bounds" in l][:1])
    check("[3] an interval range is unchanged: '(value 0; range from (0:inf))'",
          "out of bounds (value 0; range from (0:inf))!" in o3,
          [l for l in o3.splitlines() if "out of bounds" in l][:1])

# ------------------------------------------------------------- [4] ---
def nt(table, fn="noise_table"):
    return f"""module nt(p, n); inout p, n; electrical p, n;
  analog begin I(p,n) <+ V(p,n)/1e3; I(p,n) <+ {fn}('{{{table}}}, "t"); end
endmodule
"""
ok, msg = compile_src(nt("1.0, 4e-18, 1.0, 1e-18"), "ntdup")
check("[4] a duplicated frequency is refused naming it",
      not ok and "lists the frequency 1 twice" in msg, msg.strip().splitlines()[0] if msg.strip() else "")
ok, msg = compile_src(nt("100.0, 4e-18, 1.0, 4e-18, 10000.0, 1e-18"), "ntuns")
check("[4] an unsorted table is accepted (the runtime orders it)", ok, msg.strip().splitlines()[0] if not ok else "")
ok, msg = compile_src(nt("1.0, 4e-18, 10.0, 4e-18, 10.0, 1e-18", "noise_table_log"), "ntlog")
check("[4] noise_table_log with a duplicated frequency is refused under its own name",
      not ok and "noise_table_log: table lists the frequency 10 twice" in msg, msg.strip().splitlines()[0] if msg.strip() else "")
ok, msg = compile_src(nt("1.0, 4e-18, 100.0"), "ntodd")
check("[4] E-396's odd-length error still fires", not ok and "PAIRS" in msg)

# ------------------------------------------------------------- [5] ---
ok, msg = compile_src("""module ec(p, n); inout p, n; electrical p, n; parameter integer s = 1; integer o;
  analog begin case (s) endcase I(p,n) <+ V(p,n); end
endmodule
""", "ec")
check("[5] an empty case is a syntax error at its endcase",
      not ok and "case statement has no items" in msg and "no case item before this `endcase`" in msg,
      msg.strip().splitlines()[0] if msg.strip() else "")
ok, msg = compile_src("""module fc(p, n); inout p, n; electrical p, n; parameter integer s = 2; integer a, b, c;
  analog begin
    case (s) default: a = 0; 2: a = 2; endcase
    case (s) 2: case (s > 1) 1: b = 21; default: b = 20; endcase default: b = 0; endcase
    case (s) 2: c = 1; endcase
    I(p,n) <+ (a + b + c) * 0.0 + V(p,n);
  end
endmodule
""", "fc")
check("[5] default-first, nested and single-item cases compile", ok, msg.strip().splitlines()[0] if not ok else "")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
