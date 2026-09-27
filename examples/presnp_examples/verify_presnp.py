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

Enhancement-741 (Touchstone-import hunt F1, F10, F11): the converter's parser
reads Touchstone 2 -- [Version], [Number of Ports], [Two-Port Data Order],
[Number of Frequencies], a per-port [Reference] (continued over lines), [Matrix
Format] Lower/Upper, [Begin Information]..[End Information], [Network Data],
[Noise Data], [End] -- where before the numbers on the keyword lines entered the
data stream and the fit ran on misaligned frames in silence. A number count that
is not a whole number of frames is refused (a v1 file's noise-parameter rows say
so by name), [Mixed-Mode Order] and a two-port without its data order are refused
by name, a v1 `.yNp`/`.zNp` file counts its ports from the extension (it fell to
the divisor fallback, which answers 1 for every two-port frame) and its Y*R, Z/R
normalization is undone, while a v2 file's Y and Z are absolute. The [E-741]
checks use `pre_snp -native` (the parser is shared with -osdi) and compare each
block against the original network's AC response.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import math
import cmath
import re
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


# Everything this suite writes, in one place. `pre_snp` derives the .va/.osdi --
# and openvaf's per-codegen-unit objects .o/.o1../.o4 -- from the .s?p basename,
# so naming the touchstone file with a leading underscore carries the prefix
# through to every artifact. That matters because the repo's convention is that
# a leading underscore means "generated": without it these were indistinguishable
# from tracked inputs in `git status`, and after an interrupted run they simply
# looked like new source files.
GENERATED = ["_t.cir", "_o.dat"]
for _b, _e in (("_resonator", "s2p"), ("_star", "s3p"),
               ("_ladder4", "s4p"), ("_ladder8", "s8p")):
    GENERATED += [f"{_b}.{_e}", f"{_b}.va", f"{_b}.osdi", f"{_b}.o"]
    GENERATED += [f"{_b}.o{_i}" for _i in range(1, 9)]


for _b, _e in (("_noisy", "s2p"),                                # E-745
               ("_v2ord", "s2p"), ("_v2ref", "s2p"), ("_v2low", "ts"),
               ("_v2noise", "s2p"), ("_v1noise", "s2p"), ("_v1y", "y2p"),
               ("_v1z", "z2p"), ("_v2y", "s2p"), ("_mm", "s2p"),
               ("_noord", "s2p"), ("_nfreq", "s2p")):        # E-741
    GENERATED += [f"{_b}.{_e}", f"{_b}.nport", f"{_b}.va", f"{_b}.osdi"]


def tidy_all():
    cleanup(*GENERATED)


# Registered so an early exception, a failed check that raises, or a Ctrl-C
# still leaves the directory clean -- the old cleanup was the last statement in
# the file and ran only when the suite got that far. The compiler objects were
# never in the list at all.
import atexit                                    # noqa: E402
atexit.register(tidy_all)


# ================= 2-port resonant R-L-C =================
# Same series-R-L-C with shunt caps as the E-199 truth network: a transmission
# peak the fit must reproduce. pre_snp does convert+compile+load in one command.
Rr, Lr, Cr, Csh = 5.0, 1e-7, 1e-11, 5e-13


def Y2(f):
    s = 1j * 2 * math.pi * f
    ys = 1.0 / (Rr + s * Lr + 1.0 / (s * Cr))
    return [[s * Csh + ys, -ys], [-ys, s * Csh + ys]]


freqs2 = [10 ** (5 + 4 * k / 300) for k in range(301)]      # 100 kHz .. 1 GHz
write_snp(os.path.join(HERE, "_resonator.s2p"), freqs2, Y2, 2)

# The original network, built from discretes, for the reference response.
ACT2 = ("Rser p1 a 5\nL1 a b 1e-7\nCser b p2 1e-11\n"
        "Csh1 p1 0 5e-13\nCsh2 p2 0 5e-13\n")
# The pre_snp device: no snp2va.py, no pre-generated .va/.osdi -- pre_snp makes them.
NP2 = "N1 p1 p2 0 mm\n.model mm rez\n"   # E-243: explicit ref terminal (0 = ground)


def two_port_ac(dut, presnp=False, swap=False):
    if presnp:
        pre = ("pre_osdi _resonator.osdi\npre_snp _resonator.s2p rez" if swap
               else "pre_snp _resonator.s2p rez\npre_osdi _resonator.osdi")
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


cleanup("_resonator.va", "_resonator.osdi")
ra, _ = two_port_ac(ACT2)
rn, out = two_port_ac(NP2, presnp=True)

