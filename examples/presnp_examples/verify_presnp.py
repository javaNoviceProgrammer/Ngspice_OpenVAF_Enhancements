#!/usr/bin/env python3
"""Enhancement-200: the built-in `pre_snp` command.

Enhancement-199 shipped `snp2va.py`, a standalone Python converter that turns a
Touchstone `.sNp` S-parameter file into a Verilog-A n-port model. Enhancement-200
folds that converter into ngspice itself as a C command, `pre_snp`, so no external
script (and no Python) is needed: inside a `.control` block

    pre_snp myblock.s2p          <- parse .s2p -> vector-fit -> write myblock.va,
                                     then invoke openvaf-r -> write myblock.osdi
    pre_osdi myblock.osdi        <- load the freshly compiled n-port model

`pre_snp` is a `pre_` command like `pre_osdi`, so it runs *before* the circuit is
parsed. Crucially, every `pre_snp` is forced to run before every other `pre_`
command (notably `pre_osdi`) regardless of deck order, so the `.osdi` it generates
already exists when `pre_osdi` loads it -- the two lines can even appear in the
"wrong" order.

The converter finds `openvaf-r` via (in order) the `openvaf` ngspice variable, the
`OPENVAF` environment variable, `$SPICE_LIB_DIR/openvaf-r`, then `PATH`. This script
exports `OPENVAF` so the committed / locally-built compiler is used.

The checks build a Touchstone file from a network whose response is known exactly,
let `pre_snp` do the whole convert+compile+load inside ngspice, and confirm the
resulting device matches the ORIGINAL network in AC and transient. One check runs
with `pre_osdi` listed BEFORE `pre_snp` to prove the ordering guarantee.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import math
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

passed = failed = 0
Z0 = 50.0

# ngspice's pre_snp locates the compiler through these; make sure it finds ours.
ENV = dict(os.environ)
ENV["OPENVAF"] = OPENVAF


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


def run(deck):
    open(os.path.join(HERE, "_t.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_t.cir"], capture_output=True, text=True,
                       cwd=HERE, timeout=180, env=ENV)
    rows = []
    p = os.path.join(HERE, "_o.dat")
    if os.path.exists(p):
        for l in open(p):
            q = l.split()
            if q and q[0].lstrip("-")[0].isdigit():
                rows.append([float(x) for x in q])
        os.remove(p)
    return rows, r.stdout + r.stderr


def cleanup(*names):
    for f in names:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)


# ================= 2-port resonant R-L-C =================
# Same series-R-L-C with shunt caps as the E-199 truth network: a transmission
# peak the fit must reproduce. pre_snp does convert+compile+load in one command.
Rr, Lr, Cr, Csh = 5.0, 1e-7, 1e-11, 5e-13


def Y2(f):
    s = 1j * 2 * math.pi * f
    ys = 1.0 / (Rr + s * Lr + 1.0 / (s * Cr))
    return [[s * Csh + ys, -ys], [-ys, s * Csh + ys]]


freqs2 = [10 ** (5 + 4 * k / 300) for k in range(301)]      # 100 kHz .. 1 GHz
write_snp(os.path.join(HERE, "resonator.s2p"), freqs2, Y2, 2)

# The original network, built from discretes, for the reference response.
ACT2 = ("Rser p1 a 5\nL1 a b 1e-7\nCser b p2 1e-11\n"
        "Csh1 p1 0 5e-13\nCsh2 p2 0 5e-13\n")
# The pre_snp device: no snp2va.py, no pre-generated .va/.osdi -- pre_snp makes them.
NP2 = "N1 p1 p2 mm\n.model mm rez\n"


def two_port_ac(dut, presnp=False, swap=False):
    if presnp:
        pre = ("pre_osdi resonator.osdi\npre_snp resonator.s2p rez" if swap
               else "pre_snp resonator.s2p rez\npre_osdi resonator.osdi")
    else:
        pre = ""
    return run(f"""* 2-port AC
