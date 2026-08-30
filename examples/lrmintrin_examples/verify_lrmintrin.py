#!/usr/bin/env python3
"""Enhancement-510: an LRM function that crashed the compiler, and four smaller misreports.

Round 66 fuzzed 2089 constant-folded expressions through the compiler. Exactly two
crashed, and they crashed for EVERY argument:

    internal error: entered unreachable code: intrinsic log1p not found

`ln1p` and `expm1` lower to the libm routines of those names -- the LRM lists
them apart from `ln`/`exp` precisely for their precision near zero -- and the
builder asks for them by name. The intrinsic registry never declared either, so
`cx.intrinsic("log1p")` returned None and codegen hit its own `unreachable!`.
Every call whose argument was not constant-folded away crashed the compiler, in
both spellings and in every context tried (plain assignment, noise power,
`initial_step`, an operating-point variable, inside `ddt`).

It survived because the suite that added these functions writes `$ln1p(0.5)` -- a
LITERAL, which folds before codegen, so the intrinsic is never emitted. A
parameter or a probe reaches codegen; a literal does not. Checks [1]-[6] use both.

The static diff is exact: three libm names are requested by the builder, and
`hypot` is declared through a special-case branch while `log1p` and `expm1` were
declared nowhere.

ALSO FIXED HERE

  * A `localparam` chain 32 links long was refused inside a compile-time table as
    "not a compile-time constant", which it plainly is not -- the fold recursion
    bound counts parameter hops and stopped at 32, while the same chain used as an
    ordinary value worked at any depth.

  * `atanh` folded at compile time disagreed with the same call evaluated at run
    time for a NEGATIVE argument near -1: 1.3e-10 relative at -0.9999999, growing
    toward the boundary, with the run-time path exact. atanh is odd and its
    positive side is accurate, so the negative side folds through it now.

  * `pre_osdi -va` printed `system()`'s WAIT STATUS as the compiler's exit code:
    101 came out as 25856. The comment at that site quotes "exit 512" as if it
    were an exit code, which is the same encoding gone unnoticed.

  * Every resistor `.model` card reported
    "Error on .model mm : parameter (r) is not a number this parser accepts".
    The first token of a .model card is the model TYPE, and ngspice's resistor
    model has a parameter named `r`, so the type token matched a real parameter
    and the value check fired on what followed. `first_tok` already existed for
    exactly this collision -- it gates the duplicate-parameter warning -- and the
    value checks simply never consulted it.

NOT FIXED, recorded instead: constant folding loses the SIGN OF ZERO where the
run-time path keeps it (`1.0/ceil(-0.5)` is +inf folded and -inf at run time; the
same for unary minus applied to a zero). The interner is bit-exact and
`eval_unary` folds correctly, so the loss is further down the constant emission
path; rewriting `Fneg` as `0 - x` was tried and reverted because it changed
nothing and only removed an optimisation. Half-fixing it would have been worse
than recording it.
"""

import atexit
import math
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
        if junk.startswith("_li_"):
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
    osdi = os.path.join(HERE, f"_li_{tag}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, src_name), "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return (osdi if os.path.exists(osdi) else None), r.returncode, r.stdout + r.stderr


def run(body, ctl, tag, timeout=120):
    p = os.path.join(HERE, f"_li_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmintrin\n{body}.control\noption noacct\nset numdgt=17\n{ctl}\n.endc\n.end\n")
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


print("Enhancement-510: an LRM function that crashed the compiler")

# ---------------------------------------------------------------------------
# 1. ln1p / expm1 compile at all, in both spellings and both argument kinds
# ---------------------------------------------------------------------------
print("\n  ln1p and expm1 reach codegen without crashing the compiler")

LR, rc, log = build("lrmi.va", "lr")
check("lrmi.va compiles", LR is not None, log.strip()[-200:] if LR is None else "")
check("  ... and the compiler did not crash", rc != 101 and "has crashed" not in log,
      f"rc={rc}")

if LR:
    PRE = f"pre_osdi {os.path.basename(LR)}"
    WANT = {0: math.log1p(1e-10), 1: math.expm1(1e-10),
            2: math.log1p(1e-10), 3: math.expm1(1e-10)}
    NAME = {0: "ln1p(parameter)", 1: "expm1(parameter)",
            2: "$ln1p(parameter)", 3: "$expm1(parameter)"}
    for sel in range(4):
        rcx, out = run(f"V1 p 0 dc 1\nN1 p 0 mm\n.model mm lrmi sel={sel} q=1e-10\n",
                       f"{PRE}\nop\nprint @n1[y]", f"s{sel}")
        got = scalar(out, "@n1[y]")
        want = WANT[sel]
        check(f"{NAME[sel]} = {want:.12e}",
              got is not None and abs(got - want) <= 1e-15 * abs(want), f"{got}")
    # a run-time probe argument -- the form that cannot be folded at all
    for sel, nm in [(4, "ln1p(V(p,n))"), (5, "expm1(V(p,n))")]:
        rcx, out = run(f"V1 p 0 dc 0.25\nN1 p 0 mm\n.model mm lrmi sel={sel}\n",
                       f"{PRE}\nop\nprint @n1[y]", f"s{sel}")
        got = scalar(out, "@n1[y]")
        want = math.log1p(0.25) if sel == 4 else math.expm1(0.25)
        check(f"{nm} with a run-time probe = {want:.12e}",
              got is not None and abs(got - want) <= 1e-14 * abs(want), f"{got}")
    # precision near zero is the whole reason these exist
    rcx, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm lrmi sel=0 q=1e-18\n",
                   f"{PRE}\nop\nprint @n1[y]", "tiny")
    got = scalar(out, "@n1[y]")
    check("ln1p keeps its precision at 1e-18 (ln(1+x) would give 0)",
          got is not None and got != 0.0 and abs(got - 1e-18) <= 1e-15 * 1e-18, f"{got}")

