#!/usr/bin/env python3
"""Enhancement-495: seven ways a decision made once was never revisited.

ROUND 55 probed MOSFET model binning, which no earlier round had touched, and
then followed the shape it exposed into the DC sweep.

MODEL BINNING (findings 1-3)

1. THE TOLERANCE WAS ABSOLUTE, AND THE VALUES ARE METRES. `is_equal()` tested
   `fabs(a - b) < 1e-9`, a slop of one NANOMETRE applied whatever the geometry,
   so a device up to 1 nm outside EVERY declared bin was silently placed in one:
   `l=31n` bound to a bin reaching 30n, while `31.1n` was refused. As a fraction
   of the device the slop grows without bound as processes shrink -- 0.03% of a
   3 um width, but 5% of a 20 nm channel. It is now relative.

2. ADJACENT BINS OVERLAPPED, AND `.model` ORDER DECIDED. `in_range()`'s own
   comment states the rule as `min <= value < max`, but the code also accepted
   `is_equal(value, max)`, closing the interval so a device on a shared boundary
   matched both neighbours. Which it got followed the order the cards happened to
   appear in: reversing two `.model` lines moved `l=1.999u` -- unambiguously
   inside the lower bin -- into the upper one and changed i(V1) by 2.95x.
   Selection now asks the strict rule first and the closed one only where the
   strict rule matched nothing, so a device sitting exactly on the top bin's
   `lmax` still binds and nothing that works today can move.

3. AN OSDI MODEL COULD NOT BE BINNED AT ALL. The binnable set was eleven
   hardcoded built-in names, so a Verilog-A model written exactly as a BSIM PDK
   writes one died with "Unable to find definition of model nv" -- for a model
   defined twice. OSDI types are now asked through the predicate Enhancement-323
   provides, and the four bin limits are consumed on the card the way `level` is.

A DEGENERATE DISTRIBUTION SPEC (finding 4)

4. `agauss`/`gauss` refuse a variation or sigma that is zero or negative -- and
   did it in silence. Every draw returns the nominal, so a Monte Carlo run over a
   parameter that never moves reports a YIELD OF 100%: `agauss(1000,100,3)` gives
   0.12 against a tight spec, `agauss(1000,100,0)` gives 1.00, one character
   apart. The behaviour is unchanged, since a deck may legitimately zero a
   variation; it is only made audible.

A `.dc` SWEEP THAT NEVER REVISITS SETUP (findings 5-6)

Enhancement-471's own comment says `.dc` "sets the circuit up once and walks its
points inside the analysis", and that reusing a setup freezes the topology so
"the sweep quietly draws a flat line". It gave the `sweep` command the machinery
to notice and rebuild; `.dc` never got it.

5. A swept `l`/`w` that leaves the bin the device was PARSED into keeps the old
   bin, and every point past the boundary uses the wrong model (2.9x out).
6. A swept parameter that changes an OSDI device's node collapse keeps the matrix
   built for the old topology, and the sweep returns a FLAT LINE.

`alter` and `sweep` both get these right. Rebuilding mid-analysis is far wider
than the evidence, so `.dc` now REFUSES the point it cannot compute and names the
command that can -- a wrong answer being worse than a refusal.

THE ASCII RAWFILE (finding 7)

7. `DEFPREC 15` emitted SIXTEEN significant digits where a double needs
   seventeen, so `write` then `load` changed values in the last ulp while the
   binary format was exact. Over 200000 random doubles `%.15e` fails to
   round-trip 51390 of them and `%.16e` none.
"""
import math
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


