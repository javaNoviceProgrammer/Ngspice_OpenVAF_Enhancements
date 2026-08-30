#!/usr/bin/env python3
"""Enhancement-514: the analog operators, audited against Accellera VAMS-2023 4.5.

The headline is one defect with one root cause and three faces: a transient's
state arrays were seeded with ZERO instead of with the converged operating point.

  * LRM 4.5.9 -- "If the rate of change of expr is less than the specified
    maximum slew rates, slew() returns the value of expr." A CONSTANT input has
    rate of change zero, so slew must return it. It ramped up from 0 instead, at
    exactly the slew rate, for |V_bias|/rate seconds: a slew-limited buffer at a
    2.5 V mid-rail read 0.954 V at 1 us and took 2.5 us to reach its own DC bias.
  * LRM 4.5.7 -- "Output(t) = Input(max(t - td, 0))", so for t < td the output is
    Input(0), the operating point. absdelay reported 0 for the whole first `td`
    and then STEPPED to the bias.
  * LRM 4.5.10 -- "Before the expression crosses zero (0) for the first time, the
    last_crossing() function returns a negative value." It returned 0.0, and for
    an expression already ABOVE zero the zero-seeded history faked a crossing at
    t = 0, overwriting the sentinel before a model could read it.

WHY IT SURVIVED: the state is seeded with 0, and every stimulus in the
absdelay/slew/transedge/defaulttransition suites starts at 0 -- `PULSE(0 1 ...)`,
`PWL(0 0 1p 0 2p 1 ...)`, `dc 0` -- which is exactly where a zero-seeded state is
indistinguishable from a correct one. Every check below biases the input away
from zero on purpose.

Also fixed here, each against the quoted clause:

  * 4.5.8 -- "If a time_tol value of zero (0.0) is specified, the simulator shall
    apply a suitable value." transition refused it, rejecting a legal program.
  * Table 4-19 -- idtmod(expr, ic, modulus, offset, NATURE) is a listed signature
    that could never match: it declared its last argument as a real, making it
    byte-identical to the ...,abstol) form.
  * 4.5.12 -- "[the transition time] shall be nonnegative": zi_* took a negative
    one in silence, while the identical rule for transition's rise/fall was
    enforced.
  * 4.5.12 -- "A Z-filter with zero (0) transition time shall not be directly
    assigned to a branch": now a warning, on the LRM's own literal reading.
  * 4.5.7 -- "If td becomes greater than maxdelay, maxdelay will be used as a
    substitute for td." That is a SUBSTITUTION, not an error; refusing the model
    rejected a conformant program. Downgraded to a warning.

NOT FIXED, deliberately, and the reason is worth keeping: 4.5.7 also says that
with no maxdelay, "the value of td when the absdelay() is first evaluated shall
be used and any future changes to td shall be ignored". The only first-evaluation
flag a model can see is IsInitialStep, and at that flag the circuit solution is
still the zero initial guess -- a probe read inside @(initial_step) returns 0,
measurably. Latching there stores 0, which is worse than tracking; and for the
case that actually occurs (td a parameter) freezing is indistinguishable from not
freezing. Doing it right needs the simulator to latch at MODEINITTRAN, i.e. a
per-slot flag in OsdiAbsDelayInfo -- a descriptor/ABI addition not worth pairing
with these fixes.
"""

import atexit
import os
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
        if junk.startswith("_lo_"):
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


