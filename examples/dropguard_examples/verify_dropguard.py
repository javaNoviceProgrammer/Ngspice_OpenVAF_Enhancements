#!/usr/bin/env python3
"""Enhancement-505: four things the compiler's own machinery discarded.

Round 62's findings share a shape that is not the usual missing-guard one. In
each case the check or the side effect existed and was correct; something else
in the pipeline removed it, or it recognised only one of two spellings.

`$stop` WAS HOISTED OUT OF EVAL. Enhancement-55 marks a return-flag callback
op-dependent when an op-dependent branch controls it, so it stays in the eval
function. A callback under NO condition is in no such block, stayed
op-INdependent (its arguments are constants and nothing else makes it vary), and
was hoisted into the instance-init split -- which runs once at setup. A bare
`$stop;` was therefore inert: `eval_flags` stayed 0 for the whole analysis, while
the same `$stop` under a run-time condition set flag 8 at the first point.
`$finish` only appeared to work because ngspice also tests FATAL|FINISH at setup,
which is exactly where the hoisted call had gone.

Only `SetRetFlag` is moved. `Print` was tried and reverted: its arguments are
real values, and an unconditional print whose operands are computed in the init
split does not dominate its new position once the call moves to eval -- codegen
then reads a `BuilderVal::Undef` and the compiler aborts. `examples/concat_examples`
crashed outright. An unconditional `$strobe` consequently still runs at init
rather than per evaluation, which is recorded as an open finding rather than
half-fixed here.

THE `$rdist_*` DOMAINS WERE UNGUARDED FROM THE DECK. hir_ty refuses an
out-of-domain constant, but only a literal or a localparam; a `parameter`
overridden from the deck reached the RNG untouched. What came back was not merely
odd, it was impossible: `$rdist_normal(seed, 0, -1)` returned exactly the
NEGATION of the `+1` deviate, and `$rdist_exponential(seed, -1)` returned a
NEGATIVE deviate, which that distribution has no values of.

THE LAPLACE ZERO-DENOMINATOR GUARD READ ONE SPELLING. Enhancement-420 refuses a
denominator that is identically zero -- but by matching `Expr::Array`, the
`'{...}` aggregate. `laplace_*` accepts the `{...}` concatenation too and lowers
it identically (Enhancement-399 measured that deliberately), so `{0}` compiled
clean and returned a silent ZERO -- the opposite of the division by zero it is.
One apostrophe apart, the same split Enhancement-457 found in `'{4{0}}` vs
`{4{0}}`.

AN OPVAR'S NAME LOST TO THE SIMULATOR'S. ngspice writes its own instance
parameters -- `m`, `temp`, `dtemp`, `dt` -- into the lookup table first, so a
model that declares an operating-point variable with one of those names computes
it on every evaluation and can never read it back. `@n1[temp]` returned the
ambient temperature, `@n1[m]` the multiplier. The name is legal Verilog-A and
nothing said a word. It is named at load time now rather than refused: the rest
of the model works, and refusing would break a model that runs today over a name
it never reads.

WITHDRAWN from round 62: the "branch contributed as both a potential and a flow"
warning not firing for `V(a,b) <+ 0`. The site says why -- a literal-zero
contribution is a node-collapse request delivered by a `CollapseHint` callback,
not a branch residual, so "discarding one discards nothing". A decision, not a
defect.
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
        if junk.startswith("_dg_"):
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
    osdi = os.path.join(HERE, f"_dg_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src_name), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return osdi if os.path.exists(osdi) else None, r.stdout + r.stderr


def run(body, ctl, tag, timeout=120):
    p = os.path.join(HERE, f"_dg_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"dropguard\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "[TIMEOUT]"


def rows(out):
    return [float(m.group(1)) for m in
            re.finditer(r"^\s*\d+\s+(\S+)\s+\S+\s*$", out, re.M)]


def scalar(out, name):
    m = re.findall(rf"{re.escape(name)}\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?|nan|inf)", out, re.I)
    return float(m[-1]) if m else None


OSDI, clog = build("dropg.va", "m")
if not OSDI:
    print("  FAIL  dropg.va compiles  [%s]" % clog.strip()[-200:])
    sys.exit(1)
SHADOW, shadow_log = build("shadow.va", "s")
if not SHADOW:
    print("  FAIL  shadow.va compiles  [%s]" % shadow_log.strip()[-200:])
    sys.exit(1)

print("Enhancement-505: a check the pipeline discarded is not a check")

# ---------------------------------------------------------------------------
# [1]-[5]  $stop
# ---------------------------------------------------------------------------
print("\n  $stop -- hoisted out of eval when nothing gated it")

TRAN = ("Va a 0 PULSE(0 1 1n 0.1n 0.1n 5n 10n)\nN1 a 0 o mm\n.model mm dropg {card}\n"
        "Ro o 0 1meg\n.tran 0.1n 12n\n")


def stop_run(card, tag):
    rc, out = run(TRAN.format(card=card), f"pre_osdi {OSDI}\nrun\nprint v(o)", tag)
    t = rows(out)
    said = "$stop requested" in out
    return rc, (max(t) if t else None), len(t), said


rc, last, n, said = stop_run("stopmode=0", "s0")
check("[1] with no $stop the analysis runs to the end",
      last is not None and last > 11e-9, f"{n} rows, last t = {last}")

rc, last, n, said = stop_run("stopmode=1", "s1")
check("[2] a BARE `$stop;` halts the analysis", n == 0 or (last or 0) < 1e-12,
      f"{n} rows, last t = {last}")
check("[3] ...and says so", said, "message present" if said else "SILENT")

rc, last, n, said = stop_run("stopmode=2", "s2")
check("[4] `$stop` under a run-time condition still halts at that condition",
      last is not None and 2.9e-9 < last < 3.1e-9, f"last t = {last}")
check("[5] ...and still says so", said)

# ---------------------------------------------------------------------------
# [6]-[13]  $rdist_*
# ---------------------------------------------------------------------------
print("\n  $rdist_* -- a domain the deck could step outside")

OP = "V1 a 0 dc 1\nN1 a 0 o mm\n.model mm dropg {card}\nRo o 0 1meg\n"


def drawn(card, tag):
    rc, out = run(OP.format(card=card), f"pre_osdi {OSDI}\nop\nprint @n1[drawn]", tag)
    return scalar(out, "@n1[drawn]")


# a mean large enough that the draw is reliably non-zero -- a poisson(2) that
# happens to draw 0 would make the "still draws" check pass vacuously
def fatal_out(card, tag):
    rc, out = run(OP.format(card=card), f"pre_osdi {OSDI}\nop\nprint @n1[drawn]", tag)
    return out


for i, (dist, name, good) in enumerate([(0, "normal (sd)", 1.0),
                                        (1, "exponential (mean)", 1.0),
                                        (2, "poisson (mean)", 50.0),
                                        (3, "uniform (hi)", 10.0)]):
    pos = drawn(f"mode=1 dist={dist} p={good}", f"r{i}p")
    check(f"[{6+2*i}] {name}: a valid argument still draws a non-zero value",
          pos is not None and abs(pos) > 1e-12, f"{pos}")
    if dist in (1, 2):
        # E-527 (kernel audit): exponential/poisson are on LRM 9.13.2's
        # mandated-error list ("shall be greater than zero. Otherwise an
        # error shall be reported") -- a deck-supplied violation aborts with
        # the runtime fatal now instead of clamping in silence. Zero is a
        # violation too ("greater than zero").
        oneg = fatal_out(f"mode=1 dist={dist} p=-{good}", f"r{i}n")
        ozero = fatal_out(f"mode=1 dist={dist} p=0", f"r{i}z")
        check(f"[{7+2*i}] {name}: an out-of-domain argument reports the LRM "
              f"9.13.2 error (negative and zero both)",
              "9.13.2" in oneg and "9.13.2" in ozero,
              next((l.strip()[:56] for l in oneg.splitlines() if "fatal" in l.lower()), ""))
        continue
    neg = drawn(f"mode=1 dist={dist} p=-{good}", f"r{i}n")
    zero = drawn(f"mode=1 dist={dist} p=0", f"r{i}z")
    # the clamp must send an out-of-domain argument to the SAME place a zero
    # argument goes -- not to the negation of the valid draw, which is what the
    # unguarded sign produced
    same_as_zero = (neg is not None and zero is not None
                    and abs(neg - zero) < 1e-12)
    negation = (neg is not None and pos is not None and pos != 0.0
                and abs(neg + pos) < 1e-12)
    check(f"[{7+2*i}] {name}: an out-of-domain argument behaves as zero, not as a sign flip",
          same_as_zero and not negation,
          f"neg={neg}  zero={zero}"
          + ("  <<< the exact NEGATION of the valid draw" if negation else ""))

# ---------------------------------------------------------------------------
# [14]-[17]  the laplace zero denominator, both spellings
# ---------------------------------------------------------------------------
print("\n  laplace_nd -- a denominator that is identically zero, written two ways")


def compiles(num, den, tag, builtin="laplace_nd", extra=""):
    src = ('`include "disciplines.vams"\n'
           "module z(a,b,o);\n  inout a,b,o; electrical a,b,o;\n"
           f"  analog begin\n    V(o) <+ {builtin}(V(a,b), {num}, {den}{extra});\n"
           "    I(a,b) <+ V(a,b)/1e3;\n  end\nendmodule\n")
    p = os.path.join(HERE, f"_dg_{tag}.va")
    with open(p, "w") as f:
        f.write(src)
    osdi = os.path.join(HERE, f"_dg_{tag}.osdi")
    r = subprocess.run([OPENVAF, p, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return os.path.exists(osdi), r.stdout + r.stderr


ok_arr, log_arr = compiles("'{1}", "'{0}", "la")
check("[14] `'{0}` (array literal) is refused, as it always was",
      not ok_arr and "identically zero" in log_arr)
ok_cat, log_cat = compiles("{1}", "{0}", "lc")
check("[15] `{0}` (concatenation) is refused too",
      not ok_cat and "identically zero" in log_cat,
      "refused" if not ok_cat else "ACCEPTED -- would return a silent 0")
ok_zi, log_zi = compiles("{1}", "{0}", "lz", "zi_nd", ", 1n, 0")
check("[16] the same holds for `zi_nd`",
      not ok_zi and "identically zero" in log_zi)
ok_int, _ = compiles("{1}", "{0,1}", "li")
check("[17] a genuine integrator `{0,1}` is still accepted", ok_int)

# ---------------------------------------------------------------------------
# [18]-[20]  the shadowed opvar
# ---------------------------------------------------------------------------
print("\n  an opvar whose name the simulator also supplies")

rc, out = run("V1 a 0 dc 1\nN1 a 0 mm\n.model mm shadow\n",
              f"pre_osdi {SHADOW}\nop\nprint @n1[m]\nprint @n1[temp]\nprint @n1[ok]", "sh")
warns = [l for l in out.splitlines() if "same name as the simulator" in l]
check("[18] a shadowed opvar is named at load time", len(warns) >= 2,
      f"{len(warns)} warnings")
check("[19] the warning names the winner and the model",
      any("'m'" in w and "shadow" in w for w in warns),
      (warns[0][:60] if warns else ""))
check("[20] an unshadowed opvar is left alone and still reads back",
      scalar(out, "@n1[ok]") == 9.0 and not any("'ok'" in w for w in warns),
      f"ok = {scalar(out, '@n1[ok]')}")

# The case that must NOT warn, and the reason the check is narrowed to opvars.
CMC, cmc_log = build("cmcstyle.va", "c")
if CMC:
    rc, out = run("V1 a 0 dc 1\nN1 a 0 mm m=3\n.model mm cmcstyle\n",
                  f"pre_osdi {CMC}\nop\nprint i(v1)", "cm")
    cur = scalar(out, "i(v1)")
    warned = "same name as the simulator" in out
    check("[21] a model's own `m`/`dtemp` PARAMETERS are not warned about",
          not warned, "silent" if not warned else "WARNED -- E-394's has_m case")
    check("[22] ...and the multiplier still arrives through the model's own `m`",
          cur is not None and abs(cur - (-3e-3)) < 1e-12, f"i(v1) = {cur}")
else:
    check("[21] cmcstyle.va compiles", False, cmc_log.strip()[-120:])
    check("[22] (skipped)", False)

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
