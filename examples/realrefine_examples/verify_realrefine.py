#!/usr/bin/env python3
"""verify_realrefine.py -- Enhancement-867: iterative refinement of the real
(op, dc, transient) solve, the twin of Enhancement-860's for ac, and
Enhancement-868: the rows it measures.

F1 and F2 of the Sparse and KLU correctness campaign of 2026-10-11.

F1: a follower built from a VCVS of gain A, whose feedback runs through a 0 V
source, lost about A times the rounding of a double under Sparse: 1.8e-5 at
the operating point at a gain of 1e12 (after 126 iterations of gmin stepping),
2.4e-4 through a transient, 25 % at 1e15.
F2: a dc sweep of a resistance kept the pivot order of its first point, and
Sparse's refactor tests only for an exactly zero pivot: an ammeter beside the
swept load read up to 0.5 % wrong.
KLU was exact on both. After each solve from the second Newton iteration on,
the residual now gives the backward error, and where that is above rounding,
A d = r is solved with the same factors and x + d kept while it improves.

  [1] F1, the operating point at gains 1e6, 1e9, 1e12 and 1e15: to 1e-14
  [2] F1, a transient at gains 1e9, 1e12 and 1e15: to 1e-14
  [3] F1 at a gain of 1e12 converges in plain Newton, in at most 5 iterations
  [4] F2, the ammeter swept from 0.1 ohm to 40 Mohm: 0.6217/R to 1e-8
  [5] F2 started at 100 ohm: to 1e-8
  [6] a dc sweep of the gain, @e1[gain] from 1e9 down to 1: to 1e-14
  [7] F3's deck: teraohm dead ends beside a VCVS read v(1) to 1e-12
  [8] (control) the diagonal shunt stays in the solve: two current sources in
      a cutset need gmin stepping, whose last solve carries gshunt=1e-6 on
      both nodes; v(1) is -1e-6 / (g + g/(1 + g R)) to 1e-12
  [9] (control) the follower wired straight back and an inverting amplifier
      at a gain of 1e12: exact, as before

Enhancement-868 (F3): the refinement measured every row against the larger
of its own terms and its unknowns' kind scale, which kept a small current's
KCL row out when a far larger current flowed elsewhere. Now a row counts
unless its terms are at rounding of that scale, and a step is weighed
against x on common denominators.
  [10] F3, seed 187: a 6e-8 A sensor beside a 4e5 A inductor current, to
       1e-10 of the exact value (1.5e-3 under Sparse, 1e-7 under KLU on E-867)
  [11] F3, seed 365: a 1.4e-11 A sensor beside 70 A, to 1e-10

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="realrefine_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, control):
    deck = os.path.join(WORK, name + ".cir")
    with open(deck, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\nset wr_singlescale\n%s\n.endc\n.end\n" % (name, body, control))
    r = subprocess.run([NGSPICE, "-b", deck], cwd=WORK, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def table(path, ncol):
    rows = []
    if os.path.exists(path):
        for line in open(path):
            v = line.split()
            if len(v) >= ncol:
                try:
                    rows.append([float(t) for t in v[:ncol]])
                except ValueError:
                    pass
    return rows


def scalar(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


def follower(A, sensor=True, source="dc 1.234567"):
    if sensor:
        return "vin in 0 %s\ne1 out 0 in neg %r\nvfb out neg 0\nrl out 0 1k" % (source, A)
    return "vin in 0 %s\ne1 out 0 in out %r\nrl out 0 1k" % (source, A)


# [1] and [3]
VIN = 1.234567
errs, iters12 = [], None
for A in (1e6, 1e9, 1e12, 1e15):
    out = run("op%g" % A, follower(A), "op\nprint v(out)\nrusage totiter")
    v = scalar(out, "v(out)")
    ex = VIN * A / (1 + A)
    errs.append((A, abs(v - ex) / ex if v is not None else None))
    if A == 1e12:
        iters12 = scalar(out, "Total iterations")
check("[1] F1, the follower's operating point at gains 1e6 to 1e15, to 1e-14",
      all(e is not None and e < 1e-14 for _, e in errs),
      "; ".join("%g: %s" % (A, "%.1e" % e if e is not None else "no run") for A, e in errs))
check("[3] F1 at a gain of 1e12 converges in plain Newton (<= 5 iterations)",
      iters12 is not None and iters12 <= 5, "%s iterations" % iters12)

# [2]
terrs = []
for A in (1e9, 1e12, 1e15):
    path = os.path.join(WORK, "tr%g.txt" % A)
    if os.path.exists(path):
        os.remove(path)
    run("tr%g" % A, follower(A, source="dc 1.234567 sin(1.234567 0.5 1k)"),
        "tran 10u 1m\nwrdata %s v(in) v(out)" % path)
    rows = table(path, 3)
    w = max((abs(o - i * A / (1 + A)) / abs(i) for _, i, o in rows), default=None)
    terrs.append((A, w, len(rows)))
check("[2] F1, a transient at gains 1e9, 1e12 and 1e15, to 1e-14",
      all(w is not None and n > 50 and w < 1e-14 for _, w, n in terrs),
      "; ".join("%g: %s over %d points" % (A, "%.1e" % w if w is not None else "no run", n) for A, w, n in terrs))

# [4], [5], [8]
AMMETER = """v1 2 0 0.6217
l1 2 3 1u
rsh 3 1 1.4
vam 3 1 0
rl 1 0 1
r8 3 0 24"""


def ammeter(name, sweep, gshunt=0.0):
    path = os.path.join(WORK, name + ".txt")
    if os.path.exists(path):
        os.remove(path)
    body = AMMETER + ("\n.option gshunt=%r" % gshunt if gshunt else "")
    run(name, body, "%s\nwrdata %s i(vam)" % (sweep, path))
    rows = table(path, 2)
    w = max((abs(i - 0.6217 * (1 / R + gshunt)) / (0.6217 * (1 / R + gshunt)) for R, i in rows), default=None)
    return w, len(rows)


w, n = ammeter("sweep01", "dc rl 0.1 5e7 1e7")
check("[4] F2, the ammeter swept from 0.1 ohm to 40 Mohm reads 0.6217/R to 1e-8",
      w is not None and n == 5 and w < 1e-8, "%s over %d points" % ("%.1e" % w if w is not None else "no run", n))
w, n = ammeter("sweep100", "dc rl 100 5e7 1e7")
check("[5] F2 started at 100 ohm: to 1e-8",
      w is not None and n == 5 and w < 1e-8, "%s over %d points" % ("%.1e" % w if w is not None else "no run", n))

# [6]
path = os.path.join(WORK, "gain.txt")
run("gain", follower(1.0), "dc @e1[gain] 1e9 1 -2e8\nwrdata %s v(out)" % path)
rows = table(path, 2)
w = max((abs(v - VIN * A / (1 + A)) / (VIN * A / (1 + A)) for A, v in rows), default=None)
check("[6] a dc sweep of @e1[gain] from 1e9 down to 1: to 1e-14",
      w is not None and len(rows) == 5 and w < 1e-14,
      "%s over %d points" % ("%.1e" % w if w is not None else "no run", len(rows)))

# [7]
TERA = """v1 1 0 1.5623065557674634
l15 1 2 1u
r9 2 6 72.584775376258920T
r14 2 4 24.287618294387902T
r11 3 4 6.53218850813767T
l16 3 5 1u
e19 1 7 7 4 -3370.897504251147"""
out = run("tera", TERA, "op\nprint v(1) v(2) v(3) v(4) v(5) v(6) v(7)")
vals = [scalar(out, "v(%d)" % k) for k in range(1, 8)]
w = max((abs(v - 1.5623065557674634) / 1.5623065557674634 for v in vals), default=None) \
    if all(v is not None for v in vals) else None
check("[7] F3's deck: teraohm dead ends beside a VCVS read v(1) to 1e-12",
      w is not None and w < 1e-12, "%.1e" % w if w is not None else "no run")

# [8]
CUTSET = """i1 0 1 1u
i2 1 0 2u
r1 1 2 1k
c1 2 0 1n
.option gshunt=1e-6"""
out = run("cutset", CUTSET, "op\nprint v(1)")
v = scalar(out, "v(1)")
g, R = 1e-6, 1e3
ex = -1e-6 / (g + g / (1 + g * R))
w = abs(v - ex) / abs(ex) if v is not None else None
check("[8] (control) gmin stepping's last solve keeps gshunt: v(1) = -1e-6 / (g + g/(1 + gR)) to 1e-12",
      w is not None and w < 1e-12, "%s (v(1) = %s)" % ("%.1e" % w if w is not None else "no run", v))

# [9]
out1 = run("direct", follower(1e12, sensor=False), "op\nprint v(out)")
v1 = scalar(out1, "v(out)")
INV = """vin in 0 0.1234567
r1 in neg 1k
r2 neg out 10k
e1 out 0 0 neg 1e12
rl out 0 2k"""
out2 = run("inv", INV, "op\nprint v(out)")
v2 = scalar(out2, "v(out)")
e1 = abs(v1 - VIN * 1e12 / (1 + 1e12)) / VIN if v1 is not None else None
e2 = abs(v2 + 1.234567 * 1e12 / (1e12 + 11)) / 1.234567 if v2 is not None else None
check("[9] (control) the follower wired straight back and an inverting amplifier at 1e12: exact",
      e1 is not None and e2 is not None and e1 < 1e-14 and e2 < 1e-14,
      "%s, %s" % ("%.1e" % e1 if e1 is not None else "no run", "%.1e" % e2 if e2 is not None else "no run"))

# [10], [11]
SEED187 = """r0 1 0 57019618.98386242
r1 2 0 42397944.61363008
r2 3 0 1185.9215958681307
r3 4 0 42059127.20699907
r4 5 0 51128813.449417315
r5 6 0 697823.9731702745
r6 7 0 288391.3119583305
r7 8 0 9300491.413212392
r8 2 7 29.425791697455953
r9 3 4 1174786.1697386906
r10 5 7 -565996.6235436329
r11 5 8 1210.1106383772549
r12 2 7 11077.613244577262
r13 2 5 439723.69128716626
r14 4 1 14015638.662788715
r15 8 7 0.10938035001433531
r16 6 5 1822315.736195656
r17 0 2 39.74957521939269
r18 5 4 273796.1680618052
r19 0 7 3073122.6287010685
r20 6 1 2483810.871308726
r21 3 2 -0.0012556996767788722
r22 0 5 -5133.455796710275
r23 0 6 0.014246036697135521
r24 6 0 386220.73502011097
r25 8 3 15.715699941553577
r26 0 2 -0.7262969178642956
r27 5 0 0.03309971875041973
r28 7 1 41542450.7741002
r29 5 3 1373.171848818692
l30 4 0 1e-06
l31 3 6 1e-06
v32 3 0 dc 1.147477777345856
i33 0 2 dc 7.078565387998658e-06
i34 7 8 dc 0.000318864045430833
vs35 1 6 dc 0
f36 1 2 vs35 0.5995116493229709
h37 8 7 vs35 3.5010869067548067
e38 2 6 3 8 -3817.422434250245
e39 2 7 6 5 456.43823518511186"""
SEED365 = """r0 1 0 293446473.18810284
r1 2 0 21894812.25696983
r2 3 0 10225.175917759236
r3 4 0 2260.023588341368
r4 5 0 51618.572104596846
r5 6 0 51464.58205587395
r6 7 0 70190129200.4543
r7 3 1 0.014126042098234743
r8 4 2 75.17495239494531
r9 3 4 2574949.2507745503
r10 5 0 0.013495007435801978
r11 4 3 413837.44322997204
r12 2 1 0.011429488129989047
r13 6 2 386911.1253369749
v14 3 0 dc 0.9554280147914062
i15 2 6 dc 6.152411360410914e-06
vs16 7 5 dc 0
e17 2 5 3 7 2873.024115233174
f18 3 4 vs16 0.04272931680153288
h19 5 6 vs16 32.874536537289934"""
for tag, net, vec, ex in (("[10] F3, seed 187: a 6e-8 A sensor beside 4e5 A, to 1e-10", SEED187, "vs35#branch",
                           -6.17015011302667408e-08),
                          ("[11] F3, seed 365: a 1.4e-11 A sensor beside 70 A, to 1e-10", SEED365, "vs16#branch",
                           -1.36209807697663075e-11)):
    out = run("f3_%s" % vec[:4], net, "op\nprint %s" % vec)
    v = scalar(out, vec)
    w = abs(v - ex) / abs(ex) if v is not None else None
    check(tag, w is not None and w < 1e-10, "%s (%s = %s)" % ("%.1e" % w if w is not None else "no run", vec, v))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
