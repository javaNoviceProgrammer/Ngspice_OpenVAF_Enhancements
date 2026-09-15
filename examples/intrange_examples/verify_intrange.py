#!/usr/bin/env python3
"""Enhancement-635: an integer parameter's real range bounds are compared as
reals, not rounded to integers first.

`parameter integer k from (0.5:2.5]` admits 1 and 2. The run-time check used
to round the bounds to the parameter's type before comparing -- `(0.5:2.5]`
became `(1:3]`, so 1 was refused and 3 accepted; `(1.5:2.5)` became the empty
`(2:3)` and refused even 2; `exclude 2.5` excluded 3; `inf` was i32::MAX, so
`from [0:inf)` refused 2147483647 -- while the compile-time checks on the same
range (L027, the emptiness check) always read the real bounds. Now the bound
keeps its type and the parameter's value is compared as a real against it.

Checks:
  [1]  (0.5:2.5]: 1 and 2 accepted, 0 and 3 refused
  [2]  [1.5:2.5] and (1.5:2.5): only 2
  [3]  [0:10] exclude 2.5: 3 and 10 accepted, 11 refused
  [4]  [0:inf) accepts 2147483647, (-inf:inf) accepts -2147483648, [-inf:0] both ends
  [5]  a range that reads a real parameter, from (0.5:hi], follows hi
  [6]  an instance-dependent range, from (0.5:w] with an instance w
  [7]  an array parameter, per element
  [8]  a set with a real member, from {1.5, 2, 3}: 2 and 3, not 1
  [9]  a real exclude that reads a parameter, and exclude [7.5:inf)
  [10] (compiler) (1.5:1.9) and (2:3) refused as ranges no integer satisfies;
       [2:3) and (1.5:2.5] accepted; a real parameter's (2:3) accepted
  [11] (compiler) L027 still judges the default against the real bounds
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
WORK = tempfile.mkdtemp(prefix="intrange_")
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
        f.write(f"* intrange {tag}\n{deck}\n.control\nset noinit\n{pre}{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def current(out):
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", out, re.M)
    return float(m.group(1)) if m else None


def refused(out, name):
    return f"Parameter {name} of" in out and "out of bounds" in out


ok, msg = compile_src("""module m1(p,n); inout p,n; electrical p,n;
  parameter integer k = 1 from (0.5:2.5];
  analog I(p,n) <+ V(p,n)/1k*k;
endmodule
module m2(p,n); inout p,n; electrical p,n;
  parameter integer k = 2 from [1.5:2.5];
  parameter integer j = 2 from (1.5:2.5);
  analog I(p,n) <+ V(p,n)/1k*(k+j);
endmodule
module m3(p,n); inout p,n; electrical p,n;
  parameter integer k = 1 from [0:10] exclude 2.5;
  analog I(p,n) <+ V(p,n)/1k*k;
endmodule
module m4(p,n); inout p,n; electrical p,n;
  parameter integer k = 1 from [0:inf);
  parameter integer j = 1 from (-inf:inf);
  parameter integer i = 0 from [-inf:0];
  analog I(p,n) <+ V(p,n)*1e-12*k + V(p,n)*1e-12*j + V(p,n)*1e-12*i;
endmodule
module m5(p,n); inout p,n; electrical p,n;
  parameter real hi = 2.5;
  parameter integer k = 1 from (0.5:hi];
  analog I(p,n) <+ V(p,n)/1k*k;
endmodule
module m6(p,n); inout p,n; electrical p,n;
  (* type="instance" *) parameter real w = 2.5;
  parameter integer k = 1 from (0.5:w];
  analog I(p,n) <+ V(p,n)/1k*k;
endmodule
module m7(p,n); inout p,n; electrical p,n;
  parameter integer a[0:1] = '{1, 2} from (0.5:2.5];
  analog I(p,n) <+ V(p,n)/1k*(a[0]+a[1]);
