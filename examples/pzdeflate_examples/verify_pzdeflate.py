#!/usr/bin/env python3
"""verify_pzdeflate.py -- Enhancement-856: the pole-zero search divides out
the roots it has found analytically, and stops where a complex search has
converged.

F1 of the third robustness campaign of 2026-10-10.

The search finds the roots of det(G + sC) one at a time and divides each out
of the function it searches next. A root's factor was |p - s|^2 whenever p - s
was complex: right for a pair at a real trial, and not analytic at a complex
one, where a real root was divided out by its squared distance. Muller, fitting
a quadratic to that function, wandered to the iteration limit around a complex
pair it had started next to, and the analysis reported the roots found so far:
4 of 252 networks lost poles or zeros, 20 of 859 more. A complex pair on the jw
axis was found to the last digit and never declared, the test of a repeated
point asking for equal imaginary parts and a real part within 1e-12 of |Re s|
= 0. Once the search converges it can also converge on the rounding noise
beyond the last root (|s| ~ 1e21, where s*C has swamped G); a point there is a
root only if the function grows around it as at a zero.

  [1] a network with two cancelling pairs: its 4 poles and 4 zeros (1 pole on
      E-855, with the iteration-limit warning)
  [2] a complex pair of zeros (missed on E-855)
  [3] a pair of zeros on the jw axis and a far real one (1 of 4 on E-855)
  [4] a pair of zeros on the jw axis that converged and never stopped
  [5] two more networks, poles and zeros (5 of 6 poles; 3 of 5 and 3 of 5)
  [6] none of the four warns now
  [7] the rational function of [1]'s roots is ngspice's own ac response, to
      1e-9 (240 % off on E-855)
  [8] (control) a search that goes on past its last root: no roots from the
      rounding noise there
  [9] (control) a zero at s ~ 0, where the matrix is singular below the reach
      of s*C, is still a zero

Exit code 0 = pass.
"""
import cmath
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

