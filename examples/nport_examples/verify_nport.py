#!/usr/bin/env python3
"""Enhancement-199: N-port Touchstone device (snp2va.py).

A measured or simulated S-parameter block (a filter, cable, connector, amplifier)
stored in a Touchstone `.sNp` file can be dropped straight into an ngspice
simulation. `snp2va.py` converts the file into a Verilog-A n-port model realized
with `laplace_nd`, so -- via OpenVAF's OSDI laplace machinery -- the block works in
**AC *and* transient** (no convolution engine needed). Pure Python standard library
(no numpy): the converter reimplements the least-squares, matrix inverse, and
polynomial-root primitives that vector fitting needs.

Pipeline: parse Touchstone -> S(f) -> Y(f) -> common-pole vector fit (automatic
order selection, Gustavsen pole seeding, stability + passivity checks) -> emit
`I(p_i) <+ sum_j laplace_nd(V(p_j), num_ij, den) + e_ij*ddt(V(p_j))`.

The checks generate Touchstone files from networks whose response is known exactly,
run the converter + OpenVAF, and confirm the resulting device matches the ORIGINAL
network in ngspice -- in both AC and transient.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import math
import cmath
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

passed = failed = 0
Z0 = 50.0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


# --- tiny complex linear algebra (self-contained, for building the .sNp truth) --
def mat_inv(M):
    n = len(M)
    A = [[M[i][j] for j in range(n)] + [1.0 if i == j else 0j for j in range(n)]
         for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(A[r][c]))
        A[c], A[p] = A[p], A[c]
        d = A[c][c]
        A[c] = [x / d for x in A[c]]
        for r in range(n):
            if r != c and abs(A[r][c]) > 0:
                f = A[r][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    return [row[n:] for row in A]


def matmul(A, B):
    return [[sum(A[i][t] * B[t][j] for t in range(len(B))) for j in range(len(B[0]))]
            for i in range(len(A))]


def write_snp(fn, freqs, Yof, N):
    """Write a Touchstone file (S, RI) from an analytic Y(f) N-port."""
    I = [[1.0 if i == j else 0j for j in range(N)] for i in range(N)]
    with open(fn, "w") as f:
        f.write("# HZ S RI R 50\n")
        for fr in freqs:
            Y = Yof(fr)
            IpZY = [[I[i][j] + Z0 * Y[i][j] for j in range(N)] for i in range(N)]
            ImZY = [[I[i][j] - Z0 * Y[i][j] for j in range(N)] for i in range(N)]
            S = matmul(ImZY, mat_inv(IpZY))
            row = f"{fr:.7e} "
            for i in range(N):
                for j in range(N):
                    row += f"{S[i][j].real:.7e} {S[i][j].imag:.7e} "
            f.write(row + "\n")


def convert(snp, module):
    r = subprocess.run([sys.executable, os.path.join(HERE, "snp2va.py"), snp,
                        "-o", os.path.join(HERE, module + ".va"), "-m", module,
                        "--tol", "1e-3"],
                       capture_output=True, text=True, cwd=HERE)
    info = (r.stderr or "").strip()
    ok = subprocess.run([OPENVAF, module + ".va", "-o", module + ".osdi"],
                        cwd=HERE, capture_output=True, text=True).returncode == 0
    return ok, info


def run(deck):
    open(os.path.join(HERE, "_t.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_t.cir"], capture_output=True, text=True,
                       cwd=HERE, timeout=120)
    rows = []
    p = os.path.join(HERE, "_o.dat")
    if os.path.exists(p):
        for l in open(p):
            q = l.split()
            if q and q[0].lstrip("-")[0].isdigit():
                rows.append([float(x) for x in q])
        os.remove(p)
    return rows, r.stdout + r.stderr


# ================= 2-port resonant R-L-C =================
Rr, Lr, Cr, Csh = 5.0, 1e-7, 1e-11, 5e-13


def Y2(f):
    s = 1j * 2 * math.pi * f
    ys = 1.0 / (Rr + s * Lr + 1.0 / (s * Cr))
    return [[s * Csh + ys, -ys], [-ys, s * Csh + ys]]


freqs2 = [10 ** (5 + 4 * k / 300) for k in range(301)]      # 100 kHz .. 1 GHz
write_snp(os.path.join(HERE, "resonator.s2p"), freqs2, Y2, 2)
ok_c, info = convert("resonator.s2p", "resonator")
check("[convert] snp2va reads .s2p, fits, and OpenVAF compiles the model",
      ok_c, info)

ACT2 = ("Rser p1 a 5\nL1 a b 1e-7\nCser b p2 1e-11\n"
        "Csh1 p1 0 5e-13\nCsh2 p2 0 5e-13\n")
NP2 = "N1 p1 p2 mm\n.model mm resonator\n"


def two_port_ac(dut):
    return run(f"""* 2-port AC
