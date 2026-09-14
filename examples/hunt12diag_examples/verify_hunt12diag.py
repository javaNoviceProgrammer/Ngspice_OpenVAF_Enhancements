#!/usr/bin/env python3
"""Enhancement-634: the diagnostic findings D1-D24 of the 2026-09-12 hunt.

Each finding is a place where the simulator or the compiler did something
defensible and said nothing, or said the wrong thing. The fixes are messages
and small refusals; nothing binds or draws differently.

Checks:
  [D1]  mcseed=4294967297 and mcseed=-3: outside 0..4294967295, said, seed 1;
        mcseed=4294967295 is a seed of its own; mcseed=1.5 is floored, said
  [D2]  `set controlswait` under ngspice -b: the note that there is no host run
  [D3]  writemc trial=9 / analysis / status refused as fixed columns; so is
        montecarlo -writemc status=
  [D4]  highsigma on a uniform-only deck: the note that nothing was inflated
  [D5]  (compiler) `(* std=25.0, std=30.0 *)`: warned, the last is used (30)
  [D6]  a second .option savemc= card: warned, the first is used; automc_save
        beside savemc: warned, savemc used
  [D7]  writemc after a run that made no row: the message names the reason
  [D8]  .option autoadapt without adapter=: a warning that the option is ignored,
        and the deck runs
  [D9]  a model parameter on the instance line: the message names the cause
  [D10] altermod onto an exclusive bound: warned at the write, naming the range
  [D11] the OSDI flow vector is typed current, and its name parses in `let`
  [D12] the txt writer leaves a never-got cell empty
  [D13] a 4-bit bus into a 2-bit port: the bits beyond the width are named
  [D14] a `setseed` in effect is said to be set aside by the loop's default seed
  [D19] rows made by wcd's own iteration are labelled `op (wcd probe)`
  [D21] (compiler) statistics on a `from {1.0, 2.0, 3.0}` parameter: warned
  [D24] -inflate on the print spelling of a device inside a subcircuit matches (E-622's suffix rule)
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
WORK = tempfile.mkdtemp(prefix="hunt12diag_")
HDR = '`include "disciplines.vams"\n'
A = "@"


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


def run(deck, ctl, tag, pre="", spiceinit=None):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hunt12diag {tag}\n{deck}\n.control\nset noinit\n{pre}{ctl}\n.endc\n.end\n")
    sp = os.path.join(WORK, ".spiceinit")
    if spiceinit is not None:
        with open(sp, "w") as f:
            f.write(spiceinit)
    try:
        p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                           timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    finally:
        if spiceinit is not None and os.path.exists(sp):
            os.remove(sp)
    return p.stdout + p.stderr


def vals(out, name):
    return [float(v) for v in re.findall(r"^" + re.escape(name) + r"\s*=\s*(\S+)", out, re.M)]


ok, msg = compile_src("""module sres(p, n);
  inout p, n; electrical p, n;
  (* std=25.0 *) parameter real r = 1000.0 from (0:inf);
  (* dist="uniform", std=2e-4 *) parameter real g = 1e-3 from [0:1);
  (* type="instance", std=10.0 *) parameter real dr = 0.0;
  analog I(p, n) <+ V(p, n) / (r + dr) + 0.0 * g * V(p, n);
endmodule
module um(p, n);
  inout p, n; electrical p, n;
  (* dist="uniform", std=100.0 *) parameter real ru = 1000.0 from (0:inf);
  analog I(p, n) <+ V(p, n) / ru;
endmodule
module vsrc(p, n);
  inout p, n; electrical p, n;
  analog V(p, n) <+ 0.5;
endmodule
module kb2(a, b);
  inout [0:1] a; inout b; electrical [0:1] a; electrical b;
  analog begin I(a[0], b) <+ V(a[0], b)/1k; I(a[1], b) <+ V(a[1], b)/2k; end
