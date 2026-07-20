#!/usr/bin/env python3
"""Enhancement-242: the native C n-port device + `pre_snp -native`.

A built-in ngspice device that realizes an arbitrary-port linear block directly
from a pole/residue (vector-fitted) Y-parameter model

    Y_ij(s) = d_ij + s*e_ij + sum_k res_ijk / (s - p_k)          (shared poles)

stamped straight into the sparse matrix (DC / AC / transient), with no Verilog-A /
OpenVAF compile.  It rides the generic `N` dispatcher:

    N1  p1 p2 ... pN  ref   mymodel
    .model mymodel nport(file="mymodel.nport")

`pre_snp -native <file.sNp>` writes the `.nport` fit file (the same vector fit the
default `pre_snp -osdi` path feeds to openvaf-r), so a Touchstone block scales past
the compiler wall (~24-32 ports) that limits the VA->OSDI route.

Every check compares the device against a closed-form oracle (no openvaf-r needed),
so it runs anywhere and under BOTH linear solvers (KLU + Sparse 1.3):

 1. RC one-port      -- e-term (capacitor) : AC 1/Y and the transient exponential.
 2. RLC one-port     -- complex conjugate pole pair : AC 1/Y through resonance.
 3. Pi two-port      -- off-diagonal d/e cross-coupling : node voltages vs analytic.
 4. pre_snp -native  -- fit a known 2-port .s2p, reload the .nport, reproduce Y.
 5. Scaling (N=20)   -- a 6-pole full-rank model : the N-port stamp vs analytic.
"""
import cmath
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers

_check_both_solvers(__file__)          # verify under BOTH KLU and Sparse

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run_batch(deck_name, deck, out_name, saves):
    """Write `deck` to HERE, run it (`-b`, so the dual-solver harness injects the
    `.option`), and read the wrdata columns back. Relative paths, cwd=HERE."""
    open(os.path.join(HERE, deck_name), "w").write(deck)
    ctrl = (".control\nrun\nset filetype=ascii\n"
            f"wrdata {out_name} {saves}\n.endc\n")
    # splice the .control block in before .end
    if ".control" not in deck:
        deck2 = deck.replace(".end", ctrl + ".end")
        open(os.path.join(HERE, deck_name), "w").write(deck2)
    subprocess.run([NGSPICE, "-b", deck_name], cwd=HERE, capture_output=True,
                   text=True, timeout=120)
    rows = []
    with open(os.path.join(HERE, out_name)) as f:
        for ln in f:
            p = ln.split()
            if p:
                rows.append([float(x) for x in p])
    return rows


# ------------------------------------------------------------------ fixtures
def write_nport(name, N, poles, d, e, res):
    """Emit a `.nport` file. poles: [(re,im)]; d,e: N*N row-major; res: {(i,j):[(re,im)]}."""
    with open(os.path.join(HERE, name), "w") as f:
        f.write(f"NPORT 1\nnports {N}\nnpoles {len(poles)}\npoles\n")
        for pr, pi in poles:
            f.write(f"  {pr:.15e} {pi:.15e}\n")
        f.write("d\n")
        for i in range(N):
            f.write(" " + " ".join(f"{d[i*N+j]:.15e}" for j in range(N)) + "\n")
        f.write("e\n")
        for i in range(N):
            f.write(" " + " ".join(f"{e[i*N+j]:.15e}" for j in range(N)) + "\n")
        f.write("res\n")
        for i in range(N):
            for j in range(N):
                for pr, pi in res[(i, j)]:
                    f.write(f"  {pr:.15e} {pi:.15e}\n")


# ====================================================================== 1. RC
# Y = 1e-3 + s*1e-9  (G = 1 mS -> R = 1k ; C = 1 nF)
write_nport("rc.nport", 1, [], [1e-3], [1e-9], {(0, 0): []})

# 1a. AC: inject 1 A into p1 (weak 1e9-ohm DC leak), V(p1) = 1/Y
f0 = 2.0e6
rc_ac = f"""* nport RC AC
Iac 0 p1 AC 1
N1 p1 0 rcm
.model rcm nport(file="rc.nport")
Rl p1 0 1e9
.ac lin 1 {f0:g} {f0:g}
.end
"""
r = run_batch("_rc_ac.cir", rc_ac, "_rc_ac.dat", "v(p1)")
vre, vim = r[0][1], r[0][2]
Y = 1e-3 + 1j * 2 * math.pi * f0 * 1e-9
Van = 1.0 / Y
err = abs((vre + 1j * vim) - Van) / abs(Van)
check("RC one-port AC: V(p1) = 1/Y (e-term capacitor)", err < 1e-6,
      f"rel err {err:.2e}")