def _cleanup():
    for junk in os.listdir(HERE):
        # b3v33check.log is written by the BSIM3 model checker on every run and
        # does not carry the `_` prefix, so it is named here explicitly rather
        # than left behind for a future `git add` to pick up.
        if junk.startswith("_bs_") or junk == "b3v33check.log":
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
    pre = "pre_osdi binstale.osdi\n" if osdi else ""
    deck = (f"binstale {tag}\n{opts}{body}\n.control\n{pre}option noacct\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_bs_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=300,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def binof(out):
    m = re.findall(r"(?m)^\s+model\s+(\S+)", out)
    return m[-1] if m else None


def sweeprows(out):
    return [float(x) for x in
            re.findall(r"(?m)^\s*\d+\s+[\d.eE+-]+\s+(-?[\d.eE+-]+)", out)]


r = subprocess.run([OPENVAF, "binstale.va", "-o", "binstale.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-495: seven ways a decision made once was never revisited\n")
check("[E-495] the Verilog-A models compile",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "binstale.osdi")),
      (r.stdout + r.stderr).strip()[:60])

NM = "level=8 version=3.3.0"
A = f".model nch.1 nmos {NM} lmin=1u lmax=2u wmin=1u wmax=3u vth0=0.11 u0=600\n"
B = f".model nch.2 nmos {NM} lmin=2u lmax=3u wmin=1u wmax=3u vth0=0.22 u0=300\n"
NANO = (f".model nch.1 nmos {NM} lmin=10n lmax=20n wmin=1u wmax=3u\n"
        f".model nch.2 nmos {NM} lmin=20n lmax=30n wmin=1u wmax=3u\n")


def mos(L, W="2u", models=None):
    return (f"V1 d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nch l={L} w={W} pd=4u ps=4u\n"
            + (models if models is not None else A + B))


# =============================================== 1. the tolerance is relative ==
print("\na bin limit means the number it states, not 'within a nanometre'")
for L, want in (("15n", "nch.1"), ("25n", "nch.2"), ("20n", "nch.2"),
                ("10n", "nch.1"), ("30n", "nch.2")):
    rc, out = run(mos(L, models=NANO), "op\nshowmod m1", "tol" + re.sub(r"\W", "", L))
    check(f"[E-495] l={L} binds to {want}", binof(out) == want, f"{binof(out)}")

for L in ("30.5n", "31n", "9.5n", "35n"):
    rc, out = run(mos(L, models=NANO), "op\nshowmod m1", "out" + re.sub(r"\W", "", L))
    check(f"[E-495] l={L} is outside every bin and is refused",
          rc == 1 and binof(out) is None, f"rc={rc} bin={binof(out)}")

# ============================================== 2. order-independent selection ==
print("\nselection must not depend on the order the .model cards were written")
for L in ("1u", "1.5u", "1.999u", "2u", "2.5u", "3u"):
    got = []
    for k, M in enumerate((A + B, B + A)):
        rc, out = run(mos(L, models=M), "op\nshowmod m1",
                      f"ord{re.sub(r'W', '', re.sub(r'[^0-9a-z]', '', L))}{k}")
        got.append(binof(out))
    check(f"[E-495] l={L}: same bin either way", got[0] == got[1] and got[0], f"{got}")

for L, want in (("1.999u", "nch.1"), ("2u", "nch.2"), ("1.5u", "nch.1"),
                ("2.5u", "nch.2"), ("1u", "nch.1"), ("3u", "nch.2")):
    rc, out = run(mos(L), "op\nshowmod m1", "hs" + re.sub(r"\W", "", L))
    check(f"[E-495] l={L} takes the half-open rule's bin ({want})",
          binof(out) == want, f"{binof(out)}")

rc, o1 = run(mos("1.5u"), "op\nprint i(V1)", "cur1")
rc, o2 = run(mos("2.5u"), "op\nprint i(V1)", "cur2")
check("[E-495] the two bins really are different devices",
      val(o1, "i(V1)") and val(o2, "i(V1)")
      and abs(val(o1, "i(V1)") / val(o2, "i(V1)")) > 2.0,
      f"{val(o1, 'i(V1)')} vs {val(o2, 'i(V1)')}")

# =============================================================== 3. OSDI bins ==
print("\nan OSDI model may be binned, written exactly as a PDK writes one")
OA = ".model nv.1 binstale lmin=1u lmax=2u wmin=1u wmax=3u gain=1e-3\n"
OB = ".model nv.2 binstale lmin=2u lmax=3u wmin=1u wmax=3u gain=2e-3\n"


