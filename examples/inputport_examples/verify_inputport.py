#!/usr/bin/env python3
"""Enhancement-639: a contribution to a port declared `input` is warned.

LRM 5.6.1: "Implementations may issue a warning if a contribution is made to
an analog port declared with an input direction. There are no restrictions on
the probing of an analog port declared with an output direction." The compiler
said nothing: `input p; ... I(p,n) <+ V(p,n)/1k;` compiled clean and drove the
port it declared it only reads. Lint L031 `contribution_to_input_port` (warn)
is that warning, on every contribution form; probes are not judged, and an
`inout` or `output` port is not an input.

Checks:
  [1]  I(p,n) <+, V(p,n) <+, V(p) <+, a named branch (p,n), a named branch (p): each warned once, naming p
  [2]  probes only -- V(p,n), I(<p>) -- on an input port: silent; a contribution to an output port: silent
  [3]  the warning does not stop the build: the model compiles and runs
  [4]  (* openvaf_allow="contribution_to_input_port" *) on the statement, and -A, silence it; -E makes it an error
  [5]  --lints lists contribution_to_input_port as L031 among the warnings
  [6]  a branch whose other end is an internal node still names the input port; a second contribution on a clean branch adds no warning

Enhancement-686 (F4 of the 2026-09-21 hunt): LRM 6.3.6 has the simulator scale
every flow contribution by $mfactor and says it "shall issue a warning" on a
misuse that double-scales -- its `badres`, `I(a,b) <+ V(a,b)/r * $mfactor`,
"will generate an error". Nothing was said. Lint L037 `mfactor_double_scaling`
(warn) reports a flow contribution whose value depends on $mfactor, directly or
through a variable assigned from it; a `?:` condition, an `if` condition (the
LRM's `parares`), a potential contribution, a display and an opvar are not
values of a flow contribution and stay silent.
  [7]  badres, the variable route, a noise contribution: each warned once at the read; parares, a ?: condition,
       a potential contribution, a display: silent
  [8]  the allow attribute and -A silence it, -E makes it an error, --lints lists it as L037
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
WORK = tempfile.mkdtemp(prefix="inputport_")
HDR = '`include "disciplines.vams"\n'


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


def l031(msg):
    return re.findall(r"^(warning|error)\[L031\]: contribution to the input port '(\w+)'", msg, re.M)


print("Enhancement-639: a contribution to a port declared `input` is warned\n")

M = "module m(p,n); input p; inout n; electrical p,n;\n"
forms = {
    "I(p,n) <+": M + "analog I(p,n) <+ V(p,n)/1k; endmodule\n",
    "V(p,n) <+": M + "analog V(p,n) <+ 1; endmodule\n",
    "V(p) <+": M + "analog V(p) <+ 1; endmodule\n",
    "branch (p,n)": M + "branch (p,n) b; analog I(b) <+ V(b)/1k; endmodule\n",
    "branch (p)": M + "branch (p) bg; analog I(bg) <+ V(bg)/1k; endmodule\n",
}
r = {}
for i, (form, src) in enumerate(forms.items()):
    ok, msg = compile_src(src, f"c1_{i}")
    hits = l031(msg)
    r[form] = ok and hits == [("warning", "p")] and "LRM 5.6.1" in msg and "declared `input`" in msg
check("[1] every contribution form on an input port is warned once, naming the port and LRM 5.6.1",
      all(r.values()), " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in r.items()))

ok1, msg1 = compile_src(M + "analog I(n) <+ V(p,n)/1k + I(<p>)*0; endmodule\n", "c2a")
ok2, msg2 = compile_src("module m(p,n); output p; inout n; electrical p,n; analog I(p,n) <+ V(p,n)/1k; endmodule\n", "c2b")
ok3, msg3 = compile_src("module m(p,n); inout p,n; electrical p,n; analog I(p,n) <+ V(p,n)/1k; endmodule\n", "c2c")
check("[2] probes only (V(p,n), I(<p>)) on an input port are silent; a contribution to an output or inout port is silent",
      ok1 and ok2 and ok3 and not l031(msg1) and not l031(msg2) and not l031(msg3), (msg1 + msg2 + msg3)[-200:])

ok, msg = compile_src(forms["I(p,n) <+"], "c3")
deck = os.path.join(WORK, "c3.cir")
with open(deck, "w") as f:
    f.write("* inputport c3\nv1 a 0 1\nn1 a 0 mm\n.model mm m\n.control\nset noinit\npre_osdi c3.osdi\nop\nprint i(v1)\n.endc\n.end\n")
p = subprocess.run([NGSPICE, "-b", "c3.cir"], capture_output=True, text=True, timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
m = re.search(r"^i\(v1\)\s*=\s*(\S+)", p.stdout + p.stderr, re.M)
check("[3] the warning does not stop the build: the model compiles and runs (1 mA)",
      ok and m and abs(float(m.group(1)) + 1e-3) < 1e-9, (p.stdout + p.stderr)[-200:])

ok_a, msg_a = compile_src(M + 'analog (* openvaf_allow="contribution_to_input_port" *) I(p,n) <+ V(p,n)/1k; endmodule\n', "c4a")
ok_b, msg_b = compile_src(forms["I(p,n) <+"], "c4b", flags=["-A", "contribution_to_input_port"])
ok_c, msg_c = compile_src(forms["I(p,n) <+"], "c4c", flags=["-E", "L031"])
check("[4] the statement attribute and -A silence it; -E L031 makes it an error that fails the build",
      ok_a and not l031(msg_a) and ok_b and not l031(msg_b) and (not ok_c) and l031(msg_c) == [("error", "p")],
      f"{l031(msg_a)} {l031(msg_b)} {l031(msg_c)} rc_c={ok_c}")

r = subprocess.run([VAF, "--lints"], capture_output=True, text=True)
lines = r.stdout.splitlines()
i_w = next((i for i, l in enumerate(lines) if l.strip() == "WARNINGS:"), -1)
i_x = next((i for i, l in enumerate(lines) if "contribution_to_input_port" in l), -1)
i_next = next((i for i, l in enumerate(lines) if i > i_w and l.strip().endswith(":") and i_w >= 0), len(lines))
check("[5] --lints lists contribution_to_input_port as L031 under WARNINGS",
      i_w >= 0 and i_x > i_w and i_x < i_next and "L031" in lines[i_x], lines[i_x] if i_x >= 0 else r.stdout[-200:])

ok, msg = compile_src("module m(p,n,x); input p; inout n; output x; electrical p,n,x; analog begin I(x,n) <+ V(p,n)/1k; I(p,x) <+ 1e-9*V(p,x); end endmodule\n", "c6")
check("[6] a branch (p,x) to an internal/output node still names the input port p, and the clean branch (x,n) adds no warning",
      ok and l031(msg) == [("warning", "p")], f"{l031(msg)}")


def l037(msg):
    return re.findall(r"^(warning|error)\[L037\]: `\$mfactor` scales this flow contribution a second time", msg, re.M)


print("\nEnhancement-686: `$mfactor` in a flow contribution is scaled twice (LRM 6.3.6)")
B = "module b(a,b); inout a,b; electrical a,b; parameter real r = 1.0 from (0:inf);\n"
warned = {
    "badres": B + "analog I(a,b) <+ V(a,b) / r * $mfactor; endmodule\n",
    "via a variable": B + "real mf, g; analog begin mf = $mfactor; g = mf / r; I(a,b) <+ g * V(a,b); end endmodule\n",
    "noise": B + "analog I(a,b) <+ V(a,b)/r + white_noise(1e-20 * $mfactor, \"th\"); endmodule\n",
}
silent = {
    "parares": B + "analog if (r / $mfactor < 1.0e-3) V(a,b) <+ 0.0; else I(a,b) <+ V(a,b) / r; endmodule\n",
    "?: condition": B + "real reff; analog begin reff = r / $mfactor; I(a,b) <+ (reff < 1e-3) ? 0.0 : V(a,b) / r; end endmodule\n",
    "potential": B + "analog V(a,b) <+ I(a,b) * r * $mfactor * 0.0; endmodule\n",
    "display and opvar": B + "(* desc=\"m\" *) real mf; analog begin mf = $mfactor; $strobe(\"%g\", $mfactor); I(a,b) <+ V(a,b) / r; end endmodule\n",
}
rw, rs = {}, {}
for i, (k, src) in enumerate(warned.items()):
    ok, msg = compile_src(src, f"c7w_{i}")
    rw[k] = ok and len(l037(msg)) == 1 and "LRM 6.3.6" in msg and "badres" in msg
for i, (k, src) in enumerate(silent.items()):
    ok, msg = compile_src(src, f"c7s_{i}")
    rs[k] = ok and not l037(msg)
check("[7] badres, the variable route and a noise contribution are each warned once (L037, LRM 6.3.6); "
      "parares, a ?: condition, a potential contribution, a display and an opvar are silent",
      all(rw.values()) and all(rs.values()),
      " ".join(f"{k}:{'ok' if v else 'BAD'}" for k, v in {**rw, **rs}.items()))
ok1, m1 = compile_src(B + "analog begin (* openvaf_allow=\"mfactor_double_scaling\" *) I(a,b) <+ V(a,b) / r * $mfactor; end endmodule\n", "c8a")
ok2, m2 = compile_src(warned["badres"], "c8b", ("-A", "mfactor_double_scaling"))
ok3, m3 = compile_src(warned["badres"], "c8c", ("-E", "mfactor_double_scaling"))
lst = subprocess.run([VAF, "--lints"], capture_output=True, text=True).stdout
check("[8] the allow attribute and -A silence it, -E makes it an error that stops the build, --lints lists L037",
      ok1 and not l037(m1) and ok2 and not l037(m2) and not ok3 and l037(m3) == ["error"]
      and re.search(r"mfactor_double_scaling\s+L037", lst) is not None,
      (m1 + m2 + m3)[-200:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
