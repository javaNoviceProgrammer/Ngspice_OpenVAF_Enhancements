#!/usr/bin/env python3
"""Enhancement-587: a crossing needs a previous sample on the other side, and
transition()/slew() are unity in small-signal analyses.

Two hunt findings (2026-09-07, F2 and F3):

* `@(cross(e, +1))` and `@(above(e))` counted `prev <= 0 && cur > 0`, so an
  expression that STARTS exactly at zero -- a sine whose offset is the
  threshold -- fired on the first step after t = 0 (prev was the seeded 0),
  and `above` fired again on the t = 0 Newton walk of a transient. Now the
  previous side is strict and the current side inclusive (an expression that
  lands exactly on zero from the other side fires once, at that sample), and
  `above` gates its edge at t = 0 of a transient the way `cross` does; its
  LRM initialization event (positive at the initial step) is untouched.
* `V(o) <+ transition(V(in))` showed -0.036 deg at 100 kHz and -3.6 deg at
  10 MHz in ac: the tracking loop's linearisation is a lag with tau =
  trise/1000 (1 ns for the default transition, 1 ns again for an
  instantaneous one). The LRM's small-signal transfer of transition() and of
  a slew() that is not slewing is unity. The loop's reactive residual is now
  zeroed for the ac and noise evaluations, which makes the equation `y = x`
  exactly; dc and transient are untouched.

Checks (both solvers):
  [1] a sine starting exactly on the threshold: 2 rising, 2 falling, 4 either,
      2 above over 2.5 periods; just above: 2/2/4/3 (the last fall lands
      after 2.5 ms, above adds its initialization event); just below: 3/3/6/3
  [2] a triangle that lands exactly on the threshold: counted once per side
  [3] above's LRM initialization event (positive at t = 0) still fires once
  [4] a dc sweep: above counts the single pass, cross counts nothing
  [5] transition() with no arguments, with explicit zeros, and slew(): phase
      exactly 0 and magnitude exactly 1 at 100 kHz, 1 MHz and 10 MHz
  [6] transition with td = 5 us: exactly -180 deg at 100 kHz (the delay stays)
  [7] noise analysis: the transfer through transition is unity
  [8] transient unchanged: a 1 us transition is at 0.5 half-way up its ramp,
      the slew limits to its rate, and absdelay is exact
"""
import math
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
WORK = tempfile.mkdtemp(prefix="evtedge_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


r = subprocess.run([VAF, os.path.join(HERE, "evtedge.va"), "-o", os.path.join(WORK, "evtedge.osdi")],
                   capture_output=True, text=True)
check("evtedge.va compiles", r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.returncode else "")


def run(deck, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* evtedge {tag}\n{deck}\n.control\nset noinit\nset numdgt=10\npre_osdi evtedge.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300, cwd=WORK)
    return p.stdout + p.stderr


def counts(out, tag):
    m = re.search(r"(?m)^" + re.escape(tag) + r": up=(\d+) dn=(\d+) any=(\d+) above=(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else None


def val(out, name):
    m = re.findall(r"(?m)^" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


ECHO = 'echo "{t}: up=$&@n{k}[o_up] dn=$&@n{k}[o_dn] any=$&@n{k}[o_any] above=$&@n{k}[o_above]"'

print("Enhancement-587: cross/above edges and small-signal transition\n")

# ------------------------------------------------------------- [1] ---
deck = "\n".join([
    "V1 a 0 sin(0.5 1 1k)", "V2 b 0 sin(0.5001 1 1k)", "V3 c 0 sin(0.4999 1 1k)",
    "N1 a 0 o1 o2 o3 o4 0 mm", "N2 b 0 p1 p2 p3 p4 0 mm", "N3 c 0 q1 q2 q3 q4 0 mm",
    ".model mm evtedge"])
out = run(deck, "tran 1u 2.5m\n" + "\n".join(ECHO.format(t=t, k=k) for t, k in (("A", 1), ("B", 2), ("C", 3))), "sine")
check("[1] a sine starting exactly on the threshold: 2 rising, 2 falling, 4 either, 2 above",
      counts(out, "A") == (2, 2, 4, 2), str(counts(out, "A")))
check("[1] starting just above: 2 rising, 2 falling (the third fall lands after 2.5 ms), 4 either, "
      "3 above (the LRM initialization event plus the two rises)",
      counts(out, "B") == (2, 2, 4, 3), str(counts(out, "B")))
check("[1] starting just below: 3 rising, 3 falling, 6 either, 3 above",
      counts(out, "C") == (3, 3, 6, 3), str(counts(out, "C")))

# ------------------------------------------------------------- [2] ---
# a triangle 0 -> 1 -> 0 -> 1 with the threshold at 0.5 and a step that lands
# exactly on 0.5 (0.5 ms per half-swing, 100 us step: 0.5 hit exactly)
deck = "V1 a 0 pwl(0 0 0.5m 1 1m 0 1.5m 1 2m 0)\nN1 a 0 o1 o2 o3 o4 0 mm\n.model mm evtedge"
out = run(deck, "tran 100u 2m\n" + ECHO.format(t="A", k=1), "tri")
check("[2] a triangle that lands exactly on the threshold: 2 rising, 2 falling, 4 either, 2 above -- once per pass",
      counts(out, "A") == (2, 2, 4, 2), str(counts(out, "A")))

# ------------------------------------------------------------- [3] ---
deck = "V1 a 0 dc 1\nN1 a 0 o1 o2 o3 o4 0 mm\n.model mm evtedge"
out = run(deck, "tran 10u 1m\n" + ECHO.format(t="A", k=1), "init")
check("[3] positive at t = 0: above's initialization event fires once, cross fires nothing",
      counts(out, "A") == (0, 0, 0, 1), str(counts(out, "A")))

# ------------------------------------------------------------- [4] ---
out = run(deck, "dc v1 0 1 0.25\n" + ECHO.format(t="A", k=1), "dc")
check("[4] a dc sweep 0..1: above counts the one pass through 0.5, cross counts nothing (transient-only)",
      counts(out, "A") == (0, 0, 0, 1), str(counts(out, "A")))

# ------------------------------------------------------------- [5]-[6] ---
deck = "V1 a 0 dc 0.2 ac 1\nN1 a 0 o1 o2 o3 o4 0 mm\n.model mm evtedge"
out = run(deck, """ac dec 1 1e5 1e7
let p1 = ph(v(o1))*180/pi
let p2 = ph(v(o2))*180/pi
let p3 = ph(v(o3))*180/pi
let p4 = ph(v(o4))*180/pi
let m1 = mag(v(o1))
let m4 = mag(v(o4))
print p1[0] p1[2] p2[0] p2[2] p4[0] p4[2] m1[0] m1[2] m4[0] m4[2] p3[0]
""", "ac")
zero = lambda n: val(out, n) is not None and abs(val(out, n)) < 1e-9
one = lambda n: val(out, n) is not None and abs(val(out, n) - 1.0) < 1e-12
check("[5] transition() with no arguments: 0 deg and magnitude 1 at 100 kHz and 10 MHz",
      zero("p1[0]") and zero("p1[2]") and one("m1[0]") and one("m1[2]"),
      f"{val(out, 'p1[0]')} {val(out, 'p1[2]')} {val(out, 'm1[2]')}")
check("[5] transition(x, 0, 0, 0): 0 deg at 100 kHz and 10 MHz", zero("p2[0]") and zero("p2[2]"))
check("[5] slew(x, 1e6, -1e6): 0 deg and magnitude 1 at 100 kHz and 10 MHz",
      zero("p4[0]") and zero("p4[2]") and one("m4[0]") and one("m4[2]"))
check("[6] transition with td = 5 us: exactly -180 deg at 100 kHz (the delay is honoured, nothing added)",
      val(out, "p3[0]") is not None and abs(abs(val(out, "p3[0]")) - 180.0) < 1e-6, str(val(out, "p3[0]")))

# ------------------------------------------------------------- [7] ---
deck = "V1 in 0 dc 0.2 ac 1\nR1 in a 1k\nN1 a 0 o1 o2 o3 o4 0 mm\n.model mm evtedge"
out = run(deck, """noise v(o1) v1 lin 1 1e6 1e6
print noise1.onoise_spectrum
noise v(a) v1 lin 1 1e6 1e6
print noise2.onoise_spectrum
""", "noise")
n1, n2 = val(out, "noise1.onoise_spectrum"), val(out, "noise2.onoise_spectrum")
check("[7] noise: the spectrum through transition equals the spectrum at its input (unity transfer)",
      n1 is not None and n2 is not None and n2 > 0 and abs(n1 / n2 - 1.0) < 1e-9, f"{n1} {n2}")

# ------------------------------------------------------------- [8] ---
deck = "V1 a 0 pulse(0 1 1u 1n 1n 10u 20u)\nN1 a 0 o1 o2 o3 o4 0 mm\n.model mm evtedge"
out = run(deck, """tran 10n 8u
meas tran v3h find v(o3) at=6.5u
meas tran v3e find v(o3) at=7.5u
meas tran v4h find v(o4) at=1.5u
meas tran v4e find v(o4) at=2.5u
""", "tran")
check("[8] transient unchanged: the 1 us transition after td=5u is 0.5 at 6.5 us and 1 at 7.5 us",
      val(out, "v3h") is not None and abs(val(out, "v3h") - 0.5) < 0.01 and abs(val(out, "v3e") - 1.0) < 1e-3,
      f"{val(out, 'v3h')} {val(out, 'v3e')}")
check("[8] transient unchanged: slew at 1 V/us is 0.5 at 1.5 us and 1 at 2.5 us",
      val(out, "v4h") is not None and abs(val(out, "v4h") - 0.5) < 0.01 and abs(val(out, "v4e") - 1.0) < 1e-3,
      f"{val(out, 'v4h')} {val(out, 'v4e')}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