Vs in 0 dc 0 ac 1
Rs in p1 50
{dut}Rl p2 0 50
.control
{pre}
ac dec 40 1e5 1e9
wrdata _o.dat v(p2)
.endc
.end
""")


cleanup("resonator.va", "resonator.osdi")
ra, _ = two_port_ac(ACT2)
rn, out = two_port_ac(NP2, presnp=True)

made_va = os.path.exists(os.path.join(HERE, "resonator.va"))
made_osdi = os.path.exists(os.path.join(HERE, "resonator.osdi"))
check("[command] `pre_snp` reads the .s2p, vector-fits it, writes the .va, and "
      "compiles it to .osdi -- all inside ngspice", made_va and made_osdi,
      f"(.va {'ok' if made_va else 'MISSING'}, .osdi {'ok' if made_osdi else 'MISSING'})")


def relerr(a, b):
    m = min(len(a), len(b))
    def cx(r):
        return complex(r[1], r[2])
    return max(abs(cx(b[k]) - cx(a[k])) / (abs(cx(a[k])) + 1e-30) for k in range(m)) \
        if m else 1e9


if ra and rn:
    err = relerr(ra, rn)
    check("[ac] the pre_snp device matches the original R-L-C resonator in AC "
          "(incl. the transmission peak)", err < 2e-3, f"(max rel err {err:.2e})")
else:
    check("[ac] the pre_snp device matches the original R-L-C resonator in AC", False,
          out[-300:])


# ================= ordering guarantee: pre_osdi listed BEFORE pre_snp =============
# The deck writes pre_osdi first; pre_snp must still run first so the .osdi exists.
cleanup("resonator.va", "resonator.osdi")
rs, out_s = two_port_ac(NP2, presnp=True, swap=True)
if ra and rs:
    errs = relerr(ra, rs)
    ok = errs < 2e-3 and "could not be loaded" not in out_s.lower() \
        and "can't open" not in out_s.lower()
    check("[ordering] with `pre_osdi` written BEFORE `pre_snp`, pre_snp still runs "
          "first (the .osdi it makes is already there for pre_osdi)", ok,
          f"(max rel err {errs:.2e})")
else:
    check("[ordering] pre_osdi before pre_snp still works", False, out_s[-300:])


# ================= transient (one model, AC + transient) =========================
def two_port_tran(dut, presnp=False):
    pre = "pre_snp resonator.s2p rez\npre_osdi resonator.osdi" if presnp else ""
    return run(f"""* 2-port transient
Vs in 0 pulse(0 1 5n 0.2n 0.2n 40n 80n)
Rs in p1 50
{dut}Rl p2 0 50
.control
{pre}
tran 0.1n 120n
wrdata _o.dat v(p2)
.endc
.end
""")


cleanup("resonator.va", "resonator.osdi")
ta, _ = two_port_tran(ACT2)
tn, out_t = two_port_tran(NP2, presnp=True)
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
    check("[transient] the same pre_snp model matches the resonator's transient step "
          "response (AC + transient from one compiled block)", err < 5e-3,
          f"(max err {err:.2e} of peak {amp:.3f})")
else:
    check("[transient] the pre_snp model matches the resonator's transient response",
          False, out_t[-300:])


# ================= 3-port (N-port generalization through pre_snp) =================
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
ACT3 = "Rp1 p1 c 10\nRp2 p2 c 20\nRp3 p3 c 30\nCc c 0 1p\n"
NP3 = "N1 p1 p2 p3 ms\n.model ms star3\n"


def three_port(dut, presnp=False):
    pre = "pre_snp star.s3p star3\npre_osdi star.osdi" if presnp else ""
    return run(f"""* 3-port AC
