#!/usr/bin/env python3
"""Enhancement-485: eight guards that detected a fault and then used the bad value.

Round 49 hunted ngspice + OSDI for an hour. The frontend and OSDI paths came back
clean almost everywhere -- the parameter, range, temperature and state-restoration
work of E-426/427/440/455/478/480 is all visibly firing. What it found instead was
a single recurring shape, concentrated in the XSPICE code models:

    the code KNOWS the input is unusable, says so, and then answers from it.

THE HEADLINE, `xspice/cm/cmutil.c`. The shared limiter helper `cm_climit_fcn` had
its bail-out COMMENTED OUT:

    if (linear_range < 0.0) {
        printf("%s\\n",climit_range_error);
    /*      limited_out = 0.0; ... return;
    */  }

It could not simply be uncommented: those lines assign the LOCALS and return,
while the out-parameters are written at the end of the function, so restoring them
verbatim would have left *out_final uninitialised -- which is very likely why they
were disabled rather than repaired. [5] and [6] pin the repair that does work.

THE SAME SHAPE, FOUR MORE TIMES:
  * `limit`, `int`, `d_dt` never computed `linear_range` at all, so a `limit_range`
    wider than half the limit span carried the output straight past the limits
    those blocks exist to enforce -- 24.5, 96.3, 24.3 against limits of +/-1, and
    249999.75 at limit_range=1e6. Silent. E-468's own comment says it added its
    checks "as the CLIMIT sibling already does"; it ported two and not this one.
  * `pwl`'s monotonicity guard ended in `break`, which left only the CHECKING
    loop; the table was then built from the data just declared unusable and
    x=[0 2 1] answered 5.5 for an input of 0.5, above the table's whole y range.
  * `hyst` and `slew` had no checks at all, and both had shapes that killed the
    block in silence.

AND THREE IN THE FRONTEND:
  * `sens ... ac` validated nothing, while `.ac` -- in the same file -- rejects
    the same arguments by name. A reversed range did not merely go unreported: it
    swept a FABRICATED decade, 1e6 -> 1e7 ascending.
  * `disto` reported "no such parameter on this device", a DEVICE fault it does
    not have, identically for two different sweep-argument faults.
  * `.include <a directory>` and `source <a directory>` succeeded silently --
    `fopen()` on a directory succeeds on macOS, the BSDs and glibc -- so the deck
    solved a different circuit with no diagnostic anywhere.
  * `meas` clamped a negative FROM correctly and then REPORTED the window the
    user asked for rather than the one it used.

THE REPAIR IS THE CODEBASE'S OWN PATTERN. `sine`, `square` and `triangle` already
do detect -> report -> substitute a safe value (`freq = 1e-16`), and `pwl`'s size
check does detect -> report -> return. These eight sites had fallen out of it.

WHAT IS NOT HERE. Three reported findings were withdrawn, one of them at fix time:
`sweep`'s negative step is corrected on purpose (`com_sweep.c:2119`, "fix an
obvious sign slip"), XSPICE `Limits:` ARE enforced, and `.nodeset` on an OSDI
internal node really is ignored. See the round-49 notes.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, ctl, tag, timeout=120):
    path = os.path.join(HERE, f"_gs_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* guardsweep {tag}\n{deck}\n.control\noption noacct\nset numdgt=12\n"
                f"{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "-r", os.devnull, path], capture_output=True,
                       text=True, timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
    try:
        os.remove(path)
    except OSError:
        pass
    return r.returncode, (r.stdout + r.stderr)


def val(out, name):
    """Anchored to the start of a line -- round 49 lost a whole finding because an
    unanchored read matched a card ECHOED inside a diagnostic."""
    m = re.findall(r"(?m)^\s*" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


def diagnostics(out):
    """UNFILTERED: every line that is not routine banner or data. A 'no message'
    claim must never be made against a keyword filter (round 49 lost a finding
    that way too)."""
    keep = []
    for line in out.splitlines():
        s = line.strip()
        if not s or "initialization file" in s:
            continue
        if re.match(r"^(Circuit:|Doing analysis|Using SPARSE|Using KLU|Note:|"
                    r"No\. of Data|Index|\d+\s|Reducing trtol|Total|binary raw|"
                    r"ASCII raw|OP information|\S+\s*=\s*[-\d])", s):
            continue
        keep.append(s)
    return keep


LIM = ("V1 in 0 dc 0.5\nA1 in out m\nR1 out 0 1k\n"
       ".model m limit(gain=1 out_lower_limit=-1 out_upper_limit=1 limit_range={LR})")
AC = "V1 in 0 dc 1 ac 1\nR1 in out 1k\nC1 out 0 1n\nRl out 0 10k"

print("Enhancement-485: guards that detected a fault and used the bad value anyway\n")

# ---------------------------------------------- limit / int / d_dt (F4) ------
print("a limiter must not leave the limits it exists to enforce")
rc, o = run(LIM.replace("{LR}", "0.1"), "op\nprint v(out)", "lim_ok")
check("[1] a normal limit_range is untouched", abs((val(o, "v(out)") or 9) - 0.5) < 1e-9,
      f"v(out)={val(o,'v(out)')}")
check("[1] ...and says nothing", not diagnostics(o), "silent")
for lr, was in [("5", "1.1125"), ("99", "24.5057"), ("1e6", "249999.75")]:
    rc, o = run(LIM.replace("{LR}", lr), "op\nprint v(out)", f"lim{re.sub(r'\\W','',lr)}")
    v = val(o, "v(out)")
    check(f"[2] limit_range={lr} stays within the limits (was {was})",
          v is not None and -1.0001 <= v <= 1.0001, f"v(out)={v}")
rc, o = run(LIM.replace("{LR}", "99"), "op\nprint v(out)", "lim_msg")
check("[2] ...and it is reported", any("limit_range" in d for d in diagnostics(o)),
      "named")

RAMP = ("V1 in 0 pwl(0 0 1m 1)\nA1 in out m\nR1 out 0 1k\n"
        ".model m {M}(out_lower_limit=-1 out_upper_limit=1 limit_range={LR})")
for mdl, was in [("int", "95.04"), ("d_dt", "24.25")]:
    rc, o = run(RAMP.replace("{M}", mdl).replace("{LR}", "99"),
                "tran 10u 1m\nlet mx=maximum(v(out))\nlet mn=minimum(v(out))\nprint mx mn",
                f"ramp{mdl}")
    mx, mn = val(o, "mx"), val(o, "mn")
    check(f"[3] `{mdl}` stays within its limits too (was {was})",
          mx is not None and mx <= 1.0001 and (mn is None or mn >= -1.0001),
          f"max={mx} min={mn}")

# ------------------------------------------------ the shared helper (F5) -----
print("\nthe shared limiter helper: one message, correct name, usable answer")
ILIM = ("V1 in 0 dc 0.5\nVhi hi 0 dc 1\nVlo lo 0 dc -1\nA1 in hi lo out m\nR1 out 0 1k\n"
        ".model m ilimit(in_offset=0 gain=1 r_out_source=1 r_out_sink=1 i_limit_source=10 "
        "i_limit_sink=10 v_pwr_range=99 i_source_range=1e-6 i_sink_range=1e-6)")
rc, o = run(ILIM, "op\nprint v(out)", "ilim")
v = val(o, "v(out)")
check("[4] `ilimit` output is inside the rails (was 24.48)",
      v is not None and -1.05 <= v <= 1.05, f"v(out)={v}")
banners = [d for d in diagnostics(o) if "****" in d]
check("[5] the message fires ONCE, not once per Newton iteration (was 26)",
      len(banners) == 1, f"{len(banners)} banner(s)")
check("[6] ...and no longer blames CLIMIT in a deck that has none",
      not any("CLIMIT" in d for d in diagnostics(o)), "generic wording")

# ------------------------------------------------------------- pwl (F10) ----
print("\na table declared unusable must not then be used")
PWL = "V1 in 0 dc 0.5\nA1 in out m\nR1 out 0 1k\n.model m pwl(x_array=[{X}] y_array=[0 1 4] input_domain=0.01)"
rc, o = run(PWL.replace("{X}", "0 1 2"), "op\nprint v(out)", "pwl_ok")
check("[7] a well-formed table is unaffected", abs((val(o, "v(out)") or 9) - 0.5) < 1e-9,
      f"v(out)={val(o,'v(out)')}")
for x, lbl in [("0 2 1", "non-monotonic"), ("0 1 1", "duplicate x")]:
    rc, o = run(PWL.replace("{X}", x), "op\nprint v(out)", f"pwl{re.sub(r'\\W','',x)}")
    v = val(o, "v(out)")
    check(f"[8] a {lbl} table is refused, not interpolated (was 5.5)",
          v is not None and abs(v) < 1e-9, f"v(out)={v}")
rc, o = run(PWL.replace("{X}", "0 2 1"), "op\nprint v(out)", "pwl_msg")
check("[8] ...and the message is not repeated per evaluation",
      len([d for d in diagnostics(o) if "ERROR" in d]) == 1,
      f"{len([d for d in diagnostics(o) if 'ERROR' in d])} banner(s)")

# -------------------------------------------------------- hyst / slew (F6) --
print("\nhyst and slew had no checks at all")
HY = ("V1 in 0 pwl(0 0 1m 1)\nA1 in out m\nR1 out 0 1k\n"
      ".model m hyst(in_low={LO} in_high={HI} hyst={H} out_lower_limit=0 "
      "out_upper_limit=1 input_domain=0.01)")
CT = "tran 5u 1m\nlet mx=maximum(v(out))\nprint mx"
rc, o = run(HY.replace("{LO}", "0.2").replace("{HI}", "0.8").replace("{H}", "0.05"), CT, "hy_ok")
mx = val(o, "mx")
check("[9] a normal hysteresis block switches", mx is not None and mx > 0.5, f"max={mx}")
rc, o = run(HY.replace("{LO}", "0.8").replace("{HI}", "0.2").replace("{H}", "0.05"), CT, "hy_inv")
mx = val(o, "mx")
check("[10] an INVERTED in_low/in_high pair still switches (was dead at 0.0)",
      mx is not None and mx > 0.5, f"max={mx}")
check("[10] ...and is reported", any("HYST" in d for d in diagnostics(o)), "named")
rc, o = run(HY.replace("{LO}", "0.2").replace("{HI}", "0.8").replace("{H}", "99"), CT, "hy_wide")
mx = val(o, "mx")
check("[11] a hyst wider than the span still switches (was dead at 0.0)",
      mx is not None and mx > 0.5, f"max={mx}")

SL = ("V1 in 0 pulse(0 1 0 1n 1n 0.5m 1m)\nA1 in out m\nR1 out 0 1k\n"
      ".model m slew(rise_slope={R} fall_slope=1e3)")
CT2 = "tran 10u 2m\nlet mn=minimum(v(out))\nprint mn"
rc, o = run(SL.replace("{R}", "1e3"), CT2, "sl_ok")
mn = val(o, "mn")
check("[12] a normal slew rate is untouched and silent",
      mn is not None and mn >= -0.001 and not diagnostics(o), f"min={mn}")
rc, o = run(SL.replace("{R}", "-1e3"), CT2, "sl_neg")
mn = val(o, "mn")
check("[13] a NEGATIVE slew rate no longer drives the output away (was -2.0)",
      mn is not None and mn >= -0.001, f"min={mn}")
check("[13] ...and is reported", any("SLEW" in d for d in diagnostics(o)), "named")

# ------------------------------------------------------ sens / disto (F1,F2) --
print("\nthe frequency-sweep arguments `.ac` has always checked")
for cmd, ctl, word in [
        ("sens ac dec 0",     "sens v(out) ac dec 0 1 1k",     "number of points"),
        ("sens ac reversed",  "sens v(out) ac dec 10 1meg 1",  "stop frequency"),
        ("sens ac negative",  "sens v(out) ac dec 10 -1 1k",   "start frequency"),
        ("disto dec 0",       "disto dec 0 1 1k",              "number of points"),
        ("disto reversed",    "disto dec 10 1k 1",             "stop frequency")]:
    rc, o = run(AC, ctl, "sw" + re.sub(r"\W", "", cmd)[:10])
    named = any(word in d for d in diagnostics(o))
    check(f"[14] `{cmd}` names the offending argument", named,
          next((d[:44] for d in diagnostics(o) if word in d), "not named"))
check("[15] ...and `disto` no longer blames a device parameter",
      not any("no such parameter on this device" in d for d in diagnostics(o)),
      "device-fault text gone")
for cmd, ctl in [("sens ac", "sens v(out) ac dec 10 1 1k"), ("sens dc", "sens v(out)"),
                 ("disto", "disto dec 10 1 1k")]:
    rc, o = run(AC, ctl, "ok" + re.sub(r"\W", "", cmd)[:8])
    check(f"[16] a VALID `{cmd}` is unaffected", rc == 0 and not diagnostics(o), "silent")

# ------------------------------------------------------------ include (F7) --
print("\na path that exists but is not a file")
os.makedirs(os.path.join(HERE, "_gsdir"), exist_ok=True)
inc = os.path.join(HERE, "_gs_inc.inc")
with open(inc, "w") as f:
    f.write("R2 out 0 1k\n")
try:
    rc, o = run("V1 in 0 dc 1\nR1 in out 1k\n.include ./_gs_inc.inc", "op\nprint v(out)", "inc_ok")
    check("[17] a real include still works", abs((val(o, "v(out)") or 9) - 0.5) < 1e-9,
          f"v(out)={val(o,'v(out)')}")
    rc, o = run("V1 in 0 dc 1\nR1 in out 1k\n.include ./_gsdir", "op\nprint v(out)", "inc_dir")
    check("[18] `.include <directory>` is refused (was silent, v(out)=1.0)",
          rc == 1 and any("not a regular file" in d for d in diagnostics(o)),
          next((d[:46] for d in diagnostics(o) if "regular file" in d), "silent"))
    rc, o = run("V1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k", "source ./_gsdir\nop\nprint v(out)",
                "src_dir")
    check("[18] `source <directory>` too",
          any("not a regular file" in d for d in diagnostics(o)),
          next((d[:46] for d in diagnostics(o) if "regular file" in d), "silent"))
finally:
    for p in (inc,):
        if os.path.exists(p):
            os.remove(p)
    d = os.path.join(HERE, "_gsdir")
    if os.path.isdir(d):
        os.rmdir(d)

# --------------------------------------------------------------- meas (F3) --
print("\nthe measure report must state the window it used")
rc, o = run("V1 in 0 pulse(0 1 0 1n 1n 5u 10u)\nR1 in out 1k\nC1 out 0 1n",
            "tran 10n 20u\nmeas tran ref avg v(out) from=0 to=5u\n"
            "meas tran neg avg v(out) from=-1 to=5u", "meas")
rows = {m.group(1): m.group(0) for m in
        re.finditer(r"(?m)^\s*(ref|neg)\s+=\s+\S+\s+from=\s+(\S+)\s+to=\s+(\S+)", o)}
check("[19] a negative FROM still returns the correct value",
      val(o, "neg") is not None and val(o, "ref") is not None
      and abs(val(o, "neg") - val(o, "ref")) < 1e-9,
      f"neg={val(o,'neg')} ref={val(o,'ref')}")
check("[19] ...and the echoed window is now the one used, not the one asked for",
      "neg" in rows and "-1" not in rows["neg"],
      rows.get("neg", "missing")[:52])
check("[19] ...with the clamp reported",
      any("clamped to 0" in d for d in diagnostics(o)), "named")

for f in os.listdir(HERE):
    if f.startswith("_gs_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
