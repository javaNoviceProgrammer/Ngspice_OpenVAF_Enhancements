#!/usr/bin/env python3
"""Enhancement-506: a guard that only ever saw the literal.

Every value guard in `hir_ty` judges a CONSTANT. It sees a literal or a
localparam and nothing else, which is deliberate -- a `parameter`'s DEFAULT is
the author's business, and Enhancement-426 settled that the compiler does not
police it. But the ordinary way a model is used is that the deck overrides that
parameter, and on that route the value reached the runtime with nothing between.
So a value the compiler calls an outright error was accepted in silence when it
arrived the way values actually arrive.

Enhancement-504's own comment states the shape. It closed the gap for
`transition`, `$bound_step`, the noise power and `idtmod`. Round 63 found it
still open in five more places, and two further faults in the same family.

SEVEN FILTERS AND EVENTS TOOK A VALUE THE COMPILER REFUSES.

  * `zi_*` sampling period. A negative `T` inverts the bilinear map, which
    reflects every pole across the imaginary axis. The filter ran to 1.2e+240
    over 60 ns with exit code 0 and not one diagnostic -- the worst of the set,
    because the number is absurd but nothing says so.
  * `laplace_*` leading denominator coefficient. Zero divides the state-space
    normalisation. The user got gmin- and source-stepping failures ending in
    "Timestep too small; cause unrecorded" -- a convergence report for a
    structurally invalid filter the compiler can already name exactly.
  * `@(cross)` and `last_crossing` direction. Dispatched by sign, so 7 fired on
    rising edges and -3 on falling ones, and NaN made every comparison false so
    the event went silently dead.
  * The integer `$dist_*` family. Enhancement-505 clamped the real `$rdist_*`
    arms and not their integer siblings, so `$dist_exponential(seed, -1)`
    returned deviates in -10..0: every sample negative, from a distribution
    whose support is [0, inf), while its real sibling clamped to 0.

Where the domain has a natural projection the value is clamped, exactly as
Enhancement-504 did. Where it has none -- a sampling period that must be
positive, a denominator that must have a leading term, a direction that is one
of three values -- there is nothing honest to substitute, so the run time says
what the compiler says and aborts. A bounded-but-wrong substitute would only
trade a visibly absurd number for an invisibly wrong one.

TWO ARGUMENTS OF ONE BUILTIN DISAGREED. `flicker_noise(pwr, exp)` had its power
guarded at both compile and run time and its EXPONENT guarded nowhere, so a NaN
exponent made `pwr/f^exp` NaN at every frequency. A noise contribution cannot
fail to converge the way a value contribution does -- `sqrt(p)` in a `V(o) <+`
aborts the operating point loudly -- so this printed `onoise_total = nan` and
exited 0. Zeroing the power alone does NOT fix it: the runtime still evaluates
`0 / f**NaN`, which is NaN. Both arguments have to be neutralised.

TWO GUARDS RECOGNISED ONE SPELLING OR ONE FORM.

  * `noise_table_log` shared `require_non_negative` with `noise_table`, and log-log
    interpolation cannot represent a ZERO -- exactly the one value that rule
    admits. The whole spectrum came back NaN. 1e-300 works in both columns, which
    is what makes this a guard about zero and not about smallness.
  * The FILE form of `noise_table` was checked for STRUCTURE and never for
    VALUES, so a file holding a frequency of -1 produced output bit-identical to
    the same file holding +1: the sign quietly discarded. That is the defect
    Enhancement-396 fixed for an INLINE table, still live in the form the inline
    check did not cover.

And the diagnostics now name the call the author wrote. One validation arm serves
`rdist_normal | dist_normal`, which is what keeps the two spellings from
drifting; the message had been hardcoded to the `$rdist_*` half, so a
`$dist_normal` call was reported as "$rdist_normal:" and the author greps their
source for a function that is not in it. Enhancement-396 fixed that same defect
for `noise_table_log`; `laplace_state_space` is shared by all eight `laplace_*`
and `zi_*` forms and gets its name threaded in for the same reason.
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
        if junk.startswith("_dd_"):
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
    """Returns (osdi_path_or_None, compiler_output)."""
    osdi = os.path.join(HERE, f"_dd_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src_name), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return (osdi if os.path.exists(osdi) else None), r.stdout + r.stderr


def run(body, ctl, tag, timeout=180):
    p = os.path.join(HERE, f"_dd_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"deckdomain\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "[TIMEOUT]"


def rows(out):
    """Third column of every printed data row (the value)."""
    vals = []
    for line in out.splitlines():
        q = line.split()
        if len(q) >= 3 and re.match(r"^\d+$", q[0]):
            try:
                vals.append(float(q[2]))
            except ValueError:
                pass
    return vals


def scalar(out, name):
    m = re.findall(rf"{re.escape(name)}\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?|nan|inf|-inf)", out, re.I)
    return float(m[-1]) if m else None


print("Enhancement-506: a guard that only ever saw the literal")

NOISE_DECK = ("V1 in 0 dc 0 ac 1\nRs in a 1k\nN1 a 0 mm\n.model mm {model} {card}\n"
              "Rl a 0 1meg\n")
PULSE_DECK = ("V1 a 0 PULSE(0 1 20n 1n 1n 50n 200n)\nN1 a 0 o mm\n"
              ".model mm {model} {card}\nRo o 0 1meg\n")

# ---------------------------------------------------------------------------
# noise_table_log cannot represent a zero -- inline
# ---------------------------------------------------------------------------
print("\n  noise_table_log: zero is as unrepresentable as negative")

for tag, src, col in [("ntlf", "bad_ntlog_freq.va", "frequency"),
                      ("ntlp", "bad_ntlog_pwr.va", "noise power")]:
    osdi, log = build(src, tag)
    check(f"noise_table_log {col} of 0 is refused", osdi is None)
    check(f"  ... named as noise_table_log, not noise_table",
          "noise_table_log:" in log and "greater than zero" in log,
          log.strip().splitlines()[0][:70] if log.strip() else "")

OK_T, _ = build("ok_tables.va", "okt")
check("ok_tables.va compiles", OK_T is not None)
if OK_T:
    for pick, label, want in [(0, "noise_table with a zero frequency still legal", 4.997292826696e-05),
                              (1, "noise_table_log with 1e-300 still legal", 4.997292826696e-05),
                              (2, "noise_table from a clean file still legal", 4.997292826696e-05)]:
        rc, out = run(NOISE_DECK.format(model="ok_tables", card=f"pick={pick}"),
                      f"pre_osdi {os.path.basename(OK_T)}\nnoise v(a) V1 dec 5 1 1e4\n"
                      "print onoise_total", f"okt{pick}")
        got = scalar(out, "onoise_total")
        check(label, got is not None and abs(got - want) / want < 1e-6, f"{got}")

# ---------------------------------------------------------------------------
# the FILE form was checked for structure and never for values
# ---------------------------------------------------------------------------
print("\n  noise_table data files: the value rule, not just the shape")

osdi, log = build("bad_ntfile_freq.va", "ntff")
check("a file holding a frequency of -1 is refused", osdi is None)
check("  ... and the diagnostic names the offending value",
      "frequency of -1" in log, log.strip().splitlines()[0][:70] if log.strip() else "")

osdi, log = build("bad_ntfile_log.va", "ntfl")
check("a file holding a zero frequency is refused for the log form", osdi is None)
check("  ... with the log form's stricter rule",
      "noise_table_log needs every entry > 0" in log or "greater than" in log or "> 0" in log)

# ---------------------------------------------------------------------------
# the diagnostic names the call the author wrote
# ---------------------------------------------------------------------------
print("\n  $dist_* diagnostics name the author's spelling")

for tag, src, want, unwanted in [
        ("dn", "bad_distnormal.va", "$dist_normal:", "$rdist_normal:"),
        ("de", "bad_distexp.va", "$dist_exponential:", "$rdist_exponential:")]:
    osdi, log = build(src, tag)
    check(f"{want[:-1]} is refused", osdi is None)
    check(f"  ... reported as {want[:-1]}, not {unwanted[:-1]}",
          want in log and unwanted not in log,
          log.strip().splitlines()[0][:70] if log.strip() else "")

osdi, log = build("bad_rdistnormal.va", "rdn")
check("the real sibling is still reported as $rdist_normal",
      osdi is None and "$rdist_normal:" in log)

# ---------------------------------------------------------------------------
# the integer $dist_* family takes Enhancement-505's clamps too
# ---------------------------------------------------------------------------
print("\n  integer $dist_* siblings clamp like the real family")

DIST, _ = build("distfam.va", "df")
check("distfam.va compiles", DIST is not None)
if DIST:
    DECK = ("V1 a 0 dc 0.5\nN1 a 0 o mm\n.model mm distfam {card}\nRo o 0 1meg\n")
    CTL = f"pre_osdi {os.path.basename(DIST)}\ntran 1n 200n\nprint v(o)"

    # E-527 (kernel audit): LRM 9.13.2 says a non-positive mean "shall be
    # reported" as an ERROR -- the deck route used to clamp in silence; it
    # aborts with the mandated runtime fatal now.
    rc, out = run(DECK.format(card="pick=0 mean=-1"), CTL, "dfe")
    check("$dist_exponential with a deck mean of -1 reports the LRM 9.13.2 error",
          "9.13.2" in out and "$dist_exponential" in out,
          next((l.strip()[:60] for l in out.splitlines() if "fatal" in l.lower()), ""))

    rc, out = run(DECK.format(card="pick=0 mean=1"), CTL, "dfe2")
    vs = rows(out)
    check("  ... and a legal mean is untouched",
          bool(vs) and min(vs) >= 0.0 and max(vs) > 1.0, f"max={max(vs) if vs else None}")

    rc, out = run(DECK.format(card="pick=1 sdev=-1"), CTL, "dfn")
    vs = rows(out)
    check("$dist_normal with a deck sdev of -1 collapses to the mean",
          bool(vs) and max(abs(v) for v in vs) == 0.0, f"max|v|={max(abs(v) for v in vs) if vs else None}")

    rc, out = run(DECK.format(card="pick=2 hi=0"), CTL, "dfu")
    vs = rows(out)
    check("$dist_uniform with reversed deck bounds collapses to the start",
          bool(vs) and min(vs) == 10.0 and max(vs) == 10.0, f"{min(vs) if vs else None}..{max(vs) if vs else None}")

# ---------------------------------------------------------------------------
# flicker_noise: both arguments, not just the power
# ---------------------------------------------------------------------------
print("\n  flicker_noise exponent")

FLK, _ = build("flknoise.va", "fk")
check("flknoise.va compiles", FLK is not None)
if FLK:
    CTL = (f"pre_osdi {os.path.basename(FLK)}\nnoise v(a) V1 dec 5 1 1e4\nprint onoise_total")
    rc, out = run(NOISE_DECK.format(model="flknoise", card="p=0 q=0"), CTL, "fkn")
    got = scalar(out, "onoise_total")
    check("a NaN exponent leaves the spectrum finite",
          got is not None and got == got and got < 1e-3, f"{got}")
    check("  ... and the source goes inert rather than poisoning it",
          got is not None and abs(got - 2.035584e-07) / 2.035584e-07 < 1e-3, f"{got}")

    rc, out = run(NOISE_DECK.format(model="flknoise", card="p=1 q=1"), CTL, "fkg")
    got = scalar(out, "onoise_total")
    check("  ... while a usable exponent is untouched",
          got is not None and got > 1e-6, f"{got}")

# ---------------------------------------------------------------------------
# laplace: the leading denominator coefficient
# ---------------------------------------------------------------------------
print("\n  laplace_* leading denominator coefficient")

LAP, _ = build("lapfilt.va", "lp")
check("lapfilt.va compiles", LAP is not None)
if LAP:
    CTL = f"pre_osdi {os.path.basename(LAP)}\ntran 1n 60n\nprint v(o)"
    rc, out = run(PULSE_DECK.format(model="lapfilt", card="d1=0"), CTL, "lp0")
    check("a deck-set leading coefficient of zero is refused at run time",
          "laplace_nd:" in out and "highest-order coefficient" in out,
          [l for l in out.splitlines() if "OSDI" in l][:1])
    check("  ... and the analysis stops rather than reporting a convergence fault",
          rc == 1)

    rc, out = run(PULSE_DECK.format(model="lapfilt", card="d1=1e-9"), CTL, "lp1")
    vs = rows(out)
    check("  ... while a legal coefficient filters exactly as before",
          bool(vs) and abs(max(vs) - 1.0) < 1e-6, f"max={max(vs) if vs else None}")

# ---------------------------------------------------------------------------
# zi: the sampling period
# ---------------------------------------------------------------------------
print("\n  zi_* sampling period")

ZI, _ = build("zifilt.va", "zi")
check("zifilt.va compiles", ZI is not None)
if ZI:
    CTL = f"pre_osdi {os.path.basename(ZI)}\ntran 1n 60n\nprint v(o)"
    rc, out = run(PULSE_DECK.format(model="zifilt", card="T=-1e-9"), CTL, "zin")
    check("a negative deck sampling period is refused at run time",
          "zi_nd:" in out and "sampling period" in out,
          [l for l in out.splitlines() if "OSDI" in l][:1])
    check("  ... and the offending value is named", "-1e-09" in out or "-1e-9" in out)
    vs = rows(out)
    check("  ... and the filter no longer runs away to 1e+240",
          not vs or max(abs(v) for v in vs) < 1e6,
          f"max|v|={max(abs(v) for v in vs) if vs else 'no rows'}")
    check("  ... with a non-zero exit status", rc == 1)

    rc, out = run(PULSE_DECK.format(model="zifilt", card="T=1e-9"), CTL, "zig")
    vs = rows(out)
    check("  ... while a legal period filters exactly as before",
          bool(vs) and abs(max(vs) - 0.8888) < 1e-3, f"max={max(vs) if vs else None}")

# ---------------------------------------------------------------------------
# @(cross) and last_crossing: the direction
# ---------------------------------------------------------------------------
print("\n  @(cross) / last_crossing direction")

CRO, _ = build("crossdir.va", "cx")
check("crossdir.va compiles", CRO is not None)
if CRO:
    CDECK = ("V1 a 0 PULSE(0 1 10n 1n 1n 20n 50n)\nN1 a 0 o mm\n"
             ".model mm crossdir {card}\nRo o 0 1meg\n")
    CTL = f"pre_osdi {os.path.basename(CRO)}\ntran 0.5n 200n\nprint v(o)"
    rc, out = run(CDECK.format(card="dir=7"), CTL, "cx7")
    check("a deck direction of 7 is refused at run time",
          "@(cross):" in out and "direction must be" in out,
          [l for l in out.splitlines() if "OSDI" in l][:1])
    check("  ... with a non-zero exit status", rc == 1)

    for d, want in [("1", 4), ("-1", 4), ("0", 8)]:
        rc, out = run(CDECK.format(card=f"dir={d}"), CTL, f"cx{d.replace('-','m')}")
        vs = rows(out)
        check(f"  ... while dir={d} still counts {want} crossings",
              bool(vs) and int(vs[-1]) == want, f"{vs[-1] if vs else None}")

LC, _ = build("lcdir.va", "lc")
check("lcdir.va compiles", LC is not None)
if LC:
    LDECK = ("V1 a 0 PULSE(0 1 10n 1n 1n 20n 50n)\nN1 a 0 o mm\n"
             ".model mm lcdir {card}\nRo o 0 1meg\n")
    CTL = f"pre_osdi {os.path.basename(LC)}\ntran 0.5n 120n\nprint v(o)"
    rc, out = run(LDECK.format(card="dir=7"), CTL, "lc7")
    check("last_crossing shares the guard, and names itself",
          "last_crossing:" in out and "direction must be" in out,
          [l for l in out.splitlines() if "OSDI" in l][:1])

    rc, out = run(LDECK.format(card="dir=-1"), CTL, "lcm1")
    vs = rows(out)
    check("  ... while a legal direction is unchanged",
          bool(vs) and abs(vs[-1] - 8.15e-08) < 1e-9, f"{vs[-1] if vs else None}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