made_va = os.path.exists(os.path.join(HERE, "_resonator.va"))
made_osdi = os.path.exists(os.path.join(HERE, "_resonator.osdi"))
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
cleanup("_resonator.va", "_resonator.osdi")
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
    pre = "pre_snp _resonator.s2p rez\npre_osdi _resonator.osdi" if presnp else ""
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


cleanup("_resonator.va", "_resonator.osdi")
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
write_snp(os.path.join(HERE, "_star.s3p"), freqs3, Y3, 3)
ACT3 = "Rp1 p1 c 10\nRp2 p2 c 20\nRp3 p3 c 30\nCc c 0 1p\n"
NP3 = "N1 p1 p2 p3 0 ms\n.model ms star3\n"   # E-243: explicit ref terminal


def three_port(dut, presnp=False):
    pre = "pre_snp _star.s3p star3\npre_osdi _star.osdi" if presnp else ""
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


cleanup("_star.va", "_star.osdi")
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
write_snp(os.path.join(HERE, "_ladder4.s4p"), freqsL4, Ylad4, 4)
LADSUB = ("Rs1 p1 na 30\nRp1 na 0 150\nCa na 0 2e-12\n"
          "Rs2 p2 nb 30\nRp2 nb 0 150\nCb nb 0 2e-12\n"
          "Rs3 p3 nc 30\nRp3 nc 0 150\nCcc nc 0 2e-12\n"
          "Rs4 p4 nd 30\nRp4 nd 0 150\nCd nd 0 2e-12\n"
          "La na nb 8e-9\nLb nb nc 8e-9\nLcc nc nd 8e-9\n")
NPL4 = "N1 p1 p2 p3 p4 0 mm\n.model mm lad4\n"   # E-243: explicit ref terminal


def lad_tran(dut, presnp=False):
    pre = "pre_snp _ladder4.s4p lad4\npre_osdi _ladder4.osdi" if presnp else ""
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


cleanup("_ladder4.va", "_ladder4.osdi")
la4, _ = lad_tran(LADSUB)                       # discrete reference
ln4, outl = lad_tran(NPL4, presnp=True)         # the pre_snp OSDI model
made_l = os.path.exists(os.path.join(HERE, "_ladder4.osdi"))
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
write_snp(os.path.join(HERE, "_ladder8.s8p"), freqsL8, lambda f: Yladn(f, NB), NB)
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


cleanup("_ladder8.va", "_ladder8.osdi")
t0 = time.time()
run("* convert 8-port\nRd 1 0 1k\n.control\npre_snp _ladder8.s8p lad8\n.endc\n.end\n")
tconv = time.time() - t0
made8 = os.path.exists(os.path.join(HERE, "_ladder8.osdi"))
nlap = sum(l.count("laplace_nd") for l in open(os.path.join(HERE, "_ladder8.va"))) if \
    os.path.exists(os.path.join(HERE, "_ladder8.va")) else 0
check("[scalability] `pre_snp` converts an 8-port coupled network with the fast "
      "vector fit + shared-pole realization (dense O(N^4) pole solve took ~190s before)",
      made8, f"(convert+compile {tconv:.1f}s, {nlap} laplace_nd for {NB} ports)")

a8, _ = ac8(ladsub8())
n8, _ = ac8("N1 " + conn8 + " 0 mm\n.model mm lad8\n", "pre_osdi _ladder8.osdi")   # E-243: +ref
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


# ================= Enhancement-741: Touchstone 2, and the v1 Y/Z forms ===========
# Touchstone-import hunt (2026-09-26) F1, F10, F11. Every file here describes one
# of the networks above, so the block it yields must match `ra` (the resonator's
# own AC rows) or `a3` (the star's) to the fit tolerance the earlier checks use.
# `pre_snp -native` needs no compiler and shares the parser with `-osdi`.

def s_of_y(Y, z):
    """S from Y with real per-port references z[i] (Kurokawa, real z):
    S' = (I - G Y)(I + G Y)^-1 with G = diag(z), S_ij = S'_ij * sqrt(z_j / z_i)."""
    N = len(Y)
    I = [[1.0 if i == j else 0j for j in range(N)] for i in range(N)]
    GY = [[z[i] * Y[i][j] for j in range(N)] for i in range(N)]
    Sp = matmul([[I[i][j] - GY[i][j] for j in range(N)] for i in range(N)],
                mat_inv([[I[i][j] + GY[i][j] for j in range(N)] for i in range(N)]))
    return [[Sp[i][j] * math.sqrt(z[j] / z[i]) for j in range(N)] for i in range(N)]


def ma_pair(c):
    return f"{abs(c):.9e} {math.degrees(cmath.phase(c)):.7f}"


