#!/usr/bin/env python3
"""Enhancement-493: three names the simulator would not look up.

ROUND 53 found the same shape three times: a name the user wrote was not looked
up where it was written, and what came back described something else.

1. `showmod <MODEL NAME>` COULD NOT FIND THE MODEL. The device generator's
   grammar reads a bare word as an INSTANCE name and only a `#`-prefixed one as a
   MODEL name, so with `.model dm d` used by `D1`:

       showmod d1     ->  prints the model
       showmod #dm    ->  prints the model
       showmod dm     ->  "No matching instances or models"

   of a model that plainly exists. The command's own help calls its argument
   "models", and its write sibling takes the model name directly -- `altermod dm
   is=1e-12` works -- so the one command dedicated to models was the one that
   could not be handed one. It affects OSDI models identically, because the
   defect is in the name grammar rather than in any device.

2. A SAVED NAME THAT MATCHED NOTHING WAS DROPPED IN SILENCE. `.save v(n)
   v(nosuch)` recorded v(n), discarded the typo, and said nothing: the analysis
   succeeded and the vector the user asked for was merely absent. `.probe
   v(nosuch)` reaches the same path, which is why a mistyped NODE there was
   silent while a mistyped SOURCE in the same card is reported by the
   measure-source pass ("Could not find the instance line for ..."), and why
   Enhancement-418 already said it for the `@dev[param]` spelling ("no such
   device, so this vector will stay empty").

3. A RESISTOR MODEL NAMED `r` WAS UNREACHABLE. `INP2R` excluded the token `r`
   from being a model name outright -- necessary for `R1 a b r=1k`, where `r` is
   the keyword that writes the resistance -- but that also locked out a model
   actually called `r`. `.model r r rsh=1k` with `R1 a 0 r l=1u w=1u` bound
   neither model nor value, and the device came out as 1 mOhm with "resistance
   too low or not given": a message about the symptom, when the cause is that the
   model named on the line was never looked up. Every other name works, including
   every other resistor keyword (`rsh`, `l`, `w`, `tc1`, `temp`, `m`, `scale`);
   only this one letter was unreachable.

Each fix is a RETRY or a REFINEMENT of a lookup, never a reinterpretation: the
reading that works today runs first and unchanged, and only what previously found
nothing is looked at again.
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
        if junk.startswith("_nl_"):
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
    pre = "pre_osdi namelookup.osdi\n" if osdi else ""
    deck = (f"namelookup {tag}\n{body}\n.control\n{pre}option noacct\nset numdgt=12\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_nl_{tag}.cir")
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


def resistance(out):
    i = val(out, "i(V1)")
    return (-1.0 / i) if i not in (None, 0.0) else None


NOMATCH = "No matching instances or models"
DROPPED = "nothing of that name is in this analysis"

r = subprocess.run([OPENVAF, "namelookup.va", "-o", "namelookup.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-493: three names the simulator would not look up\n")
check("[E-493] the Verilog-A model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "namelookup.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# --------------------------------------------------- 1. showmod by model ----
D2 = ("V1 a 0 dc 0.7\nR1 a n 1k\nD1 n 0 dm\n.model dm d is=1e-14\n"
      "D2 n 0 dm2\n.model dm2 d is=1.5e-15\n")
print("\nshowmod must accept the name of a model")
rc, out = run(D2, "op\nshowmod dm", "smdm")
check("[E-493] `showmod <model>` finds the model", NOMATCH not in out, "")
check("[E-493] ...and shows THAT model, not another",
      re.findall(r"(?m)^\s+model\s+(\S+)", out) == ["dm"]
      and re.findall(r"(?m)^\s+is\s+(\S+)", out) == ["1e-14"],
      f"{re.findall(r'(?m)^  +model  +(\\S+)', out)}")
rc, out = run(D2, "op\nshowmod dm2", "smdm2")
check("[E-493] ...and the other model by its own name",
      NOMATCH not in out and re.findall(r"(?m)^\s+is\s+(\S+)", out) == ["1.5e-15"], "")

print("\nwhat must not move")
for lbl, ctl, want_nomatch in (
        ("`showmod <device>` still works",       "op\nshowmod d1",     False),
        ("`showmod #<model>` still works",       "op\nshowmod #dm",    False),
        ("bare `showmod` still works",           "op\nshowmod",        False),
        ("a name that is neither still reports", "op\nshowmod nosuch", True),
        ("`show <device>` still works",          "op\nshow d1",        False),
        ("`show` of an unknown still reports",   "op\nshow nosuchdev", True)):
    rc, out = run(D2, ctl, "ct" + str(abs(hash(lbl)) % 9999))
    check(f"[E-493] {lbl}", (NOMATCH in out) == want_nomatch, "")

rc, out = run(D2, "op\nshowmod dm : is", "smpar")
check("[E-493] a parameter list after a model name works",
      NOMATCH not in out and "1e-14" in out, "")
rc, out = run(D2, "op\nprint i(V1)\naltermod dm is=1e-12\nop\nprint i(V1)", "amsib")
vs = re.findall(r"(?m)^i\(v1\)\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
check("[E-493] the write sibling `altermod <model>` is unchanged",
      len(vs) > 1 and vs[0] != vs[-1], f"{vs[:2]}")

DO = "V1 a 0 dc 1\nN1 a 0 mm ri=3k\n.model mm nlk rm=5k\n"
rc, out = run(DO, "op\nshowmod mm", "osdim", osdi=True)
check("[E-493] an OSDI model is reachable by name too", NOMATCH not in out, "")
rc, out = run(DO, "op\nshowmod n1", "osdid", osdi=True)
check("[E-493] ...and by its device name, as before", NOMATCH not in out, "")

# ------------------------------------------------ 2. a dropped save name ----
DS = "V1 a 0 dc 1 sin(0 1 1k)\nR1 a n 1k\nC1 n 0 1u\n"
print("\na saved name that matches nothing must say so")
for lbl, card, ana, want in (
        (".save with a typo",            ".save v(n) v(nosuch)\n", "tran 50u 200u", True),
        (".probe with a typo",           ".probe v(nosuch)\n",     "tran 50u 200u", True),
        (".probe good + typo",           ".probe v(n) v(nosuch)\n","tran 50u 200u", True),
        (".save of a real node",         ".save v(n)\n",           "tran 50u 200u", False),
        (".probe of a real node",        ".probe v(n)\n",          "tran 50u 200u", False),
        (".probe alli",                  ".probe alli\n",          "tran 50u 200u", False),
        (".save all",                    ".save all\n",            "tran 50u 200u", False),
        (".save allv",                   ".save allv\n",           "tran 50u 200u", False),
        ("no save card at all",          "",                       "tran 50u 200u", False),
        (".save of a branch current",    ".save i(V1)\n",          "tran 50u 200u", False),
        ("@dev[param] (E-418 owns it)",  ".save @r1[i]\n",         "tran 50u 200u", False),
        ("a real node under op",         ".save v(n)\n",           "op",            False),
        ("a real node under ac",         ".save v(n)\n",           "ac dec 3 100 1k", False),
        ("a real node under dc",         ".save v(n)\n",           "dc V1 0 1 0.5", False)):
    rc, out = run(DS + card, ana, "sv" + str(abs(hash(lbl)) % 9999))
    check(f"[E-493] {lbl}", (DROPPED in out) == want, "")

rc, out = run(DS + ".save v(n) v(nosuch)\n", "tran 50u 200u\nprint v(n)[0]", "svkeep")
check("[E-493] ...and the name that DID match is still recorded",
      val(out, "v(n)[0]") is not None, "")

# --------------------------------------------- 3. a resistor model named r --
print("\na resistor model may be called `r`, and `r=` still writes a value")
for lbl, body, want in (
        ("a model named `r` binds",     "V1 a 0 dc 1\nR1 a 0 r l=1u w=1u\n.model r r rsh=1k\n", 1000.0),
        ("a model named `rmod` binds",  "V1 a 0 dc 1\nR1 a 0 rmod l=1u w=1u\n.model rmod r rsh=1k\n", 1000.0),
        ("`r=1k` still writes a value", "V1 a 0 dc 1\nR1 a 0 r=1k\n",             1000.0),
        ("`r = 1k` spaced",             "V1 a 0 dc 1\nR1 a 0 r = 1k\n",           1000.0),
        ("`R=2k` uppercase",            "V1 a 0 dc 1\nR1 a 0 R=2k\n",             2000.0),
        ("a plain value",               "V1 a 0 dc 1\nR1 a 0 1k\n",               1000.0),
        ("`r=1k tc1=0`",                "V1 a 0 dc 1\nR1 a 0 r=1k tc1=0\n",       1000.0),
        ("`r=` wins when both exist",   "V1 a 0 dc 1\nR1 a 0 r=4k\n.model r r rsh=1k\n", 4000.0),
        ("a value with `m=`",           "V1 a 0 dc 1\nR1 a 0 1k m=2\n",           500.0)):
    rc, out = run(body, "op\nprint i(V1)", "rr" + str(abs(hash(lbl)) % 9999))
    R = resistance(out)
    check(f"[E-493] {lbl}", R is not None and abs(R - want) / want < 1e-6,
          f"{R} (want {want:g})")

rc, out = run("V1 a 0 dc 1\nR1 a 0 r l=1u w=1u\n.model r r rsh=1k\n",
              "op\nprint i(V1)", "rquiet")
check("[E-493] ...with no 'resistance too low' complaint",
      "resistance too low" not in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
