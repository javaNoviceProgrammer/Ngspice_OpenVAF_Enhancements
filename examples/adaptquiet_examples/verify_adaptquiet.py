#!/usr/bin/env python3
"""Enhancement-466: `.option autoadapt` is quiet by default, and its off-words work.

Enhancement-463 reported per NODE: a line for every split, and another for every
node that did not qualify. On a deck with many shared bus nodes that buried the
run's own output. The reporting is now opt-in:

    .option autoadapt          inject adapters, say nothing
    .option autoadapt=debug    inject adapters and report each one

ERRORS are never silenced -- a missing or wrong-shaped adapter model, a name
collision, `autoadapt` without `autobus`. Those mean the option cannot do what
the deck asked for, and a deck that asked for an adapter and did not get one
must not run on in silence.

AND THE OFF-WORDS NOW WORK. In Enhancement-463 the value was never looked at,
only its presence, so

    .option autoadapt=0     .option autoadapt=false
    .option autoadapt=no    .option autoadapt=off

ALL TURNED THE FEATURE ON -- measured: each of the four injected an adapter and
moved v(a[0]) from 0.7560976 to 0.7590361. Only `noautoadapt` worked. That is
the same defect Enhancements 450, 451 and 454 each had to repair in a sibling
option; this is its fourth appearance, so the word list is the one they share.

Every check below is on the VALUE as well as the text, because "quiet" must mean
the messages stopped -- not that the adapters did.
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
        if junk.startswith("_aq_"):
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


DRIVE = "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
LOAD = "\n".join(f"Rg{k} c[{k}] 0 100" for k in range(4))
MODELS = (".model mymodel1 chan r0=1k\n.model mymodel2 chan r0=2k\n"
          ".model amod adapter ra=50\n")
ADAPTED = 0.7590361446        # v(a[0]) with the adapter injected
PLAIN = 0.7560975610          # v(a[0]) without it


def run(opts, tag, body=None):
    body = body or f"{DRIVE}\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2"
    body = "V1 in 0 dc 1\n" + body
    deck = (f"adaptquiet {tag}\n.option autobus\n{opts}{body}\n{MODELS}"
            f".control\npre_osdi adapt.osdi\noption noacct\nset numdgt=10\nop\n"
            f"print v(a[0])\n.endc\n.end\n")
    p = os.path.join(HERE, f"_aq_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=180, errors="replace")
    return r.stdout + r.stderr


def volt(out):
    m = re.search(r"^v\(a\[0\]\)\s*=\s*(-?[\d.]+e[-+]\d+)", out, re.M)
    return float(m.group(1)) if m else None


def near(v, want):
    return v is not None and abs(v - want) <= 1e-9


def chatter(out):
    """lines the option printed about its own work"""
    return [l for l in out.splitlines() if "autoadapt" in l.lower()]


r = subprocess.run([OPENVAF, "adapt.va", "-o", "adapt.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-466: autoadapt quiet by default\n")
check("[E-466] the Verilog-A models compile",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "adapt.osdi")),
      (r.stdout + r.stderr).strip()[:60])

print("\nquiet by default -- the adapters still go in")
out = run(".option autoadapt adapter=amod\n", "bare")
check("[E-466] the bare option prints nothing about itself", chatter(out) == [],
      f"{chatter(out)[:1]}")
check("[E-466] ...but the adapter IS injected", near(volt(out), ADAPTED), f"{volt(out)}")

print("\n`=debug` asks for the reporting back")
out = run(".option autoadapt=debug adapter=amod\n", "debug")
check("[E-466] `=debug` reports the split", any("split" in l for l in chatter(out)),
      f"{chatter(out)[:1]}")
check("[E-466] ...and adapts identically", near(volt(out), ADAPTED), f"{volt(out)}")

print("\nthe on-words are on, and quiet")
for w in ("true", "yes", "on"):
    out = run(f".option autoadapt={w} adapter=amod\n", "on" + w)
    check(f"[E-466] `={w}` adapts, quietly",
          near(volt(out), ADAPTED) and chatter(out) == [], f"{volt(out)}")

print("\nthe OFF-words are off -- all four turned it ON before")
for w in ("0", "false", "no", "off"):
    out = run(f".option autoadapt={w} adapter=amod\n", "off" + w)
    check(f"[E-466] `={w}` leaves the deck unadapted",
          near(volt(out), PLAIN), f"{volt(out)}")
out = run(".option noautoadapt adapter=amod\n", "noword")
check("[E-466] `noautoadapt` still works", near(volt(out), PLAIN), f"{volt(out)}")

print("\nan unknown value is reported, once, and proceeds")
out = run(".option autoadapt=bogus adapter=amod\n", "bogus")
check("[E-466] `=bogus` warns about the value",
      any("unknown autoadapt value" in l.lower() for l in chatter(out)), "")
check("[E-466] ...proceeds QUIETLY (no split note)",
      not any("split" in l for l in chatter(out)), "")
check("[E-466] ...and still adapts", near(volt(out), ADAPTED), f"{volt(out)}")

print("\nerrors are NEVER silenced, even quiet")
out = run(".option autoadapt adapter=nosuch\n", "nomodel")
check("[E-466] a missing adapter model still reports",
      any("not defined in this deck" in l for l in chatter(out)), "")
check("[E-466] ...and the deck runs unadapted", near(volt(out), PLAIN), f"{volt(out)}")
deck = os.path.join(HERE, "_aq_nobus3.cir")
with open(deck, "w") as f:
    f.write("adaptquiet nobus3\n.option autoadapt adapter=amod\n"
            "V1 in 0 dc 1\n"
            f"{DRIVE}\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2\n{MODELS}"
            ".control\npre_osdi adapt.osdi\noption noacct\nop\n.endc\n.end\n")
rr = subprocess.run([NGSPICE, "-b", "_aq_nobus3.cir"], cwd=HERE,
                    capture_output=True, text=True, timeout=180, errors="replace")
check("[E-466] autoadapt without autobus still reports",
      "requires .option autobus" in (rr.stdout + rr.stderr), "")
out = run(".option autoadapt adapter=amod\n", "selfloop",
          body=f"{DRIVE}\nN1 b b mymodel1\n"
               + "\n".join(f"Rg{k} b[{k}] 0 100" for k in range(4)))
check("[E-466] the same node on both ports still reports",
      any("appears on both ports" in l for l in chatter(out)), "")

print("\ninformational notices are debug-only")
THREE = (f"{DRIVE}\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2\nN3 b c mymodel2")
out = run(".option autoadapt adapter=amod\n", "threeq", body=THREE)
check("[E-466] a 3-port node is silent by default", chatter(out) == [],
      f"{chatter(out)[:1]}")
out = run(".option autoadapt=debug adapter=amod\n", "threed", body=THREE)
check("[E-466] ...and reported under `=debug`",
      any("more than two" in l for l in chatter(out)), "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
