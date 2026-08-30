#!/usr/bin/env python3
"""Enhancement-509: a domain the compiler refuses in source but not from the deck.

Round 65 found the vein Enhancement-506 opened, one layer deeper. Eight math
builtins and `$vt` carry a compile-time domain guard that fires for a literal AND
a localparam, with a message naming the builtin, the value and the domain:

    error: sqrt: the argument is -4, which is outside the domain of sqrt (values >= 0)

The identical value written on a MODEL CARD is a `parameter`, deliberately not
folded (Enhancement-426: the deck may replace it), so it reached libm untouched
and came back `nan`/`inf`. In an operating-point variable that is silent with exit
code 0; in a residual it surfaced as "Timestep too small; cause unrecorded" --
naming neither the model nor the call, which is the very complaint
Enhancement-504's own comment records.

`$vt` is the one with teeth. A diode `Is*(limexp(V/$vt(tabs)) - 1)` at
`tabs=-300` returned a NEGATIVE thermal voltage, inverting the exponential: the
current fell from -1.207e-04 A to -6.0e-07 A, which is the shunt resistor alone.
The device stopped being a diode and nothing said so.

THE HALF THAT MUST NOT BE GUARDED. `sqrt(V(p,n))` goes briefly negative during
Newton iteration in working models, so refusing every out-of-domain argument would
break them. The guard is emitted only for a PARAMETER-DERIVED argument -- built
from literals, localparams and parameters -- which is fixed for the whole run and
therefore cannot fire spuriously. Checks [10]-[13] hold that line.

And on the simulator side, an integer parameter overflowed silently: `(int)
round(1e300)` is undefined behaviour, saturates to 2147483647 here, and did so
BEFORE the parameter's range check -- so `from [0:2147483647]`, the idiomatic
"any non-negative integer", accepted 1e300 by landing exactly on its upper bound.
`sp=200` against `[0:100]` was refused correctly the whole time; only the values
that overflowed slipped through, and those are the absurd ones.

WITHDRAWN at fix time: round 65 also reported `idtmod` with a deck modulus <= 0
degenerating to plain `idt`. Reading the site, Enhancement-504 chose that
deliberately -- "fall back to the UNWRAPPED integral, which is exactly what
`idtmod` means with no modulus supplied, so the model keeps running and the value
stays finite". The measured identity is that decision, not a defect.
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
        if junk.startswith("_dr_"):
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


def build(src_name, tag):
    osdi = os.path.join(HERE, f"_dr_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src_name), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return (osdi if os.path.exists(osdi) else None), r.stdout + r.stderr


def run(body, ctl, tag, timeout=120):
    p = os.path.join(HERE, f"_dr_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"domainrt\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "[TIMEOUT]"


def scalar(out, name):
    m = re.findall(rf"{re.escape(name)}\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?|nan|inf)", out, re.I)
    return float(m[-1]) if m else None


def rows(out):
    return len([l for l in out.splitlines() if re.match(r"^\s*\d+\s+[-\d.]", l)])


print("Enhancement-509: a domain the compiler refuses in source but not from the deck")

# ---------------------------------------------------------------------------
# 1. every guarded domain, reached from the model card
# ---------------------------------------------------------------------------
print("\n  an out-of-domain value from the DECK is named and refused")

MD, mlog = build("mathdom.va", "md")
check("mathdom.va compiles", MD is not None, mlog.strip()[-160:] if MD is None else "")
if MD:
    CASES = [(0, "sqrt", -4.0), (1, "ln", 0.0), (2, "log", -1.0), (3, "asin", 2.0),
             (4, "acos", -3.0), (5, "acosh", 0.5), (6, "atanh", 1.0),
             (7, "**", -4.0), (8, "pow", -4.0)]
    for sel, who, q in CASES:
        rc, out = run(f"V1 p 0 dc 1\nN1 p 0 mm\n.model mm mathdom sel={sel} q={q}\n",
                      f"pre_osdi {os.path.basename(MD)}\nop\nprint @n1[y]", f"m{sel}")
        named = ("outside the domain" in out) or ("no real power" in out)
        clean = not re.search(r"=\s*(nan|inf|-inf)", out, re.I)
        check(f"{who}({q}) from the deck is refused, and says so", named and clean,
              "" if named and clean else f"named={named} no-nan={clean}")

# ---------------------------------------------------------------------------
# 2. a RUN-TIME argument must be left alone
# ---------------------------------------------------------------------------
print("\n  a run-time argument is NOT refused -- Newton iteration leaves these domains")

RT, rlog = build("rtarg.va", "rt")
check("rtarg.va compiles", RT is not None, rlog.strip()[-160:] if RT is None else "")
if RT:
    for sel, who, legal in [(0, "sqrt(V*V)", True), (1, "ln(1+V*V)", True),
                            (2, "sqrt(V)  with V<0", False), (3, "V ** 0.5 with V<0", False)]:
        rc, out = run(f"V1 p 0 PULSE(-2 2 1n 1n 1n 5n 10n)\nN1 p 0 o mm\n"
                      f".model mm rtarg sel={sel}\nRo o 0 1meg\n",
                      f"pre_osdi {os.path.basename(RT)}\ntran 0.5n 20n\nprint v(o)", f"r{sel}")
        spurious = ("outside the domain" in out) or ("no real power" in out)
        if legal:
            check(f"{who} runs untouched", (not spurious) and rows(out) > 0,
                  f"spurious={spurious} rows={rows(out)}")
        else:
            check(f"{who} is not refused by the guard", not spurious,
                  "the guard fired on a run-time value" if spurious else "")

# ---------------------------------------------------------------------------
# 3. $vt -- the one that changed a device's behaviour
# ---------------------------------------------------------------------------
print("\n  $vt: a negative absolute temperature turned a diode into an open circuit")

VD, vlog = build("vtdiode.va", "vd")
check("vtdiode.va compiles", VD is not None, vlog.strip()[-160:] if VD is None else "")
if VD:
    rc, out = run("V1 a 0 dc 0.6\nN1 a 0 mm\n.model mm vtdiode tabs=300\nRs a 0 1meg\n",
                  f"pre_osdi {os.path.basename(VD)}\nop\nprint i(v1)", "vok")
    i_ok = scalar(out, "i(v1)")
    check("a normal diode still conducts", i_ok is not None and abs(i_ok + 1.207e-04) < 1e-6,
          f"{i_ok}")
    rc, out = run("V1 a 0 dc 0.6\nN1 a 0 mm\n.model mm vtdiode tabs=-300\nRs a 0 1meg\n",
                  f"pre_osdi {os.path.basename(VD)}\nop\nprint i(v1)", "vbad")
    check("a negative absolute temperature is refused, naming $vt", "$vt" in out,
          "" if "$vt" in out else out.strip()[-120:])
    check("  ... and no longer answers with the shunt current alone",
          scalar(out, "i(v1)") is None or abs(scalar(out, "i(v1)") + 6.0e-07) > 1e-9)

# ---------------------------------------------------------------------------
# 4. an integer parameter that does not fit
# ---------------------------------------------------------------------------
print("\n  an integer parameter that overflows no longer saturates onto its own bound")

IR, ilog = build("intrange.va", "ir")
check("intrange.va compiles", IR is not None, ilog.strip()[-160:] if IR is None else "")
if IR:
    PR = f"pre_osdi {os.path.basename(IR)}\nop\nprint @n1[si] @n1[ss]"
    rc, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm intrange ip=1e300\n", PR, "i300")
    check("ip=1e300 against `from [0:2147483647]` is refused", "does not fit" in out,
          "" if "does not fit" in out else f"si={scalar(out, '@n1[si]')}")
    check("  ... and the parameter keeps its default rather than 2147483647",
          scalar(out, "@n1[si]") == 1.0, f"{scalar(out, '@n1[si]')}")
    rc, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm intrange ip=-1e300\n", PR, "in300")
    check("a negative overflow is refused too", "does not fit" in out)
    rc, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm intrange ip=2147483647\n", PR, "imax")
    check("exactly INT_MAX is still accepted", scalar(out, "@n1[si]") == 2147483647.0,
          f"{scalar(out, '@n1[si]')}")
    rc, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm intrange sp=100.4\n", PR, "iround")
    check("an in-range value that ROUNDS is still accepted", scalar(out, "@n1[ss]") == 100.0,
          f"{scalar(out, '@n1[ss]')}")
    rc, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm intrange sp=200\n", PR, "iover")
    check("a plainly out-of-range value is still refused by the range check",
          scalar(out, "@n1[ss]") is None, f"{scalar(out, '@n1[ss]')}")

# ---------------------------------------------------------------------------
# 5. the compile-time half is unchanged
# ---------------------------------------------------------------------------
print("\n  the compile-time guard is unchanged")

LD, llog = build("litdom.va", "ld")
check("a literal and a localparam are still refused at compile time", LD is None)
check("  ... and each one is still named", llog.count("outside the domain of") >= 3,
      f"{llog.count('outside the domain of')} named")

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