Vs in 0 dc 0 ac 1
Rs in p1 50
{dut}Rl p2 0 50
.control
{'pre_osdi resonator.osdi' if 'N1' in dut else ''}
ac dec 40 1e5 1e9
wrdata _o.dat v(p2)
.endc
.end
""")


ra, _ = two_port_ac(ACT2)
rn, _ = two_port_ac(NP2)
if ra and rn:
    m = min(len(ra), len(rn))
    def cx(r):
        return complex(r[1], r[2])
    err = max(abs(cx(rn[k]) - cx(ra[k])) / (abs(cx(ra[k])) + 1e-30) for k in range(m))
    check("[ac] the nport device matches the original R-L-C resonator in AC "
          "(incl. the transmission peak)", err < 1e-3, f"(max rel err {err:.2e})")
else:
    check("[ac] the nport device matches the original R-L-C resonator in AC", False)


# ================= 2-port transient =================
def two_port_tran(dut):
    return run(f"""* 2-port transient
Vs in 0 pulse(0 1 5n 0.2n 0.2n 40n 80n)
Rs in p1 50
{dut}Rl p2 0 50
.control
{'pre_osdi resonator.osdi' if 'N1' in dut else ''}
tran 0.1n 120n
wrdata _o.dat v(p2)
.endc
.end
""")


ta, _ = two_port_tran(ACT2)
tn, _ = two_port_tran(NP2)
if ta and tn:
    import bisect
    tt = [r[0] for r in tn]
    vv = [r[1] for r in tn]
    def interp(t):
        i = bisect.bisect(tt, t)
        i = max(1, min(i, len(tt) - 1))
        if tt[i] == tt[i - 1]:
            return vv[i]
        w = (t - tt[i - 1]) / (tt[i] - tt[i - 1])
        return vv[i - 1] + w * (vv[i] - vv[i - 1])
    amp = max(abs(r[1]) for r in ta)
    err = max(abs(interp(ta[k][0]) - ta[k][1]) for k in range(len(ta))) / amp
    check("[transient] the same device matches the resonator's transient step "
          "response (AC + transient from one model)", err < 5e-3,
          f"(max err {err:.2e} of peak {amp:.3f})")
else:
    check("[transient] the same device matches the resonator's transient response", False)


# ================= 3-port star (N-port generalization) =================
Rp = [10.0, 20.0, 30.0]
Cc = 1e-12


def Y3(f):
    s = 1j * 2 * math.pi * f
    y = [1.0 / r for r in Rp]
    Ycc = sum(y) + s * Cc
    return [[(y[i] if i == j else 0) - y[i] * y[j] / Ycc for j in range(3)]
            for i in range(3)]


freqs3 = [10 ** (6 + 3 * k / 200) for k in range(201)]
write_snp(os.path.join(HERE, "star.s3p"), freqs3, Y3, 3)
ok3, info3 = convert("star.s3p", "star")
ACT3 = "Rp1 p1 c 10\nRp2 p2 c 20\nRp3 p3 c 30\nCc c 0 1p\n"
NP3 = "N1 p1 p2 p3 ms\n.model ms star\n"


def three_port(dut):
    return run(f"""* 3-port AC
