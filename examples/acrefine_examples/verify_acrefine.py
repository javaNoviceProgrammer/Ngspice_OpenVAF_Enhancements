#!/usr/bin/env python3
"""verify_acrefine.py -- Enhancement-860: one step of iterative refinement after
the ac solve.

F5 of the third robustness campaign of 2026-10-10.

The ac factorization takes a pivot down to pivrel (1e-3) of its column's largest
entry, and Sparse orders the matrix at the first frequency only. On inductive
networks at a few hertz -- a 1 nH branch row carries jwL ~ 1e-8 beside entries
of order 1 -- that cost up to 6 digits on matrices of condition 5: 22 of 300
networks under Sparse (3.4e-6), 5 under KLU (2e-7), where any backward-stable
solve gives 1e-15. After the solve the residual b - A x now gives the
componentwise backward error, and where that is above rounding, A d = r is
solved with the same factors and x + d kept if it is better.

The five networks are the campaign's worst (scratchpad rc3/ac.py, AC_LOWF),
swept as it swept them; the reference is the exact complex MNA solve at each
of ngspice's frequencies.

  [1] 5025, 3.4e-6 under Sparse on E-859: to 1e-12
  [2] 5043, 5210, 5049 (Sparse 2e-7 to 3e-7, KLU 2e-7 on E-859): to 1e-12
  [3] 5035 (KLU 4.9e-8 on E-859): to 1e-12
  [4] (control) a well-conditioned RLC ladder: to 1e-13

Exit code 0 = pass.
"""
import cmath
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="acrefine_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


# seed: (nodes, f0, f1, netlist)
NETS = {
    5025: (5, 0.18458735904708334, 18.45063788274751, 'r0 1 0 215.1076967869165\nr1 2 0 890.7970439721755\nr2 3 0 753592.7099301822\nr3 4 0 774875.1833013502\nr4 5 0 19586.439175814925\nr5 0 2 28513.428499883645\nr6 2 4 23.898069797766187\nr7 3 2 277.82377474889256\nr8 4 1 2560.6613600958167\nr9 1 3 2500.3751364189293\nc10 4 0 2.7633890308248987e-12\nc11 2 3 1.5226273661037345e-13\nc12 1 3 1.860922098726546e-11\nl13 0 3 1.3488137973981875e-08\nl14 2 4 2.677111771591458e-09\nl15 0 4 4.638629213474823e-09\nl16 1 4 0.0002682684708437572\ni17 3 2 dc 0 ac 0.009174352842351803 25.740228704205293\nvs18 5 1 dc 0'),
    5043: (5, 0.21685713900626474, 174.6855717804958, 'r0 1 0 7459.071598490593\nr1 2 0 18655.093568178905\nr2 3 0 650.692280280151\nr3 4 0 115538.52487199283\nr4 5 0 3726.4787478449034\nr5 2 5 291.1020070008334\nr6 2 3 24.081443763311977\nr7 2 5 111.76397226230254\nr8 0 1 115.16971709423237\nr9 1 4 20753.634837979323\nc10 1 3 1.1607395003623624e-11\nc11 3 5 6.569647494356434e-08\nl12 5 0 8.756485135481798e-08\nl13 4 1 2.7701561461674575e-09\nl14 2 4 8.913248340498675e-09\nl15 0 1 7.694404384068067e-09\ni16 3 2 dc 0 ac 4.45139879368606e-05 -86.92827337718263\ni17 2 3 dc 0 ac 0.00044200313474908136 126.18480174056623\nvs18 3 1 dc 0\ng19 4 3 2 0 -0.0016262418381801584\nf20 2 3 vs18 0.06345847434852159'),
    5210: (5, 4.745977320365263, 3443.8500488942323, 'r0 1 0 61085.58936017628\nr1 2 0 688239.7790338417\nr2 3 0 2606.978974875307\nr3 4 0 58561.50995128403\nr4 5 0 86467.62693243612\nr5 2 5 8977.637977259888\nr6 5 0 21.64927515221003\nr7 4 1 5549.346412034284\nr8 1 0 135.29101828525106\nr9 2 5 1911.4964436047253\nc10 3 0 2.8097666185812386e-09\nl11 2 3 2.1062127524361573e-09\nl12 2 4 8.502461336866777e-07\nl13 5 0 0.0006997371065056789\nl14 0 1 7.898349234295965e-09\nl15 1 4 1.0855871795650451e-05\nk16 l12 l11 -0.6701462748311181\ni17 1 0 dc 0 ac 0.001 0.0'),
    5049: (3, 0.10351083632815272, 61.86647824417845, 'r0 1 0 1440.0203506749724\nr1 2 0 785.3725962600973\nr2 3 0 314.9180978175844\nr3 3 2 916.7663390449885\nr4 0 1 27.209696242634895\nr5 1 0 2.838132818430782\nc6 0 3 2.3656951538216056e-07\nc7 0 2 1.6649327335210466e-13\nc8 0 3 1.7047991322176637e-11\nl9 1 3 2.7272688375905663e-08\nl10 2 3 9.369433602308649e-05\nl11 1 0 1.3469063375029312e-09\nk12 l9 l10 0.8262411980321753\ni13 1 0 dc 0 ac 0.001 0.0'),
    5035: (3, 0.3076453876207483, 411.37439872523674, 'r0 1 0 1544.8915492219169\nr1 2 0 4748.403099754503\nr2 3 0 486668.0954143678\nr3 1 2 4395.085825217323\nr4 3 2 19.107446077538\nr5 3 2 231.54093782128982\nr6 0 3 54.392996054077976\nr7 1 0 3052.1377925149936\nr8 0 1 50.84054037654858\nr9 1 0 14.250575400880132\nr10 2 3 16123.233335249071\nr11 0 3 2048.9422826398454\nc12 3 0 1.5613404335638044e-13\nl13 3 1 0.00014729953260122998\nl14 3 2 1.2177523726946593e-07\nl15 0 3 2.2498305665080783e-09\nk16 l13 l15 0.33153928753239503\ni17 3 2 dc 0 ac 0.0005535453149748834 -130.9671810181415\ni18 0 3 dc 0 ac 0.0006068915168339676 87.9121545287307'),
}