endmodule
module m8(p,n); inout p,n; electrical p,n;
  parameter integer k = 2 from {1.5, 2, 3};
  analog I(p,n) <+ V(p,n)/1k*k;
endmodule
module m9(p,n); inout p,n; electrical p,n;
  parameter real x = 0.5;
  parameter integer k = 1 from [0:10] exclude x exclude [7.5:inf);
  analog I(p,n) <+ V(p,n)/1k*k;
endmodule
""", "d")
check("the models compile", ok, msg[-300:])
PRE = "pre_osdi d.osdi\n"
print("Enhancement-635: an integer parameter's real bounds are compared as reals\n")


def op(model, card, tag, inst=""):
    return run(f"v1 a 0 1\nn1 a 0 mm {inst}\n.model mm {model} {card}", "op\nprint i(v1)", tag, PRE)


def accepted(model, card, expect_ma, tag, inst=""):
    out = op(model, card, tag, inst)
    i = current(out)
    # ngspice prints six significant digits
    return i is not None and abs(i + expect_ma * 1e-3) <= 1e-5 * abs(expect_ma * 1e-3) + 1e-12, out


def rejected(model, card, name, tag, inst=""):
    out = op(model, card, tag, inst)
    return refused(out, name) and current(out) is None, out


# ---------------------------------------------------------------- 1 ---
r = {}
for kv, exp in [("k=1", 1), ("k=2", 2)]:
    r[kv] = accepted("m1", kv, exp, "c1_" + kv[-1])
for kv in ["k=0", "k=3"]:
    r[kv] = rejected("m1", kv, "k", "c1_" + kv[-1])
check("[1] from (0.5:2.5]: 1 and 2 accepted, 0 and 3 refused",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 2 ---
r = {}
r["k=2"] = accepted("m2", "k=2", 4, "c2_k2")
r["k=1"] = rejected("m2", "k=1", "k", "c2_k1")
r["k=3"] = rejected("m2", "k=3", "k", "c2_k3")
r["j=2"] = accepted("m2", "j=2", 4, "c2_j2")
r["j=1"] = rejected("m2", "j=1", "j", "c2_j1")
r["j=3"] = rejected("m2", "j=3", "j", "c2_j3")
check("[2] from [1.5:2.5] and from (1.5:2.5): 2 accepted, 1 and 3 refused (the exclusive form used to refuse 2 as well)",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 3 ---
r = {}
for kv, exp in [("k=2", 2), ("k=3", 3), ("k=10", 10)]:
    r[kv] = accepted("m3", kv, exp, "c3_" + kv[2:])
r["k=11"] = rejected("m3", "k=11", "k", "c3_11")
check("[3] from [0:10] exclude 2.5: 2, 3 and 10 accepted (3 used to be excluded), 11 refused",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 4 ---
r = {}
r["k=INT_MAX"] = accepted("m4", "k=2147483647", (2147483647 + 1) * 1e-9, "c4_max")
r["k=-1"] = rejected("m4", "k=-1", "k", "c4_m1")
r["j=INT_MIN"] = accepted("m4", "j=-2147483648", (1 - 2147483648) * 1e-9, "c4_min")
r["i=INT_MIN"] = accepted("m4", "i=-2147483648", (2 - 2147483648) * 1e-9, "c4_imin")
r["i=1"] = rejected("m4", "i=1", "i", "c4_i1")
check("[4] inf is the real infinity: [0:inf) accepts 2147483647, (-inf:inf) and [-inf:0] accept -2147483648",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 5 ---
r = {}
r["k=2"] = accepted("m5", "k=2", 2, "c5_a")
r["k=3"] = rejected("m5", "k=3", "k", "c5_b")
r["k=3 hi=3.5"] = accepted("m5", "k=3 hi=3.5", 3, "c5_c")
r["k=1 hi=0.9"] = rejected("m5", "k=1 hi=0.9", "k", "c5_d")
check("[5] from (0.5:hi] with a real parameter hi: judged against hi's value, overridden or not",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 6 ---
r = {}
r["k=2"] = accepted("m6", "k=2", 2, "c6_a")
r["k=3"] = rejected("m6", "k=3", "k", "c6_b")
r["k=3 w=3.2"] = accepted("m6", "k=3", 3, "c6_c", inst="w=3.2")
r["k=1 w=0.7"] = rejected("m6", "k=1", "k", "c6_d", inst="w=0.7")
check("[6] from (0.5:w] with an instance parameter w: judged per instance, against a real w",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 7 ---
r = {}
r["a[0]=2"] = accepted("m7", "a[0]=2", 4, "c7_a")
r["a[0]=3"] = rejected("m7", "a[0]=3", "a[0]", "c7_b")
r["a[1]=0"] = rejected("m7", "a[1]=0", "a[1]", "c7_c")
check("[7] an integer array parameter's real range is judged per element",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 8 ---
r = {}
r["k=2"] = accepted("m8", "k=2", 2, "c8_a")
r["k=3"] = accepted("m8", "k=3", 3, "c8_b")
r["k=1"] = rejected("m8", "k=1", "k", "c8_c")
check("[8] from {1.5, 2, 3}: 2 and 3 accepted, 1 refused (1.5 no longer rounds to 2)",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 9 ---
r = {}
r["k=0"] = accepted("m9", "k=0", 0, "c9_a")
r["k=7"] = accepted("m9", "k=7", 7, "c9_b")
r["k=8"] = rejected("m9", "k=8", "k", "c9_c")
r["k=1 x=1"] = rejected("m9", "k=1 x=1", "k", "c9_d")
r["k=1"] = accepted("m9", "k=1", 1, "c9_e")
check("[9] exclude x (a real parameter) and exclude [7.5:inf): 0, 1, 7 accepted; 8 refused; 1 refused once x = 1",
      all(v[0] for v in r.values()), " ".join(f"{k}:{'ok' if v[0] else 'BAD'}" for k, v in r.items()))

# --------------------------------------------------------------- 10 ---
def declares(rng, ty="integer", tag="e"):
    ok, msg = compile_src(f"module {tag}(p,n); inout p,n; electrical p,n; parameter {ty} k = 2 from {rng}; analog I(p,n) <+ V(p,n)/1k*k; endmodule\n", tag)
    return ok, msg

r = {}
ok, msg = declares("(1.5:1.9)", tag="e1")
r["(1.5:1.9)"] = (not ok) and "which no value can satisfy" in msg and "no integer lies between 1.5 and 1.9" in msg
ok, msg = declares("(2:3)", tag="e2")
r["(2:3)"] = (not ok) and "which no value can satisfy" in msg and "no integer lies between 2 and 3" in msg
ok, msg = declares("[2:3)", tag="e3")
r["[2:3)"] = ok
ok, msg = declares("(1.5:2.5]", tag="e4")
r["(1.5:2.5]"] = ok
ok, msg = declares("(2:3)", ty="real", tag="e5")
r["real (2:3)"] = ok
check("[10] (compiler) an integer range no integer satisfies is refused -- (1.5:1.9), (2:3) -- while [2:3), (1.5:2.5] and a real's (2:3) compile",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

# --------------------------------------------------------------- 11 ---
ok1, msg1 = compile_src("module f1(p,n); inout p,n; electrical p,n; parameter integer k = 3 from (0.5:2.5]; analog I(p,n) <+ V(p,n)/1k*k; endmodule\n", "f1")
ok2, msg2 = compile_src("module f2(p,n); inout p,n; electrical p,n; parameter integer k = 1 from (0.5:2.5]; analog I(p,n) <+ V(p,n)/1k*k; endmodule\n", "f2")
check("[11] (compiler) L027 judges the default against the real bounds: 3 is warned, 1 is not -- and the run-time check now agrees",
      ok1 and "L027" in msg1 and ok2 and "L027" not in msg2, (msg1 + msg2)[-200:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
