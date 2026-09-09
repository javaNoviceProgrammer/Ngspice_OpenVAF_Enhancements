#!/usr/bin/env python3
"""Enhancement-590: the diagnostic slips of the 2026-09-08 hunt (F8), resolved.

  a  `$param_given(arr)` on an ARRAY parameter was "'arr' requires a bit-select";
     it now answers for the whole array (true when any element was given).
  b  a constant an `integer` cannot hold was folded silently: `3000000000` became
     the real 3e9 (saturated when stored), `parameter integer half = 2.5` ran
     with 3. Lint L030 `lossy_integer_constant` (warn) says so.
  c  `-A L022` was "invalid value"; the printed id is accepted by -A/-W/-E and
     `--lints` prints it beside the name.
  d  `V(p,n)` inside an analog function was "'V' was not found in the current
     scope"; the message now says what the name is and where, with LRM 4.7.1.
  e  `localparam string f = {"t1", ".tbl"}` was refused as not compile-time
     for `$table_model`; a concatenation of constant strings is folded.
  f  a control string naming more axes than the table has inputs ("3L,1L" on a
     1-D table) compiled silently; it is refused, naming the counts.
  g  `leafx l1;` read as a net declaration: the "expected discipline but found
     module" error carries a note on the port connection list.
  h  an instance sharing its name with a net/parameter/variable, or declared
     twice, compiled without a word; both are errors on the source.
  i  ngspice: `s=b` on a model card ("Undefined parameter [b]") now adds the
     hint that a string value needs quotes.
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
WORK = tempfile.mkdtemp(prefix="hunt3diag_")
HDR = '`include "disciplines.vams"\n'
for f in ("t1.tbl", "t2.tbl"):
    with open(os.path.join(HERE, f)) as src, open(os.path.join(WORK, f), "w") as dst:
        dst.write(src.read())


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag, *flags):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, *flags, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run(deck, ctl, osdi, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hunt3diag {tag}\n{deck}\n.control\nset noinit\npre_osdi {osdi}.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def first_line(msg, pat="^error|^warning"):
    for ln in msg.splitlines():
        if re.match(pat, ln):
            return ln
    return msg.strip().splitlines()[0] if msg.strip() else ""


print("Enhancement-590: hunt F8, resolved\n")

# ------------------------------------------------------------- [a] ---
ok, msg = compile_src("""module pg(p, n); inout p, n; electrical p, n;
  parameter real arr[0:2] = '{1, 2, 3};
  parameter real s = 1;
  (* desc="g" *) integer g;
  (* desc="gs" *) integer gs;
  analog begin
    g = $param_given(arr);
    gs = $param_given(s);
    I(p,n) <+ V(p,n) / (arr[0] * 1k);
  end
endmodule
""", "pg")
check("[a] $param_given(arr) on an array parameter compiles", ok, first_line(msg))
if ok:
    got = {}
    for card in ("", "arr[1]=3", "arr[0]=2 arr[2]=9", "s=2"):
        out = run(f"v1 1 0 1\nn1 1 0 pm\n.model pm pg {card}", 'op\necho "R: $&@n1[g] $&@n1[gs]"', "pg", "pg_" + str(len(got)))
        m = re.search(r"(?m)^R: (.*)$", out)
        got[card] = m.group(1) if m else out[-120:]
    check("[a] nothing given: 0 0", got[""] == "0 0", got[""])
    check("[a] one element given: the array is given (1), the scalar not", got["arr[1]=3"] == "1 0", got["arr[1]=3"])
    check("[a] two elements given: still 1", got["arr[0]=2 arr[2]=9"] == "1 0", got["arr[0]=2 arr[2]=9"])
    check("[a] only the scalar given: 0 1", got["s=2"] == "0 1", got["s=2"])

# ------------------------------------------------------------- [b] ---
LOSSY = """module li(p, n); inout p, n; electrical p, n;
  parameter integer big = 3000000000;
  parameter integer half = 2.5;
  parameter integer ok = 3;
  parameter integer neg = -2147483648;
  integer i;
  analog begin
    i = 3000000000;
    I(p,n) <+ V(p,n) / 1k + 0 * (i + big + half + ok + neg);
  end