def osdimos(L, models=None):
    return (f"V1 d 0 dc 1\nN1 d 0 0 nv l={L} w=2u\n"
            + (models if models is not None else OA + OB))


for L, want in (("1.5u", 1e-3), ("2.5u", 2e-3), ("1.999u", 1e-3), ("2u", 2e-3)):
    rc, out = run(osdimos(L), "save @n1[gout]\nop\nprint @n1[gout]",
                  "ov" + re.sub(r"\W", "", L), osdi=True)
    g = val(out, "@n1[gout]")
    check(f"[E-495] OSDI l={L} selects the bin with gain={want:g}",
          g is not None and abs(g - want) < 1e-12, f"{g}")

rc, out = run(osdimos("1.5u"), "op\nprint i(V1)", "ovq", osdi=True)
check("[E-495] ...with no complaint about lmin/lmax/wmin/wmax",
      not re.search(r"unknown parameter|Model issue", out, re.I), "")

rc, out = run(osdimos("5u"), "op\nprint i(V1)", "ovout", osdi=True)
check("[E-495] an OSDI device outside every bin is refused", rc == 1, f"rc={rc}")

rc, out = run("V1 d 0 dc 1\nN1 d 0 0 nv l=1.5u w=2u\n.model nv binstale gain=5e-3\n",
              "save @n1[gout]\nop\nprint @n1[gout]", "ovplain", osdi=True)
check("[E-495] an UNbinned OSDI model is untouched",
      val(out, "@n1[gout]") == 5e-3, f"{val(out, '@n1[gout]')}")

# ============================================ 4. degenerate distribution specs ==
print("\na distribution that cannot vary must say so")
FLAT = "every sample equals the nominal"


def mc(expr, tag):
    return run(f".param vo = {expr}\nV1 out 0 dc {{vo}}\nR1 out 0 1k\n",
               "montecarlo 120 -analysis op -spec v(out) -min 995 -max 1005 "
               "-seed 3\nprint montecarlo_yield", tag)


rc, out = mc("agauss(1000,100,3)", "mcok")
y = val(out, "montecarlo_yield")
check("[E-495] a healthy agauss still varies, and says nothing",
      y is not None and 0.0 < y < 0.9 and FLAT not in out, f"yield {y}")

for expr in ("agauss(1000,100,0)", "agauss(1000,0,3)", "agauss(1000,-100,3)",
             "agauss(1000,100,-3)", "gauss(1000,0.1,0)", "gauss(1000,-0.1,3)"):
    rc, out = mc(expr, "mc" + re.sub(r"\W", "", expr)[:12])
    check(f"[E-495] {expr} is reported", FLAT in out,
          f"yield {val(out, 'montecarlo_yield')}")

for expr, lo, hi, want in (("aunif(1000,100)", 899.9, 1100.1, 1.0),
                           ("unif(1000,0.1)", 899.9, 1100.1, 1.0),
                           ("limit(1000,100)", 950, 1050, 0.0)):
    rc, out = run(f".param vo = {expr}\nV1 out 0 dc {{vo}}\nR1 out 0 1k\n",
                  f"montecarlo 120 -analysis op -spec v(out) -min {lo} -max {hi} "
                  "-seed 3\nprint montecarlo_yield", "u" + re.sub(r"\W", "", expr)[:10])
    y = val(out, "montecarlo_yield")
    check(f"[E-495] {expr} is unchanged and silent",
          y is not None and abs(y - want) < 1e-9 and FLAT not in out, f"{y}")

# ================================================= 5-6. the .dc sweep refusals ==
print("\n.dc refuses the point it cannot compute, and names the command that can")
BINMSG = "outside model bin"
COLMSG = "changes this device's node collapse"

rc, out = run(mos("1.5u"), "dc @m1[l] 1.2u 1.8u 0.2u\nprint i(V1)", "in1")
rows = sweeprows(out)
check("[E-495] a sweep that stays inside one bin still runs",
      rc == 0 and len(rows) == 4 and BINMSG not in out, f"rc={rc} n={len(rows)}")

