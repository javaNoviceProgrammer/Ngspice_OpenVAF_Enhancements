#!/usr/bin/env python3
"""Enhancement-468: seven numbers that were wrong, or measurements that were not.

Every check is a differential against an oracle that is either analytic or
already in the tree, and each records what the pre-fix binary produced.

  1  `psd` reported a total power too large by the WINDOW's power gain. A
     constant 1 V signal has total power exactly 1 V^2; it reported 1.4999 under
     the default hanning window, 1.3627 hamming, 1.7267 blackman, 1.2153
     gaussian -- and 1.000000 under `specwindow=none`, which is what pinned the
     cause. `fft_windows` scales every window for unit COHERENT gain (right for
     the amplitude spectra `fft` and `spec` produce); a PSD sums SQUARED bins
     and needs the power gain. Zero padding multiplied the error again by
     N/length, so the same signal reported 1.5 at one stop time and 3.0 at
     another.
  2  numparam's `**` and `^` evaluated pow(fabs(x), y), dropping the sign of a
     negative base: `.param {(-2)**1}` returned +2. Enhancement-446 fixed
     exactly this in the OTHER evaluator, but its suite builds only
     `B1 nb 0 v={expr}` decks, so this path was never reached -- one simulator
     answering -8 for a B-source and +8 for a `.param`.
  3  Over a NESTED `.dc` the scale restarts at every outer step, and avg/integ
     integrated straight across the restarts (0.25 and 0.5, neither the value of
     any curve nor the mean of the points) while rms on the SAME plot failed and
     max/min were right -- three answers from one code path.
  4  E-467's scale fallback let `meas dc` measure a TRAN or AC plot instead of
     refusing it, returning exactly what `meas tran` returns.
  5  `sens` reported `nan` for a diode's `ikf` on every model that leaves it at
     its default -- the only non-finite number produced across eight analyses.
  6  A built-in `.model` card or instance line that set one parameter twice took
     the last value in silence, while duplicate model CARDS and duplicate
     `.subckt` definitions are both reported.
  7  The XSPICE `limit` model accepted a negative `limit_range`, which widens the
     linear region past the limits, so the block silently stopped limiting.
"""
import math
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
        if junk.startswith("_mg_"):
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