Vs in 0 dc 0 ac 1
Rs in p1 50
{dut}Rl2 p2 0 50
Rl3 p3 0 50
.control
{'pre_osdi star.osdi' if 'N1' in dut else ''}
ac dec 30 1meg 1g
wrdata _o.dat v(p2) v(p3)
.endc
.end
""")


a3, _ = three_port(ACT3)
n3, _ = three_port(NP3)
if ok3 and a3 and n3:
    m = min(len(a3), len(n3))
    e2 = max(abs(complex(n3[k][1], n3[k][2]) - complex(a3[k][1], a3[k][2]))
             / (abs(complex(a3[k][1], a3[k][2])) + 1e-30) for k in range(m))
    e3 = max(abs(complex(n3[k][4], n3[k][5]) - complex(a3[k][4], a3[k][5]))
             / (abs(complex(a3[k][4], a3[k][5])) + 1e-30) for k in range(m))
    check("[nport] a 3-port .s3p converts and matches the original star network "
          "(both coupled outputs)", e2 < 1e-3 and e3 < 1e-3,
          f"(v(p2) {e2:.2e}, v(p3) {e3:.2e})")
else:
    check("[nport] a 3-port .s3p converts and matches the original star network", False)


# ================= high order: a 5-pole LC ladder (order-selection scaling) =====
g = [0.6180, 1.6180, 2.0000, 1.6180, 0.6180]
wc = 2 * math.pi * 100e6
C1l = g[0] / (Z0 * wc); L2l = g[1] * Z0 / wc; C3l = g[2] / (Z0 * wc)
L4l = g[3] * Z0 / wc; C5l = g[4] / (Z0 * wc)


def Ylad(f):
    s = 1j * 2 * math.pi * f

    def mul(A, B):
        return [[A[0][0] * B[0][0] + A[0][1] * B[1][0], A[0][0] * B[0][1] + A[0][1] * B[1][1]],
                [A[1][0] * B[0][0] + A[1][1] * B[1][0], A[1][0] * B[0][1] + A[1][1] * B[1][1]]]
    A = [[1, 0], [s * C1l, 1]]
    for X in ([[1, s * L2l], [0, 1]], [[1, 0], [s * C3l, 1]],
              [[1, s * L4l], [0, 1]], [[1, 0], [s * C5l, 1]]):
        A = mul(A, X)
    a, b, c, d = A[0][0], A[0][1], A[1][0], A[1][1]
    return [[d / b, -1.0 / b], [-1.0 / b, a / b]]      # ABCD -> Y (reciprocal)


freqsL = [10 ** (6 + 3 * k / 200) for k in range(201)]
write_snp(os.path.join(HERE, "ladder.s2p"), freqsL, Ylad, 2)
okL, infoL = convert("ladder.s2p", "ladder")
ACTL = (f"C1 p1 0 {C1l:.6e}\nL2 p1 x {L2l:.6e}\nC3 x 0 {C3l:.6e}\n"
        f"L4 x p2 {L4l:.6e}\nC5 p2 0 {C5l:.6e}\n")
NPL = "N1 p1 p2 ml\n.model ml ladder\n"


def ladder_run(dut, analysis, outfile):
    return run(f"""* ladder
Vs in 0 dc 0 ac 1 pulse(0 1 5n 0.1n 0.1n 30n 60n)
Rs in p1 50
{dut}Rl p2 0 50
.control
{'pre_osdi ladder.osdi' if 'N1' in dut else ''}
{analysis}
wrdata {outfile} v(p2)
.endc
.end
""")


la, _ = ladder_run(ACTL, "ac dec 40 1e6 1e9", "_o.dat")
ln, _ = ladder_run(NPL, "ac dec 40 1e6 1e9", "_o.dat")
if okL and la and ln:
    m = min(len(la), len(ln))
    eac = max(abs(complex(ln[k][1], ln[k][2]) - complex(la[k][1], la[k][2]))
              / (abs(complex(la[k][1], la[k][2])) + 1e-30) for k in range(m))
    check("[highorder] a 5-pole LC ladder converts (order-selection scales past 2 "
          "poles) and matches the filter response", eac < 5e-3,
          f"(AC max rel err {eac:.2e}; {infoL.split('->')[0].strip()})")
else:
    check("[highorder] a 5-pole LC ladder converts and matches the filter response",
          False, infoL)


# ================= passivity / stability safeguard on noisy data =================
import random
random.seed(7)
lines = [l for l in open(os.path.join(HERE, "resonator.s2p")) if not l.startswith("#")]
with open(os.path.join(HERE, "noisy.s2p"), "w") as f:
    f.write("# HZ S RI R 50\n")
    for l in lines:
        p = [float(x) for x in l.split()]
        row = f"{p[0]:.7e} "
        for k in range(4):
            c = complex(p[1 + 2 * k], p[2 + 2 * k]) * (1 + 0.005 * random.gauss(0, 1))
            row += f"{c.real:.7e} {c.imag:.7e} "
        f.write(row + "\n")
import re
oknz, infonz = convert("noisy.s2p", "noisy")
# the fit's poles are forced stable, so even a non-passive fit stays BOUNDED in tran
out = ""
if oknz:
    _, out = run("""* noisy stability
Vs in 0 pulse(0 1 5n 0.2n 0.2n 20n 40n)
Rs in p1 50
N1 p1 p2 mz
.model mz noisy
Rl p2 0 50
.control
pre_osdi noisy.osdi
tran 0.05n 200n
let mx = maximum(abs(v(p2)))
print mx
.endc
.end
""")
mm = re.search(r"mx\s*=\s*([-\d.eE+]+)", out)
bounded = mm is not None and abs(float(mm.group(1))) < 10.0
check("[robust] a noisy fit reports its passivity and (poles forced stable) stays "
      "BOUNDED in transient", oknz and bounded,
      f"(peak |v(p2)|={mm.group(1) if mm else '?'}; {infonz.split('->')[0].strip()})")

# tidy
for f in ("_t.cir", "resonator.s2p", "resonator.va", "resonator.osdi",
          "star.s3p", "star.va", "star.osdi",
          "ladder.s2p", "ladder.va", "ladder.osdi",
          "noisy.s2p", "noisy.va", "noisy.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
