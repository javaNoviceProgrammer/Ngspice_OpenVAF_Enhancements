#!/usr/bin/env python3
"""Enhancement-436: `@*:model[param]` -- one model name, every instance path.

Subcircuit expansion renames a `.model rmod` inside instance x1 to `x1:rmod`, so
after flattening a deck that declares `rmod` at top level AND inside a
subcircuit has SEVERAL distinct models: `rmod`, `x1:rmod`, `x2:rmod`, ... Before
this change there were only two ways to reach them and neither was right:

  @rmod[param]   -- the top-level card ONLY. Every subcircuit copy silently kept
                    its old value. Easy to write while meaning "the model".
  @*[param]      -- every model that has `param`, which sweeps up unrelated
                    models too (an `omod` elsewhere with the same parameter).

`@*:rmod[param]` is the missing middle: the model called `rmod`, wherever it
lives. The `*` stands for the instance path and matches ANY path INCLUDING NONE,
so the top-level card is covered alongside every `<path>:rmod`. Matching is on
the leaf name (everything after the last ':'), which makes it depth-independent
without introducing pattern syntax. `@*.rmod[param]` is accepted identically,
since Enhancements 433/435 taught the dotted spelling everywhere else.

`@rmod[param]` deliberately still means the top-level card alone -- broadening it
would silently change every deck that relies on targeting one card, which is
exactly what mismatch work needs. It now says when copies were left untouched.

The deck below is built so each reach is distinguishable:
  v(a), v(b)  driven by x1:rmod and x2:rmod   (subcircuit copies)
  v(e)        driven by the top-level rmod
  v(c)        driven by omod -- the decoy that must NOT move
All four are 1k/1k dividers reading 0.5; a model moved to 3k reads 0.25.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

DECK = """* model wildcard
V1 in 0 dc 1
X1 in a sub
Ra a 0 1k
X2 in b sub
Rb b 0 1k
X3 in c other
Rc c 0 1k
Rt in e rmod
Re e 0 1k
.model rmod r (res=1000)
.subckt sub p q
Rx p q rmod
.model rmod r (res=1000)
.ends
.subckt other p q
Ry p q omod
.model omod r (res=1000)
.ends
.control
option noacct
{ctl}
.endc
.end
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(ctl, tag):
    p = os.path.join(HERE, f"_mw_{tag}.cir")
    with open(p, "w") as f:
        f.write(DECK.format(ctl=ctl))
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=120, errors="replace")
    return r.stdout + r.stderr


def moved(cmd, tag):
    """Which of a,b,c,e changed when `cmd` ran between two operating points."""
    out = run("op\nprint v(a) v(b) v(c) v(e)\n" + cmd +
              "\nop\nprint v(a) v(b) v(c) v(e)", tag)
    got = {}
    for n in "abce":
        v = re.findall(rf"v\({n}\) = (\S+)", out)
        got[n] = (len(v) == 2 and v[0] != v[1])
    return got, out


def rows(out):
    return [l.split()[-1] for l in out.splitlines() if re.match(r"^\s*\d+\s+[-\d.]", l)]


ALL_RMOD = {"a": True, "b": True, "c": False, "e": True}   # both copies + top level
TOP_ONLY = {"a": False, "b": False, "c": False, "e": True}
EVERY = {"a": True, "b": True, "c": True, "e": True}

print("Enhancement-436: one model name, every instance path\n")

print("the new form reaches every copy INCLUDING the top-level card")
for spelling in ("@*:rmod[res]", "@*.rmod[res]"):
    got, _ = moved(f"altermod {spelling}=3000", "new" + spelling[2:6])
    check(f"[E-436] altermod {spelling} moves both subcircuit copies and the top level",
          got == ALL_RMOD, str(got))

got, _ = moved("altermod @*:omod[res]=3000", "omod")
check("[E-436] ...and selects by name -- @*:omod moves only omod",
      got == {"a": False, "b": False, "c": True, "e": False}, str(got))

print("\nthe two existing forms are unchanged")
got, out = moved("altermod @rmod[res]=3000", "top")
check("[E-436] @rmod still means the top-level card alone", got == TOP_ONLY, str(got))
check("[E-436] ...but now says that copies were left untouched",
      "models are named 'rmod'" in out and "@*:rmod" in out,
      out[-120:].replace("\n", " "))
got, _ = moved("altermod @*[res]=3000", "all")
check("[E-436] @*[res] still means every model with that parameter",
      got == EVERY, str(got))

print("\nsweep classifies the new form as a model knob")
out = run("sweep @*:rmod[res] 1k 3k 1k -analysis op -output v(a)\nprint v(a)", "swa")
check("[E-436] sweep @*:rmod moves a subcircuit copy",
      rows(out) == ["5.000000e-01", "3.333333e-01", "2.500000e-01"], str(rows(out)))
out = run("sweep @*:rmod[res] 1k 3k 1k -analysis op -output v(e)\nprint v(e)", "swe")
check("[E-436] ...and the top-level card, in the same sweep",
      rows(out) == ["5.000000e-01", "3.333333e-01", "2.500000e-01"], str(rows(out)))
out = run("sweep @*:rmod[res] 1k 3k 1k -analysis op -output v(c)\nprint v(c)", "swc")
check("[E-436] ...while the unrelated model stays put",
      rows(out) == ["5.000000e-01"] * 3, str(rows(out)))

print("\nnames that match nothing are diagnosed, not silently ignored")
out = run("op\naltermod @*:nosuch[res]=3000", "nomodel")
check("[E-436] an unknown model name is reported, and explains the flattening",
      "no loaded model is named 'nosuch'" in out and "<instance>:nosuch" in out,
      out[-110:].replace("\n", " "))
out = run("op\naltermod @*:rmod[nosuchp]=3000", "noparam")
check("[E-436] a real model with an unknown parameter is a different message",
      "no model named 'rmod' has parameter 'nosuchp'" in out,
      out[-110:].replace("\n", " "))

for junk in os.listdir(HERE):
    if junk.startswith("_mw_"):
        os.remove(os.path.join(HERE, junk))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
