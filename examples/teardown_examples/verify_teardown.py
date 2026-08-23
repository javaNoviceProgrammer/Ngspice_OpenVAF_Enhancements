#!/usr/bin/env python3
"""Enhancement-470: tearing an OSDI circuit down was quadratic in its node count.

`CKTdltNNum()` finds the node it is asked to delete by scanning the circuit's
node list from the head, and `OSDIunsetup()` calls it once per internal node --
so unsetting a device that owns k of them costs O(k*N). Every repeated analysis
pays it: a `sweep`, an `optimize`, a `montecarlo`, anything that runs an
analysis more than once.

A profile of a 1001-point parameter sweep over a 2448-unknown circuit found 77%
of the ENTIRE RUN inside it -- not in the solve, not in setup, but in the
teardown between points:

    10083 com_sweep -> sw_run_cmd -> dosim -> if_run
      8092 CKTdoJob
        8083 CKTunsetup
          8056 OSDIunsetup
            7808 CKTdltNNum          <- 77% of total

The caller knows every number it wants gone before it deletes any of them, so
it now marks them and one walk of the list removes them all: O(N) for the whole
unsetup. Measured on that deck, per sweep point:

    25 stack periods (2448 unknowns)   32.9 ms -> 7.6 ms     4.3x
    10 periods                          4.0 ms -> 2.3 ms     1.8x
     5 periods                          1.7 ms -> 1.2 ms     1.4x

The speedup GROWING with size is the signature of removing a quadratic, and it
is what this suite asserts -- an absolute millisecond figure would only be
measuring the machine.

WHAT MATTERS MORE THAN THE SPEED is that nothing moved. A teardown that frees
the wrong node, frees one twice, or leaves one behind would corrupt the next
analysis rather than fail loudly, so most of the checks below are about the
numbers and the node bookkeeping being exactly what they were.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_td_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def chain(n):
    """a ladder of n OSDI instances, each owning one internal node"""
    body = "V1 n0 0 dc 1\n"
    for i in range(n):
        body += f"N{i} n{i} n{i+1} rmod\n"
    body += f"Rl n{n} 0 1k\n.model rmod rint r1=1k r2=1k\n"
    return body


def run(body, ctl, tag):
    deck = (f"teardown {tag}\n{body}.control\npre_osdi rint.osdi\n"
            f"option noacct\nset numdgt=10\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_td_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    t0 = time.time()
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return r.stdout + r.stderr, time.time() - t0


def vals(out):
    return [v for _n, v in re.findall(r"v\(([^)]+)\)\s*=\s*(-?[\d.]+e?[-+]?\d*)",
                                      out, re.I)]


r = subprocess.run([OPENVAF, "rint.va", "-o", "rint.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-470: OSDI teardown\n")
check("[0] the model compiles", r.returncode == 0
      and os.path.isfile(os.path.join(HERE, "rint.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# ------------------------------------------------------------- correctness ---
print("nothing about the answer moved")

# a 20-instance ladder: each rint is r1+r2 = 2k, so 20 of them plus Rl = 41k
N = 20
o, _ = run(chain(N), "op\nprint v(n1) v(n%d)" % N, "one")
g = [float(x) for x in vals(o)]
want1 = 1.0 * (2000.0 * (N - 1) + 1000.0) / (2000.0 * N + 1000.0)
wantN = 1.0 * 1000.0 / (2000.0 * N + 1000.0)
check("[1] a single op is analytically right",
      len(g) == 2 and abs(g[0] - want1) < 1e-6 and abs(g[1] - wantN) < 1e-6,
      f"{g} want {want1:.9f}/{wantN:.9f}")

# the teardown runs BETWEEN analyses: repeat one and the answer must not drift
o, _ = run(chain(N), "op\nprint v(n%d)\nop\nprint v(n%d)\nop\nprint v(n%d)"
           % (N, N, N), "rep")
g = vals(o)
check("[2] three ops in a row give the identical answer",
      len(g) == 3 and len(set(g)) == 1, f"{g}")

# a sweep tears down once per point
o, _ = run(chain(N), "sweep @rmod[r1] lin 5 1k 3k -output v(n%d)\nprint v(n%d)" % (N, N),
           "swp")
rows = re.findall(r"^\d+\s+(\S+)\s*$", o, re.M)
check("[3] a 5-point sweep produces five distinct values",
      len(rows) == 5 and len(set(rows)) == 5, f"{rows}")

# and the sweep's values must match ops done by hand at the same knob settings
hand = []
for rv in ("1k", "1.5k", "2k", "2.5k", "3k"):
    oh, _ = run(chain(N), f"altermod @rmod[r1]={rv}\nop\nprint v(n{N})", "h" + rv)
    hand += vals(oh)
check("[4] ...that match ops taken by hand at the same settings",
      len(hand) == 5 and all(abs(float(a) - float(b)) < 1e-9
                             for a, b in zip(rows, hand)),
      f"sweep={rows} hand={hand}")

# ---------------------------------------------------------- node accounting ---
print("\nthe node list is left exactly as it was found")
o, _ = run(chain(N), "op\ndisplay\nop\ndisplay", "disp")
counts = [len(re.findall(r"^\s+\S+\s+:\s+(?:voltage|current)", blk, re.M))
          for blk in o.split("Here are the vectors currently active:")[1:]]
check("[5] two successive analyses expose the same vectors",
      len(counts) == 2 and counts[0] == counts[1] and counts[0] > 0, f"{counts}")
# the internal node is legitimately visible (ngspice exposes `n0#mid` just as
# it exposes `q1#collector`); what must not happen is a second copy appearing
# each time the circuit is set up again
halves = [re.findall(r"^\s+(\S*#mid)\s+:", blk, re.M)
          for blk in o.split("Here are the vectors currently active:")[1:]]
check("[6] the same N internal nodes appear each cycle -- none accumulate",
      len(halves) == 2 and sorted(halves[0]) == sorted(halves[1])
      and len(halves[0]) == N and len(set(halves[0])) == N,
      f"{len(halves[0])} then {len(halves[1])}")
o6, _ = run(chain(1), "op\nprint v(n0#mid)\nop\nprint v(n0#mid)\n"
                      "op\nprint v(n0#mid)", "mid1")
g6 = vals(o6)
check("[6] ...and an internal node holds its analytic value across cycles",
      len(g6) == 3 and len(set(g6)) == 1
      and abs(float(g6[0]) - (1.0 + 1000.0 / 3000.0) / 2.0) < 1e-6, f"{g6}")
o, _ = run(chain(N), "op\nop\nop\nop\nop\nprint v(n%d)" % N, "five")
check("[7] five setup/teardown cycles raise no error",
      "Error" not in o and "Internal Error" not in o, "")

# -------------------------------------------------------------- the scaling ---
print("\nthe cost no longer grows quadratically with the node count")
per = {}
for n in (20, 40, 80):
    _, t = run(chain(n), "sweep @rmod[r1] lin 40 1k 3k -output v(n%d)" % n,
               "sc%d" % n)
    per[n] = t / 40.0
    print(f"        {n:3d} instances: {per[n]*1000:7.2f} ms/point")
# doubling the circuit must cost clearly less than 4x per point (quadratic);
# generous bounds so this measures the algorithm, not the machine
r1 = per[40] / per[20] if per[20] else 99
r2 = per[80] / per[40] if per[40] else 99
check("[8] doubling 20->40 instances costs well under 4x per point",
      r1 < 3.0, f"{r1:.2f}x")
check("[9] doubling 40->80 instances costs well under 4x per point",
      r2 < 3.0, f"{r2:.2f}x")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
