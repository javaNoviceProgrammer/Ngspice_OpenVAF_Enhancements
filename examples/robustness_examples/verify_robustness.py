#!/usr/bin/env python3
"""
verify_robustness.py -- Enhancement-148: openvaf-r compiler hardening.

A robustness campaign (Enhancement-147) found three classes of pathological input
that made the compiler crash or hang instead of reporting an error:

  * deeply nested / chained expressions overflowed the recursive-descent parser
    (and later recursive tree traversals);
  * a file that `` `include ``s itself recursed until the stack overflowed;
  * an absurd array / bus / instance-array range (`real x[0:100000000]`) was
    expanded element-by-element until memory was exhausted.

Enhancement-148 turns each into a clean, bounded diagnostic:

  * a parse-time expression-depth limit (1000);
  * an `` `include `` nesting cap (64), mirroring the macro-recursion guard;
  * a cap on how many scalar elements an array declaration may expand to (~1M),
    applied to variable, parameter, net/bus and instance arrays.

Enhancement-219 closes a fifth pathology found by re-running the robustness
campaign: a `` `name( `` macro call whose argument list contains a stray
compiler directive (`` `include ``, `` `ifdef ``, ...) made the preprocessor's
argument collector spin on that token forever (it emitted an error without
advancing), hanging the compiler. The collector now always makes forward
progress, so such input errors cleanly instead.

Enhancement-718 (correctness campaign F4 of 2026-09-25) raises the expression
bound from 1000 to 32 768 levels. A flat sum of a thousand terms -- a generated
polynomial on one line -- tripped the old one as "nesting too deeply": the parser
reads a chain iteratively, but the passes after it recurse over the left-leaning
tree they get, one frame per operator. The front end now runs on a 512 MB thread
(as the codegen has since E-264), where a chain of 128 000 terms compiles, and the
bound sits a factor of four under what the deepest admitted shape needs. The
diagnostic names the bound and what it counts, and stands alone: an over-deep
call argument no longer draws "invalid argument count" after it.

Each check confirms the pathological input now produces a NONZERO exit quickly
(a clean error, not a crash or a hang), and that valid deep-but-reasonable input
still compiles. It also spot-checks the diagnostic text.
"""
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))

D = os.path.join(tempfile.gettempdir(), "rob148"); os.makedirs(D, exist_ok=True)
HDR = '`include "disciplines.vams"\n'
def wr(name, content):
    p = os.path.join(D, name)
    with open(p, "w") as f: f.write(content)
    return p
def modexpr(e): return HDR + "module m(a,b); inout a,b; electrical a,b;\nanalog I(a,b)<+" + e + ";\nendmodule\n"

