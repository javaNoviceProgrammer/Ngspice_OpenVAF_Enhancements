#!/usr/bin/env python3
"""Enhancement-491: an unbounded number used as a length, and four wrong ones.

Round 51 found ten defects sharing a shape: a number the deck supplies was used
without being measured against what it was about to control.

THE CRASHES. `set numdgt=<n>` is the user's print precision and nothing bounded
it. `printnum()` formatted with `sprintf(buf, "%.*e", cp_numdgt, num)` into
caller buffers of BSIZE_SP (512), and evtprint formatted into a `char[100]`.
Both thresholds land where the arithmetic says they must:

    set numdgt=510  + `print`   -> ~519 bytes into 512   SIGABRT
    set numdgt=94   + `eprint`  ->  ~103 bytes into 100  SIGTRAP

from a plain batch deck, no interactivity. printnum()'s own comment had recorded
the hazard -- "It can cause buffer overruns" -- without bounding it, while the
DSTRING sibling printnum_ds() next to it could not overflow, which is why
`fourier`, `wrdata`, `write`, `display` and `diff` were unaffected and only the
`print` family crashed.

THE WRONG NUMBERS.

  * `PTdivide` added `PTfudge_factor` -- gmin * 1e-20 -- to EVERY divisor, not
    just a zero one. `1/boltz` came out 42% low under `.option gmin=1e-3` and
    88% low under `gmin=1e-2`; `1/0` returned 1e26, 1e32 or 1e50 depending on
    gmin alone. A deck's arithmetic moved because the user reached for a
    convergence aid.
  * `sin`/`cos`/`tan` in a B-source reduced their argument with
    `x - (int)(x/2pi)*2pi`. The cast is undefined above 2^31*2pi (~1.35e10), and
    `sin(1e20)` returned +0.9993 where the answer is -0.6453. numparam AND a
    Verilog-A model each already matched libm exactly, so the B-source was the
    sole outlier -- the divergence Enhancement-399 forbids.

THE SILENT REFUSALS.

  * A `sens` filter that matched no parameter produced no plot and said nothing,
    leaving the PREVIOUS analysis current for a following `print`.
  * The interactive `meas` enforced its analysis keyword for interval
    measurements (Enhancement-468) and ignored it for point ones, so
    `meas tran ... FIND ... AT=` read a DC sweep as a transient.
  * `s_xfer` blamed the SOLVER for a model error: an all-zero denominator went
    NaN and was reported as "Dynamic gmin stepping failed", and a numerator
    longer than the denominator was announced once per evaluation -- 1238 times
    over 300 steps -- while the run returned rc=0 with the device contributing
    nothing.
  * `printf("oops ")` reached users on stdout; `show` printed `?????????` for an
    unknown parameter where every sibling command names it; a duplicate user
    `.func` was silently last-wins while shadowing a builtin warned.

Every check below is either a crash that must not happen, a number that must
equal its closed form, or a diagnostic that must name the cause.
"""
import math
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
        if junk.startswith("_ng_"):
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


