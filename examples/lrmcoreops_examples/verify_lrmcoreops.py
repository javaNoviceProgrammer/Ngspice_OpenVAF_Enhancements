#!/usr/bin/env python3
"""Enhancement-523: the core analog operators, audited against Accellera
VAMS-2023 clause 4.5, then fixed.

What this suite pins, each against the quoted clause:

  * 4.5.7 -- "If no maxdelay is specified ... the value of the delay
    argument td when the module instance is initialized shall be used";
    absdelay(V(in), td) with a time-varying td TRACKED it instead. The
    two-argument form now latches td at the first transient evaluation
    (an OSDI info-struct flag ngspice's instance data honors), while the
    three-argument maxdelay form keeps tracking within its bound exactly
    as 4.5.7 specifies for it.
  * 4.5.6 with Table 4-16 -- the ddx unknown may be "the flow through a
    branch", and I(n1,n2) IS the flow of the unnamed branch between n1
    and n2. The form was refused ("declare a named branch"); it now
    differentiates like the named form: forward orientation, reversed
    orientation (negated), and a flow that is not a system unknown
    (derivative exactly 0).
  * 4.5.5 -- idtmod's initial condition "defaults to 0" and "shall force
    the DC solution"; the no-ic form left the integrator unconstrained
    (a singular matrix regularized to an arbitrary value). idtmod(x)
    now forces the DC output to 0 exactly, like idtmod(x, 0).

Documented deviations kept (and re-pinned as the shipped contract):
absdelay's op/AC behavior (pass-through at DC, exp(-j*2*pi*f*td) in AC)
and the maxdelay clamp for td > maxdelay.
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
        if junk.startswith("_lc_"):
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
    osdi = os.path.join(HERE, f"_lc_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lc_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lc_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmcoreops\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
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


# ---- [1] absdelay: frozen td without maxdelay (4.5.7) ----------------------
print("absdelay td semantics (LRM 4.5.7):")
rc, out, osdi = compile_file("vtd.va")
check("vtd.va (time-varying td, no maxdelay) compiles", rc == 0)
if rc == 0:
    sim = run("Vin in 0 DC 0 PWL(0 0 10m 10)\n"
              "Vc ctl 0 DC 0 PULSE(0 1 4m 1u 1u 20m 100m)\nNd in ctl o dm\n"
              ".model dm vtd", "tran 5u 6m\nmeas tran o6 FIND v(o) AT=5.99m",
              "vtd", osdi)
    o6 = num(sim, "o6")
    check("td stays FROZEN at 1m: v(o)@5.99m = in(4.99m) = 4.99 "
          "(tracking would give 3.99)", close(o6, 4.99, 0.02), f"o6={o6}")

rc, out, osdi = compile_file("adel.va")
check("adel.va (plain + maxdelay forms) compiles", rc == 0)
if rc == 0:
    body = ("V1 in 0 DC 0.7 AC 1 PULSE(0.7 1.7 5m 1u 1u 20m 100m)\n"
            "Nd in o1 o2 dm\n.model dm vadel")
    sim = run(body, "op\nprint v(o1) v(o2)", "adop", osdi)
    check("DC operating point passes through (0.7 on both forms)",
          close(num(sim, "v(o1)"), 0.7, 1e-9) and close(num(sim, "v(o2)"), 0.7, 1e-9),
          f"{num(sim, 'v(o1)')}/{num(sim, 'v(o2)')}")
    sim = run(body, "ac lin 1 100 100\nprint ph(v(o1))", "adac", osdi)
    check("AC phase at 100 Hz, td=1m: -2*pi*f*td = -0.6283 rad",
          close(num(sim, "ph(v(o1))"), -0.6283, 2e-3), f"{num(sim, 'ph(v(o1))')}")
    sim = run(body, "tran 10u 8m\n"
              "meas tran o1b FIND v(o1) AT=5.9m\nmeas tran o1a FIND v(o1) AT=6.1m\n"
              "meas tran o2b FIND v(o2) AT=5.9m\nmeas tran o2a FIND v(o2) AT=6.1m",
              "adtr", osdi)
    check("td=1m: the 5m input step arrives at 6m",
          close(num(sim, "o1b"), 0.7, 0.02) and close(num(sim, "o1a"), 1.7, 0.02),
          f"{num(sim, 'o1b')} -> {num(sim, 'o1a')}")
    check("td=2m but maxdelay=1m: 4.5.7 substitutes maxdelay (step at 6m too)",
          close(num(sim, "o2b"), 0.7, 0.02) and close(num(sim, "o2a"), 1.7, 0.02),
          f"{num(sim, 'o2b')} -> {num(sim, 'o2a')}")

# ---- [2] ddx by the unnamed-branch flow (4.5.6 / Table 4-16) ---------------
print("\nddx unknowns (LRM 4.5.6, Table 4-16):")
rc, out, osdi = compile_file("ddxu.va")
check("ddx(f, I(a,b)) on a voltage-defined branch compiles "
      "(used to demand a named branch)", rc == 0,
      "" if rc == 0 else out.strip().splitlines()[0][:60])
if rc == 0:
    body = "V1 x 0 DC 2\nR1 x a 1k\nN1 a 0 mm\n.model mm ddxu"
    sim = run(body, "op\nprint @n1[g] @n1[ii]", "du", osdi)
    ii = num(sim, "@n1[ii]")
    check("the branch current is the 1 mA the divider sets", close(ii, 1e-3, 1e-9),
          f"ii={ii}")
    check("ddx(I^2, I) = 2*I = 2e-3 exactly", close(num(sim, "@n1[g]"), 2e-3, 1e-9),
          f"g={num(sim, '@n1[g]')}")

rc, out, osdi = compile_file("ddxu2.va")
check("reversed orientation ddx(f, I(b,a)) compiles", rc == 0)
if rc == 0:
    body = "V1 x 0 DC 2\nR1 x a 1k\nN1 a 0 mm\n.model mm ddxu2"
    sim = run(body, "op\nprint @n1[grev]", "du2", osdi)
    check("reversed unknown negates: ddx(I(a,b)^2, I(b,a)) = -2e-3",
          close(num(sim, "@n1[grev]"), -2e-3, 1e-9), f"{num(sim, '@n1[grev]')}")

rc, out, osdi = compile_file("ddxu3.va")
check("current-defined branch variant compiles", rc == 0)
if rc == 0:
    body = "V1 x 0 DC 2\nR1 x a 1k\nN1 a 0 mm\n.model mm ddxu3"
    sim = run(body, "op\nprint @n1[gz]", "du3", osdi)
    check("a flow that is NOT a system unknown differentiates to exactly 0",
          close(num(sim, "@n1[gz]"), 0.0, 1e-30), f"{num(sim, '@n1[gz]')}")

# ---- [3] idtmod default ic forces the DC solution (4.5.5) ------------------
print("\nidtmod initial condition (LRM 4.5.5):")
rc, out, osdi = compile_file("idtmod0.va")
check("idtmod(x) with no ic compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 DC 2\nNi in o m0\n.model m0 vaim0", "op\nprint v(o)",
              "im0", osdi)
    check("ic defaults to 0 and FORCES the DC solution: v(o) = 0 exactly",
          close(num(sim, "v(o)"), 0.0, 1e-12), f"{num(sim, 'v(o)')}")
    check("...with no singular-matrix regularization involved",
          "singular" not in sim.lower(), "")

# ---- [4] guarded forms stay guarded ----------------------------------------
print("\nstill-refused forms:")
rc, out, _ = compile_src(
    '`include "disciplines.vams"\n'
    "module negtd(i, o); inout i, o; electrical i, o;\n"
    "  analog V(o) <+ absdelay(V(i), -1m);\nendmodule\n", "negtd")
check("a negative constant td stays a compile error", rc != 0,
      (out.strip().splitlines() or [""])[0][:60])

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