rc, out = run(mos("1.2u"), "dc @m1[l] 1.2u 1.8u 0.2u\nprint i(V1)", "in1b")
oracle = []
for L in ("1.2u", "1.4u", "1.6u", "1.8u"):
    _, o = run(mos(L), "op\nprint i(V1)", "or" + re.sub(r"\W", "", L))
    oracle.append(val(o, "i(V1)"))
check("[E-495] ...and every point matches a deck parsed at that length",
      sweeprows(out) and len(sweeprows(out)) == 4
      and all(abs(a - b) <= 1e-5 * abs(b) for a, b in zip(sweeprows(out), oracle)),
      f"{sweeprows(out)} vs {oracle}")

for lbl, cmd in (("crossing into the next bin", "dc @m1[l] 1.5u 2.5u 0.5u"),
                 ("starting outside its own bin", "dc @m1[l] 2.5u 2.5u 1u"),
                 ("crossing on w", "dc @m1[w] 2u 4u 1u")):
    body = mos("1.5u") if "w]" not in cmd else mos("1.5u", "2u", 
               f".model nch.1 nmos {NM} lmin=1u lmax=9u wmin=1u wmax=3u vth0=0.11 u0=600\n"
               f".model nch.2 nmos {NM} lmin=1u lmax=9u wmin=3u wmax=9u vth0=0.22 u0=300\n")
    rc, out = run(body, cmd + "\nprint i(V1)", "x" + re.sub(r"\W", "", lbl)[:10])
    check(f"[E-495] a sweep {lbl} is refused",
          rc == 1 and BINMSG in out, f"rc={rc}")
    check(f"[E-495] ...and names `sweep` rather than blaming the device",
          "`sweep` command" in out and "the device refused" not in out, "")

COLL = "V1 p 0 dc 1\nN1 p 0 mm rs={rs}\n.model mm collstale g=1e-3\n"
rc, out = run(COLL.format(rs="100"), "dc @n1[rs] 100 1000 300\nprint i(V1)",
              "cok", osdi=True)
rows = sweeprows(out)
want = [-1.0 / (r + 1000.0) for r in (100, 400, 700, 1000)]
check("[E-495] an OSDI sweep that changes no collapse still runs",
      rc == 0 and len(rows) == 4 and COLMSG not in out, f"rc={rc} n={len(rows)}")
# the .dc table prints about six significant digits, so compare at 1e-5 --
# still four orders tighter than the flat line the defect produced
check("[E-495] ...and matches -1/(rs+1000) at every point",
      len(rows) == 4 and all(abs(a - b) <= 1e-5 * abs(b) for a, b in zip(rows, want)),
      f"{rows}")

rc, out = run(COLL.format(rs="0"), "dc @n1[rs] 0 1000 500\nprint i(V1)", "cbad", osdi=True)
check("[E-495] an OSDI sweep that crosses a node collapse is refused",
      rc == 1 and COLMSG in out, f"rc={rc}")
check("[E-495] ...and is not reported as a value the device refused",
      "the device refused" not in out, "")

print("\nthe commands that already did it right are untouched")
rc, out = run(COLL.format(rs="0"),
              "sweep @n1[rs] 0 1000 500 -analysis op -output i(V1)\n"
              "setplot sweep1\nprint all", "swok", osdi=True)
rows = sweeprows(out)
check("[E-495] `sweep` still crosses the collapse correctly",
      len(rows) == 3 and abs(rows[0] + 1e-3) < 1e-12
      and abs(rows[-1] + 5e-4) < 1e-12, f"{rows}")

rc, out = run(COLL.format(rs="0"), "op\nalter @n1[rs]=1000\nop\nprint i(V1)",
              "alok", osdi=True)
