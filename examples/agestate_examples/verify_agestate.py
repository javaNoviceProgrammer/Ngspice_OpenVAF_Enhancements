#!/usr/bin/env python3
"""Enhancement-501: what survives an internal `reset`, and what the loop commands
accept and claim on the way there.

Round 59 probed the sweep / optimize / montecarlo / aging intersection.

THE STATE. `aging` (Enhancement-157) works by writing an accumulated dose into
each device's `age` parameter with `alter`, then leaving the circuit standing so
the following analyses see the degraded device. The dose lives only in the running
circuit -- it has no deck representation -- so every command that RE-SOURCES the
deck between evaluations threw it away on the first one and ran the rest of the
loop on a fresh circuit, silently. That is `wcd`, `highsigma` and
`optimize -center`. The commands whose whole purpose is to characterise a part
were the ones that could not characterise an aged one: `wcd` reported the fresh
worst-case distance for an aged transistor, which is the answer to a question
nobody asked, with nothing in the output to say so. `montecarlo` escaped only by
accident -- Enhancement-346's fast path arms whenever a random value binds and
says so ("no per-sample reset"), and that is the usual case; its fallback path
re-sources like the others.

The dose is now recorded as it is written and replayed after an internal reset.
A `reset` the USER types drops the record, because that is what `reset` means --
so the internal ones are marked as internal, and only those replay.

THE ARGUMENTS. `aging`'s own numbers went through bare atof(): `aging abc` aged
to 0 s, and `aging nan` passed the `t <= 0` guard -- every comparison with NaN is
false -- and wrote NaN doses into every device, reporting them aged. `dynamic`'s
stop time was never checked to be a number at all, so `aging 1e8 dynamic verbose`
consumed `verbose` as the stop time and then complained about `agerate`, naming a
token the user never typed.

The same NaN hole ran through the spec bounds of the four statistical commands: a
bound is used only in comparisons, so a NaN bound is never violated and is exactly
equivalent to omitting it -- `montecarlo ... -max nan` reported 100% yield with a
Wilson interval, describing a spec that did not exist.

THE CLAIMS. A yield is a statement about variation. A deck with no random
parameter -- or with one the metric does not depend on -- produced 50 identical
samples and reported `100.000%  (50/50)` with a 95% CI of [92.865%, 100.000%]:
an interval that looks tight precisely because every sample was the same sample.
And `optimize` published what it SCORED (dcenter_yield, dcenter_cpk) but never
what it SOLVED FOR, so the shipped dcenter demo's `print xc` asked for a `.param`
as though it were a vector and printed a `checkvalid` warning on every run. The
final knob values are now published as `optimize_<name>`.

`aging ... param <name>` is unchanged in what it accepts -- some models spell
their aging state differently -- but it now says so when the dose is aimed at a
parameter other than `age` on a device that HAS an `age`: `param w` wrote 4.095e8
into a MOSFET's width, reported "1 device aged", and exited 0.
"""

import atexit
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)

