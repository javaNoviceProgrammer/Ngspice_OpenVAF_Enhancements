#!/usr/bin/env python3
"""Enhancement-640: the diagnostic slips of the 2026-09-14 hunt (F6).

Seven small things the compiler said wrongly, or did not say:
  [1]  two messages carried runs of spaces (a flattened line continuation)
  [2]  --dump-json was in --help and answered "currently unimplemented"
  [8]  E-694: --dump-json wrote string constants raw; a $fatal's message ends in a
       real newline, so any module with a message task dumped invalid JSON
  [3]  $fatal / $error / $warning / $info with no message printed no line, so
       ngspice's "see the OSDI(fatal) message above" pointed at nothing
  [4]  'std' beside 'std_rel' was an error whose text said which one "is used";
       'std' on an integer or string said "only a scalar real parameter", while
       an array's elements carry statistics
  [5]  -C foo=bar was accepted without a word although nothing consumes it
  [6]  1e400 is refused as too large, 1e308*10 folded to infinity in silence
  [7]  a statement at module scope (I(p,n) <+ ..., x = 1, $strobe, begin..end)
       was read as a net declaration and reported as three token errors
"""
import json
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
WORK = tempfile.mkdtemp(prefix="hunt13slips_")
HDR = '`include "disciplines.vams"\n'
M = "module m(p,n); inout p,n; electrical p,n;\n"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag, flags=()):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, *flags, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run(deck, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hunt13slips {tag}\n{deck}\n.control\nset noinit\npre_osdi {tag}.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def nerr(msg):
    return sum(1 for l in msg.splitlines() if l.startswith("error") and "could not compile" not in l and "failed to compile" not in l)


print("Enhancement-640: the diagnostic slips of the 2026-09-14 hunt\n")

# ---------------------------------------------------------------- 1 ---
ok1, msg1 = compile_src(M + "parameter real r=1k; aliasparam res=r; real g; analog begin g = $param_given(res) ? 2 : 1; I(p,n) <+ g*V(p,n)/1k; end endmodule\n", "c1a")
ok2, msg2 = compile_src("module ch(a,b); inout a,b; electrical a,b; parameter real r=1k; analog I(a,b) <+ V(a,b)/r; endmodule\n"
                        + M + "ch #(.zz(3)) c1(.a(p), .b(n)); endmodule\n", "c1b")
check("[1] the aliasparam-in-body help and the unknown-override error read as one line each, no runs of spaces",
      (not ok1) and "override spelling only -- 'the equations in the module shall reference the parameter by its original name'" in msg1
      and (not ok2) and "names no parameter of module 'ch' (it declares r)" in msg2
      and not re.search(r"\S {4,}\S", msg1.split("help:")[-1].split("\n")[0])
      and not re.search(r"\S {4,}\S", [l for l in msg2.splitlines() if "names no parameter" in l][0]),
      (msg1 + msg2)[-200:])

# ---------------------------------------------------------------- 2 ---
src = M + "parameter real r=1k; integer c; analog begin @(cross(V(p,n)-0.5, +1)) c = c + 1; I(p,n) <+ V(p,n)/r + ddt(1e-12*V(p,n)); end endmodule\n"
ok, msg = compile_src(src, "c2", flags=["--dump-json"])
jpath = os.path.join(WORK, "c2_m.json")
j = json.load(open(jpath)) if os.path.exists(jpath) else {}
inputs = j.get("inputs", {})
ok_a = ok and os.path.exists(os.path.join(WORK, "c2.osdi")) and set(j) >= {"cfg", "instructions", "vals", "inputs", "outputs"} \
    and "r" in inputs.get("parameters", {}) and "(p, n)" in inputs.get("voltages", {}) and "c" in j.get("outputs", {}) \
    and "c2_m.json" in msg
for f in os.listdir(WORK):
    if f.startswith("c2.") and f != "c2.va":
        os.remove(os.path.join(WORK, f))
ok, msg = compile_src(src, "c2", flags=["--dump-json", "--dry-run"])
ok_b = ok and os.path.exists(jpath) and not os.path.exists(os.path.join(WORK, "c2.osdi")) \
    and not [f for f in os.listdir(WORK) if re.match(r"c2\.o[0-9a-z]+$", f)]
r = subprocess.run([VAF, "--help"], capture_output=True, text=True)
ok_c = "unimplemented" not in r.stdout and "<output stem>_<module>.json" in r.stdout
check("[2] --dump-json writes <stem>_<module>.json (cfg, instructions, vals, inputs by kind, outputs) beside the object; with --dry-run the JSON only; --help says so",
      ok_a and ok_b and ok_c, f"a={ok_a} b={ok_b} c={ok_c} {sorted(inputs)}")

# ---------------------------------------------------------------- 3 ---
ok, msg = compile_src(M + "analog begin @(initial_step) begin $info; $warning; $error; end I(p,n) <+ V(p,n)/1k; end endmodule\n", "c3a")
out = run("v1 a 0 1\nn1 a 0 mm\n.model mm m", "op\nprint i(v1)", "c3a")
ok_a = ok and "OSDI(info) n1: $info (at the operating point)" in out and "OSDI(warn) n1: $warning (at the operating point)" in out \
    and "OSDI(err) n1: $error (at the operating point)" in out
ok, msg = compile_src(M + "analog begin @(initial_step) $fatal; I(p,n) <+ V(p,n)/1k; end endmodule\n", "c3b")
out = run("v1 a 0 1\nn1 a 0 mm\n.model mm m", "op\nprint i(v1)", "c3b")
ok_b = ok and "OSDI(fatal) n1: $fatal (at the operating point)" in out and "raised $fatal" in out
check("[3] $info / $warning / $error / $fatal with no message print their own name with the context; the fatal line ngspice points at exists",
      ok_a and ok_b, out[-300:])

# ---------------------------------------------------------------- 4 ---
ok1, msg1 = compile_src(M + "(* std_rel=0.1, std=25 *) parameter real r=1k; analog I(p,n) <+ V(p,n)/r; endmodule\n", "c4a")
ok2, msg2 = compile_src(M + "(* std=1 *) parameter integer k=3 from [1:10]; (* std=1 *) parameter string s=\"a\"; analog I(p,n) <+ V(p,n)/1k*k; endmodule\n", "c4b")
ok3, msg3 = compile_src(M + "(* std=1 *) parameter real a[0:1]='{1,2}; analog I(p,n) <+ V(p,n)/1k*a[0]; endmodule\n", "c4c")
out = run("v1 a 0 1\nn1 a 0 mm\n.model mm m\n.option osdimc osdimc_verbose mcseed=3", "op\nop\nprint i(v1)", "c4c")
check("[4] std beside std_rel: 'both given ... give one of them' (no 'is used'); std on an integer/string names the type; an array's elements still draw",
      (not ok1) and "are both given on this parameter; give one of them" in msg1 and "is used" not in msg1
      and ok2 and "statistics need a real parameter; this one is an integer" in msg2 and "this one is a string" in msg2
      and "scalar" not in msg2 and ok3 and "mm:a[0] =" in out and "mm:a[1] =" in out,
      (msg1 + msg2)[-200:])

# ---------------------------------------------------------------- 5 ---
ok, msg = compile_src(M + "analog I(p,n) <+ V(p,n)/1k; endmodule\n", "c5", flags=["-C", "foo=bar"])
r = subprocess.run([VAF, "--help"], capture_output=True, text=True)
check("[5] -C foo=bar: warned as consumed by nothing and ignored, the build goes on; --help no longer says 'passed directly to LLVM'",
      ok and "warning: -C foo=bar: no codegen option is consumed by this compiler" in msg
      and "passed directly to LLVM" not in r.stdout and "No codegen option is consumed" in r.stdout, msg[-200:])

# ---------------------------------------------------------------- 6 ---
r = {}
ok, msg = compile_src(M + "parameter real y=1e308*10; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n", "c6a")
r["1e308*10"] = (not ok) and "the default of parameter 'y' overflows to infinity" in msg and "folds to inf" in msg
ok, msg = compile_src(M + "parameter real y=-1e308*10; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n", "c6b")
r["-1e308*10"] = (not ok) and "folds to -inf" in msg
ok, msg = compile_src(M + "parameter real y=1e308+1e308; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n", "c6c")
r["1e308+1e308"] = (not ok) and "overflows to infinity" in msg
ok, msg = compile_src(M + "parameter real y=1e307*10; parameter real z=-1.7e308; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n", "c6d")
r["1e307*10, -1.7e308"] = ok
ok, msg = compile_src(M + "parameter real y=1e400; analog I(p,n) <+ V(p,n)*1e-3; endmodule\n", "c6e")
r["1e400 literal"] = (not ok) and "too large to represent" in msg
check("[6] a real default that folds to +/-infinity is refused like the literal 1e400; finite ones compile",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 7 ---
r = {}
for name, body in [("I(p,n) <+", "I(p,n) <+ V(p,n)/1k;"), ("x = 1", "real x; x = 1;"), ("$strobe", "$strobe(\"x\");"),
                   ("begin..end", "begin I(p,n) <+ V(p,n)/1k; end")]:
    ok, msg = compile_src(M + body + " endmodule\n", "c7_" + str(len(r)))
    r[name] = (not ok) and nerr(msg) == 1 and "statement outside an analog block" in msg \
        and "belong inside an analog block" in msg and "expected discipline" not in msg
ok, msg = compile_src("module ch(a,b); inout a,b; electrical a,b; parameter real r=1k; analog I(a,b) <+ V(a,b)/r; endmodule\n"
                      + M + "electrical [0:2] nd; electrical x; branch (p,n) b; ch c1(p,n); ch c2(.a(p),.b(n)); ch #(.r(2k)) c3(p,n);\n"
                      "analog begin I(b) <+ V(b)/1k; V(nd[0],n) <+ 0; V(nd[1],n) <+ 0; V(nd[2],n) <+ 0; V(x,n) <+ 0; end endmodule\n", "c7ok")
r["declarations and instances"] = ok
check("[7] a statement at module scope is one error naming it (contribution, assignment, system task, begin..end); widths, branches and instances still parse",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

# ---------------------------------------------------------------- 8 ---
# Enhancement-694 (hunt F4 of 2026-09-21): the dump wrote string constants raw.
# The message of a $fatal/$error/$warning/$info ends in a real newline (the
# lowering appends it for the run-time printf), so every module with one of
# those produced a file no JSON parser accepts; source literals survived only
# because the lexer keeps their escapes as two characters. Every string the
# dump writes -- constants, input names, keys -- is escaped now (RFC 8259 7).
src = (M + 'real x; string s;\nanalog begin x = V(p,n); s = "in\\"side\\tq"; $strobe("q\\"q\\n");\n'
       '  if (x > 100) $fatal(1, "too much: %g", x); if (x > 90) $error("e %g", x);\n'
       '  if (x > 80) $warning("w"); if (x > 70) $info("i"); if (x > 60) $fatal(0);\n'
       '  I(p,n) <+ x/1k; end endmodule\n')
ok, msg = compile_src(src, "c8", flags=["--dump-json", "--dry-run"])
jpath = os.path.join(WORK, "c8_m.json")
def _sconsts(node, acc):
    if isinstance(node, dict):
        if "sconst" in node:
            acc.append(node["sconst"])
        for v in node.values():
            _sconsts(v, acc)
    elif isinstance(node, list):
        for v in node:
            _sconsts(v, acc)
    return acc
try:
    j = json.load(open(jpath)) if os.path.exists(jpath) else None
    err = ""
except ValueError as e:
    j, err = None, str(e)
sc = _sconsts(j, []) if j is not None else []
check("[8] --dump-json is valid JSON with $fatal/$error/$warning/$info in the module, and the messages round-trip with their newline",
      ok and j is not None and "too much: %g\n" in sc and "e %g\n" in sc and "w\n" in sc and "i\n" in sc
      and any(v.startswith("$fatal") for v in sc),
      err or (f"{len(sc)} string constants: {sc[:8]}" if j is not None else first_line(msg)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