endmodule
"""
ok, msg = compile_src(LOSSY, "li")
w = re.findall(r"warning\[L030\]: (.*)", msg)
check("[b] the module still compiles (L030 is a warning)", ok, first_line(msg))
check("[b] L030 for the literal in the body and for the parameter default `big`, once each",
      sorted(w).count("integer literal 3000000000 does not fit a 32-bit integer") == 2, "; ".join(w))
check("[b] L030 for the real default 2.5 of an integer parameter, naming the rounding",
      any("'half' has the default 2.5" in x for x in w) and "rounded to 3" in msg, "; ".join(w))
check("[b] no L030 for 3 or for -2147483648", len(w) == 3 and "'ok'" not in msg and "'neg'" not in msg, "; ".join(w))
check("[b] the literal label says what happens: read as a real, saturated when stored",
      "read as the real 3e9" in msg and "saturates to 2147483647" in msg, "")
ok2, msg2 = compile_src(LOSSY, "li_allow", "-A", "lossy_integer_constant")
check("[b] -A lossy_integer_constant silences it", ok2 and "L030" not in msg2, first_line(msg2))
ok3, msg3 = compile_src(LOSSY, "li_deny", "-E", "L030")
check("[b] -E L030 (the id) makes it an error", not ok3 and "error[L030]" in msg3, first_line(msg3))

# ------------------------------------------------------------- [c] ---
L022 = """module bre(p, n); inout p, n; electrical p, n;
  electrical a; branch (p, a) b1;
  analog begin V(b1) <+ 1.0; I(b1) <+ 1m; I(a, n) <+ V(a, n) / 1k; end
endmodule
"""
ok, msg = compile_src(L022, "l22")
check("[c] the control deck warns L022", ok and "warning[L022]" in msg, first_line(msg))
ok, msg = compile_src(L022, "l22a", "-A", "L022")
check("[c] -A L022 silences it by id", ok and "L022" not in msg, first_line(msg))
ok, msg = compile_src(L022, "l22e", "-E", "L022")
check("[c] -E L022 makes it an error by id", not ok and "error[L022]" in msg, first_line(msg))
ok, msg = compile_src(L022, "l22w", "-W", "discarded_contribution")
check("[c] the name still works", ok and "warning[L022]" in msg, first_line(msg))
r = subprocess.run([VAF, "--lints"], capture_output=True, text=True)
check("[c] --lints prints the id beside each name", re.search(r"discarded_contribution\s+L022", r.stdout) is not None
      and re.search(r"lossy_integer_constant\s+L030", r.stdout) is not None, r.stdout[:200])
ok, msg = compile_src(L022, "l22bad", "-A", "L999")
check("[c] an unknown id is refused as before", not ok and "invalid value" in msg, first_line(msg, "^error"))

# ------------------------------------------------------------- [d] ---
ok, msg = compile_src("""module fb(p, n); inout p, n; electrical p, n;
  analog function real f; input x; real x; f = x + V(p, n); endfunction
  analog I(p,n) <+ f(1.0) / 1k;
endmodule
""", "fb")
check("[d] V(p,n) inside a function: the message names the nature access and the module",
      not ok and "'V' cannot be used inside an analog function: it is a nature access function of the enclosing module" in msg,
      first_line(msg))
check("[d] ... with the LRM 4.7.1 note that says to pass the probe value in", "LRM 4.7.1" in msg and "passed in as an argument" in msg, "")
ok, msg = compile_src("""module fv(p, n); inout p, n; electrical p, n;
  real modvar;
  analog function real f; input x; real x; f = x + modvar; endfunction
  analog begin modvar = 1; I(p,n) <+ f(1.0) / 1k; end
