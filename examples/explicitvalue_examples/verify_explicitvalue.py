#!/usr/bin/env python3
"""Enhancement-475: a value the deck states is used, or objected to -- never
silently replaced; and a refusal names the fault it actually found.

Seven defects from bug-hunt round 44, all of one shape. Something written in the
deck was discarded and something else quietly put in its place, or a message
pointed at the wrong line. None of them produced an error, so none of them was
visible while it was happening.

  1  `sin(0 1 0)` -- an EXPLICIT zero frequency -- fell through to 1/TSTOP, so
     the stimulus changed when the run was lengthened. Zero frequency is DC;
     unlike a zero rise time it is a meaningful thing to ask for.
  2  A subcircuit call passing a name the `.subckt` never declared had it
     silently dropped and the default used: `X1 a 0 div rr=5k` on
     `.subckt div p n r=1k` builds a 1k divider.
  3  A `.measure` that FAILED left the previous value under its output name, so
     a loop read the last iteration's answer for a measurement that never
     happened -- and `sim_status` is not set by `meas`, so nothing could tell.
  4  `tran` TMAX had no validation at all; a negative one came back as
     "singular matrix: check node b", blaming the circuit for a bad argument.
  5  `pivtol`, `pivrel`, `minbreak`, `srcsteps`, `gminsteps` and `ramptime`
     accepted nonsense silently while every sibling option refused it.
  6  Every `{{ }}` that could not be evaluated -- 13 different ways -- reported
     "{{...}} outside any .for loop". All of them were inside one.
  7  A nested `.for` reusing the enclosing index died with "device already
     exists", naming the symptom rather than the shadowing that caused it.

THE ORACLE FOR THE FIRST THREE IS THAT THE ANSWER MUST NOT MOVE. A defect that
substitutes a default is only visible if you vary the thing the default is drawn
from, so the checks below sweep TSTOP, compare against the deck the user meant,
and read a variable after a failure -- rather than asserting one number.

WHAT IS DELIBERATELY NOT CHANGED, because each is a recorded decision and the
round re-confirmed it by reading the code rather than the behaviour:
  * negative R/C/L stay unflagged -- Enhancement-438 says so in as many words
    ("negative passives are the very idiom this project's own examples use").
  * `pow(-2,0.5)` keeps returning |base|^exp and `1/0` keeps clamping to 1e32 --
    Enhancements 256/446 chose that over NaN, "because a NaN here poisons the
    Newton Jacobian".
  * `pulse` with `tr=0` still takes the timestep -- documented in a comment
    right above the code.
Checks [20]-[22] pin those three so a later round does not "fix" them.
"""
import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ev_"):
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


