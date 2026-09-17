#!/usr/bin/env python3
"""Enhancement-653: `exit` is a second name for `quit`.

`exit` was not an ngspice command: in a `.control` block it printed
"exit: no such command available in ngspice" and the block went on with its
next line; at the prompt the same. It is now a second table entry for
`com_quit`, in the ngspice and the nutmeg command tables, with the same
optional argument -- an exit status or the word `noask` -- and `sweep
-analysis exit` is refused like `-analysis quit` is.

Checks:
  [1]  `exit` in a .control block: no "no such command", the lines after it
       do not run, the "done" banner, status 0
  [2]  `exit 3` ends with status 3
  [3]  `exit noask` ends with status 0
  [4]  `exit 7` inside an `if` ends with status 7
  [5]  `exit 2` inside a `repeat` loop ends on the first pass, status 2
  [6]  `quit` and `quit 5` unchanged
  [7]  pipe mode (-p): `exit` ends the session, the next line is never read;
       `exit 4` gives status 4
  [8]  `oldhelp exit` prints the entry; `oldhelp quit` unchanged
  [9]  `set askquit`: after an `op`, `exit` asks "Are you sure you want to
       quit (yes)?" and a `yes` ends the session; `exit noask` does not ask
  [10] `sweep ... -analysis exit` is refused up front ("would destroy the
       circuit"), like `-analysis quit`, and the script continues
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="exitcmd_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


DECK = "* exitcmd {tag}\nv1 in 0 dc 1\nr1 in out 1k\nr2 out 0 1k\n.control\nop\necho before\n{cmds}\necho after\n.endc\n.end\n"


def batch(cmds, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(DECK.format(tag=tag, cmds=cmds))
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


def pipe(lines):
    p = subprocess.run([NGSPICE, "-p"], input=lines, capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


def ended(out):
    return ("no such command" not in out and "\nafter" not in out
            and "before" in out and "done" in out)


rc, out = batch("exit", "b1")
check("[1] `exit` in a .control block ends the run: no 'no such command', nothing after it, status 0",
      rc == 0 and ended(out), f"rc={rc} " + out[-200:].replace("\n", "|"))

rc, out = batch("exit 3", "b2")
check("[2] `exit 3` ends with status 3", rc == 3 and ended(out), f"rc={rc}")

rc, out = batch("exit noask", "b3")
check("[3] `exit noask` ends with status 0", rc == 0 and ended(out), f"rc={rc}")

rc, out = batch("if 1\n  exit 7\nend", "b4")
check("[4] `exit 7` inside an `if` ends with status 7", rc == 7 and ended(out), f"rc={rc}")

rc, out = batch("repeat 3\n  echo pass\n  exit 2\nend", "b5")
check("[5] `exit 2` inside a `repeat` ends on the first pass, status 2",
      rc == 2 and ended(out) and out.count("\npass") == 1, f"rc={rc} passes={out.count(chr(10) + 'pass')}")

rc1, out1 = batch("quit", "b6a")
rc2, out2 = batch("quit 5", "b6b")
check("[6] `quit` and `quit 5` unchanged", rc1 == 0 and ended(out1) and rc2 == 5 and ended(out2),
      f"rc={rc1},{rc2}")

rc, out = pipe("echo first\nexit\necho not reached\n")
rc4, out4 = pipe("echo first\nexit 4\necho not reached\n")
check("[7] pipe mode: `exit` ends the session before the next line; `exit 4` gives status 4",
      rc == 0 and rc4 == 4 and "first" in out and "not reached" not in out and "not reached" not in out4
      and "no such command" not in out, f"rc={rc},{rc4} " + out[-160:].replace("\n", "|"))

rc, out = pipe("oldhelp exit\noldhelp quit\nquit\n")
check("[8] `oldhelp exit` prints the entry; `oldhelp quit` unchanged",
      "exit : Quit ngspice (the same as quit)." in out and "quit : Quit ngspice." in out,
      out[-200:].replace("\n", "|"))

with open(os.path.join(WORK, "a.cir"), "w") as f:
    f.write("* askquit\nv1 in 0 dc 1\nr1 in 0 1k\n.end\n")
rc, out = pipe("source a.cir\nop\nset askquit\nexit\nyes\necho not reached\n")
rcn, outn = pipe("source a.cir\nop\nset askquit\nexit noask\necho not reached\n")
check("[9] `set askquit`: `exit` asks and a `yes` ends the session; `exit noask` does not ask",
      rc == 0 and "Are you sure you want to quit (yes)?" in out and "not reached" not in out
      and rcn == 0 and "Are you sure" not in outn and "not reached" not in outn,
      f"rc={rc},{rcn} " + out[-160:].replace("\n", "|"))

sweep_deck = ("* sweep\n.param pr=1k\nv1 in 0 dc 1\nr1 in out {pr}\nr2 out 0 1k\n.control\nop\n"
              "sweep pr lin 3 1k 3k -analysis exit -output v(out)\necho after-exit\n"
              "sweep pr lin 3 1k 3k -analysis quit -output v(out)\necho after-quit\n.endc\n.end\n")
with open(os.path.join(WORK, "s.cir"), "w") as f:
    f.write(sweep_deck)
p = subprocess.run([NGSPICE, "-b", os.path.join(WORK, "s.cir")], capture_output=True, text=True,
                   timeout=120, cwd=WORK)
out = p.stdout + p.stderr
check("[10] `sweep -analysis exit` is refused up front like `-analysis quit`, and the script continues",
      p.returncode == 0 and out.count("would destroy the circuit") == 2
      and "after-exit" in out and "after-quit" in out,
      f"rc={p.returncode} refusals={out.count('would destroy the circuit')} " + out[-200:].replace("\n", "|"))

print(f"\n{passed} of {checks} checks passed")
sys.exit(0 if passed == checks else 1)