endmodule
""", "fv")
check("[d] a module variable inside a function: named as a variable of the enclosing module",
      not ok and "'modvar' cannot be used inside an analog function: it is a variable of the enclosing module" in msg, first_line(msg))
ok, msg = compile_src("""module fn(p, n); inout p, n; electrical p, n;
  analog function real f; input x; real x; f = x + p; endfunction
  analog I(p,n) <+ f(1.0) / 1k;
endmodule
""", "fnet")
check("[d] a net inside a function: named as a node", not ok and "'p' cannot be used inside an analog function: it is a node" in msg, first_line(msg))
ok, msg = compile_src("""module fk(p, n); inout p, n; electrical p, n;
  parameter real k = 2;
  analog function real f; input x; real x; f = x * k; endfunction
  analog I(p,n) <+ f(V(p,n)) / 1k;
endmodule
""", "fk")
check("[d] a module parameter inside a function is still fine (LRM 4.7.1)", ok, first_line(msg))
ok, msg = compile_src("""module fu(p, n); inout p, n; electrical p, n;
  analog function real f; input x; real x; f = x + nosuch; endfunction
  analog I(p,n) <+ f(V(p,n)) / 1k;
endmodule
""", "fu")
check("[d] a name that exists nowhere keeps 'was not found'", not ok and "'nosuch' was not found in the current scope" in msg, first_line(msg))

# ------------------------------------------------------------- [e] ---
ok, msg = compile_src("""module tc(p, n, o); inout p, n; output o; electrical p, n, o;
  localparam string f = {"t1", ".tbl"};
  analog begin V(o) <+ $table_model(V(p,n), f, "1L"); I(p,n) <+ V(p,n) / 1k; end
endmodule
""", "tc")
check("[e] a concatenated localparam string is a constant table file name", ok, first_line(msg))
if ok:
    out = run("v1 1 0 1.5\nn1 1 0 o tm\n.model tm tc", 'op\necho "R: $&v(o)"', "tc", "tcrun")
    m = re.search(r"(?m)^R: (.*)$", out)
    check("[e] ... and the table is read: 2.5 at 1.5 on the linear segment", m is not None and m.group(1) == "2.5", m.group(1) if m else out[-200:])

# ------------------------------------------------------------- [f] ---
def table(ctl, dim, tag):
    if dim == 1:
        return compile_src(f"""module t1q(p, n, o); inout p, n; output o; electrical p, n, o;
  localparam string f = "t1.tbl";
  analog begin V(o) <+ $table_model(V(p,n), f, "{ctl}"); I(p,n) <+ V(p,n) / 1k; end
endmodule
""", tag)
    return compile_src(f"""module t2q(p, q, n, o); inout p, q, n; output o; electrical p, q, n, o;
  localparam string f = "t2.tbl";
  analog begin V(o) <+ $table_model(V(p,n), V(q,n), f, "{ctl}"); I(p,n) <+ V(p,n) / 1k; I(q,n) <+ V(q,n) / 1k; end
endmodule
""", tag)
ok, msg = table("3L,1L", 1, "ax1")
check("[f] \"3L,1L\" on a 1-D table still compiles (E-395) but is warned, naming the counts",
      ok and "names 2 axes but the table has 1 input" in msg and "after the first 1 are ignored" in msg, first_line(msg))
ok, msg = table("1L,1L,1L", 2, "ax2")
check("[f] three axes on a 2-D table: warned with 3 and 2", ok and "names 3 axes but the table has 2 inputs" in msg, first_line(msg))
ok, msg = table("1L,1C", 2, "ax3")
check("[f] two axes on a 2-D table: no warning", ok and "warning" not in msg, first_line(msg))
ok, msg = table("1L", 2, "ax4")
check("[f] fewer axes than inputs: no warning", ok and "warning" not in msg, first_line(msg))
ok, msg = compile_src("""module ti(p, q, n, o); inout p, q, n; output o; electrical p, q, n, o;
  localparam string f = "t2.tbl";
  analog begin V(o) <+ $table_model(V(p,n), V(q,n), f, "1L,1L,I"); I(p,n) <+ V(p,n) / 1k; I(q,n) <+ V(q,n) / 1k; end
