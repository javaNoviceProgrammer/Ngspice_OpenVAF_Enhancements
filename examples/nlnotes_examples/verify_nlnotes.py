#!/usr/bin/env python3
"""verify_nlnotes.py -- Enhancements 892 to 894, and the documented notes of the
nonlinear correctness campaign of 2026-10-15 (D1, D2, N1 to N4).

E-892 (D1): a fourier window the run spans exactly is analysed.
  [1] a `.four` over the last 2 of 3 periods, the run started at one period:
      every harmonic within 2e-3 of the exact one, and no "No transient data
      available" (E-889: "(2 * wavelength) longer than time span", then
      "No transient data available for fourier analysis")
  [2] the same through the `fourier` command at polydegree 3
  [3] a window really longer than the data is refused, with the numbers,
      and the `.four` route adds nothing after the reason
E-893 (D2): wrdata writes a vector longer than its scale in full.
  [4] a 1000-point vector in the constants plot writes 1000 rows, its index
      in the scale's column, with a note (E-889: one row, no word)
  [5] after an `op`, with wr_singlescale and wr_vecnames: 1000 rows under an
      "index" header (E-889: refused, "Vectors g and g have different
      lengths")
  [6] (control) a transient's vector writes its own rows and no note
E-894 (N2): an operating point past a megaampere is reported.
  [7] a diode an ideal source forward-biases by 4.2 V: the warning names
      v4#branch and its 1e45 A (E-889: no word)
  [8] (control) the same diode behind 1 kOhm: no warning
Notes, pinned as documented behaviour:
  [9]  N1: a level-1 MOSFET with tox (Meyer) driven around a closed path
       loses more than 10 % of the charge it moves each period, the same at
       T/200 and T/1000; BSIM3 under the same drive conserves to 1e-3
  [10] N3: MOS1's default flicker noise falls as f^-AF (AF the frequency
       exponent at nlev 2); at nlev=0 it falls as 1/f
  [11] N4: with tmax=1m a 10 mV ripple on a capacitor biased at 1 V is taken
       in fewer than a third of the steps of the unbiased one and missed;
       with tmax at its default (tstep) both are resolved

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="nlnotes_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(tag, text):
    path = os.path.join(WORK, tag + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def harmonics(out):
    rows = {}
    for m in re.finditer(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", out, re.M):
        try:
            rows[int(m.group(1))] = (float(m.group(3)), float(m.group(4)))
        except ValueError:
            pass
    return rows


def load(path, skip=0):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for k, line in enumerate(f):
            if k < skip:
                continue
            parts = line.split()
            if parts:
                rows.append([float(x) for x in parts])
    return rows


# ---- E-892 (D1) ------------------------------------------------------------
CARD = """* the campaign's Family F seed 1009: a .four over the last 2 of 3 periods
v1 h1 0 sin(0.28268603496881006 0.9434622896126247 182.5353275152428 0 0 88.74096062157099)
v2 h2 h1 sin(0.0 0.03486781388958288 365.0706550304856 0 0 151.0716002490953)
v4 h4 h2 sin(0.0 0.26473108458040834 730.1413100609713 0 0 110.1280320118014)
v5 h5 h4 sin(0.0 0.0017334015454813835 912.676637576214 0 0 -106.8129465680644)
v6 h6 h5 sin(0.0 0.09906601303000029 1095.211965091457 0 0 -122.11153102065322)
rl h6 0 1k
.tran 2.739195786406042e-06 %s 0.005478391572812084 2.739195786406042e-06
.four 182.5353275152428 v(h6)
.control
set nfreqs=8
set nperiods=2
set polydegree=1
set fourgridsize=100
run
.endc
.end
"""
amps = [0.28268603496881006, 0.9434622896126247, 0.03486781388958288, 0.0,
        0.26473108458040834, 0.0017334015454813835, 0.09906601303000029]
out = run("card", CARD % "0.016435174718436252")
h = harmonics(out)
errs = [abs(h[k][0] - abs(amps[k])) for k in range(1, 7) if k in h]
check("[1] a .four over the last 2 of 3 periods is analysed, every harmonic within 2e-3",
      len(errs) == 6 and max(errs) < 2e-3 and "No transient data" not in out,
      f"worst {max(errs) if errs else None}")

CMD = """* the campaign's Family F seed 1013: fourier over the last 2 of 3 periods
v1 h1 0 sin(-1.0162797899781149 3.397527269739203 21811836.26049136 0 0 -159.98500661191608)
v6 h6 h1 sin(0.0 0.004098509434364861 130871017.56294817 0 0 131.57135342566608)
rl h6 0 1k
.control
set nperiods=2
set polydegree=3
set fourgridsize=400
tran 4.584666728914243e-11 1.3754000186742728e-07 4.584666728914243e-08 4.584666728914243e-11
fourier 21811836.26049136 v(h6)
.endc
.end
"""
h = harmonics(run("cmd", CMD))
check("[2] the fourier command over the last 2 of 3 periods reads the fundamental and the 6th harmonic",
      1 in h and 6 in h and abs(h[1][0] - 3.397527269739203) < 1e-4 and abs(h[6][0] - 0.004098509434364861) < 1e-5,
      f"h1 {h.get(1)}, h6 {h.get(6)}")

out = run("short", CARD % "0.0137")      # 1.5 periods of data
check("[3] a window longer than the data is refused with the numbers, and nothing after it",
      "2 periods of 182.535 Hz" in out and "longer than the time span of the data" in out
      and "No transient data" not in out,
      [l for l in out.splitlines() if "period" in l or "No transient" in l][:2])

# ---- E-893 (D2) ------------------------------------------------------------
WR = """* wrdata of a vector longer than its scale
v1 a 0 1
r1 a 0 1k
.control
%s
let g = vector(1000)
%s
wrdata %s g
.endc
.end
"""
out = run("w1", WR % ("", "", "w1.txt"))
rows = load(os.path.join(WORK, "w1.txt"))
check("[4] a 1000-point vector in the constants plot writes 1000 rows, its index in the scale's column",
      len(rows) == 1000 and rows[999] == [999.0, 999.0] and "Note: g has 1000 points" in out,
      f"{len(rows)} rows")
out = run("w2", WR % ("op", "set wr_singlescale\nset wr_vecnames", "w2.txt"))
rows = load(os.path.join(WORK, "w2.txt"), skip=1)
head = open(os.path.join(WORK, "w2.txt")).readline().split() if os.path.exists(os.path.join(WORK, "w2.txt")) else []
check("[5] after an op, with wr_singlescale and wr_vecnames, 1000 rows under an index header",
      len(rows) == 1000 and head[:2] == ["index", "g"] and "different lengths" not in out,
      f"{len(rows)} rows, header {head}")

TR = """* a transient vector
v1 a 0 sin(0 1 1k)
r1 a 0 1k
.control
tran 10u 1m
wrdata w3.txt v(a)
.endc
.end
"""
out = run("w3", TR)
rows = load(os.path.join(WORK, "w3.txt"))
check("[6] (control) a transient's vector writes its own rows and no note",
      len(rows) > 50 and "Note: v(a)" not in out and "its scale" not in out, f"{len(rows)} rows")

# ---- E-894 (N2) ------------------------------------------------------------
FWD = """* a diode forward-biased by an ideal source
v4 2 0 dc -4.226577970529781
d9 0 %s dm9
%s
.model dm9 d is=1.332606006852675e-16 n=1.1654095711362193
.control
op
print v4#branch
.endc
.end
"""
out = run("fwd", FWD % ("2", ""))
m = re.search(r"carries (\S+) A in (\S+),", out)
check("[7] a diode an ideal source forward-biases by 4.2 V: the warning names v4#branch",
      m is not None and m.group(2) == "v4#branch" and float(m.group(1)) > 1e40,
      m.group(0) if m else out[-200:])
out = run("fwdr", FWD % ("3", "r1 3 2 1k"))
check("[8] (control) the same diode behind 1 kOhm: no warning", "past any junction" not in out)

# ---- notes -----------------------------------------------------------------
T = 8.072807530434066e-08
MEYER = """* the campaign's Family C seed 1110: gate, bulk and the tied drain-source driven
vga g_m 0 sin(1.9015524298740099 0.15743138227595097 12387264.23527443 0 0 318.61497946392194)
vgb g g_m sin(0 0.004366345351764501 37161792.70582329 0 0 352.8292044880176)
vda d_m 0 sin(1.3655436628937077 0.5129774049617178 12387264.23527443 0 0 122.00302714036881)
vdb d d_m sin(0 0.11542126783733705 37161792.70582329 0 0 80.75596161373954)
vba bk_m 0 sin(-1.1186092427864986 0.21433635079571234 12387264.23527443 0 0 193.57156910251175)
vbb bk bk_m sin(0 0.05835058191586141 37161792.70582329 0 0 17.10906046396265)
m1 d g d bk mm w=1.1268103095619496e-06 l=2.116683643637326e-06
%s
.option method=trap reltol=1e-6 abstol=1e-15 chgtol=1e-20 vntol=1e-9 gmin=1e-20
.control
set numdgt=17
tran %r 4.84368451826044e-07 0 %r
wrdata %s i(vga) i(vda) i(vba)
.endc
.end
"""
MOS1 = (".model mm nmos level=1 vto=0.6 kp=1e-4 tox=4.016761246164174e-09 cgso=7.888496746455857e-11 "
        "cgdo=3.890770107345762e-11 cgbo=4.64764359352431e-11 js=0 is=1e-30")
BSIM3 = ".model mm nmos level=8 version=3.3.0 tox=4.016761246164174e-09 capmod=3 js=0 jsw=0"


def charge_loss(tag, model, step):
    path = tag + ".txt"
    run(tag, MEYER % (model, step, step, path))
    data = load(os.path.join(WORK, path))
    if len(data) < 10:
        return None
    t = [r[0] for r in data]
    worst = 0.0
    for j in (1, 3, 5):
        i = [r[j] for r in data]
        cum = [0.0]
        for k in range(1, len(t)):
            cum.append(cum[-1] + (t[k] - t[k - 1]) * (i[k] + i[k - 1]) / 2.0)

        def C(tau):
            k = max(0, min(len(t) - 2, next((n for n in range(len(t)) if t[n] > tau), len(t)) - 1))
            ii = i[k] + (i[k + 1] - i[k]) * (tau - t[k]) / (t[k + 1] - t[k])
            return cum[k] + (tau - t[k]) * (i[k] + ii) / 2.0

        net = abs(C(6 * T) - C(T)) / 5.0
        moved = sum((t[k] - t[k - 1]) * (abs(i[k]) + abs(i[k - 1])) / 2.0
                    for k in range(1, len(t)) if t[k - 1] >= T) / 5.0
        worst = max(worst, net / max(moved, 1e-30))
    return worst


l200 = charge_loss("m200", MOS1, T / 200)
l1000 = charge_loss("m1000", MOS1, T / 1000)
lb = charge_loss("b200", BSIM3, T / 200)
check("[9] N1: level 1 with tox loses over 10 % of its moved charge a period, at any step; BSIM3 conserves",
      None not in (l200, l1000, lb) and l200 > 0.1 and abs(l200 - l1000) < 0.1 * l200 and lb < 1e-3,
      f"Meyer {l200} at T/200, {l1000} at T/1000; BSIM3 {lb}")

FLICKER = """* MOS1 flicker noise, kf and af only
vdd dd 0 5
vg g 0 1.5 ac 1
rd dd d 10k
m1 d g 0 0 mn w=10u l=1u
.model mn nmos level=1 vto=0.7 kp=1e-4 kf=1e-24 af=0.5 %s
.control
set numdgt=8
noise v(d) vg dec 1 1 100
setplot noise1
print onoise_spectrum
.endc
.end
"""


def decade(out):
    v = [float(m.group(1)) for m in re.finditer(r"^\d+\s+\S+\s+(\S+)\s*$", out, re.M)]
    return (v[0] / v[2]) ** 2 if len(v) == 3 else None     # PSD ratio, 1 Hz over 100 Hz


r2 = decade(run("nl2", FLICKER % ""))
r0 = decade(run("nl0", FLICKER % "nlev=0"))
check("[10] N3: MOS1's default flicker PSD falls as f^-AF (10 over two decades at af=0.5); nlev=0 as 1/f",
      r2 is not None and r0 is not None and abs(r2 - 10.0) < 0.05 and abs(r0 - 100.0) < 0.5,
      f"nlev 2: {r2}, nlev 0: {r0}")

RIPPLE = """* a 10 mV ripple on a capacitor biased at %s V
v1 a 0 sin(%s 0.01 1k)
r1 a c 1k
c1 c 0 1u
.control
tran 10u 20m 0 %s
rusage tranpoints
.endc
.end
"""


def points(out):
    m = re.search(r"Transient timepoints = (\d+)", out)
    return int(m.group(1)) if m else None


p0, p1 = points(run("r0", RIPPLE % ("0", "0", "1m"))), points(run("r1", RIPPLE % ("1", "1", "1m")))
q0, q1 = points(run("q0", RIPPLE % ("0", "0", "10u"))), points(run("q1", RIPPLE % ("1", "1", "10u")))
check("[11] N4: at tmax=1m the biased ripple takes under a third of the unbiased steps; at the default tmax both take 2000",
      None not in (p0, p1, q0, q1) and p1 * 3 < p0 and q0 >= 2000 and q1 >= 2000,
      f"tmax=1m: {p0} at 0 V, {p1} at 1 V; tmax=10u: {q0}, {q1}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
