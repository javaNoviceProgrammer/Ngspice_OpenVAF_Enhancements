#!/usr/bin/env python3
"""Enhancement-508: a compile-time table built from a value the compiler cannot fold.

Found by a STATIC AUDIT rather than a hunt. Every site in `hir_lower` that reads a
compile-time constant was enumerated -- 26 of them -- and each falls into one of
three classes:

  * SIGNATURE-PROTECTED (`as_literal(..).unwrap()` where inference already demands
    a string literal). A non-literal is refused before lowering runs.
  * LOWERED AS RUNTIME VALUES (`lower_array_elems_impl`). A `laplace_*`/`zi_*`
    coefficient goes here, which is why a deck-set filter coefficient works.
  * FOLD-TO-DEFAULT. Exactly three sites, and all three were defective.

THE RULE THE AUDIT ESTABLISHES: a site that folds a constant to build a
COMPILE-TIME ARTIFACT must REFUSE a non-foldable operand; a site that lowers to a
RUNTIME value may accept a parameter, which is Enhancement-504/506 territory.

`const_real_in_body`'s own comment states the danger without preventing it: *"the
callers build compile-time tables and turn `None` into `0.0`, so anything this
cannot fold becomes a silent zero entry"*. A `localparam` folds and is fine. An
overridable `parameter` deliberately does NOT fold -- the model card may replace
it -- so it became a zero entry, its default ignored and the deck's value ignored
with it.

  * `noise_table('{1, q, 1e3, 1e-18})` with `q` a parameter gave
    4.870871387826e-05 for BOTH q=1e-18 and q=4e-18 -- exactly the figure for a
    literal zero power.
  * `$table_model(x, '{0,0, 1,q})` with q=100 read 0 at x=0.5 instead of 50, for
    the ordinate or the abscissa: a smooth, plausible, wrong curve. That is the
    shape Enhancement-479's comment described for a localparam; its `parameter`
    half was left.
  * `$discontinuity(d)` used `as_literalsignedint`, a LITERAL only -- it did not
    even fold a localparam the way `const_num` has since Enhancement-479. So -1,
    Enhancement-24's sentinel for NO discontinuity, was misread as an ordinary
    announcement when written as a named constant, bounding the timestep on every
    crossing: 168 output rows against 132.

None of the three said anything at all.

The whole-array form of the same mistake was ALREADY refused, and says exactly why
("materialised at COMPILE time"); the guard simply checked the ARRAY and not its
ELEMENTS. `const_num` and `const_real_in_body` fold the same set, so the check is
exact rather than approximate -- that agreement is what the fix rests on.

Deliberately untouched: the RUNTIME table (a bare array-variable reference,
Enhancement-389) is an `Expr::Path`, not an `Expr::Array`, so the guard never
fires on it -- a table whose entries really are computed at run time still works.
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
        if junk.startswith("_cf_"):
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
    osdi = os.path.join(HERE, f"_cf_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src_name), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return (osdi if os.path.exists(osdi) else None), r.stdout + r.stderr


def run(body, ctl, tag, timeout=120):
    p = os.path.join(HERE, f"_cf_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"constfold\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
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
    return len([l for l in out.splitlines() if re.match(r"^\s*\d+\s", l)])


print("Enhancement-508: a compile-time table built from a value that cannot be folded")

# ---------------------------------------------------------------------------
# a parameter in a compile-time table is refused, and says why
# ---------------------------------------------------------------------------
print("\n  an overridable parameter cannot build a compile-time table")

for tag, src, who in [("ntp", "bad_nt_param.va", "noise_table"),
                      ("ntl", "bad_ntlog_param.va", "noise_table_log"),
                      ("tmo", "bad_tm_ord.va", "$table_model ordinate"),
                      ("tma", "bad_tm_absc.va", "$table_model abscissa")]:
    osdi, log = build(src, tag)
    check(f"{who} with a parameter entry is refused", osdi is None)
    check("  ... and the entry is named, with the reason",
          "not a compile-time constant" in log and "entry" in log,
          [l.strip() for l in log.splitlines() if "error" in l][:1])

# ---------------------------------------------------------------------------
# a $discontinuity degree from the DECK is honoured at run time, not refused
# ---------------------------------------------------------------------------
print("\n  a $discontinuity degree from the deck still means what it says")

DP, dplog = build("disc_param.va", "dsp")
check("disc_param.va compiles (a parameter degree is legal)", DP is not None,
      dplog.strip()[-180:] if DP is None else "")
if DP:
    DECK = ("V1 p 0 PULSE(0 1 10n 1n 1n 20n 50n)\nN1 p 0 mm\n"
            ".model mm disc_param d={D}\n")
    CTL = f"pre_osdi {os.path.basename(DP)}\ntran 1n 100n\nprint v(p)"
    rc, o_none = run(DECK.replace("{D}", "-1"), CTL, "dpm")
    rc, o_ann = run(DECK.replace("{D}", "0"), CTL, "dp0")
    n_none, n_ann = rows(o_none), rows(o_ann)
    # 132 is the un-announced step count for this deck -- the same figure the
    # literal and localparam -1 produce below.
    check("d=-1 from the deck announces nothing", n_none == 132, f"{n_none} rows")
    check("  ... while d=0 from the deck does announce", n_ann > n_none,
          f"d=-1 -> {n_none} rows, d=0 -> {n_ann} rows")

# ---------------------------------------------------------------------------
# a localparam still folds -- these must keep working untouched
# ---------------------------------------------------------------------------
print("\n  a localparam folds, and must keep working")

GOOD, glog = build("goodtab.va", "ok")
check("goodtab.va compiles", GOOD is not None, glog.strip()[-180:] if GOOD is None else "")
if GOOD:
    rc, out = run("V1 p 0 dc 0.5\nN1 p 0 mm\n.model mm goodtab\nRl p 0 1meg\n",
                  f"pre_osdi {os.path.basename(GOOD)}\nop\nprint @n1[tm_lp] @n1[tm_chain]", "ok")
    got = scalar(out, "@n1[tm_lp]")
    check("a localparam ordinate interpolates (0->0, 1->100 at x=0.5)", got == 50.0, f"{got}")
    got = scalar(out, "@n1[tm_chain]")
    check("  ... and so does a localparam CHAIN (100/2 -> 25 at x=0.5)", got == 25.0, f"{got}")

    rc, out = run("V1 in 0 dc 0 ac 1\nRs in p 1k\nN1 p 0 mm\n.model mm goodtab\nRl p 0 1meg\n",
                  f"pre_osdi {os.path.basename(GOOD)}\nnoise v(p) V1 dec 5 1 1e4\n"
                  "print onoise_total", "okn")
    got = scalar(out, "onoise_total")
    check("a localparam noise-table power is honoured, not zeroed",
          got is not None and abs(got - 4.997292826696e-05) / 4.997292826696e-05 < 1e-6,
          f"{got}")

# ---------------------------------------------------------------------------
# $discontinuity: a localparam -1 must behave like the literal -1
# ---------------------------------------------------------------------------
print("\n  $discontinuity(-1) means NO discontinuity, however it is spelled")

DISC, dlog = build("disc.va", "d")
check("disc.va compiles", DISC is not None)
if DISC:
    DECK = ("V1 p 0 PULSE(0 1 10n 1n 1n 20n 50n)\nN1 p 0 o mm\n"
            ".model mm disc sel={S}\nRo o 0 1meg\n")
    CTL = f"pre_osdi {os.path.basename(DISC)}\ntran 1n 100n\nprint v(o)"
    n = {}
    for sel, label in [(0, "literal -1"), (1, "literal 0"),
                       (2, "localparam -1"), (3, "localparam 0")]:
        rc, out = run(DECK.replace("{S}", str(sel)), CTL, f"d{sel}")
        n[sel] = rows(out)
    check("the literal forms differ (-1 announces nothing, 0 does)",
          n[0] != n[1], f"-1 -> {n[0]} rows, 0 -> {n[1]} rows")
    check("a localparam -1 matches the literal -1",
          n[2] == n[0], f"localparam -1 -> {n[2]}, literal -1 -> {n[0]}")
    check("a localparam 0 matches the literal 0",
          n[3] == n[1], f"localparam 0 -> {n[3]}, literal 0 -> {n[1]}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