# ---------------------------------------------------------------------------
# 2. a deep localparam chain is still a compile-time constant
# ---------------------------------------------------------------------------
print("\n  a localparam chain past the fold recursion bound is still constant")

DC, rc, log = build("deepchain.va", "dc")
check("a 40-link localparam chain builds a compile-time table", DC is not None,
      [l.strip() for l in log.splitlines() if "error" in l][:1])
if DC:
    rcx, out = run("V1 p 0 dc 0.5\nN1 p 0 mm\n.model mm deepchain\n",
                   f"pre_osdi {os.path.basename(DC)}\nop\nprint @n1[tm]", "dc")
    got = scalar(out, "@n1[tm]")
    check("  ... and interpolates to 50 at x=0.5, not 0", got == 50.0, f"{got}")

# ---------------------------------------------------------------------------
# 3. atanh folded == atanh at run time
# ---------------------------------------------------------------------------
print("\n  a folded atanh agrees with the same call at run time")

ATANH = """`include "disciplines.vams"
module _li_at(p, n);
  inout p, n; electrical p, n;
  parameter real t = -0.9999999;
  (* desc="folded" *) real f;
  (* desc="runtime" *) real r;
  analog begin
    f = atanh(-0.9999999);
    r = atanh(t);
    I(p, n) <+ V(p, n) / 1e3;
  end
endmodule
"""
with open(os.path.join(HERE, "_li_at.va"), "w") as fh:
    fh.write(ATANH)
AT, rc, log = build("_li_at.va", "at")
check("_li_at.va compiles", AT is not None)
if AT:
    rcx, out = run("V1 p 0 dc 1\nN1 p 0 mm\n.model mm _li_at\n",
                   f"pre_osdi {os.path.basename(AT)}\nop\nprint @n1[f] @n1[r]", "at")
    fo, ru = scalar(out, "@n1[f]"), scalar(out, "@n1[r]")
    want = math.atanh(-0.9999999)
    check("folded and run-time atanh(-0.9999999) agree", fo is not None and fo == ru,
          f"folded={fo} runtime={ru}")
    check("  ... and both equal libm", fo is not None and abs(fo - want) <= 1e-15 * abs(want),
          f"{fo} vs {want}")

# ---------------------------------------------------------------------------
# 4. a resistor .model card no longer reports a bogus parameter error
# ---------------------------------------------------------------------------
print("\n  the model TYPE token is not reported as a bad parameter")

for card, inst in [(".model mm r rsh=1", "Rs s a mm 1k"),
                   (".model mm r", "Rs s a mm 1k"),
                   (".model mm res tc1=0.01", "Rs s a mm 1k")]:
    rcx, out = run(f"V1 s 0 dc 1\n{inst}\nRd a 0 1k\n{card}\n", "op\nprint v(a)", f"m{abs(hash(card))%9999}")
    bogus = "is not a number this parser accepts" in out
    check(f"`{card}` is clean", not bogus,
          [l.strip()[:70] for l in out.splitlines() if "not a number" in l][:1])
    check("  ... and the divider still solves to 0.5", scalar(out, "v(a)") == 0.5,
          f"{scalar(out, 'v(a)')}")

# a real bad value on a .model card must STILL be reported (E-507's contract)
rcx, out = run("V1 s 0 dc 1\nRs s a 1k\nN1 a 0 mm\n.model mm lrmi q={1/0}\n",
               f"pre_osdi {os.path.basename(LR)}\nop\nprint v(a)" if LR else "op", "keep")
check("a genuinely unparsable value on a .model card is still refused",
      "is not a number this parser accepts" in out,
      "E-507's check must survive the first_tok guard")

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