vs = re.findall(r"(?mi)^i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out)
check("[E-495] `alter` still crosses the collapse correctly",
      vs and abs(float(vs[-1]) + 5e-4) < 1e-12, f"{vs[-1:]}")

rc, out = run(mos("1.5u"), "op\nalter @m1[l]=2.5u\nop\nshowmod m1", "albin")
check("[E-495] `alter` still re-selects the bin", binof(out) == "nch.2", f"{binof(out)}")

print("\nwhat must not move")
rc, out = run("V1 p 0 dc 1\nN1 p 0 mm rs=100\n.model mm collstale g=1e-3\n",
              "dc @n1[rs] -100 -100 1\nprint i(V1)", "devref", osdi=True)
check("[E-495] a value the DEVICE refuses still says exactly that",
      "the device refused" in out, "")

rc, out = run("V1 a 0 dc 0\nR1 a 0 1k\n", "dc V1 0 2 0.5\nprint i(V1)", "srcsw")
check("[E-495] an ordinary source sweep is unaffected",
      rc == 0 and len(sweeprows(out)) == 5, f"{len(sweeprows(out))}")

rc, out = run("V1 p 0 dc 1\nN1 p 0 mm rs=100 m=1\n.model mm collstale g=1e-3\n",
              "dc @n1[m] 1 4 1\nprint i(V1)", "msw", osdi=True)
rows = sweeprows(out)
check("[E-495] sweeping the m multiplier is unaffected",
      rc == 0 and len(rows) == 4
      and abs(rows[3] / rows[0] - 4.0) < 1e-5, f"{rows}")

S1 = f".model nch nmos {NM} vth0=0.11 u0=600\n"
rc, out = run(f"V1 d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nch l=2u w=1u\n{S1}",
              "dc @m1[w] 1u 8u 1u\nprint i(V1)", "unbinned")
rows = sweeprows(out)
_, o8 = run(f"V1 d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nch l=2u w=8u\n{S1}",
            "op\nprint i(V1)", "unb8")
check("[E-495] a single UNbinned model sweeps as before, and is exact",
      rc == 0 and len(rows) == 8
      and abs(rows[-1] - val(o8, "i(V1)")) <= 1e-5 * abs(val(o8, "i(V1)")),
      f"{rows[-1]} vs {val(o8, 'i(V1)')}")

# ================================================== 7. the ascii rawfile again ==
print("\nan ascii rawfile must give back the number it was written from")
D7 = "V1 a 0 dc 1 ac 1\nR1 a b 1k\nC1 b 0 1n\n"
for lbl, ana, key, ft in (("op", "op", "v(b)", "ascii"),
                          ("ac", "ac lin 1 1meg 1meg", "mag(v(b))", "ascii"),
                          ("tran", "tran 10u 50u", "v(b)[3]", "ascii"),
                          ("ac binary", "ac lin 1 1meg 1meg", "mag(v(b))", "binary")):
    tag = re.sub(r"\W", "", lbl)
    setft = "set filetype=ascii\n" if ft == "ascii" else ""
    rc, o = run(D7, f"{setft}set numdgt=17\n{ana}\nprint {key}\n"
                    f"write _bs_rt{tag}.raw", "w" + tag)
    a = val(o, key)
    rc, o2 = run(D7, f"set numdgt=17\nload _bs_rt{tag}.raw\nprint {key}", "r" + tag)
    b = val(o2, key)
    check(f"[E-495] {ft} rawfile round-trips {lbl} exactly", a is not None and a == b,
          f"{a!r} -> {b!r}")

rc, o = run(D7, "set filetype=ascii\nset rawfileprec=17\nset numdgt=17\n"
                "ac lin 1 1meg 1meg\nprint mag(v(b))\nwrite _bs_rtp.raw", "wp")
a = val(o, "mag(v(b))")
rc, o2 = run(D7, "set numdgt=17\nload _bs_rtp.raw\nprint mag(v(b))", "rp")
check("[E-495] an explicit rawfileprec is still honoured", a == val(o2, "mag(v(b))"),
      f"{a!r} -> {val(o2, 'mag(v(b))')!r}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
