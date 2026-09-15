#!/usr/bin/env python3
"""Enhancement-636: an out-of-range array index at run time is reported.

A dynamic index -- a parameter, or a value computed while solving -- outside
the array's declared range read the first element and dropped the write with
nothing said (E-489 chose the first element over NaN so that no index can
read out of bounds and a transient mid-solve value cannot poison the
iteration; that stands). Now every dimension is checked and an out-of-range
access is reported through the deferred $warning path, once per accepted
point, naming the array, the index and what the access does instead. A
constant index is refused at compile time as before, worded for an array
rather than a bus.

Checks:
  [1]  a[k] on a[0:2] with k = 3, -1, 100: reads a[0], warned with the index
  [2]  a[k] = v with k out of range: dropped, warned as dropped
  [3]  in range: no warning
  [4]  2-D: a[1][-1] on a[0:1][0:1] reads a[0][0] (it used to fold to a[0][1]), warned with both indices
  [5]  a parameter array (E-405) read out of range: warned
  [6]  a node-dependent index in a transient: warned at the accepted points where it is out of range, silent where it is in range
  [7]  an access inside an event block prints immediately
  [8]  (compiler) a literal index out of range: "array index out of range", the array named; a 2-D one names the dimension; a bus keeps "bus bit-select"
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
WORK = tempfile.mkdtemp(prefix="arrayrange_")
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


def run(deck, ctl, tag, pre=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* arrayrange {tag}\n{deck}\n.control\nset noinit\n{pre}{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def current(out):
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", out, re.M)
    return float(m.group(1)) if m else None


def warnings(out):
    return [l for l in out.splitlines() if "OSDI(warn)" in l and "out of range" in l]


ok, msg = compile_src("""module rd(p,n); inout p,n; electrical p,n;
  parameter integer k = 1;
  real a[0:2];
  analog begin
    a[0] = 10; a[1] = 20; a[2] = 30;
    I(p,n) <+ V(p,n)*a[k]*1e-3;
  end
endmodule
module wr(p,n); inout p,n; electrical p,n;
  parameter integer k = 1;
  real a[0:2];
  analog begin
    a[0] = 10; a[1] = 20; a[2] = 30;
    a[k] = 100;
    I(p,n) <+ V(p,n)*(a[0]+a[1]+a[2])*1e-3;
  end
endmodule
module md(p,n); inout p,n; electrical p,n;
  parameter integer i = 0; parameter integer j = 0;
  real a[0:1][0:1];
  analog begin
    a[0][0] = 1; a[0][1] = 2; a[1][0] = 3; a[1][1] = 4;
    I(p,n) <+ V(p,n)*a[i][j]*1e-3;
  end
endmodule
module pa(p,n); inout p,n; electrical p,n;
  parameter real a[0:2] = '{10, 20, 30};
  parameter integer k = 1;
  analog I(p,n) <+ V(p,n)*a[k]*1e-3;
endmodule
module nd(p,n); inout p,n; electrical p,n;
  real a[0:2]; integer j;
  analog begin
    a[0] = 1; a[1] = 2; a[2] = 3;
    j = (V(p,n) > 0.5) ? 7 : 1;
    I(p,n) <+ V(p,n)*a[j]*1e-3;
  end
endmodule
module ev(p,n); inout p,n; electrical p,n;
  parameter integer k = 5;
  real a[0:2]; real x;
  analog begin
    a[0] = 1; a[1] = 2; a[2] = 3;
    @(initial_step) x = a[k];
    I(p,n) <+ V(p,n)*1e-3*(1 + x);
  end