def run(path, timeout=20):
    """Return (verdict, combined_output). verdict in OK / ERROR / CRASH / HANG."""
    t = time.time()
    try:
        r = subprocess.run([OPENVAF, path, "-o", os.path.join(D, "out.osdi"), "-I", D],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", "", time.time() - t
    out = (r.stdout or "") + (r.stderr or "")
    dt = time.time() - t
    if r.returncode is not None and r.returncode < 0:
        return "CRASH", out, dt          # killed by a signal (segfault / abort)
    if "panicked at" in out.lower():
        return "CRASH", out, dt
    return ("OK" if r.returncode == 0 else "ERROR"), out, dt

print("Enhancement-148: compiler hardening (parser depth / include cap / array cap)")

# --- parser expression-depth limit ---
for name, expr in [("deep unary  (-…)", "-" * 40000 + "V(a,b)"),
                   ("deep binary (+…)", "V(a,b)" + "+1" * 40000),
                   ("deep parens", "(" * 40000 + "V(a,b)" + ")" * 40000),
                   ("deep calls  sin(…)", "sin(" * 40000 + "V(a,b)" + ")" * 40000),
                   ("deep ternary", "1?" * 40000 + "V(a,b)" + ":0" * 40000)]:
    v, o, dt = run(wr("p.va", modexpr(expr)))
    check(f"parser: {name} -> clean error, no crash/hang  [{v} {dt:.1f}s]", v == "ERROR",
          f"{v}")
    # Enhancement-718: the one error names the bound and what it counts, and no
    # knock-on follows it (E-665's recovery, extended to a call argument).
    nerr = sum(1 for l in o.splitlines() if l.startswith("error"))
    check(f"parser: {name} -> the one error names the 32768-level bound (E-718)",
          "deeper than 32768 levels" in o and nerr == 2, f"{nerr} error lines; {o[:160]!r}")

# --- Enhancement-718: the bound's edge, one term either side ---
v, o, dt = run(wr("edge.va", modexpr("V(a,b)" + "+1.0" * 32800)))
check(f"parser: chain of 32800 terms, past the bound -> the depth error  [{v} {dt:.1f}s]",
      v == "ERROR" and "deeper than 32768 levels" in o, f"{v} {o[:160]!r}")
v, o, dt = run(wr("edge_ok.va", modexpr("V(a,b)" + "+1.0" * 32700)))
check(f"valid: chain of 32700 terms, under the bound, compiles  [{v} {dt:.1f}s]", v == "OK", f"{v} {o[:160]!r}")

# --- include self-recursion ---
v, o, dt = run(wr("self.va", '`include "self.va"\n' + HDR + "module m(a); electrical a; endmodule\n"))
check(f"include: self-including file -> clean error  [{v} {dt:.1f}s]", v == "ERROR", v)
# Enhancement-650: the cycle is named at its first occurrence, not 64 levels down
check("include: diagnostic names the cycle (E-650; was the nesting-depth limit)",
      "includes a file that is already being included" in o or "nests too deeply" in o, o[:200])

# --- array / bus / instance caps ---
arrays = {
    "variable array real x[0:100000000]":
        HDR + "module m(a,b); inout a,b; electrical a,b; real x[0:100000000]; analog I(a,b)<+V(a,b); endmodule\n",
    "parameter array c[0:100000000]":
        HDR + "module m(a,b); inout a,b; electrical a,b; parameter real c[0:100000000]=0; analog I(a,b)<+V(a,b); endmodule\n",
    "net bus [0:100000000]":
        HDR + "module m(a,b); inout a,b; electrical a,b; electrical [0:100000000] bus; analog I(a,b)<+V(a,b); endmodule\n",
    "instance array s[0:100000000]":
        HDR + "module sub(p); electrical p; endmodule\nmodule m(a,b); inout a,b; electrical a,b; sub s[0:100000000](a); analog I(a,b)<+V(a,b); endmodule\n",
}
for name, src in arrays.items():
    v, o, dt = run(wr("arr.va", src))
    check(f"array: {name} -> clean error, no hang  [{v} {dt:.1f}s]", v == "ERROR", v)

v, o, dt = run(wr("arr.va", list(arrays.values())[0]))
check("array: diagnostic reports the element count / limit",
      "exceeding the limit" in o or "too large" in o, o[:200])

# --- Enhancement-219: preprocessor argument-collection loops must terminate ---
# The macro-CALL argument list (`\`name(`) and the `\`define` PARAMETER list both
# scan token by token; a token that none of the loop's expect/eat calls consumes
# (a stray directive in a macro call, a stray delimiter in a define) used to make
# the collector spin forever (error-without-advance -> hang). Each must now error
# cleanly and quickly, with or without deep leading parentheses.
MOD = HDR + "module m(a); electrical a; endmodule\n"
macro_arg = {
    "`m( then `include": '`m(`include "x.inc"\n' + MOD,
    "`m( then `ifdef":   '`m(`ifdef FOO\n' + MOD,
    "`m( then `endif":   '`m(`endif\n' + MOD,
    "`m( then `undef":   '`m(`undef X\n' + MOD,
    "`m( + 4000 '(' then `include": '`m(' + "(" * 4000 + '`include "x.inc"\n' + MOD,
    "`define M(a,/,b)":  '`define M(a,/,b) x\n' + MOD,
    "`define M(a\"b)":   '`define M(a"b) x\n' + MOD,
    "`define M(a;b)":    '`define M(a;b) x\n' + MOD,
}
for name, src in macro_arg.items():
    v, o, dt = run(wr("mac.va", src), timeout=20)
    check(f"macro-arg: {name} -> clean error, no hang  [{v} {dt:.1f}s]", v == "ERROR", v)

# --- regression: valid deep-but-reasonable input still compiles ---
def nest_tern(n):
    e = "0.0"
    for i in range(n):
        e = f"(V(a,b)>{i}?{i}*V(a,b):{e})"
    return e
def horner(n):
    e = "1e-3"
    for i in range(n):
        e = f"({e}*V(a,b) + {i}e-6)"
    return e
valid = {
    "nested ternary depth 30": modexpr(nest_tern(30)),
    "parenthesised depth 100": modexpr("(" * 100 + "V(a,b)" + ")" * 100),
    "sum of 100 terms": modexpr("V(a,b)" + "+1.0" * 100),
    # Enhancement-718: the shapes the 1000-level bound refused
    "sum of 5000 terms (E-718; the bound was 1000)": modexpr("V(a,b)" + "+1.0" * 5000),
    "nested ternary depth 2000 (E-718)": modexpr(nest_tern(2000)),
    "nested calls sin() depth 2000 (E-718)": modexpr("sin(" * 2000 + "V(a,b)" + ")" * 2000),
    "Horner polynomial of degree 2000 (E-718)": modexpr(horner(2000)),
    "small array x[0:15]": HDR + "module m(a,b); inout a,b; electrical a,b; real x[0:15]; analog begin x[3]=V(a,b); I(a,b)<+x[3]; end endmodule\n",
    "instance array s[0:7]": HDR + "module sub(p); inout p; electrical p; endmodule\nmodule m(a,b); inout a,b; electrical a,b; sub s[0:7](a); analog I(a,b)<+V(a,b); endmodule\n",
    # Enhancement-219: a genuine macro call with parenthesised (even nested) args
    # must still compile -- the hang fix must not reject valid macro usage.
    "macro call with nested-paren args":
        HDR + "`define TWO(x) ((x)+(x))\nmodule m(a,b); inout a,b; electrical a,b; "
              "analog I(a,b)<+ `TWO(V(a,b)); endmodule\n",
}
for name, src in valid.items():
    v, o, dt = run(wr("ok.va", src))
    check(f"valid: {name} still compiles", v == "OK", f"{v} {o[:150]}")

# --- Enhancement-718: the campaign's F4 shape end to end -- a 1 500-term sum evaluates,
# left to right, to the value Python's left-to-right sum gives ---
N = 1500
src = (HDR + 'module m(a,b); inout a,b; electrical a,b; (* desc="r" *) real r;\nanalog begin r = '
       + " + ".join(f"1.0/{k}" for k in range(1, N + 1)) + "; I(a,b) <+ 1e-3*r; end\nendmodule\n")
v, o, dt = run(wr("sum1500.va", src))
check(f"valid: a flat sum of {N} terms compiles (E-718; was 'nests too deeply')  [{v} {dt:.1f}s]", v == "OK", f"{v} {o[:150]}")
rfile = os.path.join(D, "r.txt")
if os.path.exists(rfile):
    os.remove(rfile)
deck = ("* E-718\nn1 a 0 mm\nv1 a 0 dc 1\n.model mm m\n.control\npre_osdi " + os.path.join(D, "out.osdi")
        + "\nop\nset numdgt=17\nwrdata " + rfile + " @n1" + "[r]\n.endc\n.end\n")
subprocess.run([NGSPICE, "-b", wr("sum1500.cir", deck)], capture_output=True, text=True, timeout=60, cwd=D)
expect = 0.0
for k in range(1, N + 1):
    expect += 1.0 / k
got = float(open(rfile).read().split()[-1]) if os.path.exists(rfile) else float("nan")
check(f"valid: ... and evaluates to the left-to-right sum {expect!r}, bit for bit", got == expect, f"got {got!r}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