def run(deck, tag):
    p = os.path.join(HERE, f"_mg_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=240, errors="replace")
    return r.stdout + r.stderr


def num(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+e?[-+]?\d*)", out, re.I)
    return float(m[-1]) if m else None


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


print("Enhancement-468: numbers that were wrong\n")

# ------------------------------------------------------------------ 1. psd ---
print("psd: total power is the signal's mean square, whatever the window")

PSD = ("psd power\nV1 in 0 dc {}\nR1 in 0 1k\n"
       ".control\noption noacct\n{}\ntran 1u {}\nlinearize v(in)\npsd 1 v(in)\n"
       ".endc\n.end\n")


def total(dc, win, span, tag):
    o = run(PSD.format(dc, ("set specwindow=" + win) if win else "* default", span), tag)
    m = re.search(r"Total noise power[^:]*:\s*([\d.eE+-]+)", o)
    return float(m.group(1)) if m else None


ref = None
for win in ("none", "hanning", "hamming", "blackman", "gaussian", ""):
    for span, pad in (("16.383m", "no padding"), ("16.384m", "zero padded")):
        t = total(1, win, span, "psd" + (win or "def") + span.replace(".", ""))
        check(f"[1] a constant 1 V reads 1 V^2 -- {win or 'default'}, {pad}",
              close(t, 1.0, 2e-4), f"{t}")

for amp, want in ((1, 0.5), (2, 2.0), (3, 4.5)):
    o = run("psd sine\nV1 in 0 dc 0 sin(0 %d 1000 0 0)\nR1 in 0 1k\n"
            ".control\noption noacct\ntran 1u 16.383m\nlinearize v(in)\npsd 1 v(in)\n"
            ".endc\n.end\n" % amp, f"psdsin{amp}")
    m = re.search(r"Total noise power[^:]*:\s*([\d.eE+-]+)", o)
    g = float(m.group(1)) if m else None
    check(f"[1] a {amp} V sine reads A^2/2 = {want}", close(g, want, 1e-3), f"{g}")

# -------------------------------------------------------------- 2. numparam ---
print("\nnumparam: `**` and `^` keep the sign of a negative base")

PAR = ("numparam power\n.param q={{{}}}\nV1 pp 0 dc 0\nRp pp 0 {{1k*q}}\n"
       ".control\noption noacct\nset numdgt=12\nop\nprint @rp[resistance]\n.endc\n.end\n")
BSRC = ("bsource power\nB1 nb 0 v={}\nR1 nb 0 1e12\n"
        ".control\noption noacct\nset numdgt=12\nop\nprint v(nb)\n.endc\n.end\n")

for expr, want in (("(-2)**1", -2.0), ("(-2)**3", -8.0), ("(-2)**5", -32.0),
                   ("(-3)**3", -27.0), ("(-2)^3", -8.0), ("pow(-2,3)", -8.0),
                   ("(-2)**2", 4.0), ("(-2)**4", 16.0)):
    o = run(PAR.format(expr), "np" + re.sub(r"\W", "", expr))
    g = num(o, "@rp[resistance]")
    g = g / 1000.0 if g is not None else None
    check(f"[2] .param {{{expr}}} = {want:g}", close(g, want, 1e-9), f"{g}")

for expr, want in (("2**3", 8.0), ("2**0.5", math.sqrt(2)), ("2**-1", 0.5),
                   ("9**0.5", 3.0)):
    o = run(PAR.format(expr), "npp" + re.sub(r"\W", "", expr))
    g = num(o, "@rp[resistance]")
    g = g / 1000.0 if g is not None else None
    check(f"[2] a positive base is untouched: {expr} = {want:g} (control)",
          close(g, want, 1e-9), f"{g}")

# the two evaluators must now agree -- the whole point of the fix
for expr in ("(-2)**3", "(-2)**1", "(-3)**3", "(-2)**2", "2**10"):
    a = num(run(PAR.format(expr), "cmpa" + re.sub(r"\W", "", expr)), "@rp[resistance]")
    a = a / 1000.0 if a is not None else None
    b = num(run(BSRC.format(expr), "cmpb" + re.sub(r"\W", "", expr)), "v(nb)")
    check(f"[2] `.param` and a B-source agree on {expr}", close(a, b, 1e-9), f"{a} vs {b}")

# ------------------------------------------------------------ 3-4. measure ---
print("\nmeasure: the right domain, or a reason")

NEST = ("nested dc\nV1 in 0 dc 1\nR1 in out 1k\nRl out 0 1k\n"
        ".control\noption noacct\nset numdgt=8\n"
        "dc V1 0 2 1 @r1[resistance] 1k 3k 1k\n{}\n.endc\n.end\n")
o = run(NEST.format("meas dc a1 AVG v(out)\nmeas dc i1 INTEG v(out)\n"
                    "meas dc r1m RMS v(out)"), "nest")
check("[3] avg/integ/rms all refuse a NESTED dc sweep (avg gave 0.25, integ 0.5)",
      o.count("NESTED dc sweep") >= 3, f"{o.count('NESTED dc sweep')} refusals")
o = run(NEST.format("meas dc m1 MAX v(out)\nmeas dc m2 MIN v(out)"), "nestmm")
check("[3] ...while max/min still work, being well defined over the whole set",
      close(num(o, "m1"), 1.0, 1e-4) and close(num(o, "m2"), 0.0, 1e-4),
      f"{num(o, 'm1')}/{num(o, 'm2')}")

SINGLE = ("single sweep\nV1 in 0 dc 1\nR1 in out 1k\nRl out 0 1k\n"
          ".control\noption noacct\nset numdgt=8\ndc V1 0 2 1\n"
          "meas dc a1 AVG v(out)\nmeas dc i1 INTEG v(out)\nmeas dc r1m RMS v(out)\n"
          ".endc\n.end\n")
o = run(SINGLE, "single")
check("[3] a SINGLE sweep is untouched: avg 0.5, integ 1.0, rms sqrt(1/3)",
      close(num(o, "a1"), 0.5, 1e-4) and close(num(o, "i1"), 1.0, 1e-4)
      and close(num(o, "r1m"), math.sqrt(1.0 / 3.0), 1e-4),
      f"{num(o, 'a1')}/{num(o, 'i1')}/{num(o, 'r1m')}")

CROSS = ("cross analysis\nV1 in 0 pulse(0 1 0 1n 1n 50m 100m)\nR1 in out 1k\n"
         "C1 out 0 1u\n.control\noption noacct\nset numdgt=8\ntran 10u 2m\n"
         "meas tran t1 MAX v(out)\nmeas dc d1 MAX v(out)\n.endc\n.end\n")
o = run(CROSS, "cross")
check("[4] `meas dc` refuses a TRAN plot again (E-467 let it measure one)",
      num(o, "d1") is None and "failed" in o, "")
check("[4] ...and `meas tran` on the same plot still works (control)",
      num(o, "t1") is not None, f"{num(o, 't1')}")
o = run("param dc scale\nV1 in 0 dc 1\nR1 in out 1k\nRl out 0 1k\n"
        ".control\noption noacct\nset numdgt=8\ndc @r1[resistance] 1k 5k 1k\n"
        "meas dc p1 MAX v(out)\nmeas dc p2 AVG v(out)\n.endc\n.end\n", "paramdc")
check("[4] a device-parameter `.dc` still measures (E-467's own fix, kept)",
      close(num(o, "p1"), 0.5, 1e-4) and num(o, "p2") is not None,
      f"{num(o, 'p1')}/{num(o, 'p2')}")

# ---------------------------------------------------------------- 5. sens ---
print("\nsens: no NaN in the table")

SENS = ("diode sens\nV1 in 0 dc 0.7\nR1 in mid 100\nD1 mid 0 dm\n"
        ".model dm d is=1e-14 n=1{}\n"
        ".control\noption noacct\nset numdgt=8\nsens v(mid)\nprint all\n.endc\n.end\n")
o = run(SENS.format(""), "sensnan")
check("[5] no non-finite sensitivity is reported (d1:ikf was nan)",
      len(re.findall(r"=\s*[-+]?(?:nan|inf)", o, re.I)) == 0, "")
check("[5] ...it reads 0 and says the derivative is undefined there",
      close(num(o, "d1:ikf"), 0.0) and "not a number" in o, f"{num(o, 'd1:ikf')}")
check("[5] the finite entries beside it are unchanged",
      close(num(o, "d1:is"), -1.7951382e12, 1e-3)
      and close(num(o, "d1:n"), 0.445102972, 1e-3),
      f"{num(o, 'd1:is')}/{num(o, 'd1:n')}")
o = run(SENS.format(" ikf=1e-3"), "sensikf")
check("[5] a model that DOES set ikf is untouched (control)",
      len(re.findall(r"=\s*[-+]?(?:nan|inf)", o, re.I)) == 0 and "not a number" not in o,
      "")

RSENS = ("resistor sens\nV1 in 0 dc 1\nR1 in out 1k\nRl out 0 1k\n"
         ".control\noption noacct\nset numdgt=10\nsens v(out)\nprint all\n.endc\n.end\n")
o = run(RSENS, "rsens")
check("[5] an ordinary resistor's own sensitivity is still exact (control)",
      close(num(o, "r1"), -2.5e-4, 1e-4) and close(num(o, "v1"), 0.5, 1e-6),
      f"r1={num(o, 'r1')} v1={num(o, 'v1')}")

# ----------------------------------------------------------- 6. duplicates ---
print("\nduplicate parameters are reported for built-ins too")

o = run("dup model param\nV1 in 0 dc 0.7\nD1 in 0 dm\n.model dm d is=1e-14 is=9e-14\n"
        ".control\noption noacct\nset numdgt=8\nop\nprint i(v1)\n.endc\n.end\n", "dupm")
check("[6] a `.model` card setting one parameter twice is reported",
      "more than once" in o, "")
o = run("dup instance param\nV1 in 0 dc 0.7\nD1 in 0 dm area=1 area=4\n"
        "Rx in 0 1meg\n.model dm d is=1e-14\n"
        ".control\noption noacct\nset numdgt=8\nop\nprint @d1[area]\n.endc\n.end\n", "dupi")
check("[6] ...and so is an instance line", "more than once" in o, "")
o = run("normal deck\nV1 in 0 dc 0.7\nD1 in 0 dm area=2\nR1 in out 1k tc1=0.01\n"
        "Rl out 0 1k\n.model dm d is=1e-14 n=1 rs=0.1\n"
        ".control\noption noacct\nop\nprint v(out)\n.endc\n.end\n", "dupok")
check("[6] an ordinary deck stays silent (control)", "more than once" not in o, "")
o = run("many params\nVd d 0 dc 2\nVg g 0 dc 1\nM1 d g 0 0 nm w=10u l=1u\n"
        ".model nm nmos level=1 vto=0.4 kp=100u gamma=0.5 phi=0.6 lambda=0.01 "
        "rd=1 rs=1 cbd=1p cbs=1p\n"
        ".control\noption noacct\nop\nprint i(vd)\n.endc\n.end\n", "dupmos")
check("[6] a ten-parameter MOSFET model stays silent (control)",
      "more than once" not in o, "")

# ----------------------------------------------------------- 7. ic/nodeset ---
print("\na card with a node but no value says so")

IC = ("ic guard\nV1 in 0 dc 1\nR1 in out 1k\nC1 out 0 1u\n{}\n"
      ".control\noption noacct\nset numdgt=8\ntran 1u 5u uic\nprint v(out)[0]\n"
      ".endc\n.end\n")
for card, tag in ((".ic v(out)", "icnov"), (".nodeset v(out)", "nsnov")):
    o = run(IC.format(card), tag)
    check(f"[7] `{card}` (no value) is reported", "no value given" in o, "")
o = run(IC.format(".ic v(out)=0.9"), "icok")
check("[7] a valued `.ic` still applies (control)",
      close(num(o, "v(out)[0]"), 0.9, 1e-3), f"{num(o, 'v(out)[0]')}")
o = run(IC.format(".nodeset v(out)=0.1"), "nsok")
check("[7] a valued `.nodeset` still applies (control)",
      close(num(o, "v(out)[0]"), 0.1, 1e-3), f"{num(o, 'v(out)[0]')}")
o = run(IC.format(".ic v(nosuchnode)=0.9"), "icbad")
check("[7] a bad node name still reports as before (control)",
      "non-existent node" in o, "")

# --------------------------------------------------------------- 8. limit ---
print("\nthe XSPICE limit block keeps limiting")

LIM = ("xspice limit\nV1 in 0 dc 1.5\nA2 %vd(in 0) out2 lim\n"
       ".model lim limit(gain=1 out_lower_limit=-1 out_upper_limit=1 limit_range={})\n"
       "R2 out2 0 1meg\n"
       ".control\noption noacct\nset numdgt=8\nop\nprint v(out2)\n.endc\n.end\n")
for lr in ("0.01", "0.1", "0", "-0.01", "-5"):
    o = run(LIM.format(lr), "lim" + lr.replace(".", "").replace("-", "n"))
    g = num(o, "v(out2)")
    check(f"[8] limit_range={lr} clamps an input of 1.5 to the declared limit 1.0",
          close(g, 1.0, 1e-6), f"{g}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