endmodule
""", "ax5")
check("[f] an 'I' sub-string is a data column, not an axis: no warning", ok and "names" not in msg, first_line(msg))
ok, msg = compile_src("""module tr(p, n); inout p, n; electrical p, n;
  real gx[0:2], gy[0:2]; real y;
  analog begin gx[0]=0.0; gx[1]=1.0; gx[2]=2.0; gy[0]=0.0; gy[1]=1.0; gy[2]=4.0;
    y = $table_model(V(p,n), gx, gy, "1L,1C"); I(p,n) <+ y * 1e-3; end
endmodule
""", "ax6")
check("[f] the runtime 1-D form with two sub-strings keeps compiling (E-395's langguard control), warned", ok and "names 2 axes" in msg, first_line(msg))

# ------------------------------------------------------------- [g] ---
LEAF = "module leafx(p, n); inout p, n; electrical p, n; parameter real r = 1k; analog I(p,n) <+ V(p,n) / r; endmodule\n"
ok, msg = compile_src(LEAF + "module g1(p, n); inout p, n; electrical p, n; leafx l1; analog I(p,n) <+ V(p,n) / 1k; endmodule\n", "g1")
check("[g] `leafx l1;` keeps its error and gains the port-connection-list note",
      not ok and "expected discipline but found module 'leafx'" in msg and "a module instance needs a port connection list" in msg, first_line(msg))

# ------------------------------------------------------------- [h] ---
for tag, decl, what in (("h1", "electrical l1;", "net"), ("h2", "parameter real l1 = 1;", "parameter"), ("h3", "real l1;", "variable")):
    ok, msg = compile_src(LEAF + f"module {tag}(p, n); inout p, n; electrical p, n; {decl} leafx l1(p, n); endmodule\n", tag)
    check(f"[h] an instance named like a {what} is refused",
          not ok and "instance 'l1' has the same name as a net, parameter, variable" in msg, first_line(msg, "^error"))
ok, msg = compile_src(LEAF + "module h4(p, n); inout p, n; electrical p, n; leafx l2(p, n); leafx l2(p, n); endmodule\n", "h4")
check("[h] an instance declared twice is refused by name, not by its mangled parameter",
      not ok and "instance 'l2' is declared twice in module 'h4'" in msg, first_line(msg, "^error"))
ok, msg = compile_src(LEAF + "module h5(p, n); inout p, n; electrical p, n; electrical m; leafx l1(p, m); leafx l2(m, n); endmodule\n", "h5")
check("[h] distinct names compile", ok, first_line(msg))

# ------------------------------------------------------------- [i] ---
ok, msg = compile_src("""module sq(p, n); inout p, n; electrical p, n;
  parameter string s = "a" from {"a", "b"};
  analog I(p,n) <+ V(p,n) / ((s == "b") ? 2k : 1k);
endmodule
""", "sq")
check("[i] the string-parameter control compiles", ok, first_line(msg))
if ok:
    out = run("v1 1 0 1\nn1 1 0 sm\n.model sm sq s=b", "op", "sq", "sq_bare")
    check("[i] ngspice: a bare word on the card gets the quoting hint",
          "'b' is not a .param name; if it is meant as a string value, quote it: \"b\"" in out, out[-300:])
    out = run('v1 1 0 1\nn1 1 0 sm\n.model sm sq s="b"', 'op\necho "R: $&v1#branch"', "sq", "sq_quoted")
    m = re.search(r"(?m)^R: (.*)$", out)
    check("[i] ... and the quoted form still sets the string (2 kOhm: -0.5 mA)", m is not None and m.group(1) == "-0.0005", m.group(1) if m else out[-200:])
    out = run("v1 1 0 1\nn1 1 0 sm\n.model sm sq s={1+}", "op", "sq", "sq_expr")
    check("[i] a broken expression keeps the plain message", "Cannot compute substitute" in out and "quote it" not in out, out[-200:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