def compile_va(src, tag):
    va = os.path.join(HERE, f"_lo_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    osdi = os.path.join(HERE, f"_lo_{tag}.osdi")
    r = subprocess.run([OPENVAF, va, "-o", osdi], cwd=HERE, capture_output=True,
                       text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lo_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmops\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def opvar(out, name):
    import re
    m = re.findall(re.escape(f"@n1[{name}]") + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


print("Enhancement-514: analog operators against Accellera VAMS-2023 4.5")

OSDI = os.path.join(HERE, "_lo_main.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "lrmops.va"), "-o", OSDI],
                   cwd=HERE, capture_output=True, text=True, timeout=300,
                   errors="replace")
check("[1] lrmops.va compiles (idtmod NATURE form, transition time_tol = 0)",
      os.path.exists(OSDI), (r.stdout + r.stderr).strip()[-150:])

# ---------------------------------------------------------------------------
# LRM 4.5.9 -- slew returns the input when the input is not moving
# ---------------------------------------------------------------------------
print("\n  4.5.9: a constant input has rate of change 0, so slew returns it")

for i, bias in enumerate(["1", "0.5", "-1", "2.5"]):
    out = run(f"V1 a 0 dc {bias}\nN1 a 0 o mm rate=1e5\nRl o 0 1meg\n.model mm lrmops()",
              "tran 0.25u 5u\nprint @n1[y_slew]", f"slew{i}", OSDI)
    got = opvar(out, "y_slew")
    ok = got is not None and abs(got - float(bias)) < 1e-6
    check(f"[{2+i}] slew holds a {bias} V bias (was a ramp up from 0)", ok, f"{got}")

out = run("V1 a 0 dc 0 PWL(0 0 0.5u 0 0.501u 1 20u 1)\nN1 a 0 o mm rate=1e5\n"
          "Rl o 0 1meg\n.model mm lrmops()", "tran 0.1u 6u\nprint @n1[y_slew]",
          "slewramp", OSDI)
got = opvar(out, "y_slew")
check("[6] slew still RATE-LIMITS a real edge (5.5us x 1e5 = 0.55)",
      got is not None and abs(got - 0.55) < 5e-3, f"{got}")

# ---------------------------------------------------------------------------
# LRM 4.5.7 -- Output(t) = Input(max(t - td, 0))
# ---------------------------------------------------------------------------
print("\n  4.5.7: for t < td the output is Input(0), the operating point")

for i, bias in enumerate(["0.7", "-0.4", "1.0"]):
    out = run(f"V1 a 0 dc {bias}\nN1 a 0 o mm td=1e-6\nRl o 0 1meg\n.model mm lrmops()",
              "tran 2.5e-08 5e-07\nprint @n1[y_del]", f"del{i}", OSDI)
    got = opvar(out, "y_del")
    ok = got is not None and abs(got - float(bias)) < 1e-9
    check(f"[{7+i}] absdelay holds {bias} V through the first td (was 0)", ok, f"{got}")

out = run("V1 a 0 dc 1 PWL(0 1 3u 1 3.001u 0 20u 0)\nN1 a 0 o mm td=1e-6\n"
          "Rl o 0 1meg\n.model mm lrmops()", "tran 0.1u 4.5u\nprint @n1[y_del]",
          "deledge", OSDI)
got = opvar(out, "y_del")
check("[10] absdelay still TRANSPORTS a real edge (1->0 at 3us arrives at 4us)",
      got is not None and abs(got) < 1e-9, f"{got}")

# ---------------------------------------------------------------------------
# LRM 4.5.10 -- negative until the expression has crossed
# ---------------------------------------------------------------------------
print("\n  4.5.10: last_crossing is NEGATIVE until the first crossing")

for i, (bias, d) in enumerate([("1", "1"), ("0.6", "1"), ("0.4", "1"), ("1", "-1")]):
    out = run(f"V1 a 0 dc {bias}\nN1 a 0 o mm dir={d}\nRl o 0 1meg\n.model mm lrmops()",
              "tran 0.5u 5u\nprint @n1[t_cross]", f"lc{i}", OSDI)
    got = opvar(out, "t_cross")
    check(f"[{11+i}] no crossing, bias {bias} dir {d}: negative (was 0.0)",
          got is not None and got < 0, f"{got}")

out = run("V1 a 0 dc 0 PWL(0 0 10u 1)\nN1 a 0 o mm dir=1\nRl o 0 1meg\n.model mm lrmops()",
          "tran 0.1u 8u\nprint @n1[t_cross]", "lcreal", OSDI)
got = opvar(out, "t_cross")
check("[15] a REAL crossing is still timed (ramp crosses 0.5 at 5us)",
      got is not None and abs(got - 5e-6) < 2e-7, f"{got}")

# ---------------------------------------------------------------------------
# compile-time clauses
# ---------------------------------------------------------------------------
print("\n  compile-time: each against the clause it implements")

HDR = '`include "disciplines.vams"\n'


def mod(tag, body, decl=""):
    return HDR + (f'module {tag}(a,c); inout a,c; electrical a,c; (*desc="y"*) real y;\n'
                  f'  {decl}\n  analog begin {body} I(a,c) <+ V(a,c)*1e-6; end\nendmodule\n')


rc, out, _ = compile_va(mod("t0", "y = transition(V(a,c), 1e-6, 1e-6, 1e-6, 0.0);"), "t0")
check("[16] 4.5.8: transition time_tol = 0 ACCEPTED (LRM defines it)", rc == 0,
      out.strip()[:70])

rc, out, _ = compile_va(mod("t1", "y = transition(V(a,c), 1e-6, 1e-6, 1e-6, -1e-9);"), "t1")
check("[17] ...but a NEGATIVE time_tol is still refused", rc != 0, out.strip()[:60])

rc, out, _ = compile_va(mod("t2", "y = idtmod(V(a,c), 1.0, 10.0, -5.0, Voltage);"), "t2")
check("[18] Table 4-19: idtmod(expr,ic,modulus,offset,NATURE) compiles", rc == 0,
      out.strip()[:70])

rc, out, _ = compile_va(mod("t3", "y = zi_nd(V(a,c), '{1.0}, '{1.0}, 1e-6, -1e-9);"), "t3")
check("[19] 4.5.12: a negative z-filter transition time is refused", rc != 0,
      out.strip()[:60])

rc, out, _ = compile_va(mod("t4", "y = zi_nd(V(a,c), '{1.0}, '{1.0}, 1e-6, 1e-9);"), "t4")
check("[20] ...and a positive one still compiles", rc == 0, out.strip()[:60])

src = HDR + ("module t5(a,c); inout a,c; electrical a,c;\n"
             "  analog I(a,c) <+ zi_nd(V(a,c), '{1.0}, '{1.0}, 1e-6, 0.0);\nendmodule\n")
rc, out, _ = compile_va(src, "t5")
check("[21] 4.5.12: zero-transition z-filter contributed DIRECTLY warns",
      rc == 0 and "warning" in out, out.strip()[:60])

src = HDR + ("module t6(a,c); inout a,c; electrical a,c;\n"
             "  analog I(a,c) <+ zi_nd(V(a,c), '{1.0}, '{1.0}, 1e-6, 0.0)*1e-3;\nendmodule\n")
rc, out, _ = compile_va(src, "t6")
check("[22] ...but a SCALED one does not -- the LRM says 'directly'",
      rc == 0 and "warning" not in out, out.strip()[:60])

rc, out, osdi9 = compile_va(mod("t7", "y = absdelay(V(a,c), 1e-5, 1e-6);"), "t7")
check("[23] 4.5.7: constant td > maxdelay WARNS, no longer refused",
      rc == 0 and "warning" in out, out.strip()[:70])

if rc == 0:
    out = run("V1 a 0 dc 0 PWL(0 0 10u 10)\nN1 a 0 mm\n.model mm t7()",
              "tran 0.2u 8u\nprint @n1[y]", "sub", osdi9)
    got = opvar(out, "y")
    check("[24] ...and maxdelay is substituted for td, per 4.5.7 (delay = 1us)",
          got is not None and abs(got - 7.0) < 1e-3, f"{got}")
else:
    check("[24] ...and maxdelay is substituted for td, per 4.5.7", False, "did not compile")

rc, out, _ = compile_va(mod("t8", "y = absdelay(V(a,c), -1e-6, 1e-5);"), "t8")
check("[25] ...while a NEGATIVE delay is still refused (4.5.7: td shall be positive)",
      rc != 0, out.strip()[:60])

# ---------------------------------------------------------------------------
# the behaviour change this makes visible, pinned on purpose
# ---------------------------------------------------------------------------
print("\n  a signal that changes during the OP has nothing left to ramp")

src = HDR + ("`default_transition 1u\n"
             "module t9(a,c); inout a,c; electrical a,c;\n"
             "  integer s; (*desc=\"y\"*) real y;\n"
             "  analog begin @(timer(0, 4u)) s = 1 - s; y = transition(s);\n"
             "    V(a,c) <+ y; end\nendmodule\n")
rc, out, osdi9b = compile_va(src, "t9")
if rc == 0:
    out = run("N1 a 0 mm\nR1 a 0 1k\n.model mm t9()",
              "op\nprint @n1[y]\ntran 0.02u 0.3u\nprint @n1[y]", "opflip", osdi9b)
    got = opvar(out, "y")
    check("[26] @(timer(0,...)) fires during the DC solve, so the OP is already 1 "
          "and the transient holds it (it used to ramp from 0, contradicting its own OP)",
          got is not None and abs(got - 1.0) < 1e-9, f"{got}")
else:
    check("[26] a signal that flips during the OP holds its OP value", False, "compile failed")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