def write_v2(fn, freqs, Yof, N, zref=None, order="12_21", mform="Full", ptype="S",
             noise=False, info=True, nfreq_kw=None, with_order=True, extra=None):
    """A Touchstone 2 file (MA format) of the network Yof: keywords per the
    specification, [Reference] split over two lines, an information block,
    optionally a [Noise Data] section after the network data."""
    z = zref or [Z0] * N
    lines = ["[Version] 2.0", f"# Hz {ptype} MA" + ("" if zref else " R 50"),
             f"[Number of Ports] {N}"]
    if N == 2 and with_order:
        lines.append(f"[Two-Port Data Order] {order}")
    lines.append(f"[Number of Frequencies] {len(freqs) if nfreq_kw is None else nfreq_kw}")
    if noise:
        lines.append("[Number of Noise Frequencies] 2")
    if zref:
        lines.append(f"[Reference] {zref[0]}")
        lines.append("   " + " ".join(str(v) for v in zref[1:]))
    if mform != "Full":
        lines.append(f"[Matrix Format] {mform}")
    if extra:
        lines += extra
    if info:
        lines += ["[Begin Information]", "  1.5 2.5 3.5  numbers that are not data",
                  "[End Information]"]
    lines.append("[Network Data]")
    if mform == "Full":
        idx = [(i, j) for i in range(N) for j in range(N)]
        if N == 2 and order == "21_12":
            idx = [(0, 0), (1, 0), (0, 1), (1, 1)]
    elif mform == "Lower":
        idx = [(i, j) for i in range(N) for j in range(i + 1)]
    else:
        idx = [(i, j) for i in range(N) for j in range(i, N)]
    for fr in freqs:
        Y = Yof(fr)
        M = s_of_y(Y, z) if ptype == "S" else Y          # v2: Y is absolute
        lines.append(f"{fr:.7e} " + " ".join(ma_pair(M[i][j]) for i, j in idx))
    if noise:
        lines += ["[Noise Data]", "1e6 2.0 0.30 20 0.5", "2e6 2.5 0.35 40 0.6"]
    lines.append("[End]")
    open(fn, "w").write("\n".join(lines) + "\n")


def write_v1_yz(fn, freqs, Yof, N, kind):
    """A Touchstone 1 Y or Z file as `wrsnp` writes it: RI, normalized to R
    (Y*R, Z/R), the two-port in the 11 21 12 22 column order."""
    idx = [(0, 0), (1, 0), (0, 1), (1, 1)] if N == 2 else \
        [(i, j) for i in range(N) for j in range(N)]
    with open(fn, "w") as f:
        f.write(f"# Hz {kind} RI R 50\n")
        for fr in freqs:
            Y = Yof(fr)
            if kind == "Y":
                M = [[Y[i][j] * Z0 for j in range(N)] for i in range(N)]
            else:
                Zm = mat_inv(Y)
                M = [[Zm[i][j] / Z0 for j in range(N)] for i in range(N)]
            f.write(f"{fr:.7e} " + " ".join(f"{M[i][j].real:.9e} {M[i][j].imag:.9e}"
                                             for i, j in idx) + "\n")


def native2(fn):
    base = os.path.splitext(fn)[0]
    return run(f"""* 2-port AC, native block from {fn}
Vs in 0 dc 0 ac 1
Rs in p1 50
N1 p1 p2 0 mm
.model mm nport(file="{base}.nport")
Rl p2 0 50
.control
pre_snp -native {fn}
ac dec 40 1e5 1e9
wrdata _o.dat v(p2)
.endc
.end
""")


def native3(fn):
    base = os.path.splitext(fn)[0]
    return run(f"""* 3-port AC, native block from {fn}
Vs in 0 dc 0 ac 1
Rs in p1 50
N1 p1 p2 p3 0 ms
.model ms nport(file="{base}.nport")
Rl2 p2 0 50
Rl3 p3 0 50
.control
pre_snp -native {fn}
ac dec 30 1meg 1g
wrdata _o.dat v(p2) v(p3)
.endc
.end
""")


def refusal(fn):
    _, out = run(f"""* pre_snp refusal of {fn}
R1 a 0 1
V1 a 0 1
.control
pre_snp -native {fn}
.endc
.end
""")
    return out


def err2(rows, out, label):
    if ra and rows:
        e = relerr(ra, rows)
        check(label, e < 2e-3, f"(max rel err {e:.2e})")
    else:
        check(label, False, out[-300:])


