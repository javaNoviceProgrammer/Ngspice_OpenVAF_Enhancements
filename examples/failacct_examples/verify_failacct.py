#!/usr/bin/env python3
"""Enhancement-438: a failed simulation must not become data.

Every command that drives an analysis in a loop used to read its metric back out
of whatever plot was left behind. ngspice leaves the PREVIOUS point's plot in
place when a run fails, so the read-back succeeded and returned a stale or zero
value, and nothing downstream could tell a failed point from a real one:

  montecarlo   a sample whose DC solution failed was COUNTED AS PASSING, so a
               run where 14 of 20 samples never solved still reported 100% yield
  sweep        a point that never converged contributed exactly 0.0 to every
               output curve -- indistinguishable from a real zero, and it
               persisted into `wrdata` files
  optimize     failed evaluations were absorbed silently and the search still
               reported that it had CONVERGED

The signal already existed: runcoms.c publishes `sim_status` per analysis. These
checks pin the three behaviours, and -- just as importantly -- pin that a run
with NO failures is unchanged, since the fix must not invent warnings.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(deck, tag, timeout=120):
    p = os.path.join(HERE, f"_fa_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


# A diode whose area is drawn from a wide Gaussian: a good fraction of the
# samples land at a negative area, which the device refuses, so the operating
# point never solves. Everything else about the deck is ordinary.
MC = """montecarlo with failing samples
.param ar=gauss(1,{sig},1)
V1 in 0 dc 0.7
R1 in nb 1k
D1 nb 0 dm area={ar}
.model dm d(is=1e-14)
.control
option noacct
montecarlo 20 -analysis op -spec v(nb) -max 1 -min 0 -seed 3
.endc
.end
"""

print("Enhancement-438: a failed simulation must not become data\n")

print("montecarlo -- samples that never solved leave the yield population")
rc, out = run(MC.replace("{sig}", "5.0"), "mc_bad")
nfail = len(re.findall(r"DC solution failed", out))
m = re.search(r"yield\s*:\s*[\d.]+%\s*\((\d+)\s*/\s*(\d+) pass\)", out)
check("[E-438] samples that failed to simulate really are present in the run",
      nfail > 0, f"{nfail} failed DC solutions")
check("[E-438] the yield denominator excludes them",
      bool(m) and int(m.group(2)) == 20 - nfail,
      f"denominator={m.group(2) if m else '?'} expected={20 - nfail}")
check("[E-438] ...and the exclusion is reported, not silent",
      "failed to simulate" in out and "EXCLUDED" in out,
      "; ".join(l.strip() for l in out.splitlines() if "NOTE" in l)[:90])

# The control that matters: a clean run must be byte-for-byte the old behaviour.
rc, out = run(MC.replace("{sig}", "0.02"), "mc_ok")
m = re.search(r"yield\s*:\s*([\d.]+)%\s*\((\d+)\s*/\s*(\d+) pass\)", out)
check("[E-438] a run with NO failures is unchanged (all 20 counted)",
      bool(m) and m.group(3) == "20" and "EXCLUDED" not in out,
      m.group(0) if m else "no yield line")

print("\nsweep -- a point that did not converge is called out")
SW = """sweep with failing points
V1 in 0 dc 0.7
R1 in nb 1k
D1 nb 0 dm area=1
.model dm d(is=1e-14)
.control
option noacct
sweep @d1[area] {spec} -analysis op -output v(nb)
.endc
.end
"""
rc, out = run(SW.replace("{spec}", "-2 2 1"), "sw_bad")
check("[E-438] a sweep whose points fail says so, naming how many",
      re.search(r"sweep: WARNING -- \d+ of \d+ points? did not converge", out) is not None,
      "; ".join(l.strip() for l in out.splitlines() if "WARNING" in l)[:96])
# Enhancement-445 changed what a failed point CONTAINS. E-438 counted them and
# said so, but the value left behind was whatever the read-back returned -- the
# PREVIOUS solution, since a failed run leaves the earlier plot in place. That
# is now NaN, so the message no longer says "reads back as 0" and the data is
# self-describing rather than a plausible-looking stale number.
# (that the values really are NaN is checked in guardgaps_examples, which prints
#  the swept vector and reads the wrdata file back)
check("[E-445] ...and says the failed points are recorded as NaN",
      "recorded as NaN" in out)
rc, out = run(SW.replace("{spec}", "1 3 1"), "sw_ok")
check("[E-438] a sweep with every point converging stays quiet",
      "did not converge" not in out)

print("\noptimize -- absorbed failures are reported")
# A Verilog-A model with `area from (0:inf)` is needed here: ngspice's BUILT-IN
# devices CLAMP an out-of-range parameter instead of refusing it, so they never
# produce the failed evaluation this path is about.
_osdi = os.path.join(HERE, "_optfail.osdi")
if not os.path.exists(_osdi):
    subprocess.run([OPENVAF, "optfail.va", "-o", "_optfail.osdi"], cwd=HERE,
                   capture_output=True, text=True, timeout=300)
OPT = """optimize over a range the model refuses
.model dm optfail is0=1e-14
V1 in 0 dc 0.6
Rs in nb 1k
N1 nb 0 dm area=2.0
.control
pre_osdi _optfail.osdi
option noacct
optimize -param @n1[area] 1 {lo} 5 -analysis op -minimize (v(nb)-0.9)^2 -maxiter 25
.endc
.end
"""
rc, out = run(OPT.replace("{lo}", "-5"), "opt_bad")
check("[E-438] optimize reports evaluations that did not solve",
      re.search(r"optimize: NOTE -- \d+ of \d+ evaluations? did not solve", out) is not None,
      "; ".join(l.strip() for l in out.splitlines() if "NOTE" in l)[:96])
rc, out = run(OPT.replace("{lo}", "0.05"), "opt_ok")
check("[E-438] a search kept inside the legal range stays quiet",
      "did not solve" not in out)

for junk in os.listdir(HERE):
    if junk.startswith("_fa_"):
        os.remove(os.path.join(HERE, junk))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
