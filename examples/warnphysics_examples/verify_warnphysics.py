#!/usr/bin/env python3
"""Enhancement-438: `.option warn_physics` -- an opt-in physical-domain check.

Every value this flags is one a simulator has good reason to accept by default:
a negative resistance is a standard small-signal equivalent, a negative
capacitance appears in de-embedding, and behavioural modelling deliberately uses
non-physical elements. Refusing them outright would break working decks. But
when such a value is a MISTAKE it was completely silent, and the results stayed
plausible rather than obviously wrong:

  K1 L1 L2 1.5   |k| > 1 makes the inductance matrix indefinite -- the coupled
                 pair GENERATES energy. On a 1:1 transformer this reports
                 |v(secondary)| = 1.178 against |v(primary)| = 0.9986.
  ron=-1         a switch that is a -1 ohm resistor when closed; a passive
                 divider then reports a NEGATIVE node voltage.
  l=-1u          a MOSFET with negative channel length sources current and
                 pushes a node ABOVE the supply rail.

So the values stay legal and the check is something you ask for.

The controls matter as much as the positives: a diagnostic that fires on a
correct circuit gets switched off and ignored. Every rule here is therefore
checked against clean multi-device decks too. (Two rules were dropped during
development for exactly this reason: flagging zero made the option warn six
times on a healthy deck, because `l`/`w` sit at 0 on every device that does not
use them; and `is` is the saturation current on a diode model but the SOURCE
CURRENT on a MOSFET instance, where negative is the normal operating point.)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def warnings_of(head, analysis, tag, opt=True):
    deck = head + (".option warn_physics\n" if opt else "") + \
        ".control\noption noacct\n" + analysis + "\n.endc\n.end\n"
    p = os.path.join(HERE, f"_wp_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=90, errors="replace")
    out = r.stdout + r.stderr
    return [l.strip() for l in out.splitlines()
            if l.startswith("Warning:") and (" -- " in l)]


XFMR = ("transformer\nV1 in 0 dc 0 ac 1\nRs in p 1\n"
        "Lp p 0 1m\nLs s 0 1m\nRl s 0 1k\nK1 Lp Ls %s\n")
SWITCH = ("switch\nV1 in 0 dc 1\nVc c 0 dc 1\nR1 in nb 1k\nS1 nb 0 c 0 sm\n"
          ".model sm sw vt=0.5 ron=%s roff=1e9\n")
MOS = ("mos\nV1 in 0 dc 1\nVg g 0 dc 2\nR1 in nb 1k\n"
       "M1 nb g 0 0 mm w=%s l=%s\n.model mm nmos(level=1)\n")
BJT = ("bjt\nV1 in 0 dc 1\nVb b 0 dc 0.7\nRc in c 1k\nQ1 c b 0 qm\n"
       ".model qm npn(bf=%s)\n")

print("Enhancement-438: .option warn_physics\n")

print("the option is OFF by default -- nothing changes for anyone who does not ask")
for nm, head, an in (("k=1.5", XFMR % "1.5", "ac lin 1 100k 100k"),
                     ("ron=-1", SWITCH % "-1", "op"),
                     ("l=-1u", MOS % ("1u", "-1u"), "op"),
                     ("bf=-100", BJT % "-100", "op")):
    w = warnings_of(head, an, "off" + nm.replace("=", "").replace("-", "m"), opt=False)
    check(f"[E-438] {nm} is still accepted silently with the option OFF", not w, str(w[:1]))

print("\nwith the option ON each non-physical value is named")
w = warnings_of(XFMR % "1.5", "ac lin 1 100k 100k", "k15")
check("[E-438] |k| > 1 is reported, and says why it is impossible",
      any("|k| > 1" in x and "generate energy" in x for x in w), str(w[:1])[:100])
w = warnings_of(SWITCH % "-1", "op", "ron")
check("[E-438] a negative switch on-resistance is reported",
      any("ron" in x for x in w), str(w[:1])[:100])
w = warnings_of(MOS % ("1u", "-1u"), "op", "len")
check("[E-438] a negative channel length is reported",
      any(" l = " in x for x in w), str(w[:1])[:100])
w = warnings_of(MOS % ("-1u", "1u"), "op", "wid")
check("[E-438] ...and a negative channel width",
      any(" w = " in x for x in w), str(w[:1])[:100])
w = warnings_of(BJT % "-100", "op", "bf")
check("[E-438] a negative forward current gain is reported",
      any("bf" in x for x in w), str(w[:1])[:100])

print("\nthe boundary is inclusive -- |k| = 1 is a real, buildable coupling")
for k in ("0.5", "0.99", "1.0", "-1.0"):
    w = warnings_of(XFMR % k, "ac lin 1 100k 100k", "k" + k.replace(".", "").replace("-", "m"))
    check(f"[E-438] k = {k} is legal and stays quiet", not w, str(w[:1])[:80])

print("\nCONTROLS -- a correct circuit must produce no physics warning at all")
controls = [
    ("plain divider", "div\nV1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k\n", "op"),
    ("mos + diode + bjt", "mix\nV1 in 0 dc 1\nVg g 0 dc 2\nVb b 0 dc 0.7\n"
     "R1 in nb 1k\nM1 nb g 0 0 mm w=1u l=1u\n.model mm nmos(level=1)\n"
     "D1 nb 0 dm\n.model dm d(is=1e-14)\nRc in cc 1k\nQ1 cc b 0 qm\n"
     ".model qm npn(bf=100)\n", "op"),
    ("switch, legal", SWITCH % "1", "op"),
    ("transformer, legal", XFMR % "0.5", "ac lin 1 100k 100k"),
    ("transient RC", "rc\nV1 in 0 dc 0 sin(0 1 1k)\nR1 in nb 1k\nC1 nb 0 1u\n",
     "tran 10u 1m"),
]
for nm, head, an in controls:
    w = warnings_of(head, an, "c" + nm.replace(" ", "")[:8])
    check(f"[E-438] no false positive on: {nm}", not w, str(w[:2])[:110])

for junk in os.listdir(HERE):
    if junk.startswith("_wp_"):
        os.remove(os.path.join(HERE, junk))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
