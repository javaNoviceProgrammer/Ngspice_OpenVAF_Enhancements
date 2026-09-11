#!/usr/bin/env python3
"""Enhancement-604: a numparam failure refuses the line, or the deck -- not the
process.

N5 of the 2026-09-10 integration hunt. `w=nan` or a trailing `w=` on an
instance line reached numparam as the brace expression {nan} / {}, could not be
evaluated, and every numparam error ended the process at nupa_done():
"ERROR: fatal error in ngspice, exit(1)" -- the interactive session and
everything sourced before it included -- where `w=1e400` on the same line is
refused at the line level ("Error on line 3 or its substitute"). The line
number in numparam's message was also mislabelled (the internal number printed
as the netlist's and vice versa), and inp_dodeck() printed only the FIRST line
of a card's error text, returning before the rest.

Now a failure on a device, model or dot card is attached to the card
(nupa_error, folded into the card's error after the parse) and the deck reader
refuses the line as it refuses any other parse error, showing the author's own
text, numparam's reason and what the parser made of the unevaluated text; a
failure elsewhere (.param, .func, a subcircuit call's value) refuses the deck,
as an unknown subcircuit does, and the batch exit status is the same as for any
refused deck. A .model card with such a failure is an error, not a "Model
issue" warning that would run the model on its default.

Checks (built-in devices, then OSDI):
  [1] w=nan: refused as a line, the line in the author's text, numparam's
      reason and the parser's message both shown; no "fatal error"; exit 1
  [2] a trailing w=: "the value is missing -- nothing follows the '='"
  [3] an interactive session that sources the bad deck survives, and its
      previous circuit still answers
  [4] .param k = nosuch + 1: the deck refused ("the circuit is not loaded"),
      the session alive; exit 1 in batch
  [5] a subcircuit call's p={nosuch}: the deck refused; the message names the
      netlist line (6), not the internal one
  [6] {nosuch} in a node position: refused (the parser alone would take it as
      a node name)
  [7] .model rm r r={nosuch}: an error, not a model-issue warning; no run
  [8] v1 in 0 dc {nan}: refused
  [9] what stays: a deck whose braces evaluate runs unchanged; w=1e400 is
      refused as before, with its own text
  [10] an OSDI instance line with w=nan: the same refusal
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
WORK = tempfile.mkdtemp(prefix="nupafail_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "rw.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule rw(p, n);\ninout p, n; electrical p, n;\n'
            'parameter real r = 1k from (0:inf);\n(* type="instance" *) parameter real w = 1u from (0:inf);\n'
            'analog I(p,n) <+ V(p,n)/r*w/1u;\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "rw.va"), "-o", os.path.join(WORK, "rw.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)

DIV = "v1 in 0 dc 1\nr1 in out 1k\nr2 out 0 1k\n"


def deck(tag, body):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* nupafail {tag}\n{body}\n.end\n")
    return path


def run(tag, body):
    path = deck(tag, body)
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr, p.returncode


FATAL = "fatal error in ngspice"
NOT_LOADED = "the circuit is not loaded"
# the dual-solver harness injects an .option card as line 2 of every deck
SHIFT = 1 if os.environ.get("_NG_SOLVER") else 0


def LN(n):
    """the 'Error on line N' header for netlist line n of the deck as written"""
    return f"Error on line {n + SHIFT} or its substitute:"


REFUSED_LINE = LN(3)
print("Enhancement-604: numparam failures refuse the line or the deck, not the process\n")

# ------------------------------------------------------------- [1] ---
out, rc = run("t1", "v1 in 0 dc 1\nr1 in out 1k w=nan\nr2 out 0 1k\n.op\n.print op v(out)")
check("[1] w=nan: the line is refused, not the process; batch exit 1",
      FATAL not in out and REFUSED_LINE in out and rc == 1 and "No. of Data Rows" not in out,
      f"rc={rc} {out[-300:]}")
check("[1] ...the line in the author's text, numparam's reason, and the parser's message, all printed",
      "  r1 in out 1k w={nan}" in out and "numparam: Undefined parameter [nan]" in out
      and "'nan' is not a .param name" in out and "parameter 'w': '{nan}' is not a number" in out,
      out[-400:])

# ------------------------------------------------------------- [2] ---
out, rc = run("t2", "v1 in 0 dc 1\nr1 in out 1k w=\nr2 out 0 1k\n.op\n.print op v(out)")
check("[2] a trailing w=: refused, and the reason names what is missing",
      FATAL not in out and REFUSED_LINE in out and "  r1 in out 1k w={}" in out
      and "the value is missing -- nothing follows the '='" in out and rc == 1, out[-400:])

# ------------------------------------------------------------- [3] ---
deck("bad", "v1 in 0 dc 1\nr1 in out 1k w=nan\nr2 out 0 1k\n.op")
out, rc = run("t3", DIV + ".control\nop\nprint v(out)\nsource bad.cir\necho still-alive\nprint v(out)\n.endc")
check("[3] an interactive session sourcing the bad deck survives; its circuit still answers",
      FATAL not in out and "still-alive" in out and out.count("v(out) = 5.000000e-01") == 2
      and "Error on line 3 or its substitute:" in out, out[-400:])   # bad.cir is not the harness's deck

# ------------------------------------------------------------- [4] ---
out, rc = run("t4", ".param k = nosuch + 1\nv1 in 0 dc 1\nr1 in out {k}\nr2 out 0 1k\n.op\n.print op v(out)")
check("[4] .param k = nosuch + 1: the deck is refused, the process is not ended; exit 1",
      FATAL not in out and NOT_LOADED in out and "Undefined parameter [nosuch]" in out
      and rc == 1 and "No. of Data Rows" not in out, f"rc={rc} {out[-400:]}")
deck("badp", ".param k = nosuch + 1\nv1 in 0 dc 1\nr1 in out {k}\nr2 out 0 1k\n.op")
out, rc = run("t4b", DIV + ".control\nop\nsource badp.cir\necho still-alive\nprint v(out)\n.endc")
check("[4] ...and a session sourcing it survives",
      FATAL not in out and NOT_LOADED in out and "still-alive" in out and "v(out) = 5.000000e-01" in out,
      out[-400:])

# ------------------------------------------------------------- [5] ---
out, rc = run("t5", ".subckt sub a b p=1k\nr1 a b {p}\n.ends\nv1 in 0 dc 1\nx1 in out sub p={nosuch}\n"
                    "r2 out 0 1k\n.op\n.print op v(out)")
check("[5] a subcircuit call's p={nosuch}: the deck refused; the message names netlist line 6",
      FATAL not in out and NOT_LOADED in out and f"Error in netlist line no. {6 + SHIFT}," in out and rc == 1,
      out[-400:])

# ------------------------------------------------------------- [6] ---
out, rc = run("t6", ".param k=2\nv1 in 0 dc 1\nr1 in {nosuch} 1k\nr2 out 0 1k\n.op\n.print op v(out)")
check("[6] {nosuch} in a node position: refused as a line (the parser alone would take it as a node)",
      FATAL not in out and LN(4) in out and "  r1 in {nosuch} 1k" in out
      and "numparam: Undefined parameter [nosuch]" in out and "No. of Data Rows" not in out, out[-400:])

# ------------------------------------------------------------- [7] ---
out, rc = run("t7", "v1 in 0 dc 1\nr1 in out rm\nr2 out 0 1k\n.model rm r r={nosuch}\n.op\n.print op v(out)")
check("[7] .model rm r r={nosuch}: an error, not a 'Model issue' warning; no run on the default",
      FATAL not in out and LN(5) in out and "Model issue" not in out
      and "numparam: Undefined parameter [nosuch]" in out and "No. of Data Rows" not in out
      and "resistance too low" not in out, out[-500:])

# ------------------------------------------------------------- [8] ---
out, rc = run("t8", "v1 in 0 dc {nan}\nr1 in out 1k\nr2 out 0 1k\n.op\n.print op v(out)")
check("[8] v1 in 0 dc {nan}: refused as a line",
      FATAL not in out and LN(2) in out
      and "parameter 'dc': '{nan}' is not a number" in out and "No. of Data Rows" not in out, out[-400:])

# ------------------------------------------------------------- [9] ---
out, rc = run("t9", ".param k=2k\nv1 in 0 dc 1\nr1 in out {k}\nr2 out 0 1k\n.op\n.print op v(out)")
check("[9] stays: a deck whose braces evaluate runs unchanged (out = 1/3 V)",
      rc == 0 and re.search(r"^\s*out\s+3\.333333e-01", out, re.M) and "Error" not in out, out[-300:])
out, rc = run("t9b", "v1 in 0 dc 1\nr1 in out 1k w=1e400\nr2 out 0 1k\n.op\n.print op v(out)")
check("[9] stays: w=1e400 is refused as before, with its own text",
      REFUSED_LINE in out and "parameter 'w': '1e400' is not a number" in out and rc == 1
      and "numparam" not in out, out[-300:])

# ------------------------------------------------------------ [10] ---
out, rc = run("t10", ".control\npre_osdi rw.osdi\n.endc\nv1 in 0 dc 1\nn1 in out rwm w=nan\nr2 out 0 1k\n"
                     ".model rwm rw r=1k\n.op\n.print op v(out)")
check("[10] an OSDI instance line with w=nan: the same line-level refusal",
      FATAL not in out and LN(6) in out and "  n1 in out rwm w={nan}" in out
      and "numparam: Undefined parameter [nan]" in out and "No. of Data Rows" not in out and rc == 1,
      out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
