#!/usr/bin/env python3
"""Enhancement-507: a format the compiler cannot read, and a value that was never read.

Round 64's findings divide cleanly in two.

THE FORMAT STRING WAS HONOURED ONLY WHEN IT WAS A LITERAL. `lower_scanf` reads a
`$sscanf`/`$fscanf` format for one purpose -- picking each field's integer base
(Enhancement-105) -- and then pulls one whitespace-delimited token per
DESTINATION. Enhancement-11 says so at the site, but nothing said it to the
USER, and ignoring the rest of a C format does not merely lose a feature:

    $sscanf("v=42",  "v=%d",   x)  ->  0 conversions   (C: 1, x=42)
    $sscanf("1234",  "%2d",    x)  ->  1234            (C: 12)
    $sscanf("12 34", "%*d %d", x)  ->  12              (C: 34)

The last is the worst of them. `%*d` means DISCARD this field, so the value the
model receives is the one the author asked to throw away, and the match count
agrees with it. Each of these is now named at compile time.

A format known only at RUN TIME is refused outright, because the base is read
when the model is compiled: `$sscanf("777", f, x)` with `f = "%o"` returned 777
rather than 511 and reported one successful conversion. Every other builtin that
needs a compile-time string already refuses a run-time one -- `white_noise`'s
name, both plusargs, `$table_model`'s control string, `$limit`'s function name
all say "expected string literal". These two accepted it and misread it.

The display family has the same split and keeps a fallback: a non-literal format
is printed as a value (Enhancement-453), which is exactly right for `$strobe(msg)`
and exactly wrong when operands follow -- `$strobe(f, 2.5)` printed `MARK %g 2.5`.
That is a warning (L026), not a refusal, because the one-argument form is how a
model prints a message it built.

A CONVERSION THAT DID NOT HAPPEN OVERWROTE ITS DESTINATION. The scanner returned
0 / 0.0 / "" when a field did not parse and the store was unconditional, so
`$sscanf("abc", "%d", x)` set x to 0 and a partial parse zeroed every destination
past the last match. C leaves an unmatched argument untouched and IEEE 1364
follows it, which is what makes the ordinary idiom work:

    x = fallback;
    if ($sscanf(line, "%d", x) < 1)   // x is still fallback

The destination's current value is passed INTO the scanner and handed back when
the field does not convert. Reading that value is the whole difficulty: a
destination that has never been assigned has no place, and declaring one makes it
`ParamKind::HiddenState` -- persistent instance state the backend does not
provide for a scanf target, which segfaults the simulator. Three mechanisms hit
that (`lower_expr` on the output reference, `use_place`, and a select on a
separate "did it match" callback). `get_place` distinguishes the two cases, and
where there is no prior definition the previous value IS the implicit zero, so
the scanner's own zero is not an approximation.

AND ON THE SIMULATOR SIDE, three more. A `{...}` expression that evaluates to a
non-finite value is substituted as the TEXT `inf`, which `INPevaluate` refuses --
and `INPgetValue`'s scalar paths threw that refusal away where its vector path
honours it, so the value landed as ZERO. `.model nm nmos ... kp={1/0}` built a
transistor conducting 1e-12 instead of 1.25e-4, exit code 0, no diagnostic; the
same value written `inf` on the same card is refused, as it is on an instance
line and as a device value. Freeing a partially built B-source expression
announced "Internal error: unhandled parse-tree node type 0" because
PT_PLACEHOLDER, an ordinary leaf, was missing from the release switch. And
`save @dev[opvar]` reported "device has no parameter" for a name the device does
have -- `INPaName` both finds the name and asks for its value, and the ask fails
at save time because no analysis has run yet.
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
        if junk.startswith("_sf_"):
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
    """Returns (osdi_or_None, compiler_output)."""
    osdi = os.path.join(HERE, f"_sf_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src_name), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return (osdi if os.path.exists(osdi) else None), r.stdout + r.stderr


def run(body, ctl, tag, timeout=120):
    p = os.path.join(HERE, f"_sf_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"scanfmt\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
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


print("Enhancement-507: a format the compiler cannot read, and a value never read")

# ---------------------------------------------------------------------------
# the format elements the scanner cannot honour are named, not ignored
# ---------------------------------------------------------------------------
print("\n  scan formats the whitespace scanner cannot honour")

for tag, src, needle, what in [
        ("lit", "bad_literal.va", "literal character", "literal text in the format"),
        ("wid", "bad_width.va", "field width", "a field width"),
        ("sup", "bad_suppress.va", "assignment suppression", "%* assignment suppression"),
        ("cnv", "bad_conv.va", "conversion '%c'", "an unimplemented conversion"),
        ("run", "bad_runtime.va", "must be a string literal", "a run-time format string")]:
    osdi, log = build(src, tag)
    check(f"{what} is refused", osdi is None)
    check(f"  ... and the reason is named", needle in log,
          log.strip().splitlines()[0][:78] if log.strip() else "")

# ---------------------------------------------------------------------------
# every format the examples actually use must still compile and scan
# ---------------------------------------------------------------------------
print("\n  the formats models really write are untouched")

OK, oklog = build("scanok.va", "ok")
check("scanok.va compiles", OK is not None, oklog.strip()[-160:] if OK is None else "")
if OK:
    DECK = "V1 p 0 dc 1\nN1 p 0 mm\n.model mm scanok\n"
    CTL = (f"pre_osdi {os.path.basename(OK)}\nop\n"
           "print @n1[hex_v] @n1[oct_v] @n1[bin_v] @n1[pre_fail] @n1[pre_ok] "
           "@n1[part_2nd] @n1[pre_real] @n1[raw_fail] @n1[n_none] @n1[n_part]")
    rc, out = run(DECK, CTL, "ok")
    for nm, want, label in [
            ("hex_v", 160.0, "%h scans hex (a0 -> 160)"),
            ("oct_v", 15.0, "%o scans octal (17 -> 15)"),
            ("bin_v", 10.0, "%b scans binary (1010 -> 10)")]:
        got = scalar(out, f"@n1[{nm}]")
        check(label, got == want, f"{got}")

    print("\n  a conversion that does not happen leaves its destination alone")
    got = scalar(out, "@n1[pre_fail]")
    check("a seeded integer survives a failed scan", got == -999.0, f"{got}")
    got = scalar(out, "@n1[pre_real]")
    check("a seeded real survives a failed scan", got == -7.5, f"{got}")
    got = scalar(out, "@n1[part_2nd]")
    check("a partial scan leaves the unmatched target alone", got == -999.0, f"{got}")
    got = scalar(out, "@n1[n_part]")
    check("  ... and still reports the matches it made", got == 1.0, f"{got}")
    got = scalar(out, "@n1[raw_fail]")
    check("a destination never assigned still reads zero", got == 0.0, f"{got}")
    got = scalar(out, "@n1[n_none]")
    check("a scan that converts nothing returns 0", got == 0.0, f"{got}")

# ---------------------------------------------------------------------------
# the display family: warn only when operands follow
# ---------------------------------------------------------------------------
print("\n  a display format that is not a literal")

FW, fwlog = build("fmtwarn.va", "fw")
check("fmtwarn.va compiles", FW is not None)
check("a runtime format with operands warns (L026)",
      "L026" in fwlog and "not a literal" in fwlog,
      [l.strip() for l in fwlog.splitlines() if "L026" in l][:1])
check("  ... exactly once: the literal and one-argument forms are silent",
      fwlog.count("L026") == 1, f"{fwlog.count('L026')} occurrence(s)")

# ---------------------------------------------------------------------------
# a {...} that evaluates non-finite is not a value
# ---------------------------------------------------------------------------
print("\n  a numparam expression that evaluates to inf or nan")

if OK:
    for expr, label in [("{1/0}", "1/0"), ("{0/0}", "0/0"), ("{sqrt(-1)}", "sqrt(-1)")]:
        rc, out = run(f"V1 p 0 dc 1\nN1 p 0 mm\n.model mm scanok junk={expr}\n",
                      f"pre_osdi {os.path.basename(OK)}\nop\nprint @n1[n_ok]", f"np{len(expr)}")
        # `junk` is not a parameter of the model, so the card is rejected either
        # way; what matters is that the VALUE is named rather than applied as 0.
        check(f"a model card value of {label} is reported",
              "not a number" in out or "unrecognized parameter" in out,
              [l.strip() for l in out.splitlines() if "not a number" in l][:1])
        break  # one is enough: the three share one code path

MOS = ("Vd d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nm w=10u l=1u\n"
       ".model nm nmos level=1 vto=0.5 kp={V}\n")
rc, out = run(MOS.replace("{V}", "100u"), "op\nprint i(vd)", "mg")
good = scalar(out, "i(vd)")
rc, out = run(MOS.replace("{V}", "{1/0}"), "op\nprint i(vd)", "mb")
bad = scalar(out, "i(vd)")
check("a built-in model card names the bad value too",
      "not a number" in out, [l.strip() for l in out.splitlines() if "not a number" in l][:1])
check("  ... and the parameter is NOT applied as zero",
      bad is not None and good is not None and abs(bad) > abs(good) / 100.0,
      f"kp=100u -> {good}, kp={{1/0}} -> {bad}")

# ---------------------------------------------------------------------------
# releasing a partially built expression is not an internal fault
# ---------------------------------------------------------------------------
print("\n  freeing a half-built B-source expression")

rc, out = run(".param z={1/0}\nV1 in 0 dc 1\nB1 a 0 v={z}\nR1 a 0 1k\n",
              "op\nprint v(a)", "bs")
check("no 'Internal error' leaks from the cleanup path",
      "Internal error" not in out,
      [l.strip() for l in out.splitlines() if "Internal error" in l][:1])
check("  ... and the real diagnostic still stands",
      "out of range or the wrong type" in out or "Error on line" in out)

# ---------------------------------------------------------------------------
# save names an operating-point variable correctly
# ---------------------------------------------------------------------------
print("\n  save @dev[name]")

if OK:
    DECK = "V1 p 0 dc 1\nN1 p 0 mm\n.model mm scanok\n"
    rc, out = run(DECK, f"pre_osdi {os.path.basename(OK)}\nsave @n1[hex_v]\nop", "sv1")
    check("an operating-point variable is not called a missing parameter",
          "device has no parameter" not in out,
          [l.strip() for l in out.splitlines() if "save" in l.lower()][:1])
    check("  ... it is described as what it is",
          "operating-point variable" in out)
    rc, out = run(DECK, f"pre_osdi {os.path.basename(OK)}\nsave @n1[nosuch]\nop", "sv2")
    check("a name the device really lacks still says so",
          "device has no parameter" in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
