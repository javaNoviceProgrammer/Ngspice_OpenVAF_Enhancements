#!/usr/bin/env python3
"""
verify_arrayscale.py -- two compiler findings of the 2026-09-07 bug hunt
(docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md, F3 and F4), fixed by
Enhancement-579.

  [1] F3: the MIR constant table aliased -0.0 onto +0.0, so every fold that produced
      a negative zero (`-0.0`, `0.0 * -1.0`, a folded `fneg`) came back positive:
      `1.0/(-0.0)` was +inf and `atan2(0.0, -0.0)` was 0. Now -inf and pi, like the
      run-time path.
  [2] F4: compile time was quadratic in an array's length -- a 10,000-entry array
      parameter took 72 s (375 s as an instance parameter), a 10,000-element local
      array written in a loop 68 s -- because every element cost CFG blocks: a
      three-block `if` diamond per element for a dynamic index read or write and for
      the retained-variable init, one per parameter in the setup function, and three
      per parameter in the OSDI access function plus four in the given-query
      function. MIR has a branchless `select` now (used by all of those), the access
      and given-query functions are table-driven and the same size for any parameter
      count, and a module with more than 1024 parameters has its setup functions
      generated at -O0 (they run once per model or instance). This suite pins the
      shapes (block counts in the MIR dump, IR function sizes) rather than seconds,
      plus a generous wall-clock bound, and re-checks every array semantics the
      change could have touched: out-of-range reads and writes, `$param_given` per
      element, model and instance overrides, alter/altermod, bounded parameters, a
      dependent default, a select feeding a contribution's derivative.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF
from _setup import NG as NGSPICE

ok_all = True
n_pass = 0
n_total = 0
HDR = '`include "disciplines.vams"\n'


def check(label, cond, detail=""):
    global ok_all, n_pass, n_total
    n_total += 1
    n_pass += bool(cond)
    ok_all = ok_all and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")


def compile_va(name, text, *flags):
    with open(os.path.join(HERE, name + ".va"), "w") as fh:
        fh.write(text)
    env = dict(os.environ, RAYON_NUM_THREADS="4", TERM="dumb")
    t0 = time.time()
    r = subprocess.run([OPENVAF, name + ".va", "-o", name + ".osdi", *flags], cwd=HERE,
                       capture_output=True, text=True, timeout=900, env=env)
    return r.returncode, r.stdout + r.stderr, time.time() - t0


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=300)
    return r.stdout + r.stderr


def opvars(out, inst="n1"):
    """{name: value} from `print @inst[name]` lines -- the FIRST print of each name"""
    res = {}
    for m in re.finditer(rf"^@{inst}\[(\w+)\] = (\S+)", out, re.M):
        res.setdefault(m.group(1), float(m.group(2)))
    return res


def blocks_per_function(dump):
    """block count of each 'Optimized ... MIR' section of a --dump-mir output"""
    res = {}
    name = None
    for line in dump.splitlines():
        m = re.match(r"^Optimized (model setup|instance setup|evaluation) MIR", line)
        if m:
            name = m.group(1)
            res[name] = 0
        elif name and re.match(r"^\s*block\d+:", line):
            res[name] += 1
    return res


def ir_function_sizes(dump):
    """{function name: line count} from a --dump-unopt-ir output"""
    sizes = {}
    name = None
    for line in dump.splitlines():
        m = re.match(r"^define .*@(\w+)\(", line)
        if m:
            name = m.group(1)
            sizes[name] = 0
        elif name:
            sizes[name] += 1
            if line.startswith("}"):
                name = None
    return sizes


def module(name, decls, body, ports="(p,n); inout p,n; electrical p,n;"):
    return (HDR + f"module {name}{ports}\n{decls}\n" +
            f"analog begin\n{body}\n  I(p,n) <+ V(p,n)*1e-3;\nend\nendmodule\n")


def cleanup():
    for f in os.listdir(HERE):
        if f.endswith((".osdi", ".va", ".txt")) or f == "_o.cir":
            try:
                os.remove(os.path.join(HERE, f))
            except OSError:
                pass


# ---------------------------------------------------------------------------
print("[1] F3: negative zero survives constant folding")
rc, log, _ = compile_va("nz", module("nz", """
parameter real zero = 0.0;
parameter real cneg = -0.0;
parameter real cneg3 = 0.0 * -1.0;
(*desc="a"*) real q1; (*desc="b"*) real q2; (*desc="c"*) real q3; (*desc="d"*) real q4; (*desc="e"*) real q5; (*desc="f"*) real q6;
real r;""", """
  q1 = 1.0/cneg; q2 = 1.0/cneg3; q3 = 1.0/(-0.0);
  r = -zero; q4 = 1.0/r;
  q5 = atan2(0.0, cneg); q6 = atan2(zero, r);"""))
check("nz.va compiles", rc == 0, log.strip().splitlines()[0] if rc else "")
out = ngspice("* nz\n.model m nz\nVs p 0 1\nN1 p 0 m\n.control\nset numdgt=12\npre_osdi nz.osdi\nop\n"
              "print @n1[q1] @n1[q2] @n1[q3] @n1[q4] @n1[q5] @n1[q6]\nquit\n.endc\n.end\n")
v = opvars(out)
check("1/(-0.0) as a parameter default is -inf", v.get("q1") == float("-inf"), v.get("q1"))
check("1/(0.0 * -1.0) folded is -inf", v.get("q2") == float("-inf"), v.get("q2"))
check("1/(-0.0) inline is -inf", v.get("q3") == float("-inf"), v.get("q3"))
check("1/(-zero) at run time is -inf (unchanged)", v.get("q4") == float("-inf"), v.get("q4"))
check("atan2(0.0, -0.0) folded is pi", abs(v.get("q5", 0) - 3.141592653589793) < 1e-12, v.get("q5"))
check("atan2(zero, -zero) at run time is pi (unchanged)", abs(v.get("q6", 0) - 3.141592653589793) < 1e-12, v.get("q6"))

# ---------------------------------------------------------------------------
print("[2] F4: the shapes -- no CFG block per array element, dispatch independent of the count")
K = 2000
arr = ", ".join(f"{k*0.001:.3f}" for k in range(K))
rc, dump, _ = compile_va("pread", module("pread", f"parameter real tab[0:{K-1}] = '{{{arr}}};\n(* type=\"instance\" *) parameter integer k = 7;\nreal s;", "  s = tab[k];"), "--dump-mir")
b = blocks_per_function(dump)
check(f"{K}-entry parameter array, dynamic read: model setup is ONE block", b.get("model setup") == 1, b)
check("... and the evaluation function is one block (a select chain, no diamonds)", b.get("evaluation") == 1, b)
rc, dump, _ = compile_va("lwrite", module("lwrite", f"real tab[0:{K-1}]; integer k; real s;", f"  for (k = 0; k < {K}; k = k + 1) tab[k] = k*0.001;\n  s = tab[5];"), "--dump-mir")
b = blocks_per_function(dump)
check(f"{K}-element local array written in a loop: evaluation has only the loop's blocks", 0 < b.get("evaluation", 0) <= 6, b)
check("... the dump shows one select per element", dump.count(" = select ") >= K, dump.count(" = select "))
rc, ir, _ = compile_va("pread", module("pread", f"parameter real tab[0:{K-1}] = '{{{arr}}};\n(* type=\"instance\" *) parameter integer k = 7;\nreal s;", "  s = tab[k];"), "--dump-unopt-ir")
sz = ir_function_sizes(ir)
check("the OSDI access function is under 200 IR lines for 2000 parameters (was 32,000)", 0 < sz.get("access_0", 10**9) < 200, sz.get("access_0"))
check("the OSDI given-query function is under 120 IR lines (was 66,000)", 0 < sz.get("param_given_0", 10**9) < 120, sz.get("param_given_0"))
rc, ir, _ = compile_va("tiny", module("tiny", "parameter real a = 1.0, b = 2.0;\nreal s;", "  s = a + b;"), "--dump-unopt-ir")
sz2 = ir_function_sizes(ir)
check("... and the same size for a two-parameter module (table-driven, not a switch)", sz2.get("access_0") == sz.get("access_0") and sz2.get("param_given_0") == sz.get("param_given_0"), (sz2.get("access_0"), sz2.get("param_given_0")))

print("[3] F4: wall clock, generously bounded (10,000-entry arrays took 68-410 s before)")
K = 10000
arr = ", ".join(f"{k*0.001:.3f}" for k in range(K))
rc, log, t_model = compile_va("big_model", module("big_model", f"parameter real tab[0:{K-1}] = '{{{arr}}};\n(* type=\"instance\" *) parameter integer k = 7;\nreal s;", "  s = tab[5] + tab[k];"))
check(f"a {K}-entry model array parameter compiles in under 30 s", rc == 0 and t_model < 30, f"{t_model:.1f} s")
rc, log, t_inst = compile_va("big_inst", module("big_inst", f"(* type=\"instance\" *) parameter real tab[0:{K-1}] = '{{{arr}}};\nreal s;", "  s = tab[5] + tab[7];"))
check(f"a {K}-entry instance array parameter compiles in under 40 s", rc == 0 and t_inst < 40, f"{t_inst:.1f} s")
K2 = 2500
arr2 = ", ".join(f"{k*0.001:.3f}" for k in range(K2))
rc, log, t_small = compile_va("mid_model", module("mid_model", f"parameter real tab[0:{K2-1}] = '{{{arr2}}};\n(* type=\"instance\" *) parameter integer k = 7;\nreal s;", "  s = tab[5] + tab[k];"))
check("4x the elements costs under 12x the time (it was 16x: quadratic)", rc == 0 and t_model < 12 * max(t_small, 0.5), f"{t_small:.1f} s -> {t_model:.1f} s")

# ---------------------------------------------------------------------------
print("[4] semantics of everything the change touched")
K, J = 2000, 1500
arr = ", ".join(f"{k*0.001:.3f}" for k in range(K))
iarr = ", ".join(f"{k*0.5:.1f}" for k in range(J))
rc, log, _ = compile_va("big", HDR + f'''module big(p,n); inout p,n; electrical p,n;
parameter real tab[0:{K-1}] = '{{{arr}}};
(* type="instance" *) parameter real itab[0:{J-1}] = '{{{iarr}}};
(* type="instance" *) parameter integer k = 5;
(* type="instance" *) parameter integer j = 3;
parameter real scale = 2.0;
parameter real dep = scale * 3.0;
(* type="instance" *) parameter real gain = 1.0 from (0:inf);
(*desc="tab[k]"*) real q1; (*desc="tab[7]"*) real q2; (*desc="itab[j]"*) real q3; (*desc="itab[9]"*) real q4;
(*desc="given tab[7]"*) real q5; (*desc="given tab[8]"*) real q6; (*desc="dep"*) real q7; (*desc="gain"*) real q8;
(*desc="given itab[9]"*) real q9; (*desc="w[j]"*) real q10; (*desc="w[3]"*) real q11; (*desc="oob read"*) real q12;
real w[0:9]; integer i;
analog begin
  for (i = 0; i < 10; i = i + 1) w[i] = i*10.0;
  w[j] = 777.0;
  q1 = tab[k]; q2 = tab[7]; q3 = itab[j]; q4 = itab[9]; q5 = $param_given(tab[7]); q6 = $param_given(tab[8]);
  q7 = dep; q8 = gain; q9 = $param_given(itab[9]); q10 = w[j]; q11 = w[3]; q12 = tab[k + {K}];
  I(p,n) <+ V(p,n)*1e-3*(1.0 + w[j]*0.0);
end
endmodule
''')
check("big.va (2000-entry model array + 1500-entry instance array) compiles", rc == 0, log.strip().splitlines()[0] if rc else "")
out = ngspice(f"""* big
.model m big tab[7]=99 scale=3
Vs p 0 1
N1 p 0 m k=5 j=3 itab[9]=-4.5 gain=2.5
N2 p 0 m k=7 j=9
.control
pre_osdi big.osdi
op
print @n1[q1] @n1[q2] @n1[q3] @n1[q4] @n1[q5] @n1[q6] @n1[q7] @n1[q8] @n1[q9] @n1[q10] @n1[q11] @n1[q12]
print @n2[q1] @n2[q3] @n2[q4] @n2[q8] @n2[q9] @n2[q10] @n2[q11]
alter @n2[itab[9]]=8.25
altermod @m[tab[5]]=55
op
print @n1[q1] @n2[q4] @n2[q9]
quit
.endc
.end
""")
a = opvars(out, "n1")
b = opvars(out, "n2")
n1_lines = re.findall(r"^@n1\[q1\] = (\S+)", out, re.M)
n2_q4 = re.findall(r"^@n2\[q4\] = (\S+)", out, re.M)
n2_q9 = re.findall(r"^@n2\[q9\] = (\S+)", out, re.M)
check("a default model-array element reads its literal (tab[5] = 0.005)", a.get("q1") == 0.005, a.get("q1"))
check("a model-card override of one element reaches that element (tab[7]=99)", a.get("q2") == 99.0 and b.get("q1") == 99.0, (a.get("q2"), b.get("q1")))
check("$param_given is per element (tab[7] given, tab[8] not)", a.get("q5") == 1.0 and a.get("q6") == 0.0, (a.get("q5"), a.get("q6")))
check("an instance-array element default and an instance override", a.get("q3") == 1.5 and a.get("q4") == -4.5 and b.get("q4") == 4.5, (a.get("q3"), a.get("q4"), b.get("q4")))
check("$param_given on an instance-array element", a.get("q9") == 1.0 and b.get("q9") == 0.0, (a.get("q9"), b.get("q9")))
check("a dependent default follows the model-card value (dep = scale*3 = 9)", a.get("q7") == 9.0, a.get("q7"))
check("a bounded instance parameter (the diamond path) is set and checked", a.get("q8") == 2.5 and b.get("q8") == 1.0, (a.get("q8"), b.get("q8")))
check("a dynamic array write inside the body lands on the indexed element only", a.get("q10") == 777.0 and a.get("q11") == 777.0 and b.get("q10") == 777.0 and b.get("q11") == 30.0, (a.get("q10"), a.get("q11"), b.get("q10"), b.get("q11")))
check("an out-of-range dynamic read still yields element 0 (Enhancement-489's rule)", a.get("q12") == 0.0, a.get("q12"))
check("alter of an instance-array element and altermod of a model-array element", len(n1_lines) == 2 and float(n1_lines[1]) == 55.0 and len(n2_q4) == 2 and float(n2_q4[1]) == 8.25 and len(n2_q9) == 2 and float(n2_q9[1]) == 1.0, (n1_lines, n2_q4, n2_q9))

rc, log, _ = compile_va("selderiv", module("selderiv", "parameter real g[0:2] = '{1e-3, 2e-3, 4e-3};\n(* type=\"instance\" *) parameter integer sel = 1;", "  I(p,n) <+ V(p,n)*g[sel];"))
out = ngspice("* selderiv\n.model m selderiv\nV1 p1 0 dc 0.5 ac 1\nN1 p1 0 m sel=2\n.control\npre_osdi selderiv.osdi\nop\nac lin 1 1k 1k\nlet mg = mag(i(v1))\nprint mg\nquit\n.endc\n.end\n")
m = re.search(r"^mg = (\S+)", out, re.M)
check("a select feeding a contribution differentiates correctly (AC conductance = g[2] + 1e-3)", m and abs(float(m.group(1)) - 5e-3) < 1e-9, m.group(1) if m else out[-200:])

cleanup()
print(f"\n{'ALL PASS' if ok_all else 'SOME FAILED'}: {n_pass}/{n_total} checks passed")
sys.exit(0 if ok_all else 1)