endmodule
""", "d")
check("the models compile", ok, msg[-300:])
PRE = "pre_osdi d.osdi\n"
SR = "v1 a 0 1\nn1 a 0 rm\n.model rm sres\n"
print("Enhancement-634: the diagnostic findings of the 2026-09-12 hunt\n")

# ------------------------------------------------------------- D1 ---
r = {}
for sd in ("4294967297", "-3", "1.5", "4294967295", "3"):
    out = run(SR + f".option osdimc mcseed={sd} osdimc_verbose", "op\nop", f"d1_{sd.replace('-', 'm').replace('.', 'p')}", PRE)
    r[sd] = (out, re.findall(r"osdimc: trial 2: rm:r = (\S+)", out))
check("[D1] mcseed=4294967297 (2^32+1) and -3 are refused as outside 0 .. 4294967295 (seed 1 used); 4294967295 is a seed "
      "of its own; 1.5 is floored and said",
      "outside the seed's range 0 .. 4294967295; using the default seed 1" in r["4294967297"][0]
      and "outside the seed's range" in r["-3"][0] and "is not an integer" not in r["4294967297"][0]
      and "not an integer; using 1" in r["1.5"][0]
      and r["4294967297"][1] == r["1.5"][1] and r["4294967295"][1] != r["1.5"][1] and r["3"][1] != r["1.5"][1]
      and "Warning" not in r["4294967295"][0].split("Circuit:")[1],
      f"{ {k: v[1] for k, v in r.items()} }")

# ------------------------------------------------------------- D2 ---
out = run("v1 a 0 1\nr1 a 0 1k", "set controlswait\nprint v(a)", "d2")
check("[D2] `set controlswait` in a batch run: the note that no host run exists and the commands run now",
      "`set controlswait` waits for a host's run only under libngspice" in out, out[-300:])

# ------------------------------------------------------------- D3 ---
out = run(".option savemc=d3.csv\n.param rr = agauss(1k,50,3)\nv1 a 0 1\nr1 a 0 {rr}",
          "op\nwritemc trial=9 analysis=2 status=1 ok=3", "d3")
head = open(os.path.join(WORK, "d3.csv")).readline().strip().split(",") if os.path.exists(os.path.join(WORK, "d3.csv")) else []
check("[D3] writemc trial= / analysis= / status= are refused as the row's fixed columns; the file has one of each and ok",
      out.count("is one of the row's fixed columns") == 3 and head == ["trial", "analysis", "status", "r1", "ok"],
      f"{head} {out[-200:]}")
out = run(".option savemc=d3b.csv\n.param rr = agauss(1k,50,3)\nv1 a 0 1\nr1 a 0 {rr}",
          "montecarlo 2 -analysis op -writemc status=v(a)", "d3b")
check("[D3] ...and montecarlo -writemc status= is refused at parse time, nothing runs",
      "-writemc `status` is one of the row's fixed columns" in out and "random samples" not in out, out[-200:])

# ------------------------------------------------------------- D4 ---
out = run(".option osdimc mcseed=3\nv1 a 0 1\nn1 a 0 um\n.model um um",
          "highsigma 20 -analysis op -metric i(v1) -max -0.0009 -seed 1", "d4", PRE)
check("[D4] highsigma on a deck whose only statistics are uniform: the note that nothing was inflated (plain Monte Carlo)",
      "nothing in this circuit was inflated -- its statistics are uniform" in out, out[-400:])

# ------------------------------------------------------------- D5 ---
ok, msg = compile_src("""module d5(p,n); inout p,n; electrical p,n;
(* std=25.0, std=30.0 *) parameter real r = 1000.0 from (0:inf);
(* std=0.5, trunc=3, trunc=1 *) parameter real k = 2.0 from (0:inf);
analog I(p,n) <+ V(p,n)/(r*k);
endmodule
""", "d5")
check("[D5] (compiler) a statistics attribute given twice is warned, the last used: 'std' 2 times, 'trunc' 2 times",
      ok and "'std' is given 2 times on this parameter; the last is the one used" in msg
      and "'trunc' is given 2 times" in msg, msg[-400:])
if ok:
    import ctypes
    lib = ctypes.CDLL(os.path.join(WORK, "d5.osdi"))
    class Info(ctypes.Structure):
        _fields_ = [("id", ctypes.c_uint32), ("dist", ctypes.c_uint32), ("std", ctypes.c_double)]
    n = ctypes.c_uint32.in_dll(lib, "OSDI_STAT_PARAM_COUNTS").value
    infos = (Info * n).in_dll(lib, "OSDI_STAT_PARAM_INFOS")
    truncs = (ctypes.c_double * n).in_dll(lib, "OSDI_STAT_PARAM_TRUNCS")
    check("[D5] ...the object carries the last values: std 30, trunc 1",
          [i.std for i in infos] == [30.0, 0.5] and list(truncs) == [0.0, 1.0],
          f"{[i.std for i in infos]} {list(truncs)}")

# ------------------------------------------------------------- D6 ---
for f in ("one.csv", "two.csv", "three.csv"):
    if os.path.exists(os.path.join(WORK, f)):
        os.remove(os.path.join(WORK, f))
out = run(".option savemc=one.csv\n.option savemc=two.csv automc_save=three.csv\n.option osdimc mcseed=2\n" + SR, "op", "d6", PRE)
check("[D6] a second .option savemc= card is warned (the first, one.csv, used); automc_save beside savemc is warned, "
      "savemc used; only one.csv exists",
      ".option savemc is given more than once with different values; the first card's (one.csv) is used" in out
      and "automc_save/osdimc_save is ignored beside .option savemc" in out
      and os.path.exists(os.path.join(WORK, "one.csv")) and not os.path.exists(os.path.join(WORK, "two.csv"))
      and not os.path.exists(os.path.join(WORK, "three.csv")), out[-300:])

# ------------------------------------------------------------- D7 ---
out = run(".option savemc=d7.csv\nv1 a 0 1\nr1 a 0 1k", "op\nwritemc x=v(a)", "d7")
check("[D7] writemc after a run that made no row: the message says the circuit has nothing to record, not 'no analysis has run'",
      "the last run made no row -- this circuit has no parameter with statistics to record" in out
      and "no analysis has run yet" not in out, out[-300:])

# ------------------------------------------------------------- D8 ---
out = run(".option autoadapt autobus\nv1 a 0 1\nr1 a 0 1k", "op\nprint v(a)", "d8")
check("[D8] .option autoadapt without adapter=: a Warning that the option is ignored, and the deck runs (v(a) = 1)",
      "Warning: .option autoadapt needs an adapter model" in out and "the option is ignored" in out
      and "Error: .option autoadapt" not in out and vals(out, "v(a)") == [1.0], out[-300:])

# ------------------------------------------------------------- D9 ---
out = run("v1 a 0 1\nn1 a 0 rm r=2k\n.model rm sres", "op", "d9", PRE)
check("[D9] a model parameter on the instance line: 'unknown parameter (r): it is a model parameter of this device -- set it on the .model card'",
      "unknown parameter (r): it is a model parameter of this device -- set it on the .model card" in out, out[-300:])

# ------------------------------------------------------------ D10 ---
out = run(".option osdimc mcseed=3\n" + SR, "op\naltermod rm r=0\nalter " + A + "n1[dr]=5\naltermod rm g=2\naltermod rm r=500", "d10", PRE)
check("[D10] altermod rm r=0 onto (0:inf) and g=2 onto [0:1) are warned at the write, naming the range; dr=5 and r=500 are not",
      "Warning: rm:r = 0 is outside the parameter's declared range from (0:inf)" in out
      and "Warning: rm:g = 2 is outside the parameter's declared range from [0:1)" in out
      and out.count("is outside the parameter's declared range") == 2, out[-400:])

# ------------------------------------------------------------ D11 ---
out = run("v1 a 0 1\nr1 a b 1k\nn1 b 0 vm m=2\n.model vm vsrc",
          "op\nlet x = n1#flow(p,n)*2\nprint x n1#flow(p,n) v1#branch\ndisplay", "d11", PRE)
check("[D11] the OSDI flow vector n1#flow(p,n) is typed current and its name parses unquoted in let/print (x = 2 * flow)",
      re.search(r"n1#flow\(p,n\)\s*:\s*current", out) is not None and len(vals(out, "x")) == 1
      and abs(vals(out, "x")[0] - 2 * vals(out, "n1#flow(p,n)")[0]) < 1e-12, out[-300:])

# ------------------------------------------------------------ D12 ---
out = run(".option savemc=d12.txt\n.param rr = agauss(1k,50,3)\nv1 a 0 1\nr1 a 0 {rr}", "op\nwritemc ia=i(v1)\nop", "d12")
lines = open(os.path.join(WORK, "d12.txt")).read().splitlines()
check("[D12] the txt writer leaves the cell a row never got empty (no 'nan')",
      len(lines) == 3 and "nan" not in lines[2] and lines[2].endswith("\t"), f"{lines}")

# ------------------------------------------------------------ D13 ---
out = run(".option autobus=kicad\n.model k2 kb2\nV0 /mid_0_ 0 1\nV1 /mid_1_ 0 2\nV2 /mid_2_ 0 3\nV3 /mid_3_ 0 4\nRb b 0 1\nN2 /mid b k2",
          "op\nprint v(b)", "d13", PRE)
check("[D13] a 4-bit bus into a 2-bit port: the warning names /mid_2_, /mid_3_ as bits beyond the port's width",
      "'/mid' was expanded to the 2 bus bits /mid_0_ .. /mid_1_ -- the port is 2 bits" in out
      and "also wires /mid_2_, /mid_3_, bits of the same bus beyond the port's width" in out, out[-400:])

# ------------------------------------------------------------ D14 ---
out = run(".param rr=agauss(1k,50,3)\nv1 a 0 1\nr1 a 0 {rr}", "setseed 5\nmontecarlo 2 -analysis op -expr r=" + A + "r1[resistance]", "d14")
check("[D14] a setseed 5 in effect is said to be set aside by montecarlo's default seed, with -seed 5 as the way to draw from it",
      "the `setseed 5` in effect is set aside for this montecarlo" in out and "give `-seed 5`" in out, out[-300:])

# ------------------------------------------------------------ D19 ---
out = run(".option savemc=d19.csv\n.param rr=agauss(1k,50,3)\nv1 a 0 1\nr1 a 0 {rr}",
          "op\nwcd -analysis op -metric v(a) -max 2 -is 2", "d19")
rows = [l.split(",") for l in open(os.path.join(WORK, "d19.csv")).read().splitlines()[1:]]
check("[D19] rows made by wcd's own iteration are labelled 'op (wcd probe)'; the plain op before it is 'op'",
      len(rows) > 2 and rows[0][1] == "op" and all(r[1] == "op (wcd probe)" for r in rows[1:]), f"{[r[1] for r in rows][:5]}")

# ------------------------------------------------------------ D21 ---
ok, msg = compile_src("""module d21(p,n); inout p,n; electrical p,n;
(* std=0.5 *) parameter real k = 2.0 from {1.0, 2.0, 3.0};
analog I(p,n) <+ V(p,n)/(1k*k);
endmodule
""", "d21")
check("[D21] (compiler) statistics on a parameter declared from {1.0, 2.0, 3.0} are warned as failing the range check",
      ok and "whose range is the discrete set `from {1.0, 2.0, 3.0}`" in msg and "fails the range check on nearly every trial" in msg,
      msg[-300:])

# ------------------------------------------------------------ D24 ---
out = run(".option osdimc mcseed=3\n.subckt blk a b\nn1 a b rm\n.ends\nv1 a 0 1\nx1 a 0 blk\n.model rm sres",
          "highsigma 4 -analysis op -metric i(v1) -max 0 -seed 1 -inflate " + A + "x1.n1[dr]", "d24", PRE)
check("[D24] -inflate on the print spelling of a device inside a subcircuit (x1.n1) matches -- no 'matched nothing' note",
      "matched a" not in out and "NOTHING was" not in out and "failures observed" in out, out[-300:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
