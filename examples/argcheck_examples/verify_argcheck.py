#!/usr/bin/env python3
"""Enhancement-497: constraints the documentation states and the code did not check.

ROUND 56 mined the manual for stated numeric constraints and asked, of each,
whether anything enforces it. Three of these five came straight out of

    pdftotext ngspice-manual.pdf | grep -E "must be|should be"

1. `disto`'s f2overf1 RATIO WAS UNVALIDATED. The manual: "it should be a real
   number between (and not equal to) 0.0 and 1.0". Values of 0, 1, 1.5, 2 and
   -0.5 were accepted in silence and MOVED THE ANSWER -- on a reactive circuit
   the 2F1-F2 product read 1.695, 1.630, 1.477 and 1.580 against 1.711 for a
   legal 0.5. At ratio 1, F2 == F1, so the plot ngspice still labels "IM: f1-f2"
   holds a product at DC; at a negative ratio the second tone sits at a negative
   frequency. Both NEIGHBOURING CASES IN THE SAME SWITCH (D_START, D_STOP) test
   their value and return E_PARMVAL; this one stored whatever arrived.

2. `setseed` SILENTLY TRUNCATED A FRACTIONAL SEED. `%d` stops at the first
   character it cannot use, so "2.5" scanned as 2 and the run used seed 2. Every
   other bad spelling is named ("Cannot use 0 / -3 / abc as seed!"), and the
   sibling command `repeat` names a fractional count outright ("bad repeat
   argument 3.7").

3. `s_xfer` INDEXED int_ic BY THE WRONG ARRAY'S SIZE. The initialisation loop
   reads PARAM(int_ic[den_size - 2 - i]) -- den_size being PARAM_SIZE(den_coeff)
   -- and nothing consulted PARAM_SIZE(int_ic), though the manual states int_ic
   "must be of size one less as the array of values specified for den_coeff".
   Too short and the initial conditions the array does not reach read as zero,
   which took v(out) at 10 us from 7.00005 to 4.99995e-05; too long and the
   surplus was never looked at.

4. THE OSCILLATOR FAMILY WENT SILENTLY DEAD. `sine`, `square`, `triangle` and
   `oneshot` detected a control/frequency array mismatch, announced it, and
   returned WITHOUT SETTING AN OUTPUT -- on every evaluation. The run ended rc=0
   with the source held at zero, and the same two lines appeared 2025 times over
   a 2 ms transient (it scales: a 1 s run prints about a million). This is
   exactly the shape Enhancement-491 fixed in s_xfer's cfunc.mod and named
   there: two arrays of different length cannot become the same length at a
   later timepoint, so say it once and stop.

5. A DUPLICATE `.param` WAS THE ONLY ONE OF ITS FAMILY TO PASS IN SILENCE:

       .func   f(x)   redefined  ->  "is defined more than once"   (E-491)
       .model  m      redefined  ->  "is already defined; keeping ..."
       .subckt s      redefined  ->  "redefinition of .subckt s, ignored"
       .param  a      redefined  ->  nothing at all

   and it resolves the OTHER WAY from two of them -- `.model` and `.subckt` keep
   the FIRST, `.param` takes the LAST -- so two included files that each set
   `vdd` agree or disagree purely by include ORDER, and a `.param` written in the
   deck is silently displaced by a library included after it. Which value wins is
   NOT changed; it is only made audible, as E-491 did for `.func`.

Also fixed, with no demonstrated consequence: dsetparm.c's D_STOP and
nsetparm.c's N_STOP each reset the START frequency field when it was the STOP
frequency that was refused. Both return E_PARMVAL before either field is read.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ac_"):
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


def run(body, ctl, tag, t=240):
    deck = f"argcheck {tag}\n{body}\n.control\noption noacct\n{ctl}\n.endc\n.end\n"
    p = os.path.join(HERE, f"_ac_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=t,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


print("Enhancement-497: constraints the documentation states and the code did not check\n")

# ============================================ 1. disto's f2overf1 ratio =======
print("disto: f2overf1 must be strictly between 0 and 1")
DIS = ("V1 in 0 dc 0.6 ac 1 distof1 1 distof2 1\nR1 in n 100\nD1 n 0 dm\n"
       "C1 n 0 100n\n.model dm d is=1e-14 n=1\n")
RATIO = "f2overf1 must be greater than 0, and not exactly 1"

# F2 BELOW F1 is the manual's convention; F2 ABOVE F1 is well posed and is what
# Enhancement-255's suite measures (f1 = 1.0 GHz, f2 = 1.3 GHz), proving it
# machine-exact against an independent QPSS harmonic-balance engine. Both run.
for r in ("0.9", "0.5", "0.001", "0.999", "1.3", "2", "1e9"):
    rc, out = run(DIS, f"disto dec 2 10k 40k {r}\nsetplot disto3\n"
                       f"let m=mag(v(n))\nprint m[1]", "ok" + re.sub(r"\W", "", r))
    check(f"[E-497] ratio {r} still runs",
          rc == 0 and val(out, "m[1]") is not None and RATIO not in out,
          f"rc={rc} {val(out, 'm[1]')}")

# only what has no meaning: the second tone at DC, at a negative frequency, or
# exactly on top of the first (F1-F2 would be DC and 2F1-F2 would be F1)
for r in ("1", "0", "-0.5", "-2"):
    rc, out = run(DIS, f"disto dec 2 10k 40k {r}\nprint all", "no" + re.sub(r"\W", "", r))
    check(f"[E-497] ratio {r} has no meaning and is refused, saying why",
          rc == 1 and RATIO in out, f"rc={rc}")

rc, out = run(DIS, "disto dec 2 10k 40k\nsetplot disto1\nlet m=mag(v(n))\nprint m[1]",
              "single")
check("[E-497] single-tone disto (no ratio at all) is untouched",
      rc == 0 and val(out, "m[1]") is not None and RATIO not in out, f"rc={rc}")

for lbl, cmd in (("points 0", "disto dec 0 1k 100k"),
                 ("start 0", "disto dec 5 0 100k"),
                 ("stop < start", "disto dec 5 100k 1k")):
    rc, out = run(DIS, cmd + "\nprint all", "nb" + re.sub(r"\W", "", lbl)[:8])
    check(f"[E-497] the neighbouring argument checks still fire: {lbl}", rc == 1,
          f"rc={rc}")

# ==================================================== 2. setseed =============
print("\nsetseed takes an integer greater than zero")
SD = "V1 a 0 dc 1\nR1 a 0 1k\n"
SEEDMSG = "as seed"


def seed(s, tag):
    rc, out = run(SD, f"setseed {s}\nop\nlet v=vector(4)\nlet g=sgauss(v)\nprint g[0]",
                  tag)
    return val(out, "g[0]"), (SEEDMSG in out)


a, m = seed("2", "s2")
b, _ = seed("3", "s3")
check("[E-497] setseed 2 is accepted and deterministic", a is not None and not m, f"{a}")
check("[E-497] a different seed gives a different stream", a != b, f"{a} vs {b}")
c, m2 = seed("2", "s2b")
check("[E-497] the same seed repeats exactly", a == c, f"{a} vs {c}")

for s in ("2.5", "2.9", "2.1"):
    v, m3 = seed(s, "f" + re.sub(r"\W", "", s))
    check(f"[E-497] setseed {s} is named rather than truncated", m3, "")

for s in ("0", "-3", "abc"):
    v, m4 = seed(s, "b" + re.sub(r"\W", "", s))
    check(f"[E-497] setseed {s} still reports as before", m4, "")

v, m5 = seed("  7  ", "spc")
check("[E-497] surrounding blanks are still fine", v is not None and not m5, f"{v}")

# ============================================== 3. s_xfer's int_ic ===========
print("\ns_xfer: int_ic needs one value per integrator")


def sxfer(ic, tag):
    body = ("V1 in 0 dc 0\nR9 in 0 1meg\nA1 in o xf\n"
            f".model xf s_xfer(num_coeff=[1] den_coeff=[1 2 1] {ic})\nR1 o 0 1k\n")
    return run(body, "tran 1u 50u\nmeas tran vo FIND v(o) AT=10u\nprint vo", tag)


rc, out = sxfer("int_ic=[5 7]", "icok")
check("[E-497] the correct size runs, and keeps its initial conditions",
      rc == 0 and val(out, "vo") is not None and abs(val(out, "vo") - 7.00005) < 1e-3,
      f"{val(out, 'vo')}")

for lbl, ic in (("too short [5]", "int_ic=[5]"),
                ("too long [5 7 9]", "int_ic=[5 7 9]"),
                ("far too long", "int_ic=[5 7 9 11 13]")):
    rc, out = sxfer(ic, "ic" + re.sub(r"\W", "", lbl)[:8])
    check(f"[E-497] {lbl} is refused, naming both sizes",
          rc == 1 and "int_ic has" in out and "den_coeff" in out, f"rc={rc}")

rc, out = sxfer("", "icnone")
check("[E-497] omitting int_ic entirely is still allowed",
      rc == 0 and val(out, "vo") is not None, f"rc={rc}")

rc, out = sxfer("int_ic=[5 7 9] num_coeff=[1 1 1 1]", "icnum")
check("[E-497] E-491's num>den guard still fires first",
      rc == 1, f"rc={rc}")

# ================================= 4. the oscillator family says it once =====
print("\nsine/square/triangle: say it once and stop")
for m in ("sine", "square", "triangle"):
    bad = (f"V1 c 0 dc 1.0\nR9 c 0 1meg\nA1 c o mm\n"
           f".model mm {m}(cntl_array=[0 1 2] freq_array=[1k 2k])\nR1 o 0 1k\n")
    rc, out = run(bad, "tran 2u 2m\nmeas tran a FIND v(o) AT=100u\nprint a", "x" + m[:4])
    n = len([x for x in out.splitlines() if "**** Error ****" in x])
    check(f"[E-497] {m}: a mismatch stops the run instead of a dead source",
          rc == 1, f"rc={rc}")
    check(f"[E-497] {m}: the message appears once, not once per timestep",
          n <= 1, f"{n} blocks over 2 ms (was 2025)")

    good = (f"V1 c 0 dc 1.0\nR9 c 0 1meg\nA1 c o mm\n"
            f".model mm {m}(cntl_array=[0 1 2] freq_array=[1k 2k 3k])\nR1 o 0 1k\n")
    rc, out = run(good, "tran 2u 200u\nmeas tran a FIND v(o) AT=100u\nprint a", "g" + m[:4])
    check(f"[E-497] {m}: a matching pair is untouched",
          rc == 0 and val(out, "a") is not None
          and not any("**** Error ****" in x for x in out.splitlines()),
          f"rc={rc} v={val(out, 'a')}")

# =========================================== 5. duplicate .param =============
print("\na redefined .param is announced, as .func/.model/.subckt already are")
DUP = "is defined more than once"


def dup(body, ctl, tag):
    rc, out = run(body, ctl, tag)
    return rc, out, DUP in out


rc, out, d = dup(".param a=1k\n.param a=4k\nV1 n 0 dc 1\nR1 n 0 {a}\n",
                 "op\nprint i(V1)", "dup1")
i = val(out, "i(V1)")
check("[E-497] a redefined .param is reported", d, "")
check("[E-497] ...and the LAST definition still wins, as before",
      i is not None and abs(-1.0 / i - 4000) < 1, f"{-1.0 / i if i else None}")

rc, out, d = dup(".param a=1k\nV1 n 0 dc 1\nR1 n 0 {a}\n", "op\nprint i(V1)", "dup2")
check("[E-497] a single definition says nothing", not d, "")

rc, out, d = dup(".param a=1k b=2k\nV1 n 0 dc 1\nR1 n 0 {a+b}\n", "op\nprint i(V1)", "dup3")
check("[E-497] two names on one card are not a duplicate", not d, "")

rc, out, d = dup(".param a=1k b=2k\n.param b=5k\nV1 n 0 dc 1\nR1 n 0 {a}\n",
                 "op\nprint i(V1)", "dup4")
check("[E-497] a repeat of the second name on a later card is reported", d, "")

rc, out, d = dup(".param a={2*1k}\n.param a={3*1k}\nV1 n 0 dc 1\nR1 n 0 {a}\n",
                 "op\nprint i(V1)", "dup5")
check("[E-497] expression-valued duplicates are reported too", d, "")

# the scoping that matters: a subcircuit's own parameters are not duplicates
rc, out, d = dup(".subckt s a rv=1k\nR1 a 0 {rv}\n.ends\n"
                 "V1 n 0 dc 1\nX1 n s rv=2k\nX2 n s rv=3k\n", "op\nprint i(V1)", "sub1")
check("[E-497] two instances passing different values are NOT a duplicate", not d, "")

rc, out, d = dup(".subckt s a\n.param loc=1k\nR1 a 0 {loc}\n.ends\n"
                 "V1 n 0 dc 1\nX1 n s\nX2 n s\n", "op\nprint i(V1)", "sub2")
check("[E-497] a subcircuit-internal .param is NOT a duplicate", not d, "")

rc, out, d = dup(".subckt s a\n.param loc=1k\nR1 a 0 {loc}\n.ends\n"
                 ".param loc=9k\nV1 n 0 dc 1\nX1 n s\n", "op\nprint i(V1)", "sub3")
check("[E-497] a top-level name matching a subcircuit's own is NOT a duplicate",
      not d, "")

# the siblings must keep reporting exactly as they did
for lbl, body, ctl, msg in (
        (".func", ".func f(x)={x*1k}\n.func f(x)={x*4k}\nV1 n 0 dc 1\nR1 n 0 {f(1)}\n",
         "op\nprint i(V1)", "more than once"),
        (".model", "V1 n 0 dc 1\nR1 n 0 rm\n.model rm r rsh=1k\n.model rm r rsh=4k\n",
         "op\nprint i(V1)", "already defined"),
        (".subckt", ".subckt s a\nR1 a 0 1k\n.ends\n.subckt s a\nR1 a 0 4k\n.ends\n"
                    "V1 n 0 dc 1\nX1 n s\n", "op\nprint i(V1)", "redefinition")):
    rc, out = run(body, ctl, "sib" + re.sub(r"\W", "", lbl))
    check(f"[E-497] duplicate {lbl} still reports as before", msg in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
