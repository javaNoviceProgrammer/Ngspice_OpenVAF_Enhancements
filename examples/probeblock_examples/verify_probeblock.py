#!/usr/bin/env python3
"""Enhancement-605: a .probe card in a deck that opens with a .control block
no longer prints ".save: no such command available in ngspice".

N3 of the 2026-09-10 integration hunt. inp_probe() adds a `.save all` card
when the deck has no save of its own, and inserted it right after the first
card after the title. Every OSDI deck opens with a .control block (for
`pre_osdi`), so the card landed INSIDE that block, where it ran as a command
-- ".save: no such command available in ngspice" -- and the save it was meant
to register was gone (the probe still worked through the vectors the probes
themselves register). The card now goes after the block's .endc; and `deck`
is no longer moved onto the inserted card, so the walks that follow start at
the deck's first card again.

Checks:
  [1] a deck opening with a .control block, then .probe v(out): no ".save:
      no such command", the probe printed
  [2] ...with a current probe i(r1): the same, r1#branch printed
  [3] an OSDI deck (pre_osdi block first) with .probe alli
  [4] stays: a deck with no leading block, .probe of a device on its first line
  [5] a deck with its own .save and a leading block: the probe's generated
      .save line (the second insertion site) is placed past the block too
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
WORK = tempfile.mkdtemp(prefix="probeblock_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


with open(os.path.join(WORK, "rr.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule rr(p, n);\ninout p, n; electrical p, n;\n'
            'parameter real r = 1k from (0:inf);\nanalog I(p,n) <+ V(p,n)/r;\nendmodule\n')
r = subprocess.run([VAF, os.path.join(WORK, "rr.va"), "-o", os.path.join(WORK, "rr.osdi")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout + r.stderr)
    sys.exit(1)


def run(body, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* probeblock {tag}\n{body}\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


NOCMD = "no such command"
DIV = "v1 in 0 dc 1\nr1 in out 1k\nr2 out 0 1k\n"
print("Enhancement-605: .probe after a leading .control block\n")

# ------------------------------------------------------------- [1] ---
out = run(".control\nset foo=1\n.endc\n" + DIV + ".probe v(out)\n.op\n.print op v(out)", "t1")
check("[1] a leading .control block, then .probe v(out): no '.save: no such command'; the probe printed",
      NOCMD not in out and re.search(r"^0\s+5\.0000\d+e-01", out, re.M), out[-300:])

# ------------------------------------------------------------- [2] ---
out = run(".control\nset foo=1\n.endc\n" + DIV + ".probe i(r1) v(out)\n.op\n.print op i(r1) v(out)", "t2")
check("[2] ...with a current probe: r1#branch printed, 0.5 mA",
      NOCMD not in out and "r1#branch" in out and re.search(r"^0\s+5\.0000\d+e-04\s+5\.0000\d+e-01", out, re.M),
      out[-300:])

# ------------------------------------------------------------- [3] ---
out = run(".control\npre_osdi rr.osdi\n.endc\nv1 in 0 dc 1\nn1 in out rm\nr2 out 0 1k\n.model rm rr r=1k\n"
          ".probe alli\n.op\n.print op v(out) i(v1)", "t3")
check("[3] an OSDI deck (pre_osdi block first) with .probe alli: quiet, the run complete",
      NOCMD not in out and re.search(r"^0\s+5\.0000\d+e-01\s+-5\.0000\d+e-04", out, re.M), out[-300:])

# ------------------------------------------------------------- [4] ---
out = run("r1 in out 1k\nv1 in 0 dc 1\nr2 out 0 1k\n.probe i(r1)\n.op\n.print op i(r1)", "t4")
check("[4] stays: no leading block, the probed device on the deck's first line",
      NOCMD not in out and "r1#branch" in out and re.search(r"^0\s+5\.0000\d+e-04", out, re.M), out[-300:])

# ------------------------------------------------------------- [5] ---
out = run(".control\nset foo=1\n.endc\n" + DIV + ".save v(out)\n.probe i(r1)\n.op\n.print op v(out) i(r1)", "t5")
check("[5] stays: a deck with its own .save and a leading block -- the probe's own .save line is placed past the block too",
      NOCMD not in out and "r1#branch" in out and re.search(r"^0\s+5\.0000\d+e-01\s+5\.0000\d+e-04", out, re.M),
      out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