Vs in 0 dc 0 ac 1
Rs in p1 50
{dut}Rl2 p2 0 50
Rl3 p3 0 50
.control
{pre}
ac dec 30 1meg 1g
wrdata _o.dat v(p2) v(p3)
.endc
.end
""")


cleanup("star.va", "star.osdi")
a3, _ = three_port(ACT3)
n3, out3 = three_port(NP3, presnp=True)
if a3 and n3:
    m = min(len(a3), len(n3))
    e2 = max(abs(complex(n3[k][1], n3[k][2]) - complex(a3[k][1], a3[k][2]))
             / (abs(complex(a3[k][1], a3[k][2])) + 1e-30) for k in range(m))
    e3 = max(abs(complex(n3[k][4], n3[k][5]) - complex(a3[k][4], a3[k][5]))
             / (abs(complex(a3[k][4], a3[k][5])) + 1e-30) for k in range(m))
    check("[nport] `pre_snp` on a 3-port .s3p compiles and matches the original star "
          "network (both coupled outputs)", e2 < 2e-3 and e3 < 2e-3,
          f"(v(p2) {e2:.2e}, v(p3) {e3:.2e})")
else:
    check("[nport] pre_snp on a 3-port .s3p matches the original star network", False,
          out3[-300:])


# ============= higher-order coupled ladder (guards two order/realization bugs) ==
# A 4-port R-L-C ladder (port -> Rs -> node with Rp||C shunt, adjacent nodes
# coupled by L) whose fit must CLIMB past two pole orders, and whose independently
# fitted improper (e*s) terms form an *indefinite* capacitance matrix. This case
# exercises two failure modes the 2-pole checks above never reach:
#   * order selection: a double-free during the climb (crashed pre_snp for any fit
#     needing >=3 pole orders), and
#   * realization: the OSDI model diverging in transient (v -> ~1e284) from the
#     non-passive e-matrix, even though DC/AC are exact.
# Both must now compile, stay BOUNDED, and match the original ladder in transient.
def Ylad4(f):
    s = 1j * 2 * math.pi * f
    n = 4
    gs, gp, Csh, Lc = 1/30.0, 1/150.0, 2e-12, 8e-9   # noqa: E741  (Csh/Lc physical)
    M = [[0j]*n for _ in range(n)]
    for i in range(n):
        M[i][i] = gs + gp + s*Csh
    for i in range(n-1):
        y = 1.0/(s*Lc)
        M[i][i] += y; M[i+1][i+1] += y; M[i][i+1] -= y; M[i+1][i] -= y
    Mi = mat_inv(M)
    return [[(gs if i == j else 0j) - gs*gs*Mi[i][j] for j in range(n)] for i in range(n)]


freqsL4 = [10 ** (6 + 3.5 * k / 160) for k in range(161)]      # 1 MHz .. ~3.2 GHz
write_snp(os.path.join(HERE, "ladder4.s4p"), freqsL4, Ylad4, 4)
LADSUB = ("Rs1 p1 na 30\nRp1 na 0 150\nCa na 0 2e-12\n"
          "Rs2 p2 nb 30\nRp2 nb 0 150\nCb nb 0 2e-12\n"
          "Rs3 p3 nc 30\nRp3 nc 0 150\nCcc nc 0 2e-12\n"
          "Rs4 p4 nd 30\nRp4 nd 0 150\nCd nd 0 2e-12\n"
          "La na nb 8e-9\nLb nb nc 8e-9\nLcc nc nd 8e-9\n")
NPL4 = "N1 p1 p2 p3 p4 mm\n.model mm lad4\n"


def lad_tran(dut, presnp=False):
    pre = "pre_snp ladder4.s4p lad4\npre_osdi ladder4.osdi" if presnp else ""
    return run(f"""* 4-port ladder transient
Vs in 0 pulse(0 1 1n 0.1n 0.1n 4n 8n)
Rs in p1 50
{dut}Rl2 p2 0 50
Rl3 p3 0 50
Rl4 p4 0 50
.control
{pre}
tran 0.02n 12n
wrdata _o.dat v(p2) v(p3)
.endc
.end
""")


cleanup("ladder4.va", "ladder4.osdi")
la4, _ = lad_tran(LADSUB)                       # discrete reference
ln4, outl = lad_tran(NPL4, presnp=True)         # the pre_snp OSDI model
made_l = os.path.exists(os.path.join(HERE, "ladder4.osdi"))
check("[order] `pre_snp` compiles a 4-port coupled ladder whose fit climbs past two "
      "pole orders (order-selection buffer reuse would double-free before the fix)",
      made_l, "(.osdi ok)" if made_l else "(.osdi MISSING -- pre_snp crashed)")

if la4 and ln4:
    import bisect
    # wrdata real: 2 cols per vector -> v(p2)=col 1, scale=col 0
    tt = [r[0] for r in ln4]; vv = [r[1] for r in ln4]

    def itp(t):
        i = bisect.bisect(tt, t); i = max(1, min(i, len(tt)-1))
        if tt[i] == tt[i-1]:
            return vv[i]
        w = (t - tt[i-1])/(tt[i] - tt[i-1])
        return vv[i-1] + w*(vv[i] - vv[i-1])
    pk_ref = max(abs(r[1]) for r in la4)
    pk_osd = max(abs(r[1]) for r in ln4)
    errL = max(abs(itp(r[0]) - r[1]) for r in la4) / (pk_ref + 1e-30)
    check("[realization] the 4-port pre_snp model stays BOUNDED and matches the ladder "
          "in transient (indefinite e-matrix diverged to ~1e284 before the fix)",
          pk_osd < 5*pk_ref and errL < 5e-2,
          f"(peak osdi {pk_osd:.3f} vs ref {pk_ref:.3f}, max err {errL:.2e})")
else:
    check("[realization] the 4-port pre_snp model stays bounded and matches in transient",
          False, outl[-300:])


# ============= scalability: fast fit + shared realization at 8 ports ============
# An 8-port coupled ladder -- the size the original converter struggled at (its
# pole solve stacked all N^2 elements into one dense least-squares: ~190 s and an
# O(N^4)-memory matrix). The fast (block-reduced) vector fit, reciprocity (fit the
# symmetric upper triangle only), and the shared-pole realization (filter each
# input port once, O(N*Np) laplace_nd instead of O(N^2*Np)) bring it down to a few
# seconds and a compact model. This checks that an 8-port converts+compiles and
# that the shared-realization device matches the original network in AC.
import time
def Yladn(f, n):
    s = 1j * 2 * math.pi * f
    gs, gp, Csh, Lc = 1/30.0, 1/150.0, 2e-12, 8e-9   # noqa: E741
    M = [[0j]*n for _ in range(n)]
    for i in range(n):
        M[i][i] = gs + gp + s*Csh
    for i in range(n-1):
        y = 1.0/(s*Lc)
        M[i][i] += y; M[i+1][i+1] += y; M[i][i+1] -= y; M[i+1][i] -= y
    Mi = mat_inv(M)
    return [[(gs if i == j else 0j) - gs*gs*Mi[i][j] for j in range(n)] for i in range(n)]


NB = 8
NODES = "abcdefgh"
freqsL8 = [10 ** (6 + 3.5 * k / 140) for k in range(141)]
write_snp(os.path.join(HERE, "ladder8.s8p"), freqsL8, lambda f: Yladn(f, NB), NB)
conn8 = " ".join(f"p{i+1}" for i in range(NB))
loads8 = "".join(f"Rl{i+1} p{i+1} 0 50\n" for i in range(1, NB))


def ladsub8():
    s = ""
    for i in range(NB):
        s += f"Rs{i+1} p{i+1} n{NODES[i]} 30\nRp{i+1} n{NODES[i]} 0 150\nCq{i+1} n{NODES[i]} 0 2e-12\n"
    for i in range(NB-1):
        s += f"Lq{i+1} n{NODES[i]} n{NODES[i+1]} 8e-9\n"
    return s


probes8 = [1, 2, 4, NB]
pr8 = " ".join(f"v(p{i})" for i in probes8)


def ac8(dut, pre=""):
    return run(f"""* 8-port ladder AC
