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

  * 4.5.8 -- "transition() forces all positive transitions of expr to
    occur over rise_time": since Enhancement-698 the ramp takes rise_time
    whatever the swing (a 0 -> 2 step is at 1.0 half way through its 1 us
    and at 2.0 after it). Until then the operator was a rate-limited loop
    at the fixed rate 1/rise_time, an approximation this suite pinned as
    the shipped contract (1.0996 at 2.1u); it now pins the LRM value.
  * 4.5.12 -- "If a root (a pole or zero) is zero, then the term associated
    with it is implemented as z, rather than (1 - z^-1 r)": since
    Enhancement-699 a zi_zp/zi_zd/zi_np root at the origin is the one-period
    delay (a pole) or advance (a zero) the clause makes it. The root
    expansion built the term 1, so zi_zp(x, , '{0, 0}, T) was a wire while
    zi_nd(x, '{0, 1}, '{1}, T), the same delay as coefficients, was right;
    on the unit circle only the PHASE shows the missing factor.
"""

import atexit
import cmath
import math
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

# ---- [4] the ramp takes rise_time whatever the swing (4.5.8, E-698) --------
print("\n4-arg transition amplitude (LRM 4.5.8, Enhancement-698):")
rc, out, osdi = compile_file("trans_amp.va")
check("trans_amp.va compiles", rc == 0)
if rc == 0:
    sim = run("Ndut in out 0 m1\nVin in 0 dc 0 pulse(0 1 1u 1n 1n 40u 80u)\n"
              ".model m1 trans_amp",
              "tran 5n 6u\nmeas tran vmid FIND v(out) AT=1.5u\n"
              "meas tran vend FIND v(out) AT=2.1u\n"
              "meas tran vend3 FIND v(out) AT=5.9u", "ta", osdi)
    check("the 0->2 ramp with trise=1u is half way (1.0) at 1.5u and complete (2.0) at 2.1u "
          "-- it used to run at the fixed rate 1/trise and read 1.0996 at 2.1u, the "
          "approximation E-512 documented",
          close(num(sim, "vmid"), 1.0, 0.02) and close(num(sim, "vend"), 2.0, 1e-6),
          f"vmid={num(sim, 'vmid')} vend={num(sim, 'vend')}")
    check("...and holds 2.0 to the next edge",
          close(num(sim, "vend3"), 2.0, 1e-9), f"{num(sim, 'vend3')}")

# ---- [5] z-filter roots at the origin are the factor z (4.5.12, E-699) ---
print("\nz-filter roots at the origin (LRM 4.5.12, Enhancement-699):")
rc, out, osdi = compile_src(
    '`include "disciplines.vams"\n'
    "module zorig(i, o1, o2, o3, o4, o5, o6);\n"
    "  inout i, o1, o2, o3, o4, o5, o6; electrical i, o1, o2, o3, o4, o5, o6;\n"
    "  localparam real zr = 0.0;\n"
    "  analog begin\n"
    "    V(o1) <+ zi_zp(V(i), , '{0.0, 0.0}, 1u);              // a pole at the origin: 1/z\n"
    "    V(o2) <+ zi_np(V(i), '{1.0}, '{zr, 0.0}, 1u);         // the same, np spelling, a localparam zero\n"
    "    V(o3) <+ zi_zd(V(i), '{0.0, 0.0}, '{1.0}, 1u);        // a zero at the origin: z\n"
    "    V(o4) <+ zi_zp(V(i), '{0.0, 0.0}, '{0.5, 0.0}, 1u);   // z/(1 - 0.5 z^-1)\n"
    "    V(o5) <+ zi_nd(V(i), '{0.0, 1.0}, '{1.0}, 1u);        // z^-1 as coefficients (the reference)\n"
    "    V(o6) <+ zi_zp(V(i), , '{0.0, 0.0, 0.0, 0.0, 0.5, 0.0}, 1u); // two origin poles and one at 0.5\n"
    "  end\nendmodule\n", "zorig")
check("zorig (six z filters with roots at the origin) compiles", rc == 0,
      out.strip().splitlines()[-1][:80] if rc else "")
if rc == 0:
    # wT = 0.5 at f = 0.5/(2 pi T); the AC of the z filters is the bilinear image
    # z = (1 + sT/2)/(1 - sT/2) (documented), and ngspice's ph() is in radians,
    # printed to six significant digits (hence 1e-5)
    T = 1e-6
    f = 0.5 / (2 * math.pi * T)
    s = 2j * math.pi * f
    z = (1 + s * T / 2) / (1 - s * T / 2)
    exp = {1: cmath.phase(1 / z), 2: cmath.phase(1 / z), 3: cmath.phase(z),
           4: cmath.phase(z / (1 - 0.5 / z)), 5: cmath.phase(1 / z),
           6: cmath.phase(1 / (z * z * (1 - 0.5 / z)))}
    body = "V1 i 0 DC 1 AC 1\nNd i o1 o2 o3 o4 o5 o6 dm\n.model dm zorig"
    ctl = (f"ac lin 1 {f:.9g} {f:.9g}\n"
           + "\n".join(f"print ph(v(o{k}))" for k in range(1, 7))
           + "\nop\nprint v(o4) v(o6)")
    sim = run(body, ctl, "zo", osdi)

    def ph(k):
        return num(sim, f"ph(v(o{k}))")

    check("a pole at the origin (zp) is the one-period delay z^-1: phase -0.4900 rad at "
          "wT = 0.5, exactly the nd spelling's -- it read 0 (the term was 1, a wire)",
          close(ph(1), exp[1], 1e-5) and close(ph(5), exp[5], 1e-5),
          f"zp={ph(1)} nd={ph(5)} exp={exp[1]:.6f}")
    check("...and in the np spelling with a localparam zero", close(ph(2), exp[2], 1e-5),
          f"{ph(2)}")
    check("a zero at the origin (zd) is the one-period advance z: +0.4900 rad",
          close(ph(3), exp[3], 1e-5), f"{ph(3)}")
    check("z/(1 - 0.5 z^-1): +0.0914 rad (it read -0.3985, the phase of 1/(1 - 0.5 z^-1))",
          close(ph(4), exp[4], 1e-5), f"{ph(4)} exp={exp[4]:.6f}")
    check("two origin poles beside a real one: 1/(z^2 (1 - 0.5 z^-1)), -1.3784 rad",
          close(ph(6), exp[6], 1e-5), f"{ph(6)} exp={exp[6]:.6f}")
    check("the DC gains are those at z = 1: 2 for both o4 and o6",
          close(num(sim, "v(o4)"), 2.0, 1e-9) and close(num(sim, "v(o6)"), 2.0, 1e-9),
          f"{num(sim, 'v(o4)')} {num(sim, 'v(o6)')}")
    sim = run(body.replace("DC 1 AC 1", "DC 0 PULSE(0 1 1u 1n 1n 1 2)"),
              "tran 10n 3u\nmeas tran a1 FIND v(o1) AT=1.05u\nmeas tran b1 FIND v(o5) AT=1.05u\n"
              "meas tran a2 FIND v(o1) AT=2.5u\nmeas tran b2 FIND v(o5) AT=2.5u", "zot", osdi)
    check("transient: the zp delay and the nd delay trace the same step response "
          "(the zp one read 1.0 at 1.05u, a wire, against the all-pass's -0.81)",
          num(sim, "a1") is not None and num(sim, "a1") < 0
          and close(num(sim, "a1"), num(sim, "b1"), 1e-6)
          and close(num(sim, "a2"), num(sim, "b2"), 1e-6),
          f"zp={num(sim, 'a1')},{num(sim, 'a2')} nd={num(sim, 'b1')},{num(sim, 'b2')}")

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