# [E-741a] v2, 12_21 order, [Reference] over two lines, an information block
write_v2(os.path.join(HERE, "_v2ord.s2p"), freqs2, Y2, 2, zref=[50.0, 50.0])
r, o = native2("_v2ord.s2p")
err2(r, o, "[E-741a] a Touchstone 2 two-port ([Version], [Number of Ports], "
     "[Two-Port Data Order] 12_21, [Reference] over two lines, an information "
     "block) matches the original resonator in AC")

# [E-741b] per-port [Reference] 50 75: the S-matrix changes, the block must not
write_v2(os.path.join(HERE, "_v2ref.s2p"), freqs2, Y2, 2, zref=[50.0, 75.0])
r, o = native2("_v2ref.s2p")
err2(r, o, "[E-741b] a per-port [Reference] 50 75 is carried into the S-to-Y "
     "conversion: the block matches the resonator although its S-matrix differs")

# [E-741c] the 3-port star as a .ts file in Lower matrix format
write_v2(os.path.join(HERE, "_v2low.ts"), freqs3, Y3, 3, mform="Lower")
r3, o3 = native3("_v2low.ts")
if a3 and r3:
    m = min(len(a3), len(r3))
    e2 = max(abs(complex(r3[k][1], r3[k][2]) - complex(a3[k][1], a3[k][2]))
             / (abs(complex(a3[k][1], a3[k][2])) + 1e-30) for k in range(m))
    e3 = max(abs(complex(r3[k][4], r3[k][5]) - complex(a3[k][4], a3[k][5]))
             / (abs(complex(a3[k][4], a3[k][5])) + 1e-30) for k in range(m))
    check("[E-741c] a 3-port .ts file in [Matrix Format] Lower (the port count from "
          "[Number of Ports], the triangle mirrored) matches the star on both outputs",
          e2 < 2e-3 and e3 < 2e-3, f"(v(p2) {e2:.2e}, v(p3) {e3:.2e})")
else:
    check("[E-741c] a 3-port .ts file in Lower format matches the star", False, o3[-300:])

# [E-741d] 21_12 order and a [Noise Data] section after the network data
write_v2(os.path.join(HERE, "_v2noise.s2p"), freqs2, Y2, 2, order="21_12", noise=True)
r, o = native2("_v2noise.s2p")
err2(r, o, "[E-741d] a v2 file in 21_12 order with a [Noise Data] section after the "
     "network data: the network is read, the noise rows are not, the block matches")

# [E-741e] a v1 file with noise-parameter rows is refused by name, nothing written
src = open(os.path.join(HERE, "_resonator.s2p")).read()
open(os.path.join(HERE, "_v1noise.s2p"), "w").write(
    src + "! noise parameters\n1e6 2.0 0.30 20 0.5\n2e6 2.5 0.35 40 0.6\n3e6 3.0 0.40 60 0.7\n")
o = refusal("_v1noise.s2p")
check("[E-741e] a v1 .s2p with noise-parameter rows after the network data is refused "
      "with the count, the frame size and the rows named, and no .nport is written",
      "noise-parameter rows" in o and "frames of 9" in o
      and not os.path.exists(os.path.join(HERE, "_v1noise.nport")),
      "" if "noise-parameter rows" in o else o[-300:])

# [E-741f, g] the v1 Y and Z forms `wrsnp` writes: port count from .y2p/.z2p,
# the Y*R / Z/R normalization undone
write_v1_yz(os.path.join(HERE, "_v1y.y2p"), freqs2, Y2, 2, "Y")
r, o = native2("_v1y.y2p")
err2(r, o, "[E-741f] a v1 .y2p (Y*R as wrsnp writes it) is read as a 2-port and "
     "de-normalized: the block matches the resonator")
check("[E-741f] ... and pre_snp reports it as a 2-port (the deck's title says 2-port too, "
      "so the test is on the converter's own report)", "(2-port," in o,
      o[-200:] if "(2-port," not in o else "")
write_v1_yz(os.path.join(HERE, "_v1z.z2p"), freqs2, Y2, 2, "Z")
r, o = native2("_v1z.z2p")
err2(r, o, "[E-741g] a v1 .z2p (Z/R) is read as a 2-port and de-normalized: the "
     "block matches the resonator")

# [E-741h] a v2 Y file: absolute admittances, no normalization
write_v2(os.path.join(HERE, "_v2y.s2p"), freqs2, Y2, 2, ptype="Y")
r, o = native2("_v2y.s2p")
err2(r, o, "[E-741h] a v2 Y file (absolute, as the v2 specification stores it) matches "
     "the resonator")

