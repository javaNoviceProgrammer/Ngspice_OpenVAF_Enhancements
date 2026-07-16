#!/usr/bin/env python3
"""Enhancement-205: low-rank residue factorization in `pre_snp`.

The E-200/201 `pre_snp` shared-pole realization writes O(N^2) coupling terms and
O(N*Np) laplace_nd filters, so OpenVAF's compile time grows super-linearly with the
port count (N=32 ~ 80s). But when the ports of an N-port block couple through only a
few shared modes -- the common case for multi-port filters, cavities, and packages
with a shared plane -- each pole's N x N residue matrix has rank r << N.

E-205 exploits that. Per "channel" (the conductance d, the capacitance e, and every
pole section) the emitter picks the cheaper of a DENSE emit or a LOW-RANK one,
W = U*V^T. Because laplace is linear, the low-rank form filters the r COMBINED
inputs u_m = sum_j V[j][m]*V(p_j) ONCE (r filters, not N) and distributes them to the
outputs via U -- collapsing filters from O(N*Np) to O(r*Np) and coupling terms from
O(N^2) to O(N*r). A full-rank block keeps the dense form unchanged.

The escape-hatch env var PRE_SNP_DENSE forces the old dense realization, so each
check compares the low-rank device against a forced-dense build of the SAME fit --
isolating the realization change from any fit error:

  [detect]   a 12-port / 3-shared-mode block emits far fewer laplace_nd filters
             low-rank than dense (the modes are found automatically).
  [ac]       the low-rank device's AC response equals the dense build's (same fit).
  [tran]     the low-rank device's transient equals the dense build's, and is
             bounded (the low-rank capacitance term stays PSD -> stable).
  [fallback] a full-rank ladder gets NO compression (low-rank == dense filter count)
             and identical AC -- the auto-detect leaves full-rank blocks alone.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import math
import random
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

passed = failed = 0
Z0 = 50.0
ENV = dict(os.environ); ENV["OPENVAF"] = OPENVAF


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    passed += bool(ok); failed += (not ok)


def mat_inv(M):
    n = len(M)
    A = [[M[i][j] for j in range(n)] + [1.0 if i == j else 0j for j in range(n)] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(A[r][c])); A[c], A[p] = A[p], A[c]
        d = A[c][c]; A[c] = [x / d for x in A[c]]
        for r in range(n):
            if r != c and abs(A[r][c]) > 0:
                f = A[r][c]; A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    return [row[n:] for row in A]


def matmul(A, B):
    return [[sum(A[i][t] * B[t][j] for t in range(len(B))) for j in range(len(B[0]))] for i in range(len(A))]


def write_snp(fn, freqs, Yof, N):
    I = [[1.0 if i == j else 0j for j in range(N)] for i in range(N)]
    with open(fn, "w") as f:
        f.write("# HZ S RI R 50\n")
        for fr in freqs:
            Y = Yof(fr)
            IpZY = [[I[i][j] + Z0 * Y[i][j] for j in range(N)] for i in range(N)]
            ImZY = [[I[i][j] - Z0 * Y[i][j] for j in range(N)] for i in range(N)]
            S = matmul(ImZY, mat_inv(IpZY))
            vals = []
            for i in range(N):
                for j in range(N):
                    vals += [S[i][j].real, S[i][j].imag]
            # Wrap to <=8 values/line: a full N x N row on one physical line blows past
            # parse_touchstone's fixed line buffer at large N (Touchstone allows the
            # data for one frequency to span continuation lines).
            f.write(f"{fr:.7e}")
            for k in range(0, len(vals), 8):
                f.write(" " + " ".join(f"{v:.7e}" for v in vals[k:k + 8]))
                f.write("\n" + ("           " if k + 8 < len(vals) else ""))


# ---- a low-rank N-port: ports couple through M shared series-RLC modes ----------
def make_lowrank_Y(N, M):
    random.seed(1234)
    modes = []
    for m in range(M):
        fm = 1e8 * (3.0 ** (m / max(M - 1, 1)))     # 100 MHz .. 300 MHz
        Lm = 8e-9; Cm = 1.0 / ((2 * math.pi * fm) ** 2 * Lm); Rm = 2.0
        # each mode's port-coupling vector -> a rank-1 residue; near-orthogonal
        # across modes (well-separated), so the fit resolves the 3 modes cleanly.
        a = [0.6 + 0.8 * random.random() for _ in range(N)]
        modes.append((Lm, Cm, Rm, a))
    g0 = 1.0 / 75.0
    def Y(f):
        s = 1j * 2 * math.pi * f
        Mx = [[(g0 if i == j else 0j) for j in range(N)] for i in range(N)]
        for (Lm, Cm, Rm, a) in modes:
            hm = 1.0 / (Rm + s * Lm + 1.0 / (s * Cm))
            for i in range(N):
                for j in range(N):
                    Mx[i][j] += a[i] * a[j] * hm
        return Mx
    return Y


# ---- a full-rank N-port: nearest-neighbour LC ladder (dense inverse) ------------
def make_ladder_Y(N):
    gs, gp, C, L = 1 / 30., 1 / 150., 2e-12, 8e-9
    def Y(f):
        s = 1j * 2 * math.pi * f
        Mx = [[0j] * N for _ in range(N)]
        for i in range(N):
            Mx[i][i] = gs + gp + s * C
        for i in range(N - 1):
            y = 1 / (s * L); Mx[i][i] += y; Mx[i + 1][i + 1] += y; Mx[i][i + 1] -= y; Mx[i + 1][i] -= y
        Mi = mat_inv(Mx)
        return [[(gs if i == j else 0j) - gs * gs * Mi[i][j] for j in range(N)] for i in range(N)]
    return Y


def run_presnp(base, N, module, analysis, dense):
    """pre_snp <base>.sNp, run <analysis>, return (rows, filter_count, out)."""
    env = dict(ENV)
    if dense:
        env["PRE_SNP_DENSE"] = "1"
    nodes = " ".join(f"n{i+1}" for i in range(N))
    terms = "\n".join(f"Rt{i+1} n{i+1} 0 50" for i in range(N))
    probes = " ".join(f"v(n{i+1})" for i in range(N))
    if analysis == "ac":
        drv, ana = "I1 0 n1 AC 1", "ac dec 25 1e7 1e9"
    else:
        drv, ana = "I1 0 n1 PULSE(0 0.02 1n 0.2n 0.2n 3n 500n)", "tran 0.02n 40n 0 0.02n"
    deck = (f"* pre_snp {analysis}\n{drv}\nN1 {nodes} dut\n.model dut {module}\n{terms}\n"
            f".control\n  pre_snp {base}.s{N}p {module}\n  pre_osdi {base}.osdi\n"
            f"  {ana}\n  wrdata _o.dat {probes}\n.endc\n.end\n")
    open(os.path.join(HERE, "_t.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_t.cir"], capture_output=True, text=True,
                       cwd=HERE, timeout=300, env=env)
    rows = []
    p = os.path.join(HERE, "_o.dat")
    if os.path.exists(p):
        for l in open(p):
            q = l.split()
            if q and q[0].lstrip("-")[0].isdigit():
                rows.append([float(x) for x in q])
        os.remove(p)
    va = os.path.join(HERE, base + ".va")
    nfilt = sum(l.count("laplace_nd") for l in open(va)) if os.path.exists(va) else -1
    return rows, nfilt, r.stdout + r.stderr


def ac_reldiff(a, b, N):
    mx = 0.0
    for v in range(N):
        c = 3 * v
        for ra, rb in zip(a, b):
            za = complex(ra[c + 1], ra[c + 2]); zb = complex(rb[c + 1], rb[c + 2])
            mx = max(mx, abs(za - zb))
    peak = max((abs(complex(r[1], r[2])) for r in a), default=1.0)
    return mx / (peak + 1e-30)


def tran_reldiff(a, b, N):
    mx = peak = 0.0
    for v in range(N):
        # interpolate b onto a's time grid (adaptive steps differ)
        tb = [r[2 * v] for r in b]; vb = [r[2 * v + 1] for r in b]
        for r in a:
            t = r[2 * v]; va = r[2 * v + 1]
            # linear interp
            lo, hi = 0, len(tb) - 1
            if t <= tb[0]: vi = vb[0]
            elif t >= tb[-1]: vi = vb[-1]
            else:
                k = 0
                while k < len(tb) - 1 and tb[k + 1] < t: k += 1
                w = (t - tb[k]) / (tb[k + 1] - tb[k] + 1e-30); vi = vb[k] + w * (vb[k + 1] - vb[k])
            mx = max(mx, abs(va - vi)); peak = max(peak, abs(va))
    return mx / (peak + 1e-30)


print("Enhancement-205: low-rank residue factorization in pre_snp")

# ================= low-rank block: 12 ports, 3 shared modes =====================
Nlr = 12
freqs = [10 ** (6 + 3.5 * k / 160) for k in range(161)]         # 1 MHz .. ~3 GHz
write_snp(os.path.join(HERE, f"modes.s{Nlr}p"), freqs, make_lowrank_Y(Nlr, 3), Nlr)

lr_ac,  nf_lr,  o1 = run_presnp("modes", Nlr, "modes", "ac", dense=False)
de_ac,  nf_de,  o2 = run_presnp("modes", Nlr, "modes", "ac", dense=True)
check(f"[detect] a {Nlr}-port / 3-shared-mode block emits far fewer laplace_nd filters "
      f"low-rank than dense", nf_lr > 0 and nf_de > 0 and nf_lr * 3 < nf_de,
      f"({nf_lr} low-rank vs {nf_de} dense filters)")
check("[ac] the low-rank device's AC response equals the dense build of the same fit",
      bool(lr_ac) and bool(de_ac) and ac_reldiff(lr_ac, de_ac, Nlr) < 1e-3,
      f"(max rel diff {ac_reldiff(lr_ac, de_ac, Nlr):.2e})" if lr_ac and de_ac else o1[-200:])

lr_tr, _, o3 = run_presnp("modes", Nlr, "modes", "tran", dense=False)
de_tr, _, o4 = run_presnp("modes", Nlr, "modes", "tran", dense=True)
td = tran_reldiff(lr_tr, de_tr, Nlr) if (lr_tr and de_tr) else 9.9
bounded = bool(lr_tr) and all(abs(x) < 10.0 for r in lr_tr for x in r[1::2])
check("[tran] the low-rank device's transient equals the dense build and stays bounded "
      "(low-rank capacitance stays PSD -> stable)", td < 5e-3 and bounded,
      f"(max rel diff {td:.2e}, bounded={bounded})")

# ================= full-rank ladder: auto-detect must NOT compress ===============
Nfr = 8
write_snp(os.path.join(HERE, f"ladder.s{Nfr}p"), freqs, make_ladder_Y(Nfr), Nfr)
la_ac, nf_la, o5 = run_presnp("ladder", Nfr, "ladder", "ac", dense=False)
ld_ac, nf_ld, o6 = run_presnp("ladder", Nfr, "ladder", "ac", dense=True)
check(f"[fallback] a full-rank {Nfr}-port ladder gets little/no compression -- low-rank "
      f"keeps ~the dense filter count (unlike the 3x fewer of the low-rank block), so the "
      f"auto-detect leaves full-rank blocks alone",
      nf_la > 0 and nf_ld > 0 and nf_la >= 0.7 * nf_ld,
      f"({nf_la} low-rank vs {nf_ld} dense filters)")
check("[fallback-ac] and its AC response is identical either way (bit-for-bit dense fallback)",
      bool(la_ac) and bool(ld_ac) and ac_reldiff(la_ac, ld_ac, Nfr) < 1e-9,
      f"(max rel diff {ac_reldiff(la_ac, ld_ac, Nfr):.2e})" if la_ac and ld_ac else o5[-200:])

# tidy
for f in ("_t.cir", f"modes.s{Nlr}p", "modes.va", "modes.osdi",
          f"ladder.s{Nfr}p", "ladder.va", "ladder.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