# 1b. transient: step through Rs=1k -> settles to 0.5 with tau = C*(Rs||R) = 0.5us
rc_tr = """* nport RC tran
V1 in 0 PULSE(0 1 0 1p 1p 1 2)
Rs in p1 1k
N1 p1 0 rcm
.model rcm nport(file="rc.nport")
.tran 5n 3u
.end
"""
r = run_batch("_rc_tr.cir", rc_tr, "_rc_tr.dat", "v(p1)")
tau = 1e-9 * 500.0
emax = max(abs(v - 0.5 * (1 - math.exp(-t / tau))) for t, v in r)
check("RC one-port transient: 0.5*(1-e^{-t/tau}) exponential", emax < 1e-4,
      f"max|dev-analytic| {emax:.2e}")

# ===================================================================== 2. RLC
# series-RLC one-port: Y = sC/(s^2 LC + sRC + 1); R=10 L=1mH C=1nF -> conj poles
R, L, C = 10.0, 1e-3, 1e-9
b, c = R / L, 1.0 / (L * C)
disc = cmath.sqrt(complex(b * b - 4 * c))
p1, p2 = (-b + disc) / 2, (-b - disc) / 2
r1 = (p1 / L) / (p1 - p2)
r2 = (p2 / L) / (p2 - p1)
write_nport("rlc.nport", 1, [(p1.real, p1.imag), (p2.real, p2.imag)],
            [0.0], [0.0], {(0, 0): [(r1.real, r1.imag), (r2.real, r2.imag)]})
fr = 1.0e6                                   # near the 1/(2pi sqrt(LC)) resonance
rlc_ac = f"""* nport RLC AC
Iac 0 p1 AC 1
N1 p1 0 rlcm
.model rlcm nport(file="rlc.nport")
Rl p1 0 1e9
.ac lin 1 {fr:g} {fr:g}
.end
"""
r = run_batch("_rlc_ac.cir", rlc_ac, "_rlc_ac.dat", "v(p1)")
vre, vim = r[0][1], r[0][2]
s = 1j * 2 * math.pi * fr
Yr = r1 / (s - p1) + r2 / (s - p2)
Van = 1.0 / Yr
err = abs((vre + 1j * vim) - Van) / abs(Van)
check("RLC one-port AC: complex conjugate pole pair through resonance", err < 1e-5,
      f"rel err {err:.2e}")

# ====================================================================== 3. Pi
# 2-port Pi: Y11=1e-3+s1e-9, Y12=Y21=-1e-3, Y22=1e-3+s2e-9
write_nport("pi.nport", 2, [],
            [1e-3, -1e-3, -1e-3, 1e-3], [1e-9, 0.0, 0.0, 2e-9],
            {(0, 0): [], (0, 1): [], (1, 0): [], (1, 1): []})
fp = 2.0e6
pi_ac = f"""* nport Pi 2-port AC
Vg g 0 AC 1
Rs g p1 1k
N1 p1 p2 0 pim
.model pim nport(file="pi.nport")
Rl p2 0 4k
.ac lin 1 {fp:g} {fp:g}
.end
"""
r = run_batch("_pi_ac.cir", pi_ac, "_pi_ac.dat", "v(p1) v(p2)")
v1 = r[0][1] + 1j * r[0][2]
v2 = r[0][4] + 1j * r[0][5]
# analytic MNA: unknowns V1,V2. Nodes g fixed by Vg=1 (ideal src) through Rs.
sp = 1j * 2 * math.pi * fp
Y = [[1e-3 + sp * 1e-9, -1e-3], [-1e-3, 1e-3 + sp * 2e-9]]
Gs, Gl = 1 / 1e3, 1 / 4e3
# (Y + diag(Gs,Gl)) V = [Gs*Vg, 0]
A = [[Y[0][0] + Gs, Y[0][1]], [Y[1][0], Y[1][1] + Gl]]
det = A[0][0] * A[1][1] - A[0][1] * A[1][0]
V1a = (Gs * 1.0 * A[1][1]) / det
V2a = (-A[1][0] * Gs * 1.0) / det
err = max(abs(v1 - V1a) / abs(V1a), abs(v2 - V2a) / abs(V2a))
check("Pi two-port AC: off-diagonal d/e cross-coupling vs analytic MNA", err < 1e-5,
      f"rel err {err:.2e}")