# [E-741i] refusals by name: mixed-mode order, a two-port without its data order,
# a [Number of Frequencies] that disagrees with the frames
write_v2(os.path.join(HERE, "_mm.s2p"), freqs2, Y2, 2, extra=["[Mixed-Mode Order] D1,2 C1,2"])
o_mm = refusal("_mm.s2p")
write_v2(os.path.join(HERE, "_noord.s2p"), freqs2, Y2, 2, with_order=False)
o_no = refusal("_noord.s2p")
write_v2(os.path.join(HERE, "_nfreq.s2p"), freqs2, Y2, 2, nfreq_kw=999)
o_nf = refusal("_nfreq.s2p")
ok_i = ("Mixed-Mode Order" in o_mm and "[Two-Port Data Order]" in o_no
        and "says 999" in o_nf
        and not any(os.path.exists(os.path.join(HERE, f"{b}.nport"))
                    for b in ("_mm", "_noord", "_nfreq")))
check("[E-741i] [Mixed-Mode Order], a v2 two-port without [Two-Port Data Order], and a "
      "[Number of Frequencies] that disagrees with the frames are each refused by name",
      ok_i, "" if ok_i else (o_mm[-150:] + o_no[-150:] + o_nf[-150:]))


# ================= Enhancement-745: the fit's acceptance limit ==================
# Touchstone-import hunt F5. The converter reported its rms relative error and
# emitted the model whatever the value. A fit above 0.1 (the worst element's
# relative rms error) is refused with the number, the limit and the flags that
# accept it; -maxerr <x> raises the limit, -force removes it.
import random
_rng = random.Random(745)
with open(os.path.join(HERE, "_noisy.s2p"), "w") as _f:
    _f.write("# HZ S RI R 50\n")
    for _fr in freqs2[::3]:
        _f.write(f"{_fr:.7e} " + " ".join(f"{_rng.uniform(-0.7, 0.7):.6f}" for _ in range(8)) + "\n")
o = refusal("_noisy.s2p")
m = re.search(r"rms relative error of ([0-9.e+-]+) \((\d+) poles\), above the limit of 0\.1", o)
check("[E-745a] a file of random S-parameters (unfittable) is refused: the fit's rms relative error, its pole count and "
      "the limit named, the causes and the -maxerr/-force flags given, no .nport written",
      m is not None and float(m.group(1)) > 0.1 and "-maxerr <x> or -force" in o
      and not os.path.exists(os.path.join(HERE, "_noisy.nport")), o[-300:] if m is None else f"(err {m.group(1)}, {m.group(2)} poles)")
_, o = run("* accept\nR1 a 0 1\nV1 a 0 1\n.control\npre_snp -native -maxerr 2 _noisy.s2p\n.endc\n.end\n")
check("[E-745b] `-maxerr 2` accepts the same fit: the .nport is written and the run says it was accepted under -maxerr, "
      "above the default limit",
      os.path.exists(os.path.join(HERE, "_noisy.nport")) and "accepted under -maxerr, above the default limit of 0.1" in o, o[-300:])
cleanup("_noisy.nport")
_, o = run("* force\nR1 a 0 1\nV1 a 0 1\n.control\npre_snp -native -force _noisy.s2p\n.endc\n.end\n")
check("[E-745c] `-force` accepts it too, saying so",
      os.path.exists(os.path.join(HERE, "_noisy.nport")) and "accepted under -force" in o, o[-300:])
cleanup("_noisy.nport")
_, o1 = run("* bad maxerr\nR1 a 0 1\nV1 a 0 1\n.control\npre_snp -native -maxerr abc _noisy.s2p\n.endc\n.end\n")
_, o2 = run("* bad maxerr\nR1 a 0 1\nV1 a 0 1\n.control\npre_snp -native -maxerr 0 _noisy.s2p\n.endc\n.end\n")
check("[E-745d] `-maxerr abc` and `-maxerr 0` are refused naming the flag and the default; nothing written",
      "-maxerr needs a positive number" in o1 and "-maxerr needs a positive number" in o2
      and not os.path.exists(os.path.join(HERE, "_noisy.nport")), (o1 + o2)[-300:])
cleanup("_v2ord.nport")                       # written by [E-741a] above
_, o = run("* tight limit\nR1 a 0 1\nV1 a 0 1\n.control\npre_snp -native -maxerr 1e-9 _v2ord.s2p\n.endc\n.end\n")
check("[E-745e] a limit tighter than a clean fit's error refuses even the resonator (the limit is the user's), and the "
      "default limit does not touch the suite's clean fits (every check above ran under it)",
      "above the limit of 1e-09" in o and not os.path.exists(os.path.join(HERE, "_v2ord.nport")), o[-300:])

# tidy -- see tidy_all() above; the atexit hook makes this idempotent.
tidy_all()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