WORK = tempfile.mkdtemp(prefix="pzdeflate_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


# generated networks of the campaign (scratchpad rc3/pz.py); the exact roots are
# the finite generalized eigenvalues of the MNA pencil and its Rosenbrock pencil
NETS = {
    1233: (2, """r0 2 0 800.0594332283658
r1 3 0 805.6365653752729
r2 4 0 9030.049467843333
r3 3 0 106.52723925521391
c4 3 4 2.538010009170991e-12
c5 2 1 4.211006706589182e-11
c6 0 3 5.950993827586065e-10
l7 1 2 9.521919413088302e-05""",
           [-43946641.328, -17732678.6863, complex(-14840954.0707, 5398345.03954)],
           [-43946641.328, -17732678.6863, complex(0, 15792278.0781)]),
    1088: (4, """r0 2 0 9343.415260758931
r1 3 0 2871.8878154793633
r2 4 0 1775.959611189461
r3 5 0 27104.496537972558
r4 6 0 882.820636222763
r5 6 2 247.494380925892
r6 2 0 285.12077801382605
r7 5 1 13700.954346044133
r8 0 2 293.33674698041307
r9 1 2 337.95038464797585
r10 3 4 36457.334132247284
r11 0 5 39.72664875288858
r12 6 2 136.26119838670476
r13 6 0 333.00449091600694
r14 1 6 14.650333364163608
r15 5 2 877.2297370749272
c16 5 4 2.790395299556951e-09
c17 6 2 1.843718519018912e-11
c18 6 2 3.53062222312269e-10
c19 1 3 1.996293482259927e-11
c20 5 2 2.8860825361992e-10
c21 0 1 1.1066969414421879e-12
l22 5 1 3.894511321787911e-05""",
           [-137187084.418, -29439294.915, -18815114.1821, -955807.334476, -212213.473612],
           [-38291756.9193, -18896534.0162, complex(-2669021.56259, 12093728.5191), 0.0]),
    1036: (2, """r0 2 0 12213.927100528505
r1 3 0 9718.165980112653
r2 4 0 184.23520111095132
r3 5 0 156.14464812428378
r4 2 3 36.77525238718397
r5 2 4 17877.687930503726
c6 4 2 1.5890078887000344e-09
c7 2 1 1.3341831097695672e-09
c8 5 4 3.2857276995577486e-12
c9 0 1 1.5781492126555704e-11
c10 2 1 2.2970273927682195e-09
l11 2 1 9.572869355936416e-07""",
           [-1954940992.56, -3504300.14839, complex(-738874.290451, 16790487.255)],
           [-1953169863.23, -3443937.68437, complex(0, 16961069.006)]),
    1250: (2, """r0 2 0 1518.188076552654
r1 3 0 298.3199619264667
r2 2 3 20104.329479254364
r3 1 0 3111.2767121818056
r4 3 2 194.14841986608772
c5 2 1 4.843089091495626e-11
l6 1 2 9.530835879315709e-07
g7 2 3 3 2 -0.0024381403353944233""",
           [complex(-30852308.3449, 143918481.562)],
           [complex(0, 147188295.273)]),
    5589: (2, """r0 2 0 351.6686993301312
r1 3 0 8325.60823084938
r2 4 0 262.6394971031836
r3 5 0 11061.472707697503
r4 6 0 37747.659885875175
r5 0 6 10733.51315659748
r6 0 1 3624.5835234570127
r7 3 0 11.00546870428351
r8 5 0 370.9613561645906
r9 4 6 36251.39046804313
r10 4 3 71633.85822365397
r11 6 0 313.9694950094132
r12 6 3 2733.2330185462997
r13 2 1 285.2962411497037
r14 2 5 376.88556177168294
r15 1 3 139.70775465210076
r16 1 6 7009.455296506003
c17 6 1 2.0616057777437144e-10
c18 3 0 1.3729415987203575e-10
c19 5 6 5.627324629218489e-10
c20 1 3 3.4579420887511245e-09
c21 2 4 6.762442808717961e-10
c22 5 4 3.868556940485654e-09
l23 4 6 9.1048870337621e-05""",
           [-106331268.667, -27403712.944, -10287831.8128, complex(-1897642.04111, 3619735.63704),
            -633804.753635],
           [-30687587.3173, complex(-14309908.2691, 14304742.3122), complex(-1929102.05614, 3514278.66617),
            -714768.322008]),
    5981: (4, """r0 2 0 1863.5724317218196
r1 3 0 1696.155344258715
r2 4 0 2380.5922298679734
r3 5 0 651.9214108437883
r4 6 0 3806.2268837557344
r5 4 6 20.481907623228125
r6 6 4 2392.271873173916
r7 3 5 5410.239980968067
r8 3 1 81.03352020222118
r9 0 3 1629.5484200386263
r10 2 3 23.86282801780919
r11 4 0 662.2929334850379
r12 6 2 7635.219036765092
c13 5 6 9.078850534967963e-10
c14 1 4 2.8841327214754348e-09
c15 2 1 8.250035129989074e-10
c16 4 5 2.1357458213936117e-11
c17 2 6 2.849013941117485e-09
l18 3 6 8.708964835562226e-06""",
           [-100937790.663, -4550187.41576, -1677329.3675, complex(-1661940.95836, 4721265.93812)],
           [-101566505.352, -3074637.3032, -1907941.32119, complex(-1616027.46748, 4571977.94867)]),
    5144: (2, """r0 2 0 751.6621112455969
r1 3 0 2242.8805267829744
r2 4 0 233.82913645264819
r3 2 1 3214.9176608872826
r4 0 1 2401.1131058899327
r5 3 1 3431.974162550692
c6 2 4 9.409339439826161e-09
c7 0 1 1.483250148713678e-11""",
           [-126062.643227],
           [-454508.73937]),
    1050: (3, """r0 2 0 46116.702745980896
r1 3 0 1804.1667911598556
r2 4 0 57177.79637143923
r3 0 1 473.46004586105465
r4 0 3 509.9657452744231
c5 4 3 2.059744338679145e-12
c6 0 4 7.859387025184202e-11
c7 3 2 1.808760111440185e-09
l8 1 2 4.8260260403737445e-06
g9 3 1 2 1 -0.0002828602829227118""",
           [-1022011299.95, -99591759.885, -1410408.69702, -216843.504208],
           [-216844.669498, 0.0, 732539858.494]),
}


def full(roots):
    """a pair is listed once; add its conjugate"""
    out = []
    for r in roots:
        r = complex(r)
        out.append(r)
        if r.imag != 0:
            out.append(r.conjugate())
    return out


def run_pz(seed):
    out, body = NETS[seed][0], NETS[seed][1]
    path = os.path.join(WORK, "pz%d.cir" % seed)
    with open(path, "w") as f:
        f.write("* pz %d\n%s\n.control\nset numdgt=17\npz 1 0 %d 0 vol pz\nprint all\n.endc\n.end\n"
                % (seed, body, out))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    text = p.stdout + p.stderr
    poles = [complex(float(a), float(b)) for a, b in
             re.findall(r"^pole\(\d+\) = (\S+?),(\S+)$", text, re.M)]
    zeros = [complex(float(a), float(b)) for a, b in
             re.findall(r"^zero\(\d+\) = (\S+?),(\S+)$", text, re.M)]
    warn = re.findall(r"Warning: Pole-zero.*", text)
    return poles, zeros, warn


def match(got, ref):
    """every exact root has its own root within 1e-6 (relative, floor 1); nothing extra"""
    got = list(got)
    missing = []
    for z in full(ref):
        if not got:
            missing.append(z)
            continue
        j = min(range(len(got)), key=lambda k: abs(got[k] - z))
        if abs(got[j] - z) / max(abs(z), 1.0) > 1e-6:
            missing.append(z)
        else:
            got.pop(j)
    return missing, got


RES = {seed: run_pz(seed) for seed in NETS}


def roots_ok(seed, which):
    poles, zeros, _ = RES[seed]
    ref = NETS[seed][2] if which == "poles" else NETS[seed][3]
    miss, extra = match(poles if which == "poles" else zeros, ref)
    return not miss and not extra, "%d %s; missing %s, extra %s" % (
        len(poles if which == "poles" else zeros), which,
        ["%.4g%+.4gj" % (z.real, z.imag) for z in miss], ["%.4g%+.4gj" % (z.real, z.imag) for z in extra])


# [1]
ok_p, dp = roots_ok(1233, "poles")
ok_z, dz = roots_ok(1233, "zeros")
check("[1] two cancelling pairs: the 4 poles and 4 zeros", ok_p and ok_z, dp + " / " + dz)

# [2]
ok, d = roots_ok(1088, "zeros")
check("[2] a complex pair of zeros, -2.67e6 +- j1.21e7, among 5", ok and roots_ok(1088, "poles")[0], d)

# [3]
ok, d = roots_ok(1036, "zeros")
check("[3] a pair of zeros on the jw axis, +-j1.70e7, and one at -1.95e9", ok and roots_ok(1036, "poles")[0], d)

# [4]
ok, d = roots_ok(1250, "zeros")
check("[4] the pair of zeros at +-j1.47e8, found and declared", ok and roots_ok(1250, "poles")[0], d)

# [5]
oks = [roots_ok(s, w) for s in (5589, 5981) for w in ("poles", "zeros")]
check("[5] two more networks, poles and zeros", all(o for o, _ in oks),
      "; ".join(d for o, d in oks if not o))

# [6]
warned = {s: RES[s][2] for s in (1233, 1088, 1036, 1250, 5589, 5981) if RES[s][2]}
check("[6] none of these warns that the search gave up", not warned,
      "; ".join("%d: %s" % (s, w[0][:70]) for s, w in warned.items()))

# [7]
poles, zeros, _ = RES[1233]
path = os.path.join(WORK, "ac1233.cir")
with open(path, "w") as f:
    f.write("* ac 1233\nvin 1 0 dc 0 ac 1\n%s\n.control\nset numdgt=17\nset wr_singlescale\n"
            "ac dec 10 1e5 1e9\nwrdata %s v(2)\n.endc\n.end\n" % (NETS[1233][1], os.path.join(WORK, "ac.txt")))
subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
pts = []
if os.path.exists(os.path.join(WORK, "ac.txt")):
    for line in open(os.path.join(WORK, "ac.txt")):
        try:
            fr, re_, im_ = (float(x) for x in line.split()[:3])
            pts.append((fr, complex(re_, im_)))
        except ValueError:
            pass
worst = None
if pts and poles:
    def h(fr):
        s = 2j * math.pi * fr
        num = 1.0
        for z in zeros:
            num *= (s - z)
        den = 1.0
        for p in poles:
            den *= (s - p)
        return num / den
    k = sum(v / h(fr) for fr, v in pts) / len(pts)
    worst = max(abs(k * h(fr) - v) / abs(v) for fr, v in pts)
check("[7] the rational function of [1]'s roots is ngspice's ac response to 1e-9",
      worst is not None and worst < 1e-9, "%d points, worst %.3g" % (len(pts), worst if worst is not None else -1))

# [8]
ok_p, dp = roots_ok(5144, "poles")
ok_z, dz = roots_ok(5144, "zeros")
check("[8] (control) past the last root: one pole and one zero, nothing from the noise at |s| ~ 1e21",
      ok_p and ok_z, dp + " / " + dz)

# [9]
ok, d = roots_ok(1050, "zeros")
check("[9] (control) a zero at s ~ 0 is still a zero, with -2.17e5 and 7.33e8", ok and roots_ok(1050, "poles")[0], d)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
