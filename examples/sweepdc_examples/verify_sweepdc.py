#!/usr/bin/env python3
"""Enhancement-533: `sweep` hands eligible op-point sweeps to one dc analysis.

With the default `-analysis op`, a single dc-sweepable knob and evenly spaced
points, the sweep's point loop -- npt COLD operating points, one plot each --
is replaced by ONE dc analysis: a warm NIiter continuation, exactly `.dc`.
Measured on the motivating deck (a 1000-device OSDI ladder, 9900 points):
21.2 s per-point -> 2.16 s handed, identical within Newton tolerance.

The safety net is that the two engines were already complementary: `.dc`
REFUSES a point that moves an OSDI node collapse (E-495, recommending `sweep`)
and aborts on device-rejected values (E-427) or non-convergence -- every such
outcome falls back to the per-point loop unchanged. `-perpoint` forces the old
loop; `dc temp` never rebuilds a temperature-moved collapse (a known-open
finding the sweeptemp suite pins), so the temp knob hands over only when the
deck has no OSDI device.

Pinned here: the handover fires where eligible and is BIT-IDENTICAL to a
direct `dc`; it agrees with `-perpoint` within convergence tolerance; every
ineligible spelling (log spacing, live `@` outputs, model knobs, `-vs`
families, `-perpoint`, OSDI+temp) stays on the loop; the collapse-moving
instance sweep falls back and lands on closed-form values; and the knob is
restored to its nominal afterwards.
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
        if junk.startswith("_sdc_"):
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


def run_deck(deck, tag, timeout=300):
    p = os.path.join(HERE, f"_sdc_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def col(fname, idx=1):
    rows = []
    with open(os.path.join(HERE, fname)) as f:
        for line in f:
            if line.strip():
                rows.append(float(line.split()[idx]))
    return rows


HANDED = "handing all"
FELLBACK = "falling back to one op per point"

DIV = """V1 in 0 5
R1 in mid 1k
R2 mid 0 500
D1 mid 0 dm
.model dm d(is=1e-14)
"""


def sweep_deck(control):
    return "sweepdc probe\n" + DIV + ".control\noption noacct\n" + control + "\n.endc\n.end\n"


# ---- the handover itself ---------------------------------------------------
print("the handover: eligible op sweeps become one dc analysis:")

out = run_deck(sweep_deck(
    "sweep @R2[resistance] 100 1000 100 -output v(mid)\n"
    "wrdata _sdc_hand.csv v(mid)\n"
    "sweep @R2[resistance] 100 1000 100 -perpoint -output v(mid)\n"
    "wrdata _sdc_pp.csv v(mid)\n"
    "dc R2 100 1000 100\n"
    "wrdata _sdc_dc.csv v(mid)"), "three")
check("[1] the eligible sweep announces the handover, the -perpoint one "
      "does not", out.count(HANDED) == 1 and FELLBACK not in out)
h, p, d = col("_sdc_hand.csv"), col("_sdc_pp.csv"), col("_sdc_dc.csv")
check("[2] handed sweep is BIT-IDENTICAL to a direct dc",
      len(h) == len(d) == 10 and all(a == b for a, b in zip(h, d)))
wp = max(abs(a - b) for a, b in zip(h, p)) if len(h) == len(p) else 1e9
check("[3] ...and agrees with -perpoint within Newton tolerance",
      len(h) == len(p) and wp < 1e-3, f"max dv = {wp:.2e}")

out = run_deck(sweep_deck(
    "sweep V1 1 5 1 -output v(mid)\nwrdata _sdc_vs.csv v(mid)"), "vsrc")
vs = col("_sdc_vs.csv")
check("[4] a bare source knob hands over through dc's classic arm",
      # 1/3 exactly minus ~1.3 uV: the diode already leaks ~4 nA at 0.33 V
      HANDED in out and len(vs) == 5 and abs(vs[0] - 1.0 / 3.0) < 5e-5,
      f"v(mid)@1V = {vs[0] if vs else None}")

out = run_deck(sweep_deck(
    "sweep @R2[resistance] list 100 200 300 400 -output v(mid)"), "ulist")
check("[5] a UNIFORM list qualifies (spacing is judged from the values)",
      HANDED in out)

out = run_deck(sweep_deck(
    "sweep @R2[resistance] 100 1000 100 -output v(mid)\n"
    "print @R2[resistance]"), "restore")
m = re.search(r"@r2\[resistance\]\s*=\s*(\S+)", out)
check("[6] the knob returns to its nominal after a handed sweep",
      m is not None and abs(float(m.group(1)) - 500.0) < 1e-9,
      m.group(1) if m else "no readback")

# ---- everything that must stay on the loop ---------------------------------
print("ineligible spellings stay on the per-point loop:")

for label, ctl in [
    ("[7] log (dec) spacing", "sweep @R2[resistance] dec 5 100 1000 -output v(mid)"),
    ("[8] a live @-output (prescreened, no dc is run)",
     "sweep @R2[resistance] 100 1000 300 -output @d1[gd]"),
    ("[9] a model-parameter knob", "sweep @dm[is] list 1e-14 2e-14 -output v(mid)"),
    ("[10] a -vs family",
     "sweep @R2[resistance] 100 400 100 -vs V1 list 3 5 -output v(mid)"),
]:
    out = run_deck(sweep_deck(ctl), "inel")
    check(label + " runs per-point", HANDED not in out and "points into plot" in out
          or "curves" in out)

# ---- temp: OSDI declines, built-ins keep the speedup -----------------------
print("the temp knob: dc cannot follow an OSDI collapse, built-ins are safe:")

r = subprocess.run([OPENVAF, os.path.join(HERE, "sdccoll.va"), "-o",
                    os.path.join(HERE, "_sdc_coll.osdi")], cwd=HERE,
                   capture_output=True, text=True, timeout=600)
check("[11] the collapse-gated OSDI model compiles", r.returncode == 0)

out = run_deck("""temp osdi decline
V1 a 0 1
N1 a 0 mm rs=0
.model mm sdccoll
.control
option noacct
pre_osdi _sdc_coll.osdi
sweep temp 0 100 25 -output i(v1)
.endc
.end
""", "tosdi")
check("[12] `sweep temp` with an OSDI device in the deck stays per-point",
      HANDED not in out and "points into plot" in out)

out = run_deck(sweep_deck("sweep temp 0 100 25 -output v(mid)\n"
                          "wrdata _sdc_th.csv v(mid)\n"
                          "sweep temp 0 100 25 -perpoint -output v(mid)\n"
                          "wrdata _sdc_tp.csv v(mid)"), "tbi")
th, tp = col("_sdc_th.csv"), col("_sdc_tp.csv")
wt = max(abs(a - b) for a, b in zip(th, tp)) if len(th) == len(tp) else 1e9
check("[13] ...a built-in-only deck hands temp over, matching -perpoint "
      "(the diode moves with T, so the points are non-trivial)",
      HANDED in out and len(th) == 5 and wt < 1e-3
      and max(th) - min(th) > 1e-3, f"max dv = {wt:.2e}")

# ---- the fallback: dc's E-495 refusal is the sweep's cue -------------------
print("the fallback: a collapse-moving sweep lands on the per-point loop:")

out = run_deck("""collapse fallback
V1 a 0 1
N1 a 0 mm rs=0
.model mm sdccoll
.control
option noacct
pre_osdi _sdc_coll.osdi
sweep @N1[rs] 0 2000 500 -output i(v1)
wrdata _sdc_fb.csv i(v1)
.endc
.end
""", "fb")
fb = col("_sdc_fb.csv")
want = [-1.0 / (rs + 1000.0) for rs in (0, 500, 1000, 1500, 2000)]
wf = max(abs(a - b) for a, b in zip(fb, want)) if len(fb) == 5 else 1e9
check("[14] dc refuses the moved topology and the sweep says so",
      HANDED in out and FELLBACK in out)
check("[15] ...and the per-point loop lands on the closed-form values "
      "(series resistance appears exactly)",
      len(fb) == 5 and wf < 1e-12, f"max err = {wf:.2e}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