SCRATCH = tempfile.mkdtemp(prefix="agestate_verify_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(deck, tag, timeout=900):
    p = os.path.join(SCRATCH, f"{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=SCRATCH,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


NUM = r"-?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|nan|inf)"


def scalar(out, name):
    m = re.findall(rf"{re.escape(name)}\s*=\s*({NUM})", out, re.I)
    return float(m[-1]) if m else None


def yieldpct(out):
    m = re.findall(rf"yield\s+:\s+({NUM})%", out)
    return float(m[-1]) if m else None


def pfail(out):
    m = re.findall(rf"P\(fail\)\s*:\s*({NUM})", out)
    return float(m[-1]) if m else None


def beta(out):
    m = re.findall(rf"beta\s*=\s*({NUM})", out, re.I)
    return float(m[-1]) if m else None


osdi = os.path.join(SCRATCH, "agemos.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "agemos.va"), "-o", osdi],
                   capture_output=True, text=True, timeout=300, cwd=SCRATCH)
if not os.path.exists(osdi):
    print("  FAIL  agemos.va compiles  [%s]" % (r.stdout + r.stderr).strip()[-160:])
    sys.exit(1)

MODEL = ".model amos agemos vth0=0.5 kp=100u w=2u l=0.5u\n"
# A common-source stage whose drain node reports the device: aging raises vth,
# the current falls, and v(d) rises. vth0 carries the process variation the
# statistical commands need.
CORE = (".param rv = agauss(10000, 400, 3)\n"
        "Vdd dd 0 dc 1.0\nR1 dd d {rv}\nVg g 0 dc 1.8\nN1 d g 0 amos\n"
        + MODEL)


def deck(ctl, core=CORE):
    return ("agestate\n" + core + ".control\noption noacct\nset numdgt=10\n"
            "pre_osdi %s\n%s\n.endc\n.end\n" % (osdi, ctl))


print("Enhancement-501: aged state across an internal reset, and loop-command claims")

# ---------------------------------------------------------------------------
# [1]-[6]  THE HEADLINE: the aged device must still be aged inside the loop
# ---------------------------------------------------------------------------
print("\n  aged state survives the internal reset")

WCD = "wcd -metric v(d) -max {hi} -analysis op"
rc, fresh = run(deck("op\n" + WCD.format(hi="0.19")), "wfresh")
rc, aged = run(deck("op\naging 3e9\n" + WCD.format(hi="0.19")), "waged")
bf, ba = beta(fresh), beta(aged)
check("[1] wcd on a fresh device reports a worst-case distance", bf is not None,
      f"beta = {bf}")
check("[2] wcd on an AGED device reports a DIFFERENT distance", 
      bf is not None and ba is not None and abs(ba - bf) > 1e-3,
      f"fresh {bf} vs aged {ba}")
check("[3] the aged distance is the SMALLER one (degradation costs margin)",
      bf is not None and ba is not None and ba < bf, f"{ba} < {bf}")

rc, out = run(deck("op\naging 3e9\nmontecarlo 30 -analysis op -spec v(d) "
                   "-max 0.175 -seed 5"), "mcaged")
rc, out0 = run(deck("op\nmontecarlo 30 -analysis op -spec v(d) -max 0.175 -seed 5"),
               "mcfresh")
ya, yf = yieldpct(out), yieldpct(out0)
check("[4] montecarlo yields differ fresh vs aged (fast path: already did)", 
      ya is not None and yf is not None and abs(ya - yf) > 1e-9,
      f"fresh {yf} vs aged {ya}")

rc, out = run(deck("op\naging 3e9\nhighsigma 200 -scale 3 -metric v(d) -max 0.175 "
                   "-analysis op -seed 5"), "hsaged")
rc, out0 = run(deck("op\nhighsigma 200 -scale 3 -metric v(d) -max 0.175 "
                    "-analysis op -seed 5"), "hsfresh")
pa, pf = pfail(out), pfail(out0)
check("[5] highsigma failure probabilities differ fresh vs aged",
      pa is not None and pf is not None and pa != pf, f"fresh {pf} vs aged {pa}")

# A `reset` the USER types is still a reset.
rc, out = run(deck("op\naging 3e9\nreset\n" + WCD.format(hi="0.19")), "wreset")
br = beta(out)
check("[6] a user-typed `reset` still clears the aged state",
      br is not None and bf is not None and abs(br - bf) < 1e-6,
      f"after reset {br} == fresh {bf}")

# ---------------------------------------------------------------------------
# [7]-[14]  `aging` argument validation
# ---------------------------------------------------------------------------
print("\n  `aging` refuses a target it cannot age to")

for i, (arg, why) in enumerate(
        [("nan", "NaN passes every `<= 0` test"), ("inf", "infinite target"),
         ("0", "zero target"), ("-1", "negative target"), ("abc", "not a number")]):
    rc, out = run(deck(f"op\naging {arg}\nprint @n1[age]"), f"ag{i}")
    refused = "usage: aging" in out or re.search(r"aging:.*(number|positive)", out)
    aged = re.search(r"device%s aged" % "s?", out)
    check(f"[{7+i}] `aging {arg}` is refused ({why})", bool(refused) and not aged,
          "refused" if refused else "ACCEPTED")

rc, out = run(deck("op\naging 1e8 dynamic verbose"), "agdynv")
check("[12] `dynamic verbose` blames `verbose`, not some other token",
      "verbose" in out and "dynamic" in out and "agerate" not in out.split("dynamic")[-1][:200],
      (re.findall(r"aging:.*", out) or ["(nothing)"])[0][:70])

rc, out = run(deck("op\naging 1e8 dynamic nan"), "agdynn")
check("[13] `dynamic nan` is refused", 
      bool(re.search(r"aging:.*(number|positive|finite)", out)) or "usage: aging" in out)

rc, out = run(deck("op\naging 3e9\nprint @n1[age]"), "aggood")
age = scalar(out, "@n1[age]")
check("[14] a good target still ages the device", age is not None and age > 0,
      f"age = {age}")

# ---------------------------------------------------------------------------
# [15]-[16]  `aging param` plausibility
# ---------------------------------------------------------------------------
print("\n  `aging param` says when the dose is aimed somewhere odd")

rc, out = run(deck("op\naging 1e8 param w"), "agpw")
check("[15] `param w` warns that the device also has an `age`",
      "also has an 'age' parameter" in out, "warned" if "also has" in out else "SILENT")
rc, out = run(deck("op\naging 1e8"), "agpa")
check("[16] the default `param age` says nothing", "also has an 'age' parameter" not in out)

# ---------------------------------------------------------------------------
# [17]-[24]  spec bounds must be numbers, and may be negative
# ---------------------------------------------------------------------------
print("\n  a spec bound that is not a number is refused, not ignored")

BAD = [("[17]", "montecarlo 20 -analysis op -spec v(d) -max nan -seed 3", "montecarlo -max nan"),
       ("[18]", "montecarlo 20 -analysis op -spec v(d) -max abc -seed 3", "montecarlo -max abc"),
       ("[19]", "highsigma 100 -scale nan -metric v(d) -max 0.175 -analysis op -seed 3",
        "highsigma -scale nan"),
       ("[20]", "highsigma 100 -scale 3 -metric v(d) -max nan -analysis op -seed 3",
        "highsigma -max nan"),
       ("[21]", "wcd -metric v(d) -max nan -analysis op", "wcd -max nan"),
       ("[22]", "wcd -metric v(d) -max 0.19 -tol abc -analysis op", "wcd -tol abc")]
for i, (n, cmd, label) in enumerate(BAD):
    rc, out = run(deck(cmd), f"sb{i}")
    ref = re.search(r"(must be finite|is not a number|needs a number)", out)
    ran = re.search(r"(yield\s+:|beta\s*=|P\(fail\))", out)
    check(f"{n} `{label}` is refused", bool(ref) and not ran,
          (ref.group(0) if ref else "ACCEPTED"))

rc, out = run(deck("montecarlo 20 -analysis op -spec v(d) -min -1 -max 0.9 -seed 3"), "sbneg")
check("[23] a NEGATIVE bound still works (it is a legal limit)",
      yieldpct(out) is not None, f"yield = {yieldpct(out)}%")
rc, out = run(deck("montecarlo 20 -analysis op -spec v(d) -max 0.175 -seed 3"), "sbgood")
check("[24] an ordinary bound still works",
      yieldpct(out) is not None, f"yield = {yieldpct(out)}%")

# ---------------------------------------------------------------------------
# [25]-[27]  a yield computed from samples that never varied
# ---------------------------------------------------------------------------
print("\n  a yield says whether anything actually varied")

FLAT = "Vdd dd 0 dc 1.0\nR1 dd d 10k\nR2 d 0 10k\n"
UNUSED = ".param junk = agauss(1, 0.5, 3)\n" + FLAT
MC = "montecarlo 40 -analysis op -spec v(d) -min 0.1 -max 0.9 -seed 7"
rc, out = run(deck(MC, core=FLAT), "nv0")
check("[25] no random parameter at all -> the yield says so",
      "every sample gave the SAME value" in out,
      "NOTE" if "SAME value" in out else "unwarned %s%%" % yieldpct(out))
rc, out = run(deck(MC, core=UNUSED), "nv1")
check("[26] a random parameter the metric ignores -> also says so",
      "every sample gave the SAME value" in out)
rc, out = run(deck(MC), "nv2")
check("[27] a genuinely varying deck says nothing",
      "every sample gave the SAME value" not in out)

# ---------------------------------------------------------------------------
# [28]-[30]  optimize publishes the answer, not only the score
# ---------------------------------------------------------------------------
print("\n  optimize publishes what it solved for")

DC = (".param xc = 4.0\n.param vo = agauss(xc, 1.5, 3)\n"
      "V1 out 0 dc {vo}\nR1 out 0 1k\n")
rc, out = run(deck("optimize -dparam xc 4.0 3 7 -center -lhs -samples 60 -analysis op "
                   "-spec v(out) -min 4 -max 6 -seed 3\nprint optimize_xc", core=DC), "oc")
xc = scalar(out, "optimize_xc")
check("[28] `optimize_xc` is published and printable", xc is not None, f"optimize_xc = {xc}")
check("[29] it holds the CENTRED value, not the starting one",
      xc is not None and abs(xc - 5.0) < 0.5 and abs(xc - 4.0) > 0.1, f"{xc} ~ 5")
check("[30] printing it produces no `checkvalid` warning",
      "not available" not in out, "clean" if "not available" not in out else "checkvalid")

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