# ============================================================ 4. pre_snp -native
# a known 2-port .s2p (single coupled resonator), fit -> .nport -> reproduce Y
Cc = 0.1e-12
fresn = [1.2e9, 2.4e9]
Cn = [1e-12, 1e-12]
Ln = [1.0 / ((2 * math.pi * fp_) ** 2 * cn_) for fp_, cn_ in zip(fresn, Cn)]
Rn = [8.0, 8.0]


def known_Y(fq):
    s_ = 1j * 2 * math.pi * fq
    Y = [[0j, 0j], [0j, 0j]]
    for i in range(2):
        yb = s_ * Cn[i] / (1 + s_ * Rn[i] * Cn[i] + s_ * s_ * Ln[i] * Cn[i])
        Y[i][i] += yb
    yc = s_ * Cc
    Y[0][0] += yc; Y[1][1] += yc; Y[0][1] -= yc; Y[1][0] -= yc
    return Y


def y_to_s(Y, Z0=50.0):
    a = [[(-Z0 * Y[0][0] + (1 if 0 == 0 else 0)), 0], [0, 0]]
    # S = (I - Z0 Y)(I + Z0 Y)^-1
    ImY = [[1 - Z0 * Y[0][0], -Z0 * Y[0][1]], [-Z0 * Y[1][0], 1 - Z0 * Y[1][1]]]
    IpY = [[1 + Z0 * Y[0][0], Z0 * Y[0][1]], [Z0 * Y[1][0], 1 + Z0 * Y[1][1]]]
    d = IpY[0][0] * IpY[1][1] - IpY[0][1] * IpY[1][0]
    inv = [[IpY[1][1] / d, -IpY[0][1] / d], [-IpY[1][0] / d, IpY[0][0] / d]]
    S = [[ImY[0][0] * inv[0][0] + ImY[0][1] * inv[1][0],
          ImY[0][0] * inv[0][1] + ImY[0][1] * inv[1][1]],
         [ImY[1][0] * inv[0][0] + ImY[1][1] * inv[1][0],
          ImY[1][0] * inv[0][1] + ImY[1][1] * inv[1][1]]]
    return S


with open(os.path.join(HERE, "coupled.s2p"), "w") as f:
    f.write("# HZ S RI R 50\n")
    for k in range(80):
        fq = 0.4e9 + k * (3.6e9 - 0.4e9) / 79
        S = y_to_s(known_Y(fq))
        row = f"{fq:.8e}"
        for i in range(2):
            for j in range(2):
                row += f" {S[i][j].real:.8e} {S[i][j].imag:.8e}"
        f.write(row + "\n")

# pre_snp -native writes coupled.nport (no openvaf-r; just fit + write)
subprocess.run([NGSPICE, "-p"], input="snp -native coupled.s2p\nquit\n",
               cwd=HERE, capture_output=True, text=True, timeout=120)
have_fit = os.path.isfile(os.path.join(HERE, "coupled.nport"))
if have_fit:
    fq = 1.2e9                                # near the first resonance
    snp_ac = f"""* pre_snp -native reload
Iac 0 p1 AC 1
Iac2 0 p2 AC 0
N1 p1 p2 0 cm
.model cm nport(file="coupled.nport")
Rl1 p1 0 1e9
Rl2 p2 0 1e9
.ac lin 1 {fq:g} {fq:g}
.end
"""
    r = run_batch("_snp_ac.cir", snp_ac, "_snp_ac.dat", "v(p1) v(p2)")
    # inject 1A into p1 only: V = Yinv * [1,0] -> V1 = Yinv00, V2 = Yinv10
    Y = known_Y(fq)
    d = Y[0][0] * Y[1][1] - Y[0][1] * Y[1][0]
    V1a, V2a = Y[1][1] / d, -Y[1][0] / d
    v1 = r[0][1] + 1j * r[0][2]
    v2 = r[0][4] + 1j * r[0][5]
    err = max(abs(v1 - V1a) / abs(V1a), abs(v2 - V2a) / abs(V2a))
    check("pre_snp -native: fit .s2p -> .nport reproduces the known 2-port Y",
          err < 1e-3, f"rel err {err:.2e}")
