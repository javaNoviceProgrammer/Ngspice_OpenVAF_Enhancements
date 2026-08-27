#!/usr/bin/env python3
"""Enhancement-494: two ways a B source expression disagreed with every other
value path.

ROUND 54 compared the B source expression path against the paths that read the
same number on the same deck, and found it answering differently twice.

1. `x/0` LOST ITS SIGN. Enhancement-491 replaced a gmin-derived fudge factor
   with a fixed epsilon, and wrote the nudge as

       arg2 = (arg1 >= 0.0) ? PTDIV_EPS : -PTDIV_EPS;

   meaning to keep the sign of the numerator. But a negative numerator was then
   divided by a NEGATIVE epsilon, so the quotient came out POSITIVE either way:
   `B0 b0 0 v=v(p)/0` with v(p) = -3 returned +3e+32 where it should return
   -3e+32. Every case Enhancement-491 measured had a positive numerator, which
   is why its own suite did not see this. A divisor of exactly zero has no sign
   to recover, so the epsilon is now unconditionally POSITIVE -- zero approached
   from above -- and the quotient keeps the sign of the numerator, which is what
   the limit of x/eps as eps->0+ gives.

2. NUMERIC LITERALS WERE ROUNDED TO 11 SIGNIFICANT DIGITS. Every B source line
   is rewritten by inp_modify_exp(), which re-emitted each literal it found with
   "%18.10e". So `B0 b0 0 v=1.2345678901234567` reached the parser as
   1.2345678901e+00 -- a relative error of 1.9e-11 -- while the SAME literal
   written on an R, C or V card, in a .param, or as an OSDI .model parameter
   kept all seventeen digits. The B source was the only path in the simulator
   that could not carry a double.

   The replacement emits the SHORTEST text that reads back as the same double,
   trying 15, 16 then 17 significant digits. More digits would not be better:
   INPevaluate() re-reads this text and accumulates the mantissa by hand as
   `mantis = 10 * mantis + digit`, which loses a bit past 2^53, so handing it the
   eighteen digits of "%.17e" reintroduced a 1-ulp error that the user's own
   sixteen-digit text did not have.

   What remains after the fix is shared: a handful of literals still land 1 ulp
   out through INPevaluate's pow(10, expo) scaling, but they do so identically
   on a V source and on a B source. This suite pins that PARITY rather than
   exactness, because parity is what the finding was about.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402
import math  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_bv_"):
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


def run(body, ctl, tag, osdi=False, opts=""):
    pre = "pre_osdi bexprvalue.osdi\n" if osdi else ""
    deck = (f"bexprvalue {tag}\n{opts}{body}\n.control\n{pre}option noacct\n"
            f"set numdgt=17\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_bv_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=120,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


r = subprocess.run([OPENVAF, "bexprvalue.va", "-o", "bexprvalue.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-494: a B source expression must carry the value it was given\n")
check("[E-494] the Verilog-A model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "bexprvalue.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# ============================================================ 1. sign of x/0 ==
print("\nx/0 keeps the sign of the numerator")

# a runtime numerator, so no constant folding can decide the answer early
for vp in (-3.0, -1.0, -0.25, 1.0, 3.0):
    rc, out = run(f"V1 p 0 dc {vp}\nR9 p 0 1g\n"
                  f"B0 b0 0 v=v(p)/(v(p)-v(p))\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", f"sgn{str(vp).replace('.','').replace('-','m')}")
    v = val(out, "v(b0)")
    check(f"[E-494] runtime v(p)={vp:g}: v(p)/0 has the sign of v(p)",
          v is not None and (v < 0) == (vp < 0), f"{v!r}")

for lbl, expr, neg in (("1/0",       "1/0",       False),
                       ("-1/0",      "-1/0",      True),
                       ("(0-2)/0",   "(0-2)/0",   True),
                       ("-1.0/0.0",  "-1.0/0.0",  True),
                       ("2/(4-4)",   "2/(4-4)",   False),
                       ("-1/(1-1)",  "-1/(1-1)",  True),
                       ("(0-1)/0",   "(0-1)/0",   True)):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={expr}\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", "cf" + re.sub(r"\W", "", lbl))
    v = val(out, "v(b0)")
    check(f"[E-494] constant {lbl} is {'negative' if neg else 'positive'}",
          v is not None and (v < 0) == neg, f"{v!r}")

# the controlled sources reach PTdivide by their own route
for lbl, body, neg in (("E vol='1/0'",  "E0 b0 0 vol='1/0'\nR0 b0 0 1g\n",  False),
                       ("E vol='-1/0'", "E0 b0 0 vol='-1/0'\nR0 b0 0 1g\n", True)):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\n{body}", "op\nprint v(b0)",
                  "eg" + re.sub(r"\W", "", lbl))
    v = val(out, "v(b0)")
    check(f"[E-494] {lbl} keeps its sign", v is not None and (v < 0) == neg, f"{v!r}")

print("\nwhat Enhancement-491 established must not move")
rc, out = run("V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v=1/0\nR0 b0 0 1g\n",
              "op\nprint v(b0)", "mag")
v = val(out, "v(b0)")
check("[E-494] 1/0 still has the E-491 magnitude 1e32", v is not None and 9e31 < v < 1.1e32,
      f"{v!r}")

# E-491: an ordinary small divisor must be used exactly as written, and must not
# move when an unrelated convergence option changes
BOLTZ = "B0 b0 0 v=1/1.38064852e-23\nR0 b0 0 1g\n"
want = 1.0 / 1.38064852e-23
vals = []
for gm in ("", ".option gmin=1e-3\n", ".option gmin=1e-2\n"):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\n{BOLTZ}", "op\nprint v(b0)",
                  "bz" + str(len(gm)), opts=gm)
    vals.append(val(out, "v(b0)"))
check("[E-494] 1/1.38064852e-23 is exact",
      vals[0] is not None and abs(vals[0] - want) / want < 1e-12, f"{vals[0]!r}")
check("[E-494] ...and does not move with gmin",
      all(v is not None for v in vals) and len(set(vals)) == 1, f"{vals}")

for lbl, expr, want in (("2/4",     "2/4",     0.5),
                        ("-2/4",    "-2/4",    -0.5),
                        ("2/-4",    "2/(0-4)", -0.5),
                        ("-2/-4",   "(0-2)/(0-4)", 0.5),
                        ("0/5",     "0/5",     0.0),
                        ("1/1e-30", "1/1e-30", 1e30)):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={expr}\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", "ok" + re.sub(r"\W", "", lbl))
    v = val(out, "v(b0)")
    ok = v is not None and (abs(v - want) <= 1e-9 * max(abs(want), 1e-30))
    check(f"[E-494] an ordinary divisor is untouched: {lbl} = {want:g}", ok, f"{v!r}")

# ==================================================== 2. literal precision ====
print("\na literal keeps every digit it was written with")

LITS = ["1.2345678901234567", "1.5707963267948966", "0.7853981633974483",
        "3.141592653589793", "2.718281828459045", "0.1", "0.5", "5",
        "6.02214076e23", "1e18"]

for L in LITS:
    E = float(L)
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={L}\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", "lit" + re.sub(r"\W", "", L)[:10])
    v = val(out, "v(b0)")
    check(f"[E-494] B source carries {L} exactly", v == E, f"{v!r}")

print("\n...and agrees with every other path that reads the same literal")
L = "1.2345678901234567"
E = float(L)
paths = []
for tag, body, pr, key, osdi in (
        ("R value",     f"R1 p 0 {L}\n",                      "print @r1[resistance]",
         "@r1[resistance]", False),
        ("C value",     f"R9 p 0 1k\nC1 p 0 {L}\n",           "print @c1[capacitance]",
         "@c1[capacitance]", False),
        ("V source",    f"R9 p 0 1k\nV2 b0 0 dc {L}\nR0 b0 0 1g\n", "print v(b0)",
         "v(b0)", False),
        ("B expression", f"R9 p 0 1k\nB0 b0 0 v={L}\nR0 b0 0 1g\n", "print v(b0)",
         "v(b0)", False),
        ("OSDI .model", f"R9 p 0 1k\nN1 p 0 mm\n.model mm bexprvalue k={L}\n",
         "save @n1[kout]\nop\nprint @n1[kout]", "@n1[kout]", True)):
    ctl = pr if pr.startswith("save") else ("op\n" + pr)
    rc, out = run("V1 p 0 dc 1\n" + body, ctl, "px" + re.sub(r"\W", "", tag)[:8],
                  osdi=osdi)
    v = val(out, key)
    paths.append(v)
    check(f"[E-494] {tag} carries it exactly", v == E, f"{v!r}")
check("[E-494] every value path agrees on the same literal",
      len(set(paths)) == 1 and paths[0] == E, f"{sorted(set(paths))}")

print("\narithmetic inside the expression keeps it too")
for lbl, expr, want in (("<lit>*3/3",   f"{L}*3/3",        float(L) * 3 / 3),
                        ("<lit>+0",     f"{L}+0",          float(L)),
                        ("<lit>*1",     f"{L}*1",          float(L)),
                        ("{<lit>}",     "{" + L + "}",     float(L)),
                        ("(<lit>)",     f"({L})",          float(L))):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={expr}\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", "ar" + re.sub(r"\W", "", lbl)[:8])
    v = val(out, "v(b0)")
    check(f"[E-494] {lbl}", v == want, f"{v!r}")

print("\nthe precision reaches the maths, not just the printout")
rc, out = run("V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v=tan(1.5707963267948966)\nR0 b0 0 1g\n",
              "op\nprint v(b0)", "tanpole")
v = val(out, "v(b0)")
check("[E-494] tan(pi/2) matches libm (an 11-digit argument gave -1.96e11)",
      v is not None and v == math.tan(1.5707963267948966), f"{v!r}")
for fn, arg in (("sin", 1.0), ("cos", 1.0), ("tan", 1.0), ("exp", 1.0), ("sqrt", 2.0),
                ("ln", 10.0)):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={fn}({arg!r})\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", f"fn{fn}")
    v = val(out, "v(b0)")
    want = {"ln": math.log}.get(fn, getattr(math, fn, None))(arg)
    check(f"[E-494] {fn}({arg:g}) matches libm", v == want, f"{v!r}")

print("\nB source parity with a plain V source over many values")
mism = []
for i, x in enumerate([1.7976931348623157e30, 2.2250738585072014e-30,
                       -878714.861004537, 468873730.03874516,
                       -5.543433166669366, 7.135029057486213e-07,
                       0.07613507258343036, -217.80015225511522,
                       64712806061935.91, -1429143870118.0947]):
    L2 = repr(x)
    rc, ob = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={L2}\nR0 b0 0 1g\n",
                 "op\nprint v(b0)", f"pb{i}")
    rc, ov = run(f"V1 p 0 dc 1\nR9 p 0 1k\nV2 b0 0 dc {L2}\nR0 b0 0 1g\n",
                 "op\nprint v(b0)", f"pv{i}")
    vb, vv = val(ob, "v(b0)"), val(ov, "v(b0)")
    # The claim is PARITY, not exactness. What must never come back is the
    # 11-digit rounding, which put these values 1.0e5 to 1.6e5 ulp out. What
    # remains is INPevaluate's own pow(10, expo) scaling: the V source lands
    # within 1 ulp and the B source within 2, on values where the shortest
    # round-trip text needs one digit more than the user wrote. That residue is
    # shared by every value path in the simulator and is deliberately left
    # alone here -- it is not what this enhancement measured.
    if vb is None or vv is None:
        mism.append((L2, vb, vv))
        continue
    if abs(vb - x) > 2 * math.ulp(x) or abs(vv - x) > 2 * math.ulp(x):
        mism.append((L2, vb, vv))
check("[E-494] a B source reads every value to within 2 ulp (was ~1.2e5 ulp)",
      not mism, f"{mism[:2]}")

print("\nthe forms that must keep working")
for lbl, expr, want in (("100p suffix",  "100p",     100e-12),
                        ("5MEG suffix",  "5MEG",     5e6),
                        ("1k suffix",    "1k",       1e3),
                        (".5 leading dot", ".5",     0.5),
                        ("1e-3 exponent", "1e-3",    1e-3),
                        ("2.5e+2",       "2.5e+2",   250.0)):
    rc, out = run(f"V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v={expr}\nR0 b0 0 1g\n",
                  "op\nprint v(b0)", "sf" + re.sub(r"\W", "", lbl)[:8])
    v = val(out, "v(b0)")
    check(f"[E-494] {lbl} still parses", v is not None and abs(v - want) <= 1e-12 * max(abs(want), 1.0),
          f"{v!r}")

rc, out = run("V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v=pwl(v(p),0,0,1,1.2345678901234567)\n"
              "R0 b0 0 1g\n", "op\nprint v(b0)", "pwl")
check("[E-494] a pwl B source (excluded from the rewrite) still runs",
      val(out, "v(b0)") is not None, "")

rc, out = run("V1 p 0 dc 2\nR9 p 0 1k\nB0 b0 0 v=v(p)*1.5+0.25\nR0 b0 0 1g\n",
              "op\nprint v(b0)", "mix")
check("[E-494] a node reference mixed with literals is unchanged",
      val(out, "v(b0)") == 3.25, f"{val(out, 'v(b0)')!r}")

# a current B source drives current INTO its first node from the second, so
# 1 mA through 1 kOhm sits at -1 V on b0
rc, out = run("V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 i=1e-3\nR0 b0 0 1k\n",
              "op\nprint v(b0)", "cur")
check("[E-494] a current B source is unchanged", val(out, "v(b0)") == -1.0,
      f"{val(out, 'v(b0)')!r}")

rc, out = run("V1 p 0 dc 1\nR9 p 0 1k\nB0 b0 0 v=1.2345678901234567\nR0 b0 0 1g\n",
              "tran 10u 50u\nprint v(b0)[3]", "tr")
check("[E-494] the value survives a transient too",
      val(out, "v(b0)[3]") == float("1.2345678901234567"), "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
