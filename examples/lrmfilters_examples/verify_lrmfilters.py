#!/usr/bin/env python3
"""Enhancement-524: the filter operators, audited against Accellera
VAMS-2023 clauses 4.5.8-4.5.15, then fixed.

What this suite pins, each against the quoted clause:

  * 4.5.8 -- "If neither rise_time nor fall_time are specified or are
    equal to zero (0.0), the rise and fall time default to the value
    defined by `default_transition." An EXPLICIT zero used to clamp to an
    instantaneous step, skipping the directive; transition(s, 0.0, 0.0)
    under `default_transition 1u now ramps over 1u.
  * 4.5.8 -- with NO directive at all, a bare transition(x) (and the
    delay-only transition(x, td)) used to pass its input through
    UNFILTERED. It now applies the negligible-but-nonzero ramp the
    LRM's "default to ... 0 causes the transition to happen in one
    timestep" language implies: DC is an exact pass-through and a
    transient settles to the target within a few nanoseconds.
  * 4.5.14 / Table 4-20 -- the laplace_* coefficient vectors are
    CONSTANT-class arguments; a solution-dependent expression there is
    frozen at analysis start per the LRM, but this implementation
    re-evaluates it every iteration, so it TRACKS. That deviation is now
    AUDIBLE: a coefficient reading the solution draws a warning naming
    the filter; parameter-built coefficients stay silent.

Documented approximations re-pinned as the shipped contract: the 4-arg
transition ramp reaches its final value amplitude-independently (E-512)
-- the audit's amplitude-approximation values are pinned so any change
to that contract is caught here.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lf_"):
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


def compile_file(name):
    osdi = os.path.join(HERE, f"_lf_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lf_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lf_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmfilters\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\n{ctl}\nquit\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def num(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def close(a, b, tol):
    return a is not None and abs(a - b) <= tol


# ---- [1] explicit zero honors `default_transition (4.5.8) ------------------
print("transition(s, 0.0, 0.0) under `default_transition 1u:")
rc, out, osdi = compile_file("trans_zero.va")
check("trans_zero.va compiles", rc == 0)
if rc == 0:
    sim = run("Ndut in out 0 m1\nVin in 0 dc 0 pulse(0 1 1u 1n 1n 20u 40u)\n"
              ".model m1 trans_zero",
              "tran 5n 4u\nmeas tran vmid FIND v(out) AT=1.5u\n"
              "meas tran vend FIND v(out) AT=2.1u", "tz", osdi)
    check("mid-ramp at 1.5u reads ~0.5: the 1u directive ramp is taken "
          "(the old clamp stepped instantaneously to 1.0)",
          close(num(sim, "vmid"), 0.5, 0.01), f"vmid={num(sim, 'vmid')}")
    check("the ramp completes by 2.1u", close(num(sim, "vend"), 1.0, 0.01),
          f"vend={num(sim, 'vend')}")

# ---- [2] bare transition without a directive (4.5.8) -----------------------
print("\nbare transition(x), no directive:")
rc, out, osdi = compile_file("f8t.va")
check("f8t.va compiles", rc == 0)
if rc == 0:
    body = "V1 i 0 DC 0.7 PULSE(0 1 1u 1n 1n 20u 40u)\nNd i o dm\n.model dm f8t"
    sim = run(body, "op\nprint v(o)", "f8dc", osdi)
    check("DC: exact pass-through (0.7)", close(num(sim, "v(o)"), 0.7, 1e-12),
          f"{num(sim, 'v(o)')}")
    sim = run(body, "tran 5n 3u\nmeas tran vend FIND v(o) AT=2.5u", "f8tr", osdi)
    check("transient: the negligible ramp settles to the target (>= 0.999)",
          num(sim, "vend") is not None and num(sim, "vend") >= 0.999,
          f"vend={num(sim, 'vend')}")

rc, out, _ = compile_src(
    '`include "disciplines.vams"\n'
    "module f8d(i, o); inout i, o; electrical i, o;\n"
    "  analog V(o) <+ transition(V(i), 1u);\nendmodule\n", "f8d")
check("the delay-only form transition(x, td) routes the same way (compiles)",
      rc == 0)

# ---- [3] dynamic laplace coefficients warn (4.5.14 / Table 4-20) -----------
print("\nsolution-dependent laplace coefficients:")
rc, out, osdi = compile_file("dyncoef2.va")
check("dyncoef2.va (coefficient reads V(ctl)) compiles", rc == 0)
check("...and draws the DynamicFilterCoeff warning naming laplace_nd",
      "laplace_nd" in out and "TRACK" in out and "warning" in out,
      next((l for l in out.splitlines() if "TRACK" in l), "")[:70])
if rc == 0:
    # the tracking semantics themselves: with V(ctl) pinned constant the
    # filter is the matching fixed lowpass
    sim = run("V1 in 0 DC 1 AC 1\nVc ctl 0 DC 1\nNd in ctl out 0 dm\n"
              ".model dm dyncoef2", "ac lin 1 1e6 1e6\nprint mag(v(out))",
              "dyn", osdi)
    mag = num(sim, "mag(v(out))")
    check("with the coefficient held at 1.0 the filter is the 1 MHz lowpass "
          "(|H| = 0.7071 at the corner)", close(mag, 0.7071, 0.01), f"|H|={mag}")

rc, out, _ = compile_src(
    '`include "disciplines.vams"\n'
    "module lpar(i, o, g); inout i, o, g; electrical i, o, g;\n"
    "  parameter real k = 1.0;\n"
    "  analog V(o, g) <+ laplace_nd(V(i, g), '{k}, '{1.0, 1.59155e-7});\n"
    "endmodule\n", "lpar")
check("a parameter-built coefficient stays silent", rc == 0 and "TRACK" not in out,
      "")

# ---- [4] the documented amplitude approximation stays pinned (E-512) -------
print("\n4-arg transition amplitude contract (documented approximation):")
rc, out, osdi = compile_file("trans_amp.va")
check("trans_amp.va compiles", rc == 0)
if rc == 0:
    sim = run("Ndut in out 0 m1\nVin in 0 dc 0 pulse(0 1 1u 1n 1n 40u 80u)\n"
              ".model m1 trans_amp",
              "tran 5n 6u\nmeas tran vend FIND v(out) AT=2.1u\n"
              "meas tran vend3 FIND v(out) AT=5.9u", "ta", osdi)
    check("the 0->2 ramp with trise=1u reads ~1.0996 at 2.1u -- the shipped "
          "amplitude approximation, pinned so a contract change is caught",
          close(num(sim, "vend"), 1.0996, 0.005), f"{num(sim, 'vend')}")
    check("...and does reach 2.0 well before the next edge",
          close(num(sim, "vend3"), 2.0, 0.01), f"{num(sim, 'vend3')}")

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
