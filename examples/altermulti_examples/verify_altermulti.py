#!/usr/bin/env python3
"""Enhancement-586: `alter` and `altermod` apply EVERY name=value pair, an
unquoted word reaches a string parameter, and a $fatal abort ends cleanly.

`alter n1 ga=5m gb=6m` set `ga` and dropped `gb`; `altermod mm ma=3 mb=4` set
`ma` only; built-in devices did the same (`alter r1 r=2k temp=50` left temp at
27, `altermod dm is=2e-14 n=1.5` left n at 1). The worker split the first
word carrying '=' and treated the rest as more value; its "only a single
param-value pair" error sat on the legacy `=`-less path and never fired.

Now the front end counts the assignments and hands the worker one
`<target> name = value` list per pair, each with its own journal bracket. A
pair written `@dev[param]=value` carries its own target. One pair,
`alter dev = value` and the legacy form are unchanged. Also: `altermod mm mode=quad` (a bare word for a STRING parameter)
said "no such vector quad" -- a bare identifier is tried on the string setter
first; and a $fatal during the operating point no longer trails the stock
"doAnalyses: impossible error - can't occur" after its own message.

Checks (both solvers):
  [1] two instance pairs on an OSDI instance, two model pairs on its card
  [2] three pairs; pairs written with spaces around '='; a mix of a plain
      pair and an @dev[p]= pair
  [3] built-ins: alter r1 r=2k temp=50; alter c1 c=2p m=3; altermod dm is n
  [4] the single-pair forms are unchanged: alter dev = value, @dev[p] = value,
      a vector value [ 0 5 1n ], and the legacy no-'=' form still refused
  [5] altermod mm mode=quad (unquoted) applies; a numeric parameter given an
      unknown bare name still reports the vector error
  [6] $fatal during op: the message once, no "impossible error" line
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
WORK = tempfile.mkdtemp(prefix="altermulti_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


r = subprocess.run([VAF, os.path.join(HERE, "ip.va"), "-o", os.path.join(WORK, "ip.osdi")],
                   capture_output=True, text=True)
check("ip.va compiles", r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.returncode else "")


def run(ctl, tag, deck=None):
    deck = deck or """V1 p 0 dc 1
N1 p 0 mm ga=1m gb=2m
.model mm ip"""
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* altermulti {tag}\n{deck}\n.control\nset noinit\npre_osdi ip.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def val(out, name):
    m = re.findall(r"(?m)^" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


def echoed(out, tag):
    m = re.search(r"(?m)^" + re.escape(tag) + r": (.*)$", out)
    return m.group(1) if m else ""


print("Enhancement-586: multi-pair alter/altermod\n")

# --------------------------------------------------------------- [1] ---
out = run("""op
alter n1 ga=5m gb=6m
op
echo "A: ga=$&@n1[o_ga] gb=$&@n1[o_gb]"
altermod mm ma=3 mb=4
op
echo "B: ma=$&@n1[o_ma] mb=$&@n1[o_mb]"
""", "pairs")
check("[1] alter n1 ga=5m gb=6m sets both instance parameters",
      echoed(out, "A") == "ga=0.005 gb=0.006", echoed(out, "A"))
check("[1] altermod mm ma=3 mb=4 sets both model parameters",
      echoed(out, "B") == "ma=3 mb=4", echoed(out, "B"))

# --------------------------------------------------------------- [2] ---
out = run("""op
altermod mm ma=2 mb=3 mode="quad"
op
echo "A: ma=$&@n1[o_ma] mb=$&@n1[o_mb] q=$&@n1[o_q]"
alter n1 ga = 7m gb = 8m
op
echo "B: ga=$&@n1[o_ga] gb=$&@n1[o_gb]"
alter n1 ga=9m @n1[gb]=10m
op
echo "C: ga=$&@n1[o_ga] gb=$&@n1[o_gb]"
""", "forms")
check("[2] three pairs including a quoted string: ma=2 mb=3 mode=quad",
      echoed(out, "A") == "ma=2 mb=3 q=1", echoed(out, "A"))
check("[2] pairs with spaces around '=': ga = 7m gb = 8m",
      echoed(out, "B") == "ga=0.007 gb=0.008", echoed(out, "B"))
check("[2] a plain pair and an @n1[gb]= pair on one line",
      echoed(out, "C") == "ga=0.009 gb=0.01", echoed(out, "C"))

# --------------------------------------------------------------- [3] ---
out = run("""op
alter r1 r=2k temp=50
alter c1 c=2p m=3
altermod dm is=2e-14 n=1.5
show r1 : resistance temp
show c1 : capacitance m
showmod dm : is n
""", "builtin", deck="""V1 p 0 dc 1
R1 p 0 1k
C1 p 0 1p
D1 p 0 dm
N1 p 0 mm
.model dm d is=1e-14 n=1
.model mm ip""")
def shown(out, name):
    m = re.search(r"(?m)^\s*" + re.escape(name) + r"\s+(\S+)", out)
    return m.group(1) if m else None
check("[3] built-in resistor: alter r1 r=2k temp=50 sets both",
      shown(out, "resistance") == "2000" and shown(out, "temp") == "50",
      f"{shown(out, 'resistance')} {shown(out, 'temp')}")
check("[3] built-in capacitor: alter c1 c=2p m=3 sets both",
      shown(out, "capacitance") == "2e-12" and shown(out, "m") == "3",
      f"{shown(out, 'capacitance')} {shown(out, 'm')}")
check("[3] built-in diode model: altermod dm is=2e-14 n=1.5 sets both",
      shown(out, "is") == "2e-14" and shown(out, "n") == "1.5", f"{shown(out, 'is')} {shown(out, 'n')}")

# --------------------------------------------------------------- [4] ---
out = run("""op
alter r1 = 3k
alter @r1[temp] = 40
alter @v1[pulse] = [ 0 5 1n ]
show r1 : resistance temp
alter r1 resistance 4k temp 60
show r1 : resistance
""", "single", deck="""V1 p 0 dc 1
R1 p 0 1k
N1 p 0 mm
.model mm ip""")
check("[4] single-pair forms unchanged: alter dev = value, @dev[p] = value, a [ ] vector",
      shown(out, "resistance") == "3000" and shown(out, "temp") == "40" and "cannot evaluate" not in out,
      f"{shown(out, 'resistance')} {shown(out, 'temp')}")
check("[4] the legacy `=`-less form with two pairs is still refused, resistance stays 3000",
      "Only a single param - value pair supported" in out and out.count("resistance                  3000") == 2)

# --------------------------------------------------------------- [5] ---
out = run("""op
altermod mm mode=quad
op
echo "A: q=$&@n1[o_q] i=$&i(v1)"
altermod mm ma=nosuchvec
echo "B: done"
""", "string")
check("[5] altermod mm mode=quad (unquoted) reaches the string parameter: q=1 and the current doubles",
      echoed(out, "A") == "q=1 i=-0.006" and "no such vector" not in out.split("A: ")[0],
      echoed(out, "A"))
check("[5] a numeric parameter given an unknown bare name still reports the vector error",
      "no such vector nosuchvec" in out or "nosuchvec" in out and "Error" in out)

# --------------------------------------------------------------- [6] ---
out = run("""op
echo "A: after"
""", "fatal", deck="""V1 p 0 dc 6
N1 p 0 mm
.model mm ip""")
check("[6] a $fatal during op: the OSDI(fatal) line and the abort message once, no 'impossible error' "
      "(the control block stops at the abort, as it always did)",
      len(re.findall(r"(?m)^OSDI\(fatal\)", out)) == 1 and "raised $fatal during the operating point" in out
      and "impossible error" not in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
