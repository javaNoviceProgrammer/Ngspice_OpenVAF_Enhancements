#!/usr/bin/env python3
"""Enhancement-503: setup reuse for decks containing a built-in semiconductor.

Enhancement-471 reuses the matrix between sweep points instead of tearing the
circuit down and rebuilding it. It was offered only to circuits built entirely
from types whose topology is fixed unconditionally -- the linear elements and
sources -- plus OSDI, whose node collapse is re-decided and compared on every
CKTtemp. Any other device type refused reuse outright.

That is a per-TYPE gate for a per-PARAMETER hazard. A built-in semiconductor
decides its node collapse in DEVsetup from a small, knowable set of parameters
and from nothing else: a BJT builds its internal collector, base and emitter
nodes from `rc`, `rb`, `re` and `rco`; a diode its `internal`, `internal_sw` and
`qp` nodes from `rs`, `rsw`, `vp` and `tt`; a JFET from `rd` and `rs`; the
MOS1/2/3/6/9 family from `rd`, `rs`, `rsh` and the per-instance squares `nrd`,
`nrs`. Sweep any other knob and the topology cannot move.

So the sweep now DECLARES which parameters it is varying, and CKTdoJob allows
reuse for these types when none of the declared parameters is one that builds a
node. Measured on a mostly-linear deck held back by a single transistor:

    sections   before    after   recovered
         300   0.372s   0.163s     2.29x
         600   1.101s   0.334s     3.29x
        1200   4.504s   0.682s     6.61x

The declaration is what makes it safe, and its absence is what keeps it safe:
`sw_request_reuse()` CLEARS it, so a caller that cannot enumerate what it varies
-- Monte Carlo, whose draws are bound through the deck -- inherits nothing and
keeps E-471's original, stricter gate. A `.param` knob also declares nothing,
because a deck parameter reaches a model parameter through an expression this
code cannot see, and could be feeding the very `rc` that decides a collapse.

What this suite is really checking is that the answers did not move. Reuse that
changes a number is not an optimisation, it is a bug -- Enhancement-471's own
note records that a naive version silently froze a node collapse and drew a flat
curve. Every check below compares the swept curve against the same sweep with
`.option reusesetup=0`, and asserts that the curve actually MOVES first, because
a comparison of two flat lines proves nothing.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_rd_"):
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


def run(deck, tag, timeout=900):
    p = os.path.join(HERE, f"_rd_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def reused(out):
    m = re.search(r"setup reused at (\d+) of (\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def curve(out):
    return [float(v) for v in
            re.findall(r"^\s*\d+\s+(-?[\d.]+e?[-+]?\d*)", out, re.M)]


# ---------------------------------------------------------------------------
# decks
# ---------------------------------------------------------------------------
# Enhancement-533: every deck here runs its sweep with `-perpoint`. This suite
# pins the E-471/E-503 setup-REUSE machinery, which lives in the per-point
# loop -- the eligible knobs (a resistor, `temp` on a built-in-only deck, a
# source) would otherwise hand the whole sweep to one dc analysis and leave no
# reuse decision to observe. The handover itself is pinned by sweepdc_examples.
def bjt(n, knob, reuse=True):
    L = ["bjt amplifier chain"]
    if not reuse:
        L.append(".option reusesetup=0")
    L += [".option noacct",
          ".model qmod npn bf=100 is=1e-16 rc=1 rb=2 re=0.5 va=50 rco=3",
          ".model rmod r rsh=100", "Vcc vcc 0 dc 5", "V1 in 0 dc 0.7"]
    prev = "in"
    for i in range(n):
        L += [f"Rc{i} vcc c{i} rmod w=1u l=10u", f"Q{i} c{i} {prev} e{i} qmod",
              f"Re{i} e{i} 0 200", f"Cc{i} c{i} 0 1p"]
        prev = f"c{i}"
    L += [f"Rout {prev} out 1k", "Rload out 0 100k", ".control", "set ngdebug",
          f"sweep {knob} -perpoint -output v(out) -analysis op", "print v(out)",
          ".endc", ".end"]
    return "\n".join(L) + "\n"


def diode(n, knob, reuse=True):
    L = ["diode ladder"]
    if not reuse:
        L.append(".option reusesetup=0")
    L += [".option noacct", ".model dmod d is=1e-14 rs=2 n=1.05 tt=1e-9 cjo=1p",
          "V1 in 0 dc 3"]
    prev = "in"
    for i in range(n):
        L += [f"D{i} {prev} n{i} dmod", f"R{i} n{i} 0 10k"]
        prev = f"n{i}"
    L += [f"Rout {prev} out 1k", "Rl out 0 5k", ".control", "set ngdebug",
          f"sweep {knob} -perpoint -output v(out) -analysis op", "print v(out)",
          ".endc", ".end"]
    return "\n".join(L) + "\n"


def mos(n, knob, reuse=True):
    L = ["mos ladder"]
    if not reuse:
        L.append(".option reusesetup=0")
    L += [".option noacct",
          ".model nm nmos level=1 vto=0.7 kp=100u rd=1 rs=1 rsh=0",
          "Vdd vdd 0 dc 3", "Vg g 0 dc 1.5"]
    prev = "vdd"
    for i in range(n):
        L += [f"M{i} d{i} g {prev} 0 nm w=10u l=1u", f"R{i} d{i} 0 50k"]
        prev = f"d{i}"
    L += [f"Rout {prev} out 1k", "Rl out 0 10k", ".control", "set ngdebug",
          f"sweep {knob} -perpoint -output v(out) -analysis op", "print v(out)",
          ".endc", ".end"]
    return "\n".join(L) + "\n"


def same_answer(mk, knob, tag):
    """(reused_on, npts, spread_of_curve, max_rel_diff)"""
    a = run(mk(8, knob, reuse=True), "on" + tag)
    b = run(mk(8, knob, reuse=False), "of" + tag)
    ca, cb = curve(a), curve(b)
    k, n = reused(a)
    if not ca or len(ca) != len(cb):
        return k, n, 0.0, None
    spread = (max(cb) - min(cb)) / max(abs(max(cb)), 1e-30)
    d = max(abs(x - y) / max(abs(y), 1e-30) for x, y in zip(ca, cb))
    return k, n, spread, d


print("Enhancement-503: setup reuse with a built-in semiconductor in the deck")

# ---------------------------------------------------------------------------
# [1]-[8]  the BJT: safe knobs reuse, topology knobs do not
# ---------------------------------------------------------------------------
print("\n  BJT -- reuse for the knobs that cannot move a node")

SAFE_BJT = [("model param `bf`",        "@qmod[bf] lin 20 50 150"),
            ("model WILDCARD `@*[bf]`", "@*[bf] lin 20 50 150"),
            ("instance `resistance`",   "@rout[resistance] lin 20 1k 3k"),
            ("global `temp`",           "temp lin 20 0 100"),
            ("voltage source `@v1[dc]`", "@v1[dc] lin 20 0.6 0.8")]
for i, (nm, k) in enumerate(SAFE_BJT):
    kk, n, spread, d = same_answer(bjt, k, f"b{i}")
    check(f"[{1+i}] {nm}: reuses AND the answer is unchanged",
          kk is not None and kk > 0 and d == 0.0 and spread > 1e-9,
          f"reused {kk}/{n}, curve spread {spread:.1e}, diff {d}")

TOPO_BJT = [("`rc`", "@qmod[rc] lin 20 0 10"),
            ("`rb`", "@qmod[rb] lin 20 0 10"),
            ("`rco` (gates a 4th node via its GIVEN flag)",
             "@qmod[rco] lin 20 1 10")]
for i, (nm, k) in enumerate(TOPO_BJT):
    kk, n, spread, d = same_answer(bjt, k, f"t{i}")
    check(f"[{6+i}] sweeping {nm} refuses reuse", kk == 0,
          f"reused {kk}/{n}" + ("" if kk == 0 else "  <<< REUSED A MOVING TOPOLOGY"))

# ---------------------------------------------------------------------------
# [9]-[13]  diode and MOSFET
# ---------------------------------------------------------------------------
print("\n  diode and MOSFET")

kk, n, spread, d = same_answer(diode, "@dmod[n] lin 20 1.0 1.3", "d0")
check("[9] diode `n` reuses and the answer is unchanged",
      kk is not None and kk > 0 and d == 0.0 and spread > 1e-9,
      f"reused {kk}/{n}, spread {spread:.1e}, diff {d}")
kk, n, _, _ = same_answer(diode, "@dmod[rs] lin 20 0 5", "d1")
check("[10] diode `rs` refuses reuse", kk == 0, f"reused {kk}/{n}")
kk, n, _, _ = same_answer(diode, "@dmod[tt] lin 20 0 2e-9", "d2")
check("[11] diode `tt` refuses reuse (it gates the `qp` node)", kk == 0,
      f"reused {kk}/{n}")

kk, n, spread, d = same_answer(mos, "@nm[vto] lin 20 0.5 0.9", "m0")
check("[12] MOSFET `vto` reuses and the answer is unchanged",
      kk is not None and kk > 0 and d == 0.0 and spread > 1e-9,
      f"reused {kk}/{n}, spread {spread:.1e}, diff {d}")
kk, n, _, _ = same_answer(mos, "@nm[rd] lin 20 0 5", "m1")
check("[13] MOSFET `rd` refuses reuse", kk == 0, f"reused {kk}/{n}")

# ---------------------------------------------------------------------------
# [14]-[16]  the declaration is a whole-token match, and absence is strict
# ---------------------------------------------------------------------------
print("\n  the declaration itself")

kk, n, spread, d = same_answer(bjt, "@rmod[rsh] lin 20 80 120", "w0")
check("[14] `rsh` is not read as the MOSFET's `rs` (whole-token match)",
      kk is not None and kk > 0 and d == 0.0,
      f"reused {kk}/{n}, diff {d}")

# a .param knob declares nothing: a deck parameter can reach any model parameter
D = bjt(8, "@qmod[bf] lin 20 50 150")
D = D.replace(".model qmod npn bf=100", ".param bfv=100\n.model qmod npn bf={bfv}", 1)
D = D.replace("sweep @qmod[bf] lin 20 50 150", "sweep bfv lin 20 50 150", 1)
out = run(D, "p0")
kk, n = reused(out)
check("[15] a `.param` knob declares nothing, so the strict gate applies",
      kk == 0, f"reused {kk}/{n}")

# montecarlo does not declare, so it must not gain reuse on a BJT deck
MC = bjt(8, "@qmod[bf] lin 2 50 150").replace(
    "sweep @qmod[bf] lin 2 50 150 -perpoint -output v(out) -analysis op",
    "montecarlo 6 -analysis op -spec v(out) -max 99 -seed 3", 1)
MC = MC.replace(".model qmod npn bf=100",
                ".param bfr=agauss(100,10,3)\n.model qmod npn bf={bfr}", 1)
out = run(MC, "mc0")
check("[16] montecarlo, which cannot declare, still runs and reports a yield",
      "yield" in out, (re.findall(r"yield[^\n]*", out) or ["(none)"])[0][:44])

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
