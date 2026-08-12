#!/usr/bin/env python3
"""Enhancement-446: what the netlist wrote, quietly discarded.

Six places where something explicitly written in the deck was thrown away or
reinterpreted, with nothing printed. They differ in mechanism but share a shape:
the value the user typed was not the value the simulator used.

  * an explicitly written `TD1=0` on an EXP source was read as "argument not
    supplied" and replaced by the timestep -- so the waveform started one step
    late and THE ANSWER DEPENDED ON THE TIMESTEP (~4% error at a 100us step)
  * the same `!= 0.0` test made PULSE `PW=0` and `PER=0` mean different things
    for a voltage source and a current source
  * a PWL list with an odd token count invented a value for the dangling time
    (the V source made up 0; the I source ate the token as a value)
  * a third `.dc` sweep source was neither run nor refused -- a 2-D grid came
    back with the third variable pinned, looking complete
  * surplus `.ac` arguments were dropped in silence
  * `pow(fabs(x), y)` dropped the SIGN of a negative base, so `(-2)**3` was +8
    while this simulator's own Verilog-A pow(-2,3) is -8
  * `@c1[capacitance]` reported the m-multiplied total while `@r1[resistance]`
    reported the written value

Every check below is paired with a control that must NOT move -- an omitted
argument, a positive base, a complete PWL list, a two-source `.dc` -- because
each fix narrows what is accepted and the risk is over-reach.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ad_"):
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


def run(deck, tag, timeout=180):
    p = os.path.join(HERE, f"_ad_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    return r.returncode, r.stdout + r.stderr


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(\S+)", out, re.I)
    return m[-1] if m else None


def waveform(dev, tag, stop="1.02m", step="5u"):
    rc, out = run(f"e446\n{dev}\nR1 a 0 1k\n.control\noption noacct\nset numdgt=12\n"
                  f"tran {step} {stop} 0 {step} uic\nprint v(a)\n.endc\n.end\n", tag)
    return rc, [(float(t), float(y)) for t, y in
                re.findall(r"^\s*\d+\s+(\S+)\s+(\S+)", out, re.M)], out


def at(rows, t):
    return min(rows, key=lambda r: abs(r[0] - t))[1] if rows else None


print("Enhancement-446: what the netlist wrote, quietly discarded\n")

# ------------------------------------------------- EXP: an explicit TD1 of 0 ---
print("an explicitly written TD1=0 on an EXP source")
EXACT = lambda t: 1 - math.exp(-t / 1e-3)          # noqa: E731  (TD1=0, TAU1=1m)
for src, who in (("V1 a 0 exp(0 1 0 1m 5m 1m)", "voltage"),
                 ("I1 0 a exp(0 1m 0 1m 5m 1m)", "current")):
    rc, rows, _ = waveform(src, "exp" + who)
    sel = [r for r in rows if 0.99e-3 <= r[0] <= 1.01e-3]
    worst = max((abs(y - EXACT(t)) for t, y in sel), default=None)
    check(f"[E-446] the {who} source now evaluates EXP at the current timepoint",
          rc == 0 and worst is not None and worst < 1e-9, f"worst err {worst:.2e}")

# the whole point: the result must no longer depend on the timestep
errs = []
for step in ("5u", "50u", "100u"):
    rc, rows, _ = waveform("V1 a 0 exp(0 1 0 1m 5m 1m)", "step" + step, step=step)
    r = min(rows, key=lambda x: abs(x[0] - 1e-3))
    errs.append(abs(r[1] - EXACT(r[0])))
check("[E-446] ...so the answer no longer depends on the timestep",
      max(errs) < 1e-9, f"errors {['%.1e' % e for e in errs]} at 5u/50u/100u")

# controls: omitted arguments must default exactly as before
rc, rows, _ = waveform("V1 a 0 exp(0 1)", "expdef", stop="200u", step="1u")
peak = max(y for _, y in rows)
check("[E-446] an OMITTED TD1 still defaults as before (control)",
      rc == 0 and abs(peak - 0.617107) < 1e-4, f"peak {peak:.6f}")
# a zero TIME CONSTANT is a divisor -- it must still fall back, not divide by 0
rc, rows, _ = waveform("V1 a 0 exp(0 1 0 0 5m 1m)", "exptau")
finite = all(math.isfinite(y) for _, y in rows)
check("[E-446] a zero TAU still falls back rather than dividing by zero (control)",
      rc == 0 and finite and len(rows) > 0, f"{len(rows)} finite points")

# ------------------------------------------- PULSE: PW=0 / PER=0, V versus I ---
print("\nPULSE zero-valued arguments read the same by both source types")


def pulse_pair(vspec, ispec, tag):
    out = {}
    for who, dev in (("V", f"V1 a 0 pulse({vspec})"), ("I", f"I1 0 a pulse({ispec})")):
        rc, rows, _ = waveform(dev, tag + who, stop="6m", step="2u")
        out[who] = [at(rows, t) for t in (1.5e-3, 2.5e-3, 3.5e-3)]
    return out


d = pulse_pair("0 1 1m 1u 1u 0 4m", "0 1m 1m 1u 1u 0 4m", "pw0")
check("[E-446] PW=0 means a zero-width pulse for BOTH sources",
      d["V"] == d["I"] and all(abs(x) < 1e-9 for x in d["V"]), f"V={d['V']} I={d['I']}")
d = pulse_pair("0 1 1m 1u 1u 1m 0", "0 1m 1m 1u 1u 1m 0", "per0")
check("[E-446] PER=0 means a single pulse for BOTH sources",
      d["V"] == d["I"] and abs(d["V"][0] - 1.0) < 1e-9 and abs(d["V"][1]) < 1e-9,
      f"V={d['V']} I={d['I']}")
d = pulse_pair("0 1 1m 1u 1u 1m 4m", "0 1m 1m 1u 1u 1m 4m", "pfull")
check("[E-446] a fully specified PULSE is unchanged and agrees (control)",
      d["V"] == d["I"] and abs(d["V"][0] - 1.0) < 1e-9, f"V={d['V']} I={d['I']}")

# ------------------------------------------------------- PWL: odd token count ---
print("\na PWL list with an odd token count is refused, not guessed at")
for who, src in (("voltage", "V1 a 0 pwl(0 0 1m 1 2m)"),
                 ("current", "I1 0 a pwl(0 0 1m 1m 2m)")):
    rc, out = run(f"e446\n{src}\nR1 a 0 1k\n.control\noption noacct\n"
                  f"tran 5u 3m uic\nprint v(a)\n.endc\n.end\n", "pwlodd" + who)
    check(f"[E-446] the {who} source refuses an incomplete final point",
          rc != 0 and "time/value PAIRS" in out, f"rc={rc}")
for who, src, want in (("voltage", "V1 a 0 pwl(0 0 1m 1 2m 0)", 0.5),
                       ("current", "I1 0 a pwl(0 0 1m 1m 2m 0)", 0.5)):
    rc, rows, out = waveform(src, "pwlok" + who, stop="3m")
    v = at(rows, 0.5e-3)
    check(f"[E-446] a complete {who} PWL list still works (control)",
          rc == 0 and v is not None and abs(v - want) < 2e-3, f"v@0.5ms={v}")

# ------------------------------------------------------ .dc / .ac extra args ---
print("\nan analysis refuses arguments it cannot use")
DC = ("V1 in1 0 dc 0\nV2 in2 0 dc 0\nV3 in3 0 dc 0\n"
      "R1 in1 nb 1k\nR2 in2 nb 1k\nR3 in3 nb 1k\nRL nb 0 1k")


def dc_run(spec, tag):
    return run(f"e446\n{DC}\n.control\noption noacct\ndc {spec}\nprint v(nb)\n"
               f".endc\n.end\n", tag)


rc, out = dc_run("V1 0 2 1 V2 0 2 1 V3 0 2 1", "dc3")
check("[E-446] a THIRD .dc sweep source is refused, not silently pinned",
      rc != 0 and "at most two" in out, f"rc={rc}")
rc, out = run(f"e446\n{DC}\n.dc V1 0 2 1 V2 0 2 1 V3 0 2 1\n.print dc v(nb)\n.end\n",
              "dc3card")
check("[E-446] ...on the .dc CARD too", "at most two" in out, "")
rc, out = dc_run("V1 0 2 1 V2 0 2 1", "dc2")
rows = re.findall(r"^\s*\d+\s+(\S+)\s+(\S+)", out, re.M)
check("[E-446] a two-source .dc still runs its full grid (control)",
      rc == 0 and len(rows) == 9, f"{len(rows)} rows")
rc, out = dc_run("V1 0 2 1", "dc1")
check("[E-446] a one-source .dc still runs (control)",
      rc == 0 and len(re.findall(r"^\s*\d+\s+(\S+)\s+(\S+)", out, re.M)) == 3, "")

AC = "V1 in 0 dc 1 ac 1\nR1 in nb 1k\nC1 nb 0 1u"
rc, out = run(f"e446\n{AC}\n.control\noption noacct\nac lin 5 100 1k 99\n"
              f"print mag(v(nb))\n.endc\n.end\n", "acx")
check("[E-446] surplus .ac arguments are refused", "surplus arguments" in out, "")
rc, out = run(f"e446\n{AC}\n.control\noption noacct\nac lin 5 100 1k\n"
              f"print mag(v(nb))\n.endc\n.end\n", "acok")
check("[E-446] a well-formed .ac is unaffected (control)",
      rc == 0 and len(re.findall(r"^\s*\d+\s+(\S+)\s+(\S+)", out, re.M)) == 5
      and "surplus" not in out, "")

# --------------------------------------------------- pow() of a negative base ---
print("\nthe sign of a negative base survives")


def bval(expr, tag):
    rc, out = run(f"e446\nV1 in 0 dc 1\nB1 nb 0 v={expr}\nR1 nb 0 1k\n.control\n"
                  f"option noacct\nset numdgt=10\nop\nprint v(nb)\n.endc\n.end\n", tag)
    v = val(out, "v(nb)")
    return rc, (float(v) if v is not None else None)

for expr, want in (("(-2)**3", -8.0), ("(-2)**1", -2.0), ("(-2)**5", -32.0),
                   ("(-2)^3", -8.0), ("pow(-2,3)", -8.0), ("(-2)**2", 4.0),
                   ("(-2)**4", 16.0)):
    rc, g = bval(expr, "pw" + re.sub(r"\W", "", expr))
    check(f"[E-446] {expr} = {want:g}",
          g is not None and abs(g - want) < 1e-9, f"{g}")
# the sibling that was always right, and the model-side answer it now matches
rc, g = bval("pwr(-2,3)", "pwrctl")
check("[E-446] pwr(-2,3) is unchanged at -8 (control)",
      g is not None and abs(g + 8.0) < 1e-9, f"{g}")
# positive bases must be untouched, including fractional exponents
for expr, want in (("2**3", 8.0), ("2**0.5", math.sqrt(2)), ("2**-1", 0.5),
                   ("0**0", 1.0), ("9**0.5", 3.0)):
    rc, g = bval(expr, "pp" + re.sub(r"\W", "", expr))
    check(f"[E-446] a positive base is untouched: {expr} = {want:g} (control)",
          g is not None and abs(g - want) < 1e-9, f"{g}")
# a negative base with a NON-integer exponent has no real value: it must stay
# finite (a NaN here poisons the Jacobian -- E-256/E-440), not become NaN
rc, g = bval("(-2)**0.5", "pnan")
check("[E-446] a negative base with a fractional exponent stays FINITE (control)",
      g is not None and math.isfinite(g), f"{g}")
# E-440's guard on 0 raised to a negative power must still hold. It is refused
# while the expression is parsed, so the deck never runs -- that is the same
# before and after this change.
rc, out = run("e446\nV1 in 0 dc 1\nB1 nb 0 v=pow(0,-1)\nR1 nb 0 1k\n.control\n"
              "option noacct\nop\nprint v(nb)\n.endc\n.end\n", "pzero")
check("[E-446] pow(0,-1) is still refused outright (control)",
      rc != 0 and "out of range for pow" in out, f"rc={rc}")

# ------------------------------------------- @c[capacitance] reporting vs m= ---
print("\n@c[capacitance] reports what the deck wrote, like @r[resistance]")


def query(dev, q, tag):
    rc, out = run(f"e446\nV1 in 0 dc 0 ac 1\nRs in nb 1k\n{dev}\n.control\n"
                  f"option noacct\nset numdgt=10\nop\nprint {q}\n.endc\n.end\n", tag)
    v = val(out, q)
    return rc, (float(v) if v is not None else None)


rc, c2 = query("C1 nb 0 1u m=2", "@c1[capacitance]", "cm2")
rc, c1 = query("C1 nb 0 1u", "@c1[capacitance]", "cm1")
rc, r2 = query("R1 nb 0 1k m=2", "@r1[resistance]", "rm2")
check("[E-446] `C1 .. 1u m=2` reports the written 1u", c2 is not None and abs(c2 - 1e-6) < 1e-15, f"{c2}")
check("[E-446] ...matching how `R1 .. 1k m=2` has always reported 1k (control)",
      r2 is not None and abs(r2 - 1000.0) < 1e-9, f"{r2}")
check("[E-446] and m=1 is unchanged (control)", c1 is not None and abs(c1 - 1e-6) < 1e-15, f"{c1}")


# the SIMULATION must not move: m=2 still behaves as 2u
def acmag(dev, tag):
    rc, out = run(f"e446\nV1 in 0 dc 0 ac 1\nR1 in nb 1k\n{dev}\n.control\n"
                  f"option noacct\nset numdgt=10\nac lin 1 159.1549431 159.1549431\n"
                  f"print mag(v(nb))\n.endc\n.end\n", tag)
    v = val(out, "mag(v(nb))")
    return float(v) if v is not None else None


m2 = acmag("C1 nb 0 1u m=2", "phm2")
two = acmag("C1 nb 0 2u", "ph2u")
par = acmag("C1 nb 0 1u\nC2 nb 0 1u", "phpar")
check("[E-446] the SIMULATION is unchanged: m=2 still equals 2u and two 1u",
      None not in (m2, two, par) and abs(m2 - two) < 1e-12 and abs(m2 - par) < 1e-12,
      f"m=2 {m2}, 2u {two}, parallel {par}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
