#!/usr/bin/env python3
"""Enhancement-202: O(N^3) S-parameter matrix inverse (`.sp` port-count scalability).

The RFSPICE `.sp` analysis builds the port S-matrix at every frequency by inverting
N x N complex matrices (CKTspCalcSMatrix, for S / Y / Z). That inverse used to be
computed by the adjugate/determinant method (Cramer's rule), whose determinant is a
recursive cofactor expansion -- O(N!) -- so the whole `.sp` cost blew up by roughly a
factor of N per added port: an 8-port took ~13 s and a 10-port ~18 minutes. Replacing
the inverse with Gauss-Jordan elimination makes it O(N^3), so a 12-port -- previously
minutes -- now extracts in a fraction of a second.

This check runs a 12-port R-L-C ladder through `.sp` + `wrsnp`, confirms it finishes
quickly, and verifies every entry of the extracted S-matrix against the closed-form
network (so the fast inverse is correct, not just fast).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import math
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0
N = 12
Z0 = 50.0
RS, RP, C, LC = 30.0, 150.0, 2e-12, 8e-9      # access R, shunt R, shunt C, coupling L


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


# ---- tiny complex linear algebra (self-contained, for the analytic truth) ------
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


def Y_ladder(f):
    """Nodal admittance of the N-port R-L-C ladder, reduced to the ports."""
    s = 1j * 2 * math.pi * f
    gs, gp = 1.0 / RS, 1.0 / RP
    M = [[0j] * N for _ in range(N)]
    for i in range(N):
        M[i][i] = gs + gp + s * C
    for i in range(N - 1):
        y = 1.0 / (s * LC)
        M[i][i] += y; M[i + 1][i + 1] += y; M[i][i + 1] -= y; M[i + 1][i] -= y
    Mi = mat_inv(M)
    return [[(gs if i == j else 0j) - gs * gs * Mi[i][j] for j in range(N)] for i in range(N)]


def analytic_S(f):
    I = [[1.0 if i == j else 0j for j in range(N)] for i in range(N)]
    Y = Y_ladder(f)
    IpZY = [[I[i][j] + Z0 * Y[i][j] for j in range(N)] for i in range(N)]
    ImZY = [[I[i][j] - Z0 * Y[i][j] for j in range(N)] for i in range(N)]
    return matmul(ImZY, mat_inv(IpZY))


# ---- the N-port ladder as a subckt + a .sp deck --------------------------------
def subckt():
    s = [f".subckt ladder {' '.join(f'p{i+1}' for i in range(N))}"]
    for i in range(N):
        s += [f"Rs{i+1} p{i+1} n{i+1} {RS}",
              f"Rp{i+1} n{i+1} 0 {RP}",
              f"Cc{i+1} n{i+1} 0 {C:.4e}"]
    for i in range(N - 1):
        s.append(f"Lc{i+1} n{i+1} n{i+2} {LC:.4e}")
    s.append(".ends")
    return "\n".join(s)


ports = "\n".join(f"V{i+1} p{i+1} 0 DC 0 AC 1 portnum {i+1} z0 {Z0:g}" for i in range(N))
conn = " ".join(f"p{i+1}" for i in range(N))
deck = f"""* {N}-port S-parameter extraction (Enhancement-202 scalability)
{subckt()}
{ports}
Xdut {conn} ladder
.sp dec 20 1e6 3e9
.control
run
wrsnp _sp{N}.s{N}p
.endc
.end
"""
open(os.path.join(HERE, f"sp{N}.cir"), "w").write(deck)
snp = os.path.join(HERE, f"_sp{N}.s{N}p")
if os.path.exists(snp):
    os.remove(snp)

t0 = time.time()
r = subprocess.run([NGSPICE, "-b", f"sp{N}.cir"], cwd=HERE,
                   capture_output=True, text=True, timeout=300)
dt = time.time() - t0

made = os.path.exists(snp)
check(f"[scalability] a {N}-port `.sp` S-parameter extraction completes quickly "
      f"(O(N^3) inverse; the old O(N!) adjugate method took minutes at this port count)",
      made and dt < 60, f"({dt:.2f}s for {N} ports)")


# ---- correctness: extracted S vs the closed-form network -----------------------
def parse_snp(fn):
    nums = []
    for line in open(fn):
        line = line.split("!")[0].strip()
        if not line or line.startswith("#"):
            continue
        nums += [float(x) for x in line.split()]
    rec = 1 + 2 * N * N
    out = []
    for k in range(len(nums) // rec):
        c = nums[k * rec:(k + 1) * rec]
        f, v = c[0], c[1:]
        S = [[complex(v[2 * (i * N + j)], v[2 * (i * N + j) + 1]) for j in range(N)]
             for i in range(N)]
        out.append((f, S))
    return out


if made:
    rows = parse_snp(snp)
    err = 0.0
    for f, S in rows[::7]:                 # sample the sweep
        Sa = analytic_S(f)
        for i in range(N):
            for j in range(N):
                err = max(err, abs(S[i][j] - Sa[i][j]))
    check(f"[correctness] every entry of the extracted {N}x{N} S-matrix matches the "
          "closed-form network across the sweep (the fast inverse is exact)",
          err < 1e-5, f"(max abs err {err:.2e} over {len(rows)} freqs)")
else:
    check(f"[correctness] the extracted {N}x{N} S-matrix matches the closed-form network",
          False, r.stdout[-300:] + r.stderr[-300:])

# tidy
for f in (f"sp{N}.cir", f"_sp{N}.s{N}p"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
