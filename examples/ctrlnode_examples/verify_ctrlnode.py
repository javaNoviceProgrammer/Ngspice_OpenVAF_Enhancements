#!/usr/bin/env python3
"""Enhancement-492: a node named only in a device's CONTROL position.

`E`, `G` and `S` take a controlling node PAIR, and those two names were bound the
same way the output pair is -- INPtermInsert, which CREATES the node. So a typo
simply invented a node and the run continued against it.

For `E` and `G` the invented node has no path to ground, the matrix goes
singular, and the user is told

    Warning: singular matrix:  check node nosuch

a node they never wrote, reported as a fault in their circuit. `S` is worse: a
switch only READS its control voltage to decide open/closed and stamps nothing
for it, so the matrix stays non-singular, the solve succeeds, and the answer is
silently wrong. Measured, with the switch's real control at 1 V and vt=0.5:

    S1 a b ctl    0 sw     v(b) = 0.999001      (closed, correct)
    S1 a b nosuch 0 sw     v(b) = 9.99999e-07   (open,  rc=0, SILENT)

a factor of a million, from one mistyped character, with no diagnostic at all.

**A phantom reference is dangerous exactly where it is READ but not STAMPED.**

Every other route already answers this question. `.ic` and `.nodeset` report
"IC on non-existent node - %s, ignored"; `F`, `H`, `W` and a B-source's `i()`
report "unknown controlling source"; and all thirteen output constructs name a
vector that does not exist. Only the controlling-node pair skipped it.

The mechanism is Enhancement-429's, unchanged: a control reference does not make
a node real, so it does not set `devRef`, and whatever is still unmarked once the
deck is parsed was named in a control position and nowhere else. The check runs
in pass 3 for the same reason `.ic`'s does -- only once every device card has
been read is "did anything connect to this?" answerable -- and it REFUSES rather
than warns, because a switch would otherwise carry on and answer from a node that
is not in the circuit.

TWO DIAGNOSTICS THAT NAMED THE WRONG THING, from the same round:

  * CKTop reported "a Verilog-A device raised $fatal" for a deck containing no
    Verilog-A device. E-378 added that message and E-399 narrowed its entry to
    `E_PANIC` checks, whose comment argues the test is exact because E_PANIC and
    E_ITERLIM are distinct values. True -- but the invariant the MESSAGE relies on
    is "E_PANIC means a Verilog-A $fatal", and E_PANIC has around ten producers.
    `.option klu` with a netlist whose matrix has only current sources reached it
    through op, dc, ac and tran alike.
  * KLU printed nine lines for one condition: "KLU Matrix is empty" four times
    plus five NULL-object errors that are its consequences. PreOrder's own comment
    says an empty matrix is legitimate ("XSPICE pure digital circuits produce
    empty KLU matrix") and it returns success for one.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_cn_"):
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


def run(body, ctl, tag, osdi=False):
    pre = "pre_osdi ctrlnode.osdi\n" if osdi else ""
    deck = (f"ctrlnode {tag}\n{body}\n.control\n{pre}option noacct\nset numdgt=12\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_cn_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=120,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


REPORTED = "does not exist -- no device"
SW = "\n.model sw sw vt=0.5 ron=1 roff=1e9\nRb b 0 1k\n"

r = subprocess.run([OPENVAF, "ctrlnode.va", "-o", "ctrlnode.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-492: a node named only in a control position\n")
check("[E-492] the Verilog-A control model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "ctrlnode.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# ------------------------------------------------- the silent wrong answer --
print("\nthe switch: a mistyped control node used to answer, silently")
rc, out = run("Vc ctl 0 dc 1\nV1 a 0 dc 1\nS1 a b ctl 0 sw" + SW,
              "op\nprint v(b)", "sok")
good = val(out, "v(b)")
check("[E-492] a correct control node closes the switch",
      rc == 0 and good is not None and abs(good - 0.999000999) < 1e-6, f"{good}")
check("[E-492] ...and says nothing", REPORTED not in out, "")

rc, out = run("Vc ctl 0 dc 1\nV1 a 0 dc 1\nS1 a b nosuch 0 sw" + SW,
              "op\nprint v(b)", "sbad")
check("[E-492] a mistyped control node is reported", REPORTED in out, "")
check("[E-492] ...naming the node that does not exist", "'nosuch'" in out, "")
check("[E-492] ...and the deck is REFUSED, not answered", rc != 0, f"rc={rc}")
check("[E-492] ...so no plausible wrong number is produced",
      val(out, "v(b)") is None, f"{val(out,'v(b)')}")

print("\nthe controlled sources, which failed visibly but blamed the wrong node")
for dev, card in (("E", "E1 b 0 nosuch 0 2"), ("G", "G1 b 0 nosuch 0 1m")):
    rc, out = run(f"V1 a 0 dc 1\nR1 a 0 1k\n{card}\nRb b 0 1k\n",
                  "op\nprint v(b)", f"cs{dev}")
    check(f"[E-492] {dev} with a mistyped control node is reported",
          REPORTED in out and rc != 0, f"rc={rc}")

# ------------------------------------------------------ what must not move --
print("\nlegitimate control references must be untouched")
CTRL_OK = [
    ("a real control node", "V1 a 0 dc 1\nR1 a 0 1k\nE1 b 0 a 0 2\nRb b 0 1k\n", 2.0),
    ("control is the source's OWN output",
     "V1 a 0 dc 1\nR1 a 0 1k\nE1 b 0 b 0 0.5\nRb b 0 1k\n", 0.0),
    ("control node defined LATER in the deck",
     "V1 a 0 dc 1\nE1 b 0 late 0 2\nRb b 0 1k\nRlate late 0 1k\nVl late 0 dc 3\n", 6.0),
    ("control node is ground",
     "V1 a 0 dc 1\nR1 a 0 1k\nE1 b 0 0 0 2\nRb b 0 1k\n", 0.0),
    ("switch control through a subcircuit port",
     "Vc ctl 0 dc 1\nV1 a 0 dc 1\nX1 a b ctl s\n.subckt s p q c\nS1 p q c 0 sw\n.ends" + SW,
     0.999000999),
]
for lbl, body, want in CTRL_OK:
    rc, out = run(body, "op\nprint v(b)", "ok" + str(abs(hash(lbl)) % 9999))
    v = val(out, "v(b)")
    check(f"[E-492] {lbl}",
          rc == 0 and v is not None and abs(v - want) < 1e-6 and REPORTED not in out,
          f"{v} (want {want})")

rc, out = run("Vc ctl 0 dc 1\nV1 a 0 dc 1\nX1 a b ctl s\n.subckt s p q c\n"
              "S1 p q nosuch 0 sw\n.ends" + SW, "op\nprint v(b)", "subbad")
check("[E-492] ...and a typo INSIDE a subcircuit is still caught",
      REPORTED in out and rc != 0, f"rc={rc}")

print("\nthe siblings that already validated their reference must not change")
for dev, card, ctl in (("F", "F1 b 0 Vnope 2", "unknown controlling source"),
                       ("H", "H1 b 0 Vnope 2", "unknown controlling source"),
                       ("W", "W1 b 0 Vnope csw\n.model csw csw it=0.5", "unknown controlling source")):
    rc, out = run(f"V1 a 0 dc 1\nR1 a 0 1k\n{card}\nRb b 0 1k\n", "op\nprint v(b)", f"sib{dev}")
    check(f"[E-492] {dev} still names its missing controlling source", ctl in out, "")

rc, out = run("V1 a 0 dc 1\nR1 a 0 1k\nRb b 0 1k\n.ic v(nosuch)=1\n", "op\nprint v(b)", "icph")
check("[E-492] `.ic` still names a non-existent node (E-429's own path)",
      "non-existent node" in out, "")

# ------------------------------------------- the two misdirected messages ---
print("\nCKTop must not blame Verilog-A for a fault that is not Verilog-A's")
CLAIM = "Error: a Verilog-A device raised $fatal"
HONEST = "abandoned by a fault outside the Newton solve"
for ana in ("op", "tran 1u 10u", "ac lin 1 1k 1k", "dc I1 0 1m 0.5m"):
    src = "I1 0 a dc 0 ac 1\n" if ana.startswith("ac") else "I1 0 a dc 1m\n"
    rc, out = run(".option klu\n" + src, f"{ana}\nprint v(a)",
                  "va" + ana.split()[0])
    check(f"[E-492] no Verilog-A claim for a deck with no VA device ({ana.split()[0]})",
          CLAIM not in out, "")
    check(f"[E-492] ...and it says what it does know ({ana.split()[0]})",
          HONEST in out, "")

rc, out = run("V1 a 0 dc 1\nN1 a 0 fm\n.model fm vfatal trip=0.5\n",
              "op\nprint v(a)", "realfatal", osdi=True)
check("[E-492] a REAL Verilog-A $fatal is still named as such", CLAIM in out, "")
check("[E-492] ...and still points at the OSDI(fatal) line", "OSDI(fatal)" in out, "")

print("\nKLU says once what an empty matrix is, not nine times what it is not")
rc, out = run(".option klu\nI1 0 a dc 1m\n", "op\nprint v(a)", "kluempty")
check("[E-492] the empty matrix is described in one note",
      out.count("no matrix to solve") == 1, f"{out.count('no matrix to solve')}")
check("[E-492] ...with no 'KLU Matrix is empty' repetitions",
      "KLU Matrix is empty" not in out, "")
check("[E-492] ...and no NULL-object messages, which were its consequences",
      "object is NULL" not in out, "")

print("\nsolvers must still agree, and neither must go quiet on a real circuit")
for opt in ("", ".option klu\n"):
    name = "klu" if opt else "sparse"
    rc, out = run(opt + "V1 a 0 dc 1\nR1 a b 1k\nR2 b 0 1k\n", "op\nprint v(b)", "sv" + name)
    v = val(out, "v(b)")
    check(f"[E-492] {name} still solves an ordinary divider",
          rc == 0 and v is not None and abs(v - 0.5) < 1e-9, f"{v}")
    check(f"[E-492] ...without the empty-matrix note ({name})",
          "no matrix to solve" not in out, "")

DIG = ("V1 a 0 PULSE(0 1 0 1u 1u 10u 20u)\nR1 a 0 1k\nAadc [a] [dn] ab\n"
       ".model ab adc_bridge\nAinv dn dout iv\n.model iv d_inverter\n")
rc, out = run(".option klu\n" + DIG, "tran 1u 40u\neprint dout", "kludig")
check("[E-492] a mixed-signal KLU run gets no spurious empty-matrix note",
      rc == 0 and "no matrix to solve" not in out, f"rc={rc}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
