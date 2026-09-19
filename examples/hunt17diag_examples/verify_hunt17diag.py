#!/usr/bin/env python3
"""Enhancement-665: the diagnostic slips and run-time silences of the 2026-09-18
hunt (F11, F12, F13, F15), each pinned end-to-end through the committed
openvaf-r (and ngspice for the two run-time cases).

  a  `1e3n`, `0.5e`, `1meg` were "unexpected token identifier; expected 'exclude'
     or 'from'" (the leftover letters, in the range-clause vocabulary); now one
     located "malformed number literal `1e3n`" with the LRM 2.6.2 rule, and
     `1meg` told that Verilog-A's mega is `1M`.
  b  a node-array index out of range summarised "could not compile
     `x.va__namerange.va`" -- the elaborated copy; the summary names the source.
  c  `nature Qx; access = Qx;` was "'Qx' was already declared" plus two
     knock-ons; now the rule: the access function needs a name of its own.
  d  `forever begin ... end` was "expected ';'" plus "'forever' was not found";
     now one error naming the loops Verilog-A has (LRM A.6.4).
  e  a non-ASCII identifier was "encountered unexpected token!" (no noun).
  f  `(* desc= *)` was the generic expression-start list; now "no value after '='".
  g  an undeclared macro reference left a hole the parser then complained
     about (`= ;`); the reference now leaves a `0` behind, one error. E-672:
     at file scope and in statement position the `0` itself drew a second
     error inside the virtual `__macro_synth.va`; a syntax error at a hole is
     dropped, and `__LINE__` in the same position is still reported.
  h  `(* corner="ss=0.5 %" *)` blamed the stray `%`; now the reason (no space).
  i  `parameter string s = "z" from {"x", "y"}` compiled without L027.
  j  an escaped identifier `\\foo+bar` exported `foo+bar`, which ngspice reads as
     a subtraction; L036 now names any character ngspice cannot read, not `$` only.
  k  a flat sum of 999 parameters tripped the nesting limit and then reported
     "'p997' was not found" and "'p998' was already declared"; one error now.
  l  `absdelay(V, td)` with a parameter `td = -1e-9` and `$bound_step(bs)` with
     `bs = -1e-9` ran in silence; the deck-fixed value is now said once per
     accepted point (E-651's rule) and projected (0 delay; the bound ignored).
     A run-time variable is projected in silence, as E-651 does.
  m  withdrawn on re-check, pinned as expected behaviour: `` `ifdef Z 6 `` -- the
     text after the name is the conditional group (LRM 10.x), skipped when Z
     is undefined; `$discontinuity(-1)` is the limiting-discontinuity marker
     (E-420 refuses anything below it).
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
WORK = tempfile.mkdtemp(prefix="hunt17diag_")
HDR = '`include "disciplines.vams"\n'
H = "module m(p, n); inout p, n; electrical p, n;\n"
T = "analog I(p,n) <+ V(p,n)*1e-3;\nendmodule\n"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag, *flags, hdr=True):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write((HDR if hdr else "") + src)
    r = subprocess.run([VAF, *flags, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def errors(msg):
    return [l for l in msg.splitlines() if l.startswith("error") and "could not compile" not in l]


def run(deck, ctl, osdi, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hunt17diag {tag}\n{deck}\n.control\nset noinit\npre_osdi {osdi}.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


# ------------------------------------------------------------- [a] ---
for lit, note in (("1e3n", "not both"), ("0.5e", "digits after the `e`"), ("1meg", "`1M`")):
    ok, msg = compile_src(H + f"parameter real r = {lit};\n" + T, "lit_" + lit.replace(".", "_"))
    e = errors(msg)
    check(f"[a] `{lit}`: one located error naming the literal, with its rule; not the range-clause vocabulary",
          not ok and len(e) == 1 and f"malformed number literal `{lit}`" in e[0] and note in msg and "expected 'exclude'" not in msg,
          "; ".join(e) or msg[:120])

# ------------------------------------------------------------- [b] ---
ok, msg = compile_src(H + "electrical a[0:1];\nanalog I(a[2], n) <+ V(p,n)*1e-3;\nendmodule\n", "nodearr")
check("[b] a node-array index out of range: the summary names the source file, not the elaborated copy",
      not ok and "could not compile `nodearr.va`" in msg and "__namerange" not in msg.split("could not compile")[-1], msg[-160:].replace("\n", "|"))

# ------------------------------------------------------------- [c] ---
ok, msg = compile_src('nature Qx; access = Qx; units = "C"; abstol = 1e-12; endnature\n'
                      'discipline dd; potential Voltage; flow Qx; enddiscipline\n'
                      'module m(p,n); inout p,n; dd p,n;\nanalog Qx(p,n) <+ V(p,n)*1e-3;\nendmodule\n', "natacc")
check("[c] `nature Qx; access = Qx;`: the rule is named (a name of its own), no 'already declared'",
      not ok and "nature 'Qx' names its access function 'Qx' too" in msg and "already declared" not in msg
      and "LRM 3.6.1" in msg, "; ".join(errors(msg)))

# ------------------------------------------------------------- [d] ---
ok, msg = compile_src(H + "integer i;\nanalog begin forever begin i = 1; end I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n", "forever")
e = errors(msg)
check("[d] `forever begin ... end`: one error, the loops Verilog-A has named; no 'forever was not found'",
      not ok and len(e) == 1 and "a bare identifier before `begin`" in e[0] and "repeat (n)" in msg and "was not found" not in msg,
      "; ".join(e))

# ------------------------------------------------------------- [e] ---
ok, msg = compile_src(H + "parameter real rö = 1;\n" + T, "nonascii")
check("[e] a non-ASCII identifier: the headline has a noun; the lookalike note still says which character",
      not ok and "unexpected character(s) in the source" in msg and "encountered unexpected token" not in msg, errors(msg)[0] if errors(msg) else msg[:100])

# ------------------------------------------------------------- [f] ---
ok, msg = compile_src(H + "(* desc= *) parameter real r = 1;\n" + T, "descempty")
e = errors(msg)
check("[f] `(* desc= *)`: 'no value after =', not the expression-start list", not ok and len(e) == 1 and "has no value after '='" in e[0] and "system function identifier" not in msg, "; ".join(e))

# ------------------------------------------------------------- [g] ---
ok, msg = compile_src("`define X 1\n`undef X\n" + H + "parameter real r = `X;\n" + T, "undefuse")
e = errors(msg)
check("[g] an undeclared macro reference: one error, no knock-on about the hole it left", not ok and len(e) == 1 and "has not been declared" in e[0], "; ".join(e))
# Enhancement-672 (hunt F5 of 2026-09-19): the hole at FILE scope -- a
# misspelled directive alone on its line -- was "unexpected token integer;
# expected 'discipline', 'nature' or 'module'" at a position inside the virtual
# `__macro_synth.va`. The hole's context is marked and the parser drops any
# syntax error located at it; a legitimate synthesized token (`__LINE__`) in
# the same position is not a hole and is still reported.
ok, msg = compile_src("`unknown_directive\n" + H + T, "undeffile")
e = errors(msg)
check("[g] ...at file scope (a misspelled directive alone on its line): one error, nothing about `__macro_synth.va`",
      not ok and len(e) == 1 and "has not been declared" in e[0] and "__macro_synth" not in msg, "; ".join(e))
ok, msg = compile_src(H + "analog begin\n`nosuch\n I(p,n) <+ V(p,n)*1e-3;\nend\nendmodule\n", "undefstmt")
e = errors(msg)
check("[g] ...in statement position: one error", not ok and len(e) == 1 and "has not been declared" in e[0], "; ".join(e))
ok, msg = compile_src("`__LINE__\n" + H + T, "linefile")
e = errors(msg)
check("[g] ...`__LINE__` alone at file scope is not a hole: still refused as an unexpected integer", not ok and len(e) == 1 and "unexpected token integer" in e[0], "; ".join(e))

# ------------------------------------------------------------- [h] ---
ok, msg = compile_src(H + '(* corner="ss=0.5 %" *) parameter real r = 1;\n' + T, "cornerpct")
check("[h] `corner=\"ss=0.5 %\"`: the reason is the space, and the value was taken as absolute",
      not ok and "written without a space" in msg and "read as an absolute value" in msg, errors(msg)[0][:160] if errors(msg) else msg[:100])

# ------------------------------------------------------------- [i] ---
ok, msg = compile_src(H + 'parameter string s = "z" from {"x", "y"};\nparameter string t = "x" from {"x", "y"};\n'
                      'parameter string u = "q" exclude "q";\n' + T, "strfrom")
w = re.findall(r"warning\[L027\]: (.*)", msg)
check("[i] a string default outside its `from` set, and one its `exclude` names: L027 each; one inside: none",
      ok and len(w) == 2 and any("'s'" in x for x in w) and any("'u'" in x for x in w) and not any("'t'" in x for x in w)
      and "\"z\" satisfies none" in msg and "\"q\" is a value" in msg, "; ".join(w))

# ------------------------------------------------------------- [j] ---
ok, msg = compile_src(H + "parameter real \\foo+bar = 1;\nparameter real a$b = 2;\n" + T, "escaped")
w = re.findall(r"warning\[L036\]: (.*)", msg)
check("[j] `\\foo+bar` exports `foo+bar`: L036 names the `+`; `a$b` still names the `$`",
      ok and len(w) == 2 and any("'foo+bar' has a `+`" in x for x in w) and any("'a$b' has a `$`" in x for x in w), "; ".join(w))

# ------------------------------------------------------------- [k] ---
n = 999
deep = H + "".join(f"parameter real p{i} = 1;\n" for i in range(n)) + "analog I(p,n) <+ V(p,n)*1e-3 + 0*(" + "+".join(f"p{i}" for i in range(n)) + ");\nendmodule\n"
ok, msg = compile_src(deep, "deep")
e = errors(msg)
check("[k] a flat sum of 999 parameters: the nesting limit, once, and nothing about the parameters after it",
      not ok and len(e) == 1 and "nests too deeply" in e[0] and "was not found" not in msg and "already declared" not in msg, "; ".join(e))

# ------------------------------------------------------------- [l] ---
ok1, _ = compile_src(H + "parameter real td = -1e-9;\nanalog I(p,n) <+ absdelay(V(p,n), td)*1e-3;\nendmodule\n", "adp")
ok2, _ = compile_src(H + "real td;\nanalog begin td = -1e-9; I(p,n) <+ absdelay(V(p,n), td)*1e-3; end\nendmodule\n", "adv")
ok3, _ = compile_src(H + "parameter real bs = -1e-9;\nanalog begin $bound_step(bs); I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n", "bsp")
ok4, _ = compile_src(H + "parameter real bs = 1e-7;\nanalog begin $bound_step(bs); I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n", "bsok")
check("[l] the four run-time models compile", ok1 and ok2 and ok3 and ok4)
if ok1 and ok2 and ok3 and ok4:
    DECK = "v1 in 0 dc 0 pulse(0 1 1u 1n 1n 5u 10u)\nn1 in 0 mm\n.model mm m"
    out = run(DECK, "tran 1u 6u\nprint length(time)", "adp", "adp_run")
    check("[l] absdelay with a parameter delay of -1e-9: the warning names the value and the LRM rule, 0 is used; the run completes",
          "absdelay: the delay is -1e-09, negative (LRM 4.5.7" in out and "0 is used" in out and "length(time)" in out, out[-200:].replace("\n", "|"))
    out = run(DECK, "tran 1u 6u\nprint length(time)", "adv", "adv_run")
    check("[l] ...a run-time variable delay is projected in silence (E-651's rule)", "absdelay:" not in out and "length(time)" in out, out[-120:].replace("\n", "|"))
    out = run(DECK, "tran 1u 6u\nprint length(time)", "bsp", "bsp_run")
    check("[l] $bound_step with a parameter bound of -1e-9: the warning, the bound ignored; the run completes",
          "$bound_step: the bound is -1e-09, not positive" in out and "incumbent bound stands" in out and "length(time)" in out, out[-200:].replace("\n", "|"))
    out = run(DECK, "tran 1u 6u\nprint length(time)", "bsok", "bsok_run")
    check("[l] ...a positive parameter bound: no word", "$bound_step:" not in out and "length(time)" in out, out[-120:].replace("\n", "|"))

# ------------------------------------------------------------- [m] ---
ok, msg = compile_src("`ifdef Z 6\n`endif\n" + H + T, "ifdeftok")
check("[m] `` `ifdef Z 6 `` with Z undefined: the `6` is the skipped group's text (LRM), compiles without a word", ok and "warning" not in msg, msg[:100])
ok, msg = compile_src(H + "analog begin $discontinuity(-1); $discontinuity(-2); I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n", "discneg")
check("[m] `$discontinuity(-1)` is the limiting-discontinuity marker (accepted); `-2` is refused (E-420)",
      not ok and len(errors(msg)) == 1 and "-2" in msg and "$discontinuity" in msg, "; ".join(errors(msg)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