def run(body, ctl, tag):
    if not body.endswith("\n"):
        body += "\n"          # else ".control" joins the last element line
    deck = f"explicitvalue\n{body}.control\noption noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n"
    p = os.path.join(HERE, f"_ev_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return r.stdout + r.stderr


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def diagnosed(out):
    """case-INSENSITIVE: ngspice writes both "Warning" and "WARNING - ..."."""
    return [l.strip() for l in out.splitlines()
            if re.search(r"(?i)\b(warning|error)\b", l) and "spinit" not in l]


print("Enhancement-475: an explicit value is honoured or refused, never replaced\n")

# ----------------------------------------------------- 1. sin freq = 0 -------
print("an explicit zero frequency is DC, and does not follow TSTOP")

SIN0 = "V1 a 0 sin(1 1 0)\nR1 a 0 1k\n"
mm = [(val(o, "mx"), val(o, "mn")) for o in
      (run(SIN0, f"tran 20n {t}\nmeas tran mx MAX v(a)\nmeas tran mn MIN v(a)", f"s{t}")
       for t in ("20u", "40u", "80u"))]
check("[0] sin(1 1 0) is a constant, not an oscillation",
      all(m == (1.0, 1.0) for m in mm), f"{mm}")
check("[1] ...and it is the same constant at every TSTOP", len(set(mm)) == 1, f"{mm}")

# the crossing time of an explicitly-specified sine must not move with TSTOP
t50 = [val(run("V1 a 0 sin(0 1 50k)\nR1 a 0 1k",
               f"tran 20n {t}\nmeas tran tm WHEN v(a)=0.5 RISE=1", f"f{t}"), "tm")
       for t in ("20u", "40u")]
check("[2] an explicit 50 kHz is unchanged by this fix",
      t50[0] is not None and t50[0] == t50[1]
      and abs(t50[0] - 1.0 / 6e5) < 1e-9, f"{t50}")

# OMITTING the frequency must still default to 1/TSTOP -- that is documented
tom = [val(run("V1 a 0 sin(0 1)\nR1 a 0 1k",
               f"tran 20n {t}\nmeas tran tm WHEN v(a)=0.5 RISE=1", f"o{t}"), "tm")
       for t in ("20u", "40u")]
check("[3] OMITTING the frequency still defaults to 1/TSTOP",
      tom[0] is not None and tom[1] is not None
      and abs(tom[1] - 2 * tom[0]) < tom[0] * 1e-3, f"{tom}")

# the current source carries the same code and the same fix
im = [(val(o, "mx"), val(o, "mn")) for o in
      (run("I1 0 a sin(1m 1m 0)\nR1 a 0 1k",
           f"tran 20n {t}\nmeas tran mx MAX v(a)\nmeas tran mn MIN v(a)", f"i{t}")
       for t in ("20u", "40u"))]
check("[4] the current source behaves identically",
      len(set(im)) == 1 and im[0] == (1.0, 1.0), f"{im}")

# ------------------------------------------ 2. unknown subckt parameter ------
print("\na parameter name the .subckt never declared is reported")

SUB = ".subckt div p n r=1k\nRa p m {r}\nRb m n {r}\n.ends\n"


def sub_r(call, tag):
    """r as the circuit actually built it: i(v1) = -1/(2r)"""
    o = run(f"V1 a 0 dc 1\n{call}\n" + SUB, "op\nprint i(v1)", tag)
    i = val(o, "i(v1)")
    return (None if not i else round(-1.0 / (2 * i))), o


r_ok, o_ok = sub_r("X1 a 0 div r=5k", "p1")
r_bad, o_bad = sub_r("X1 a 0 div rr=5k", "p2")
check("[5] a declared name still takes effect", r_ok == 5000, f"r={r_ok}")
check("[6] a misspelled name is now reported",
      any('"rr" is not a parameter' in l for l in diagnosed(o_bad)),
      (diagnosed(o_bad) or ["none"])[0][:60])
check("[7] ...and it still falls back to the default, as before",
      r_bad == 1000, f"r={r_bad}")
check("[8] a correct call stays silent", not diagnosed(o_ok), "")
for tag, call in (("p3", "X1 a 0 div"), ("p4", "X1 a 0 div r=5k m=2"),
                  ("p5", "X1 a 0 div PARAMS: r=5k")):
    _, o = sub_r(call, tag)
    check(f"[8-{tag}] `{call}` stays silent", not diagnosed(o), "")

# ------------------------------------------------ 3. failed measurement ------
print("\na failed measurement does not leave the previous answer behind")

o = run("V1 a 0 dc 0 sin(0 1 1k)\nR1 a 0 1k\n",
        "tran 1u 1m\n"
        "meas tran xx FIND v(a) AT=0.25m\n"
        "meas tran xx FIND v(a) AT=5m\n"
        "echo AFTERFAIL\n"
        "print xx\n", "m1")
after = o.split("AFTERFAIL", 1)[1] if "AFTERFAIL" in o else o
check("[9] the first measurement succeeds", "9.99996" in o, "")
check("[10] the second reports failure", "failed!" in o, "")
check("[11] ...and the name no longer holds the old value",
      "not available" in o and not re.search(r"^xx\s*=\s*9\.99", after, re.M),
      "stale value still readable"
      if re.search(r"^xx\s*=\s*9\.99", after, re.M) else "")

# a measurement that never succeeded already behaved this way; the two now agree
o2 = run("V1 a 0 dc 0 sin(0 1 1k)\nR1 a 0 1k\n",
         "tran 1u 1m\nmeas tran yy FIND v(a) AT=5m\nprint yy\n", "m2")
check("[12] a never-set name behaves the same way", "not available" in o2, "")

# ------------------------------------------------------- 4. tran TMAX --------
print("\ntran TMAX is validated, and says so")

o = run("V1 a 0 dc 0 pulse(0 1 0 1n 1n 5u 10u)\nR1 a b 1k\nC1 b 0 1n\n",
        "tran 1u 100u 0 -1u\nprint v(b)", "t1")
check("[13] a negative TMAX names TMAX, not the circuit",
      any("TMAX is invalid" in l for l in diagnosed(o))
      and not any("singular matrix" in l for l in diagnosed(o)),
      (diagnosed(o) or ["none"])[0][:56])
for tag, cmd, want_ok in (("t2", "tran 1u 100u 0 1u", True),
                          ("t3", "tran 1u 100u 0 0", True),
                          ("t4", "tran 1u 100u", True)):
    o = run("V1 a 0 dc 0 pulse(0 1 0 1n 1n 5u 10u)\nR1 a b 1k\nC1 b 0 1n\n",
            f"{cmd}\nprint v(b)", tag)
    check(f"[13-{tag}] `{cmd}` still runs",
          not any("TMAX is invalid" in l for l in diagnosed(o)), "")

# --------------------------------------------------- 5. option guards --------
print("\nthe options that accepted nonsense in silence now refuse it")

NET = "V1 a 0 dc 1\nR1 a b 1k\nR2 b 0 1k\nC1 b 0 1n\n"
BAD = [("pivtol", "-1"), ("pivtol", "0"), ("pivrel", "-1"), ("pivrel", "0"),
       ("pivrel", "2"), ("minbreak", "-1"), ("srcsteps", "-1"),
       ("gminsteps", "-1"), ("ramptime", "-1")]
missed = [f"{o}={v}" for o, v in BAD
          if not diagnosed(run(NET, f"option {o}={v}\nop\nprint v(b)",
                               f"g{o}{v.replace('-','m')}"))]
check("[14] every one of the nine bad settings is diagnosed",
      not missed, f"silent: {missed}")

GOOD = [("pivtol", "1e-3"), ("pivrel", "0.5"), ("minbreak", "0"),
        ("srcsteps", "0"), ("gminsteps", "0"), ("ramptime", "0")]
noisy = [f"{o}={v}" for o, v in GOOD
         if diagnosed(run(NET, f"option {o}={v}\nop\nprint v(b)",
                          f"h{o}{v.replace('.','p')}"))]
check("[15] and every legitimate setting stays silent",
      not noisy, f"noisy: {noisy}")
# zero means "the default"/"off" for these four -- refusing it would be wrong
o = run(NET, "option gminsteps=0\noption srcsteps=0\nop\nprint v(b)", "g0")
check("[16] zero still means 'off' where that is its meaning",
      val(o, "v(b)") == 0.5, f"{val(o,'v(b)')}")

# ------------------------------------------------- 6/7. .for messages --------
print("\na .for refusal names the fault it actually found")


def for_err(body, tag):
    o = run(f"V1 a 0 dc 0\n{body}", "op\nprint v(a)", tag)
    e = [l.strip() for l in o.splitlines()
         if l.startswith("Error") and "incomplete" not in l]
    return e[0] if e else ""


# an expression that can never resolve is named as such, wherever it sits
for n, expr in enumerate(("", "i/0", "i%0", "i+", "(i", "i)", "1 2", "i*",
                          "i&1", "i^2", "1.5")):
    e = for_err(f".for i in range(1,2)\nR{{{{{expr}}}}} a 0 1k\n.endfor\n", f"x{n}")
    check(f"[17-{n}] `{{{{{expr}}}}}` is called a bad expression, not 'outside a loop'",
          "not a whole-number expression" in e, e[:56])

# an unbound NAME is a different fault and gets a different sentence
e = for_err(".for i in range(1,2)\nR{{j}} a 0 1k\n.endfor\n", "x20")
check("[18] an unresolved NAME says it was never resolved",
      "was never resolved" in e and "{{j}}" in e, e[:60])

# and with no .for anywhere, the original message is still the right one
e = for_err("R{{i}} a 0 1k\n", "x21")
check("[19] with no .for in the deck, 'outside any .for loop' still stands",
      "outside any .for loop" in e, e[:60])

# the shadowed index is refused by name
e = for_err(".for i in range(1,2)\n.for i in range(1,2)\nR{{i}}x a 0 1k\n"
            ".endfor\n.endfor\n", "x22")
check("[19b] a nested loop reusing the index names the shadowing",
      "reuses the index" in e and "device already exists" not in e, e[:60])

# a valid loop is untouched
o = run(".for i in range(1,3)\nR{{i}} n{{i-1}} n{{i}} 1k\n.endfor\n"
        "V1 n0 0 dc 1\nRl n3 0 1k\n", "op\nprint i(v1)", "x23")
check("[19c] a valid loop still builds the circuit",
      val(o, "i(v1)") is not None and abs(val(o, "i(v1)") + 1.0 / 4000.0) < 1e-12,
      f"{val(o,'i(v1)')}")

# ------------------------------------------- what must NOT be 'fixed' --------
# Each of these is a recorded decision with a stated reason. They are pinned
# here because all three LOOK like the defects above and are not.
print("\nthe three lookalikes that are deliberate, and stay that way")

o = run("V1 a 0 dc 1\nR1 a 0 -1k\n", "op\nprint i(v1)", "d1")
check("[20] a negative resistance stays legal and unflagged (E-438)",
      val(o, "i(v1)") == 0.001 and not diagnosed(o), f"{val(o,'i(v1)')}")

o = run("V1 a 0 dc 1\nB1 b 0 v=pow(-4,0.5)\nR1 b 0 1k\n", "op\nprint v(b)", "d2")
check("[21] pow(-4,0.5) still returns 2, not NaN (E-256/446)",
      val(o, "v(b)") == 2.0, f"{val(o,'v(b)')}")

tr = [val(run("V1 a 0 pulse(0 1 0 0 1n 5u 10u)\nR1 a 0 1k",
              f"tran {s} 40u\nmeas tran tm WHEN v(a)=0.5 RISE=1", f"d3{s}"), "tm")
      for s in ("10n", "40n")]
check("[22] pulse tr=0 still takes the timestep, as documented",
      tr[0] is not None and tr[1] is not None and tr[1] > tr[0], f"{tr}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
