#!/usr/bin/env python3
"""verify_sourcenest.py -- Enhancement-843: `source` nesting is bounded.

F6 of the 2026-10-10 robustness and correctness campaign. A deck that `source`s
itself, or two decks that source each other, recursed

    com_source -> inp_spsource -> the control block -> com_source

until the stack overflowed: SIGSEGV after about 3 900 levels on an 8 MB stack. A
`.spiceinit` that sources itself did the same before the deck was read. The
netlist twin, `.include`, has stopped at 50 levels since Enhancement-212;
`source` is now refused past the same depth, with the same kind of message.

  [1] a deck that sources itself: refused at level 50, exit 1, no signal
  [2] two decks that source each other: the same
  [3] a .spiceinit that sources itself: the same, before the deck
  [4] a chain of 50 nested sources runs to the bottom (the limit admits 50)
  [5] a chain of 51 is refused at the 51st
  [6] 60 sources one after another in a loop all run: the depth unwinds

Under `set interactive` (ngspice -i) a failed `source` drops to a prompt. That
prompt ran away at the end of its input -- the lexer had no case for EOF and
grew its buffer until a 2 GB realloc failed -- and once that was fixed, every
command typed there ran a second time when it ended. Both were there before for
a missing file; the depth refusal leads to the same prompt.

  [7] ngspice -i with its input at end of file: refused, the prompt ends, the
      levels unwind, exit 0 and no allocation failure
  [8] a command typed at that prompt runs once
  [9] the same prompt after a missing file: the typed command runs once, the
      prompt ends at end of input, and the deck's block goes on

[7] to [9] pipe their input, and run on POSIX systems only. The solver plays
no part, so the checks run once. Exit code 0 = pass.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

WORK = tempfile.mkdtemp(prefix="sourcenest_")
MSG = "source nesting too deep (> 50 levels)"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def write(d, name, text):
    with open(os.path.join(d, name), "w") as f:
        f.write(text)


def deck(title, body):
    # `.op` so a batch run that finishes normally exits 0 ("no simulations run" is 1)
    return f"* {title}\nr1 1 0 1k\nv1 1 0 1\n.op\n.control\n{body}\n.endc\n.end\n"


def run(d, name):
    p = subprocess.run([NGSPICE, "-b", name], cwd=d, capture_output=True, text=True,
                       timeout=120, errors="replace")
    return p.returncode, p.stdout + p.stderr


def refused(rc, out):
    """Refused by the guard: exit 1 (not a signal) and the message once."""
    return rc == 1 and out.count(MSG) == 1


def sub(name):
    d = os.path.join(WORK, name)
    os.makedirs(d)
    return d


# [1] a deck that sources itself
d = sub("self")
write(d, "s.cir", deck("s.cir", "echo LEVEL\nsource s.cir"))
rc, out = run(d, "s.cir")
n = out.count("LEVEL")
check("[1] a deck that sources itself: refused with the message, exit 1, 51 levels (the deck and 50 sources)",
      refused(rc, out) and n == 51, f"rc={rc} levels={n}")

# [2] two decks that source each other
d = sub("mutual")
write(d, "a.cir", deck("a.cir", "echo LEVEL\nsource b.cir"))
write(d, "b.cir", deck("b.cir", "echo LEVEL\nsource a.cir"))
rc, out = run(d, "a.cir")
n = out.count("LEVEL")
check("[2] two decks that source each other: refused with the message, exit 1",
      refused(rc, out) and n == 51, f"rc={rc} levels={n}")

# [3] a .spiceinit that sources itself, read from the deck's directory
d = sub("init")
write(d, ".spiceinit", "echo INIT\nsource .spiceinit\n")
write(d, "t.cir", "* t\nr1 1 0 1k\nv1 1 0 1\n.op\n.end\n")
rc, out = run(d, "t.cir")
n = out.count("INIT")
check("[3] a .spiceinit that sources itself: refused with the message, exit 1, 50 levels",
      refused(rc, out) and n == 50, f"rc={rc} levels={n}")


# [4], [5] chains of distinct decks
def chain(name, depth):
    d = sub(name)
    for i in range(depth):
        write(d, f"d{i}.cir", deck(f"d{i}", f"source d{i + 1}.cir"))
    write(d, f"d{depth}.cir", deck(f"d{depth}", "echo BOTTOM"))
    return run(d, "d0.cir")


rc, out = chain("chain50", 50)
check("[4] a chain of 50 nested sources runs to the bottom, exit 0",
      rc == 0 and "BOTTOM" in out and MSG not in out, f"rc={rc}")
rc, out = chain("chain51", 51)
check("[5] a chain of 51 is refused at the 51st, exit 1",
      refused(rc, out) and "BOTTOM" not in out and re.search(r"^\s+d51\.cir$", out, re.M) is not None,
      f"rc={rc}")

# [6] sequential sources do not accumulate depth
d = sub("loop")
write(d, "leaf.cir", deck("leaf", "echo LEAF"))
write(d, "top.cir", deck("top", "repeat 60\nsource leaf.cir\nend\necho DONE"))
rc, out = run(d, "top.cir")
n = out.count("LEAF")
check("[6] 60 sources one after another in a loop all run: the depth unwinds after each",
      rc == 0 and n == 60 and "DONE" in out and MSG not in out, f"rc={rc} leaves={n}")

# [7], [8] the prompt a failed `source` drops to under -i
if os.name == "posix":
    d = sub("interactive")
    write(d, "s.cir", deck("s.cir", "echo LEVEL\nsource s.cir"))

    def run_i(stdin_text):
        p = subprocess.run([NGSPICE, "-i", "s.cir"], cwd=d, input=stdin_text, capture_output=True,
                           text=True, timeout=120, errors="replace")
        return p.returncode, p.stdout + p.stderr

    rc, out = run_i("")
    check("[7] ngspice -i with its input at end of file: refused, the prompt ends, exit 0",
          rc == 0 and out.count(MSG) == 1 and out.count("LEVEL") == 51 and "can't allocate" not in out,
          f"rc={rc} levels={out.count('LEVEL')}")
    rc, out = run_i("echo TYPED\n")
    check("[8] a command typed at that prompt runs once, not again when the prompt ends",
          rc == 0 and out.count("TYPED") == 1 and "can't allocate" not in out,
          f"rc={rc} typed={out.count('TYPED')}")
    write(d, "nf.cir", deck("nf.cir", "source nosuch.cir\necho AFTER"))
    p = subprocess.run([NGSPICE, "-i", "nf.cir"], cwd=d, input="echo TYPED\n", capture_output=True,
                       text=True, timeout=120, errors="replace")
    out = p.stdout + p.stderr
    check("[9] after a missing file: the typed command runs once, then the block goes on, exit 0",
          p.returncode == 0 and out.count("TYPED") == 1 and "AFTER" in out and "can't allocate" not in out,
          f"rc={p.returncode} typed={out.count('TYPED')} after={'AFTER' in out}")
else:
    print("  SKIP  [7] to [9] pipe an interactive session's input: POSIX only")

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