def exact(N, text, f):
    """node voltages 1..N at frequency f: the complex MNA of R C L K V I E F G H"""
    els = [l.split() for l in text.splitlines() if l.strip()]
    w = 2 * math.pi * f
    br = {}
    for e in els:
        if e[0][0] in "vleh":
            br[e[0]] = N + len(br)
    M = N + len(br)
    A = np.zeros((M + 1, M + 1), complex)
    z = np.zeros(M + 1, complex)
    def idx(n):
        n = int(n)
        return n - 1 if n > 0 else M
    def g(a, b, y):
        for p, q, s in ((a, a, 1), (b, b, 1), (a, b, -1), (b, a, -1)):
            A[idx(p), idx(q)] += s * y
    val = {e[0]: float(e[-1]) for e in els if e[0][0] in "rcl"}
    for e in els:
        k, name = e[0][0], e[0]
        if k == "r":
            g(e[1], e[2], 1 / float(e[3]))
        elif k == "c":
            g(e[1], e[2], 1j * w * float(e[3]))
        elif k == "i":
            I = float(e[6]) * cmath.exp(1j * math.radians(float(e[7]))) if len(e) > 6 else 0
            z[idx(e[1])] -= I
            z[idx(e[2])] += I
        elif k == "g":
            a, b, c, d, v = e[1], e[2], e[3], e[4], float(e[5])
            for p, s1 in ((a, 1), (b, -1)):
                for q, s2 in ((c, 1), (d, -1)):
                    A[idx(p), idx(q)] += s1 * s2 * v
        if name in br:
            r = br[name]
            a, b = e[1], e[2]
            A[idx(a), r] += 1
            A[idx(b), r] -= 1
            A[r, idx(a)] += 1
            A[r, idx(b)] -= 1
            if k == "v":
                if "ac" in e:
                    i = e.index("ac")
                    z[r] = float(e[i + 1]) * cmath.exp(1j * math.radians(float(e[i + 2])))
            elif k == "l":
                A[r, r] -= 1j * w * float(e[3])
            elif k == "e":
                A[r, idx(e[3])] -= float(e[5])
                A[r, idx(e[4])] += float(e[5])
            elif k == "h":
                A[r, br[e[3]]] -= float(e[4])
    for e in els:
        k = e[0][0]
        if k == "k":
            m = float(e[3]) * math.sqrt(val[e[1]] * val[e[2]])
            A[br[e[1]], br[e[2]]] -= 1j * w * m
            A[br[e[2]], br[e[1]]] -= 1j * w * m
        elif k == "f":
            r = br[e[3]]
            A[idx(e[1]), r] += float(e[4])
            A[idx(e[2]), r] -= float(e[4])
    return np.linalg.solve(A[:M, :M], z[:M])[:N]