Vs in 0 dc 0 ac 1
Rs in p1 50
{dut}{loads8}.control
{pre}
ac dec 15 1e6 3e9
wrdata _o.dat {pr8}
.endc
.end
""")


cleanup("ladder8.va", "ladder8.osdi")
t0 = time.time()
run("* convert 8-port\nRd 1 0 1k\n.control\npre_snp ladder8.s8p lad8\n.endc\n.end\n")
tconv = time.time() - t0
made8 = os.path.exists(os.path.join(HERE, "ladder8.osdi"))
nlap = sum(l.count("laplace_nd") for l in open(os.path.join(HERE, "ladder8.va"))) if \
    os.path.exists(os.path.join(HERE, "ladder8.va")) else 0
check("[scalability] `pre_snp` converts an 8-port coupled network with the fast "
      "vector fit + shared-pole realization (dense O(N^4) pole solve took ~190s before)",
      made8, f"(convert+compile {tconv:.1f}s, {nlap} laplace_nd for {NB} ports)")

a8, _ = ac8(ladsub8())
n8, _ = ac8("N1 " + conn8 + " mm\n.model mm lad8\n", "pre_osdi ladder8.osdi")
if made8 and a8 and n8:
    m = min(len(a8), len(n8))
    e8 = 0.0
    for c in range(len(probes8)):            # wrdata AC: 3 cols/vec -> 1+3c, 2+3c
        ref = [complex(a8[k][1+3*c], a8[k][2+3*c]) for k in range(m)]
        tst = [complex(n8[k][1+3*c], n8[k][2+3*c]) for k in range(m)]
        mx = max(abs(v) for v in ref) + 1e-30
        e8 = max(e8, max(abs(tst[k]-ref[k]) for k in range(m)) / mx)
    check("[scalability] the 8-port shared-realization device matches the original "
          "coupled network in AC across all probed ports", e8 < 5e-2,
          f"(max rel err {e8:.2e})")
else:
    check("[scalability] the 8-port shared-realization device matches in AC", False)


# tidy
cleanup("_t.cir", "resonator.s2p", "resonator.va", "resonator.osdi",
        "star.s3p", "star.va", "star.osdi",
        "ladder4.s4p", "ladder4.va", "ladder4.osdi",
        "ladder8.s8p", "ladder8.va", "ladder8.osdi")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