else:
    check("pre_snp -native: fit .s2p -> .nport reproduces the known 2-port Y",
          False, "coupled.nport not produced")

# =================================================================== 5. scaling
# N=20, 3 shared complex modes (6 poles), FULL-RANK symmetric residues.
N = 20
M = 3
import random
random.seed(7)
fresM = [0.8e9 + m * (3.2e9 - 0.8e9) / (M - 1) for m in range(M)]
Qm = 15.0
polesN = []
Rm = []
for m in range(M):
    w = 2 * math.pi * fresM[m]
    polesN += [(-w / (2 * Qm), w), (-w / (2 * Qm), -w)]
    A = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(i, N):
            v = random.gauss(0, 1) * 2e-4 / math.sqrt(N) * w
            A[i][j] = A[j][i] = v
    Rm.append(A)
dN = [0.0] * (N * N)
eN = [0.0] * (N * N)
for i in range(N):
    dN[i * N + i] = 1e-3
    eN[i * N + i] = 2e-13
resN = {}
for i in range(N):
    for j in range(N):
        lst = []
        for m in range(M):
            lst.append((Rm[m][i][j], 0.0))         # residue for pole p_m
            lst.append((Rm[m][i][j], 0.0))         # for conj(p_m): conj of a real is itself
        resN[(i, j)] = lst
write_nport("big20.nport", N, polesN, dN, eN, resN)


def Y20(fq):
    s_ = 1j * 2 * math.pi * fq
    Y = [[0j] * N for _ in range(N)]
    for i in range(N):
        Y[i][i] += 1e-3 + s_ * 2e-13
        for j in range(N):
            for m in range(M):
                pr, pi = polesN[2 * m]
                pp = complex(pr, pi)
                Y[i][j] += Rm[m][i][j] / (s_ - pp) + Rm[m][i][j] / (s_ - pp.conjugate())
    return Y


fq = 1.0e9
ports = " ".join(f"p{i+1}" for i in range(N))
deck = [f"* nport scaling N={N}", "Iac 0 p1 AC 1",
        f"N1 {ports} 0 bigm", '.model bigm nport(file="big20.nport")']
deck += [f"R{i+1} p{i+1} 0 50" for i in range(N)]
deck += [f".ac lin 1 {fq:g} {fq:g}", ".end"]
saves = " ".join(f"v(p{i+1})" for i in range(N))
r = run_batch("_big20.cir", "\n".join(deck) + "\n", "_big20.dat", saves)
Vng = [r[0][3 * i + 1] + 1j * r[0][3 * i + 2] for i in range(N)]
# analytic: (Y + 0.02 I) V = e1  -> solve by Gaussian elimination
Y = Y20(fq)
A = [[Y[i][j] + (0.02 if i == j else 0) for j in range(N)] for i in range(N)]
rhs = [1.0 + 0j if i == 0 else 0j for i in range(N)]
for col in range(N):
    piv = max(range(col, N), key=lambda rr: abs(A[rr][col]))
    A[col], A[piv] = A[piv], A[col]
    rhs[col], rhs[piv] = rhs[piv], rhs[col]
    for rr in range(N):
        if rr != col:
            f_ = A[rr][col] / A[col][col]
            for cc in range(col, N):
                A[rr][cc] -= f_ * A[col][cc]
            rhs[rr] -= f_ * rhs[col]
Va = [rhs[i] / A[i][i] for i in range(N)]
mx = max(abs(v) for v in Va)
err = max(abs(Vng[i] - Va[i]) for i in range(N)) / mx
check(f"scaling N={N}: full N-port stamp (6 poles, full-rank) vs analytic solve",
      err < 1e-6, f"max rel err {err:.2e}")

# ------------------------------------------------------------------ tidy temps
# Every deck / data file / fit fixture is regenerated on each run, so leave the
# committed directory as just this script + README.
for f in os.listdir(HERE):
    if (f.startswith("_") and (f.endswith(".cir") or f.endswith(".dat"))) or \
       f.endswith(".nport") or f in ("coupled.s2p",):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
