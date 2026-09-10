#!/usr/bin/env python3
"""Enhancement-593: a `.adapt`-listed node that is refused is reported, and the
refusal names the extra use.

`.option autoadapt` is quiet by default (E-466): the "did not qualify" notices
sit behind `=debug`. That silence also covered a node the deck named in
`.adapt` -- E-467 reports a name that selects nothing, but a name that selects
a candidate the rules then refuse (a third OSDI port, a capacitor on one of
its bits) said nothing, and the deck ran unadapted. And in debug mode the
refusal was a count, "occurs 3 times", with no word about where the third use
is. F3 of the 2026-09-09 dig.

Checks:
  [1] quiet default, `.adapt x`, a capacitor on x[2]: the refusal names
      `c1 x[2] 0 1p` and the two OSDI instances, and the bus stays unsplit
  [2] the same with a resistor on the base token `x`
  [3] the same with a third OSDI port on x: "more than two OSDI ports (n1, n2 and n3)"
  [4] quiet default, no `.adapt`, the capacitor: still silent (E-466 holds)
  [5] `=debug`, no `.adapt`, the capacitor: the refusal names the line
  [6] `.adapt x` with nothing in the way: adapted, quietly
  [7] `.adapt x, y` where y is refused and x adapted: one refusal, one split
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
WORK = tempfile.mkdtemp(prefix="adaptlisted_")
HDR = '`include "disciplines.vams"\n'
MODELS = {
    "busdev": """module busdev(a, b);
inout [0:4] a; inout b; electrical [0:4] a; electrical b;
parameter real g = 1e-3;
genvar i;
analog for (i = 0; i <= 4; i = i + 1) I(a[i], b) <+ g * (i + 1) * V(a[i], b);
endmodule
""",
    "amod5": """module amod5(p, n);
inout [0:4] p, n; electrical [0:4] p, n;
parameter real r = 10;
genvar i;
analog for (i = 0; i <= 4; i = i + 1) I(p[i], n[i]) <+ V(p[i], n[i])/r;
endmodule
""",
}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


for name, src in MODELS.items():
    with open(os.path.join(WORK, name + ".va"), "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, os.path.join(WORK, name + ".va"), "-o", os.path.join(WORK, name + ".osdi")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(options, netlist, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* adaptlisted {tag}\n.option autobus {options}\n.control\npre_osdi busdev.osdi\npre_osdi amod5.osdi\n.endc\n"
                f".model bm busdev\n.model am5 amod5 r=10\n{netlist}\n.control\nop\nprint v(x[0])\nprint v(x_f[0])\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def chatter(out):
    # E-572's "split node ... so its bits no longer exist" is the control block's
    # own print v(x[0]) being answered after a split; it is not a refusal
    return [l for l in out.splitlines() if "autoadapt" in l and "split node" not in l]


BUS = "v0 s1 0 1\nN1 x s1 bm\nN2 x s2 bm\nr2 s2 0 1k\n"
UNSPLIT = "v(x[0]) = 9.411765e-01"


print("Enhancement-593: a listed node that is refused is reported\n")

# ------------------------------------------------------------- [1] ---
out = run("autoadapt adapter=am5", BUS + "c1 x[2] 0 1p\n.adapt x", "t1")
check("[1] quiet, `.adapt x`, a capacitor on x[2]: the refusal names the line and the two instances",
      "bus node 'x' is also used by `c1 x[2] 0 1p` (3 uses, not the two OSDI ports n1 and n2 alone); not adapted" in out,
      "; ".join(chatter(out))[:300])
check("[1] ... and the bus stays unsplit", UNSPLIT in out and "vector x_f is not available" in out, "")
# ------------------------------------------------------------- [2] ---
out = run("autoadapt adapter=am5", BUS + "r9 x 0 1k\n.adapt x", "t2")
check("[2] quiet, `.adapt x`, a resistor on the base token: the refusal names `r9 x 0 1k`",
      "bus node 'x' is also used by `r9 x 0 1k` (3 uses" in out, "; ".join(chatter(out))[:300])
# ------------------------------------------------------------- [3] ---
out = run("autoadapt adapter=am5", BUS + "N3 x s3 bm\nr3 s3 0 1k\n.adapt x", "t3")
check("[3] quiet, `.adapt x`, a third OSDI port: names n1, n2 and n3",
      "bus node 'x' is used by more than two OSDI ports (n1, n2 and n3)" in out, "; ".join(chatter(out))[:300])
# ------------------------------------------------------------- [4] ---
out = run("autoadapt adapter=am5", BUS + "c1 x[2] 0 1p\n", "t4")
check("[4] quiet, no `.adapt`, the capacitor: still silent (E-466's default holds)",
      chatter(out) == [] and UNSPLIT in out, "; ".join(chatter(out))[:200])
# ------------------------------------------------------------- [5] ---
out = run("autoadapt=debug adapter=am5", BUS + "c1 x[2] 0 1p\n", "t5")
check("[5] `=debug`, no `.adapt`: the refusal names the line",
      "is also used by `c1 x[2] 0 1p`" in out, "; ".join(chatter(out))[:300])
# ------------------------------------------------------------- [6] ---
out = run("autoadapt adapter=am5", BUS + ".adapt x", "t6")
check("[6] `.adapt x` with nothing in the way: adapted, quietly",
      chatter(out) == [] and "v(x_f[0]) = " in out and "vector x is not available" in out, "; ".join(chatter(out))[:200])
# ------------------------------------------------------------- [7] ---
out = run("autoadapt adapter=am5", BUS + "N3 y s1 bm\nN4 y s4 bm\nr4 s4 0 1k\nc1 y[1] 0 1p\n.adapt x, y", "t7")
check("[7] `.adapt x, y`, y blocked by a capacitor: x split, y's refusal names `c1 y[1] 0 1p`",
      "v(x_f[0]) = " in out and "bus node 'y' is also used by `c1 y[1] 0 1p`" in out and "bus node 'x'" not in "".join(chatter(out)),
      "; ".join(chatter(out))[:300])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