def run(body, ctl, tag, osdi=False):
    pre = "pre_osdi numguard.osdi\n" if osdi else ""
    deck = (f"numguard {tag}\n{body}\n.control\n{pre}option noacct\nset numdgt=12\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_ng_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=120,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


r = subprocess.run([OPENVAF, "numguard.va", "-o", "numguard.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-491: bounded output fields and honest arithmetic\n")
check("[E-491] the Verilog-A cross-check model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "numguard.osdi")),
      (r.stdout + r.stderr).strip()[:60])

RC = "V1 a 0 dc 1\nR1 a 0 1k\n"

# ------------------------------------------------------- the crashes --------
print("\nan unbounded numdgt must not write past the field it formats into")
for nd in (510, 600, 1000, 2000, 10000, 100000):
    rc, out = run(RC, f"set numdgt={nd}\nop\nprint v(a)", f"p{nd}")
    check(f"[E-491] `print` survives numdgt={nd}", rc == 0,
          f"rc={rc}" if rc != 0 else "")

EVT = ("V1 a 0 PULSE(0 1 0 1u 1u 10u 20u)\nR1 a 0 1k\n"
       "Aadc [a] [dn] adcbr\n.model adcbr adc_bridge\n")
for nd in (94, 100, 200, 1000, 100000):
    rc, out = run(EVT, f"set numdgt={nd}\ntran 1u 50u\neprint dn", f"e{nd}")
    check(f"[E-491] `eprint` survives numdgt={nd}", rc == 0,
          f"rc={rc}" if rc != 0 else "")

rc, out = run(RC, "set numdgt=1000\nop\nprint v(a)", "clampmsg")
check("[E-491] ...and says once that it narrowed the field",
      "does not fit the output field" in out, "")
check("[E-491] ...saying it only once, not per value",
      out.count("does not fit the output field") == 1,
      f"{out.count('does not fit the output field')}x")

print("\nordinary precisions are untouched")
for nd, want in ((6, 7), (12, 13), (17, 18)):
    rc, out = run(RC, f"set numdgt={nd}\nop\nprint v(a)", f"n{nd}")
    m = re.search(r"v\(a\)\s*=\s*(\S+)", out)
    digits = len(m.group(1).split("e")[0].replace("-", "").replace(".", "")) if m else -1
    check(f"[E-491] numdgt={nd} still prints {want} significant digits",
          rc == 0 and digits == want, f"{m.group(1) if m else '?'}")

# ------------------------------------------------------- the divisor --------
print("\na divisor is used as written; only an exact zero is nudged")
BOLTZ = 1.38064852e-23
EXACT = 1.0 / BOLTZ
for gm in (None, "1e-12", "1e-6", "1e-3", "1e-2", "1"):
    pre = "" if gm is None else f".option gmin={gm}\n"
    rc, out = run(pre + RC + f"B0 n 0 V=1/{BOLTZ}\nRk n 0 1meg\n",
                  "op\nprint v(n)", f"b{gm}")
    v = val(out, "v(n)")
    err = abs(v - EXACT) / EXACT if v else 1.0
    check(f"[E-491] 1/boltz is exact with gmin={gm or 'default'}",
          rc == 0 and err < 1e-12, f"rel.err {err:.1e}")

for d, exact in (("1e-28", 1e28), ("1e-30", 1e30), ("1e-32", 1e32), ("1e-34", 1e34)):
    rc, out = run(RC + f"B0 n 0 V=1/{d}\nRk n 0 1meg\n", "op\nprint v(n)",
                  "d" + d.replace("-", "m").replace("e", ""))
    v = val(out, "v(n)")
    check(f"[E-491] 1/{d} is exact", v is not None and abs(v - exact) / exact < 1e-12,
          f"{v}")

zero = []
for gm in ("1e-12", "1e-6", "1e-30", "1"):
    rc, out = run(f".option gmin={gm}\nV1 a 0 dc 0\nR1 a 0 1k\n"
                  "B0 n 0 V=1/v(a)\nRk n 0 1meg\n", "op\nprint v(n)",
                  "z" + gm.replace("-", "m"))
    zero.append(val(out, "v(n)"))
check("[E-491] 1/0 no longer depends on gmin", len(set(zero)) == 1, f"{zero}")
check("[E-491] ...and is still finite, so the solve continues",
      all(z is not None and abs(z) < float("inf") for z in zero), f"{zero[0]}")

# ------------------------------------------------------- the trig -----------
print("\ntrig matches libm at every magnitude, and so matches the other evaluators")
for fn, ref in (("sin", math.sin), ("cos", math.cos), ("tan", math.tan)):
    for x in ("1e3", "1e9", "1.35e10", "1e12", "1e15", "1e20"):
        rc, out = run(RC + f"B0 n 0 V={fn}({x})\nRk n 0 1meg\n", "op\nprint v(n)",
                      f"t{fn}{x.replace('.','').replace('+','')}")
        v = val(out, "v(n)")
        want = ref(float(x))
        check(f"[E-491] {fn}({x}) matches libm",
              v is not None and abs(v - want) < 1e-11, f"{v} vs {want:.12f}")

print("\nthe three evaluators agree, which is the point")
X = "1e20"
_, o_b = run(RC + f"B0 n 0 V=sin({X})\nRk n 0 1meg\n", "op\nprint v(n)", "xb")
_, o_p = run(f".param s={{sin({X})}}\n" + RC + "B0 n 0 V=s\nRk n 0 1meg\n",
             "op\nprint v(n)", "xp")
_, o_v = run("V1 a 0 dc 0\nN1 a 0 vm\n.model vm vsin x=" + X + "\nR1 a 0 1\n",
             "op\nprint i(V1)", "xv", osdi=True)
b, p_ = val(o_b, "v(n)"), val(o_p, "v(n)")
m = re.findall(r"(?m)^\s*i\(v1\)\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", o_v, re.I)
va = -float(m[-1]) if m else None
want = math.sin(float(X))
check("[E-491] B-source sin(1e20) == libm", b is not None and abs(b - want) < 1e-11, f"{b}")
check("[E-491] numparam agrees", p_ is not None and abs(p_ - want) < 1e-11, f"{p_}")
check("[E-491] Verilog-A agrees", va is not None and abs(va - want) < 1e-9, f"{va}")

# ------------------------------------------------------- silent refusals ----
print("\na sens filter that matches nothing says so")
SENS = "V1 a 0 dc 2\nR9 a b 1meg\nR8 b 0 1meg\n"
rc, out = run(SENS, "op\nsens v(b) totalnonsense", "s1")
check("[E-491] an unmatched filter is reported",
      "no parameter of this circuit matches the filter" in out, "")
check("[E-491] ...naming the filter that missed", "'totalnonsense'" in out, "")
rc, out = run(SENS, "op\nsens v(b) r8\nprint r8", "s2")
check("[E-491] a filter that DOES match still works",
      rc == 0 and abs((val(out, "r8") or 0) - 5e-7) < 1e-11, f"{val(out,'r8')}")
rc, out = run(SENS, "op\nsens v(b)\nprint r8 r9", "s3")
check("[E-491] and no filter at all still varies everything",
      rc == 0 and abs((val(out, "r8") or 0) - 5e-7) < 1e-11
      and "matches the filter" not in out, f"{val(out,'r8')}")

print("\nthe meas analysis keyword is enforced for POINT measurements too")
MD = "V1 in 0 dc 1 sin(0 1 1k)\nR1 in n 1k\nC1 n 0 1u\n"
rc, out = run(MD, "dc V1 0 1 0.1\nmeas tran m FIND v(n) AT=0.5", "m1")
check("[E-491] `meas tran ... FIND` over a dc plot is refused",
      "not a tran analysis" in out, "")
rc, out = run(MD, "tran 10u 1m\nmeas dc m FIND v(n) AT=0.5m", "m2")
check("[E-491] `meas dc ... FIND` over a tran plot is refused",
      "not a dc analysis" in out, "")
rc, out = run(MD, "dc V1 0 1 0.1\nmeas dc m FIND v(n) AT=0.5\nprint m", "m3")
check("[E-491] the matching keyword still measures",
      rc == 0 and abs((val(out, "m") or 0) - 0.5) < 1e-9, f"{val(out,'m')}")
rc, out = run(MD, "tran 10u 1m\nmeas tran m AVG v(n) FROM=0.2m TO=0.8m\nprint m", "m4")
check("[E-491] interval measurements are unchanged (E-468 still holds)",
      rc == 0 and val(out, "m") is not None, f"{val(out,'m')}")

print("\ns_xfer names its own fault instead of blaming the solver")
SX = "V1 a 0 dc 0 PULSE(0 1 0 1u 1u 20u 40u)\nR1 a 0 1k\n"
rc, out = run(SX + "Asx a o sx\n.model sx s_xfer num_coeff=[1] den_coeff=[0]\n"
              "Ro o 0 1meg\n", "tran 2u 60u", "x1")
check("[E-491] an all-zero denominator is refused",
      "every denominator coefficient is zero" in out, "")
check("[E-491] ...and gmin stepping is not blamed",
      "gmin stepping failed" not in out, "")
rc, out = run(SX + "Asx a o sx\n.model sx s_xfer num_coeff=[1 1 1] den_coeff=[1]\n"
              "Ro o 0 1meg\n", "tran 2u 600u", "x2")
check("[E-491] num>den is announced once, not once per evaluation",
      out.count("Numerator coefficient array size") == 1,
      f"{out.count('Numerator coefficient array size')}x")
rc, out = run(SX + "Asx a o sx\n.model sx s_xfer num_coeff=[1] den_coeff=[1 1]\n"
              "Ro o 0 1meg\n", "tran 2u 60u\nprint v(o)[10]", "x3")
check("[E-491] a valid transfer function is untouched",
      rc == 0 and val(out, "v(o)[10]") is not None, f"{val(out,'v(o)[10]')}")

print("\ndiagnostics that named nothing now name something")
rc, out = run(".param pv={ln(0)}\n" + RC + "B0 n 0 V=pv\nRk n 0 1meg\n", "op", "o1")
check("[E-491] no bare `oops` reaches the user", "oops" not in out, "")
rc, out = run(RC, "op\nshow r1 : nosuchp", "o2")
check("[E-491] `show` names an unknown parameter",
      "has no parameter" in out and "nosuchp" in out, "")
rc, out = run(RC, "op\nshow r1 : resistance", "o3")
check("[E-491] ...and a real parameter is still shown",
      rc == 0 and "has no parameter" not in out, "")
rc, out = run(".func f(x)={2*x}\n.func f(x)={3*x}\n" + RC
              + "B0 m 0 V=f(3)\nRm m 0 1meg\n", "op\nprint v(m)", "o4")
check("[E-491] a duplicate .func is announced", "defined more than once" in out, "")
check("[E-491] ...and still resolves to the last definition, as before",
      abs((val(out, "v(m)") or 0) - 9.0) < 1e-9, f"{val(out,'v(m)')}")
rc, out = run(".func sin(x)={99}\n" + RC + "B0 m 0 V=sin(3)\nRm m 0 1meg\n",
              "op\nprint v(m)", "o5")
check("[E-491] shadowing a builtin keeps E-467's own warning",
      "redefines the built-in" in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