def worst_error(seed, N, f0, f1, text):
    out = os.path.join(WORK, "o%d.txt" % seed)
    deck = os.path.join(WORK, "d%d.cir" % seed)
    vecs = " ".join("v(%d)" % n for n in range(1, N + 1))
    with open(deck, "w") as f:
        f.write("* ac %d\n%s\n.control\nset numdgt=17\nset wr_singlescale\nac dec 7 %r %r\nwrdata %s %s\n"
                ".endc\n.end\n" % (seed, text, f0, f1, out, vecs))
    subprocess.run([NGSPICE, "-b", deck], cwd=WORK, capture_output=True, text=True, timeout=120)
    if not os.path.exists(out):
        return None, 0
    worst, pts = 0.0, 0
    for line in open(out):
        v = line.split()
        if len(v) < 1 + 2 * N:
            continue
        try:
            row = [float(t) for t in v]
        except ValueError:
            continue
        ex = exact(N, text, row[0])
        ng = np.array([complex(row[1 + 2 * k], row[2 + 2 * k]) for k in range(N)])
        worst = max(worst, float(np.max(np.abs(ng - ex)) / np.max(np.abs(ex))))
        pts += 1
    return worst, pts


res = {s: worst_error(s, *NETS[s]) for s in NETS}


def line(seeds):
    return "; ".join("%d: %s over %d points" % (s, "%.2g" % res[s][0] if res[s][0] is not None else "no run",
                                                  res[s][1]) for s in seeds)


ok = lambda s: res[s][0] is not None and res[s][1] > 0 and res[s][0] < 1e-12

# [1]
check("[1] network 5025 (3.4e-6 under Sparse on E-859) to 1e-12 of the exact solve", ok(5025), line([5025]))

# [2]
check("[2] networks 5043, 5210, 5049 to 1e-12", all(ok(s) for s in (5043, 5210, 5049)), line([5043, 5210, 5049]))

# [3]
check("[3] network 5035 (KLU 4.9e-8 on E-859) to 1e-12", ok(5035), line([5035]))

# [4]
LADDER = "\n".join(["v0 1 0 dc 0 ac 1 0"] +
                    ["r%d %d %d 50" % (i, i + 1, i + 2) for i in range(8)] +
                    ["c%d %d 0 1e-9" % (i, i + 2) for i in range(8)] +
                    ["l%d %d 0 1e-6" % (i, i + 2) for i in range(0, 8, 3)])
w, n = worst_error(1, 9, 1e3, 1e9, LADDER)
check("[4] (control) a well-conditioned RLC ladder to 1e-13", w is not None and n > 0 and w < 1e-13,
      "%.2g over %d points" % (w if w is not None else -1, n))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