endmodule
""", "d")
check("the models compile", ok, msg[-300:])
PRE = "pre_osdi d.osdi\n"
print("Enhancement-636: an out-of-range array index at run time is reported\n")


def op(model, card, tag):
    return run(f"v1 a 0 1\nn1 a 0 mm\n.model mm {model} {card}", "op\nprint i(v1)", tag, PRE)


# ---------------------------------------------------------------- 1 ---
r = {}
for kv in ["k=3", "k=-1", "k=100"]:
    out = op("rd", kv, "c1_" + kv[2:].replace("-", "m"))
    w = warnings(out)
    idx = kv[2:]
    r[kv] = (current(out) is not None and abs(current(out) + 10e-3) < 1e-8
             and len(w) >= 1
             and all(f"index [{idx}] of `a`, declared [0:2], is out of range; the read returns a[0]" in l for l in w))
check("[1] a[k] on a[0:2] with k = 3, -1, 100 reads a[0] (10 mA) and is warned with the index, the declaration and what is read",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 2 ---
out = op("wr", "k=3", "c2")
w = warnings(out)
check("[2] a[k] = 100 with k = 3 is dropped (the sum stays 60 mA) and warned as dropped",
      current(out) is not None and abs(current(out) + 60e-3) < 1e-8 and len(w) >= 1
      and all("index [3] of `a`, declared [0:2], is out of range; the assignment is dropped" in l for l in w),
      "; ".join(w[:1]) + f" i={current(out)}")

# ---------------------------------------------------------------- 3 ---
out1 = op("rd", "k=2", "c3a")
out2 = op("wr", "k=1", "c3b")
check("[3] in range: a[2] reads 30 mA, a[1] = 100 gives 140 mA, no warning",
      abs(current(out1) + 30e-3) < 1e-8 and abs(current(out2) + 140e-3) < 1e-8
      and not warnings(out1) and not warnings(out2), f"{current(out1)} {current(out2)}")

# ---------------------------------------------------------------- 4 ---
out = op("md", "i=1 j=-1", "c4a")
w = warnings(out)
ok4a = abs(current(out) + 1e-3) < 1e-9 and w and all(
    "index [1][-1] of `a`, declared [0:1] [0:1], is out of range; the read returns a[0][0]" in l for l in w)
out = op("md", "i=1 j=1", "c4b")
ok4b = abs(current(out) + 4e-3) < 1e-9 and not warnings(out)
check("[4] 2-D: a[1][-1] on a[0:1][0:1] reads a[0][0] (1 mA; it used to fold to a[0][1]) and is warned with both indices; a[1][1] is 4 mA, silent",
      ok4a and ok4b, f"{w[:1]}")

# ---------------------------------------------------------------- 5 ---
out = op("pa", "k=7", "c5")
w = warnings(out)
check("[5] a parameter array read out of range (E-405) reads a[0] and is warned",
      abs(current(out) + 10e-3) < 1e-8 and w and all("index [7] of `a`, declared [0:2]" in l for l in w), f"{w[:1]}")

# ---------------------------------------------------------------- 6 ---
out = run("v1 a 0 sin(0.5 0.5 1k)\nn1 a 0 mm\n.model mm nd", "tran 10u 1m\nprint length(time)", "c6", PRE)
w = warnings(out)
m = re.search(r"length\(time\)\s*=\s*(\S+)", out)
npts = float(m.group(1)) if m else 0
times = [float(re.search(r"at t = (\S+)\)", l).group(1)) for l in w if "at t = " in l]
check("[6] a node-dependent index in a transient: warned at the accepted points of the half period where V > 0.5 (t < 0.5 ms), silent in the other half",
      0 < len(w) < npts and times and max(times) < 0.5e-3 + 1e-9 and all("index [7]" in l for l in w),
      f"{len(w)} of {npts:.0f} points, last at {max(times) if times else None}")

# ---------------------------------------------------------------- 7 ---
out = op("ev", "", "c7")
w = warnings(out)
check("[7] an access inside an event block prints immediately (x = a[5] at the initial step: warned, x reads a[0] = 1, so 2 mA)",
      abs(current(out) + 2e-3) < 1e-9 and w and all("index [5] of `a`" in l for l in w), f"{w[:1]} i={current(out)}")

# ---------------------------------------------------------------- 8 ---
r = {}
ok, msg = compile_src("module e1(p,n); inout p,n; electrical p,n; real a[0:2]; analog begin a[0]=1; I(p,n) <+ V(p,n)*a[-1]*1e-3; end endmodule\n", "e1")
r["a[-1]"] = (not ok) and "array index out of range" in msg and "the array 'a' is declared [0:2]" in msg and "bus" not in msg
ok, msg = compile_src("module e2(p,n); inout p,n; electrical p,n; real a[0:1][0:2]; analog begin a[0][0]=1; I(p,n) <+ V(p,n)*a[0][3]*1e-3; end endmodule\n", "e2")
r["a[0][3]"] = (not ok) and "array index out of range" in msg and "that dimension of the array 'a' is declared [0:2]" in msg
ok, msg = compile_src("module e3(p,n); inout p,n; electrical p,n; parameter real a[0:2] = '{1,2,3}; analog I(p,n) <+ V(p,n)*a[3]*1e-3; endmodule\n", "e3")
r["param a[3]"] = (not ok) and "array index out of range" in msg and "the array 'a' is declared [0:2]" in msg
ok, msg = compile_src("module e4(a,b); inout [0:3] a; inout b; electrical [0:3] a; electrical b; analog I(a[4],b) <+ V(a[4],b)/1k; endmodule\n", "e4")
r["bus a[4]"] = (not ok) and "bus bit-select index out of range" in msg and "this bus was declared with width [0:3]" in msg
check("[8] (compiler) a literal index out of range is 'array index out of range' naming the array (and the dimension for a 2-D one); a bus keeps 'bus bit-select'",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
