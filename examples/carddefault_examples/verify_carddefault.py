#!/usr/bin/env python3
"""Enhancement-599: a .model card's instance defaults are visible and movable,
and a hoisted `pre_osdi -f` says where it runs.

F4 of the 2026-09-10 integration hunt: `.model am alias width=3` is honoured
(an instance without `w` reads 3) but `showmod am` did not list it and
`altermod am width=5` was refused with a message recommending the very card
it could not change -- after the card's defaults are replayed onto the
instances, nothing could tell an instance that took the default from one
that wrote its own. The parser keeps that distinction now (INPcardDefaultNote),
so `altermod` moves the default onto the instances that follow the card,
leaves the ones that set their own value (on the line, or by a later `alter`),
records it on the card, and `showmod` lists the card's instance defaults.

F5: every `pre_` line in a control block is hoisted into the pre-pass, so a
`pre_osdi -f` written after a `shell` that recompiles the file ran before
it, said "reloaded", and reloaded the old object. A `-f` behind other
commands in its block now gets a Note naming `osdi -f` as the form that acts
there; ordinary layouts stay quiet. And `pre_osdi` is a live command at the
prompt, where it used to be "no such command".

Checks:
  [1] showmod lists the card's instance defaults, by the card's spelling
  [2] altermod moves the default onto the followers only; the line's own
      value and an `alter`ed value are kept; the count is reported
  [3] an alias spelling on the card and the base name in the command are one
      parameter: no duplicate row, the row updated
  [4] a model whose card carried no default: altermod establishes one
  [5] nothing follows: recorded, and the message says nothing changes
  [6] reading the parameter through the model name names the card's default
      when there is one
  [7] the pre-pass Note fires for `pre_osdi -f` behind commands and not for
      a plain `pre_osdi` after a `set`
  [8] `pre_osdi` typed at the prompt loads the file
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
WORK = tempfile.mkdtemp(prefix="carddefault_")
N1, N2, N3, AM = "@" + "n1", "@" + "n2", "@" + "n3", "@" + "am"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "cd.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule cd(p, n);\ninout p, n; electrical p, n;\n'
            'parameter real r = 1k from (0:inf);\naliasparam res = r;\n'
            '(* type="instance" *) parameter real w = 1 from (0:inf);\naliasparam width = w;\n'
            'analog I(p,n) <+ V(p,n)*w/r;\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "cd.va"), "-o", os.path.join(WORK, "cd.osdi")], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(deck, ctl, tag, pre="pre_osdi cd.osdi"):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* carddefault {tag}\n.control\n{pre}\n.endc\nv1 a 0 1\n{deck}\n.control\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def vals(out):
    return {m.group(1).lower(): float(m.group(2)) for m in re.finditer(r"(?m)^(@\S+) = (\S+)", out)}


DECK = f"n1 a 0 am w=2\nn2 a 0 am\nn3 a 0 am width=4\n.model am cd width=3 r=1k"
PR = f"print {N1}[w]\nprint {N2}[w]\nprint {N3}[w]"

print("Enhancement-599: card-level instance defaults, and the hoisted pre_osdi -f\n")

# ------------------------------------------------------------- [1] ---
out = run(DECK, "op\nshowmod am\n" + PR, "t1")
v = vals(out)
check("[1] the card's default is honoured: n2 reads 3, n1 its own 2, n3 its own 4",
      v.get(f"{N1}[w]") == 2 and v.get(f"{N2}[w]") == 3 and v.get(f"{N3}[w]") == 4, f"{v}")
check("[1] showmod lists it under 'instance defaults on this card', by the card's spelling",
      re.search(r"instance defaults on this card:\s*\n\s*width\s+3\b", out) is not None, out[-300:])

# ------------------------------------------------------------- [2] ---
out = run(DECK, "op\naltermod am width=5\nop\n" + PR + f"\nalter {N2}[w] = 9\naltermod am w=6\nop\n" + PR, "t2")
v = vals(out)
first = re.search(r"altermod: 'width' is an instance parameter; 5 is now the default of model am -- 1 instance follows it, 2 keep their own value", out)
check("[2] altermod moves the default onto the follower only, and says 1 follows / 2 keep", first is not None, out[-400:])
prints = re.findall(rf"(?m)^{re.escape(N2)}\[w\] = (\S+)", out)
check("[2] ...n2 reads 5 after it; n1 and n3 keep 2 and 4",
      len(prints) == 2 and float(prints[0]) == 5 and v.get(f"{N1}[w]") == 2 and v.get(f"{N3}[w]") == 4, f"{prints} {v}")
check("[2] after `alter @n2[w]=9` the next altermod leaves n2 alone (0 follow, 3 keep)",
      "6 is recorded as the default of model am, but every one of its 3 instances sets its own value, so nothing changes" in out
      and float(prints[1]) == 9, f"{prints}")

# ------------------------------------------------------------- [3] ---
out = run(DECK, "op\naltermod am w=5\nshowmod am", "t3")
rows = re.findall(r"(?m)^\s+(width|w)\s+(\S+)\s*$", out.split("instance defaults on this card:")[-1])
check("[3] the card's `width=3` and the command's `w=5` are one parameter: one row, updated to 5",
      rows == [("width", "5")], f"{rows}")

# ------------------------------------------------------------- [4] ---
out = run("n1 a 0 am\nn2 a 0 am w=2\n.model am cd r=1k", "op\naltermod am w=7\nop\n" + f"print {N1}[w]\nprint {N2}[w]\nshowmod am", "t4")
v = vals(out)
check("[4] a card without a default: altermod establishes one (n1 follows: 7; n2 keeps 2) and showmod lists it",
      v.get(f"{N1}[w]") == 7 and v.get(f"{N2}[w]") == 2 and re.search(r"instance defaults on this card:\s*\n\s*w\s+7\b", out) is not None
      and "1 instance follows it, 1 keeps its own value" in out, f"{v}")

# ------------------------------------------------------------- [5] ---
out = run("n1 a 0 am w=2\n.model am cd r=1k", "op\naltermod am w=7\nop\n" + f"print {N1}[w]", "t5")
check("[5] every instance sets its own: recorded, 'nothing changes', n1 keeps 2",
      "7 is recorded as the default of model am, but every one of its 1 instance sets its own value, so nothing changes" in out
      and vals(out).get(f"{N1}[w]") == 2, out[-300:])

# ------------------------------------------------------------- [6] ---
out = run(DECK, f"op\nprint {AM}[w]", "t6")
check(f"[6] reading {AM}[w] still refuses, and names the card's default of 3",
      "the .model card gives w=3 as the default of the instances that do not set it" in out and "showmod am" in out, out[-300:])
out = run("n1 a 0 am\n.model am cd r=1k", f"op\nprint {AM}[w]", "t6b")
check("[6] ...and without a card default the message is unchanged",
      "a model has no value of its own to read. Read it from an instance" in out, out[-300:])

# ------------------------------------------------------------- [7] ---
out = run("n1 a 0 am\n.model am cd r=1k", "op\nshell true\npre_osdi -f cd.osdi\nop\nprint v(a)", "t7")
check("[7] `pre_osdi -f` behind three commands: the Note names the pre-pass, the count and `osdi -f`",
      "is a pre-pass command: it runs before the circuit is read, ahead of the 3 commands above it" in out
      and "write it without the prefix: `osdi -f cd.osdi`" in out, out[-400:])
out = run("n1 a 0 am\n.model am cd r=1k", "op\nprint v(a)", "t7b", pre="set ngbehavior=ltpsa\npre_osdi cd.osdi")
check("[7] ...and the hoisted reload of a relative name works when ngspice runs elsewhere (was: 'could not stage a reload copy')",
      'reloaded "cd.osdi"' in subprocess.run([NGSPICE, "-b", os.path.join(WORK, "t7.cir")], capture_output=True, text=True,
                                             timeout=120, cwd=HERE).stdout, "")
check("[7] a plain `pre_osdi` after a `set` stays quiet", "pre-pass command" not in out and "v(a) = " in out, out[-200:])
out = run("n1 a 0 am\n.model am cd r=1k", "op\nprint v(a)", "t7c", pre="pre_osdi -f cd.osdi")
check("[7] `pre_osdi -f` at the head of its block stays quiet too", "pre-pass command" not in out and "v(a) = " in out, out[-200:])

# ------------------------------------------------------------- [8] ---
with open(os.path.join(WORK, "use.cir"), "w") as f:
    f.write("* use\nv1 a 0 1\nn1 a 0 am\n.model am cd r=2k\n.end\n")
p = subprocess.run([NGSPICE, "-p"], input="pre_osdi cd.osdi\nsource use.cir\nop\nprint i(v1)\nquit\n",
                   capture_output=True, text=True, timeout=120, cwd=WORK)
out = p.stdout + p.stderr
check("[8] `pre_osdi cd.osdi` typed at the prompt loads the file (was 'no such command')",
      "no such command" not in out and re.search(r"i\(v1\) = -5\.0+e-04", out) is not None, out[-300:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
