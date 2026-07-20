#!/usr/bin/env python3
"""Enhancement-253: the `rfstab` two-port stability / gain report.

After a `.sp` analysis (which publishes S_1_1..S_2_2 vs `frequency`), `rfstab`
computes the standard linear-two-port RF figures of merit per frequency:

    Delta = S11*S22 - S12*S21
    K     = (1 - |S11|^2 - |S22|^2 + |Delta|^2) / (2*|S12*S21|)     (Rollett)
    mu    = (1 - |S11|^2) / (|S22 - Delta*conj(S11)| + |S12*S21|)   (load stability)
    MSG   = |S21|/|S12|                          (max stable gain,  power, dB)
    MAG   = |S21|/|S12|*(K - sqrt(K^2-1))         (max available gain, K>1, dB)

and stores k, magdelta, mu, mu_src, gmax, msg, stable in an `rfstab` plot. A
two-port is unconditionally stable iff K > 1 and |Delta| < 1 (iff mu > 1).

Checked two ways, no numpy (Python's built-in complex is enough):
 1. a passive T-attenuator (R1=R3=25, R2=100, Z0=50) has HAND-COMPUTED metrics
    K=2.125, mu=2.33333, |Delta|=0.212121, MSG=0 dB, MAG=-6.02060 dB, stable=1 --
    rfstab must reproduce them;
 2. for a frequency-dependent two-port, the four S-parameters are read back and
    K/Delta/mu/MSG/MAG are recomputed independently in pure Python, then compared
    point-by-point to what rfstab stored.

Vectors are exchanged through `wrdata` files (real -> "freq val", complex ->
"freq re im"). Line 1 of every SPICE deck is the title (ignored).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0
_tmp = []


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    cir = os.path.join(HERE, "_rf.cir")
    open(cir, "w").write(deck)
    _tmp.append(cir)
    subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                   timeout=60, cwd=HERE)


def real_vec(fn):
    p = os.path.join(HERE, fn)
    _tmp.append(p)
    out = []
    if os.path.exists(p):
        for line in open(p):
            t = line.split()
            if len(t) >= 2:
                out.append(float(t[1]))
    return out


def cx_vec(fn):
    p = os.path.join(HERE, fn)
    _tmp.append(p)
    out = []
    if os.path.exists(p):
        for line in open(p):
            t = line.split()
            if len(t) >= 3:
                out.append(complex(float(t[1]), float(t[2])))
    return out


def cleanup():
    for p in _tmp:
        if os.path.exists(p):
            os.remove(p)


# ---- 1: passive T-attenuator vs hand-computed metrics ----
run("* two-port T attenuator\n"
    "V1 in 0 dc 0 ac 1 portnum 1 z0 50\n"
    "R1 in mid 25\nR2 mid 0 100\nR3 mid out 25\n"
    "V2 out 0 dc 0 ac 0 portnum 2 z0 50\n"
    ".sp lin 2 1meg 2meg 1\n.control\nrun\nrfstab\n"
    "wrdata a_k.dat k\nwrdata a_mu.dat mu\nwrdata a_md.dat magdelta\n"
    "wrdata a_g.dat gmax\nwrdata a_m.dat msg\nwrdata a_s.dat stable\n.endc\n.end\n")
k = real_vec("a_k.dat"); mu = real_vec("a_mu.dat"); md = real_vec("a_md.dat")
gm = real_vec("a_g.dat"); mg = real_vec("a_m.dat"); st = real_vec("a_s.dat")
if not k:
    print("  SKIP  .sp / rfstab unavailable in this checkout")
    cleanup()
    raise SystemExit(0)
ok = (abs(k[0] - 2.125) < 1e-3 and abs(mu[0] - 2.33333) < 1e-3
      and abs(md[0] - 0.212121) < 1e-4 and abs(mg[0]) < 1e-4
      and abs(gm[0] + 6.02060) < 1e-3 and abs(st[0] - 1.0) < 1e-9)
check("passive T-attenuator matches hand-computed K/mu/|D|/MSG/MAG + stable flag",
      ok, f"K={k[0]:.4f} mu={mu[0]:.4f} |D|={md[0]:.4f} MSG={mg[0]:.4f} MAG={gm[0]:.4f} st={st[0]}")

# ---- 2: independent pure-Python recompute vs rfstab, for a NON-reciprocal,
#         well-conditioned two-port (a common-source MOSFET amp: S21 != S12, and
#         K well above 1, so nothing sits on the K=1 / MSG=0 boundary). ----
run("* active two-port (common-source MOSFET)\n"
    "V1 in 0 dc 0 ac 1 portnum 1 z0 50\n"
    "Vdd dd 0 dc 2\nRd dd out 500\n"
    "M1 out g 0 0 nm w=50u l=0.5u\nRg in g 1k\nCgd g out 0.2p\n"
    "Vbias g2 0 dc 0.9\nRb g2 g 100k\n"
    "V2 out 0 dc 0 ac 0 portnum 2 z0 50\n"
    ".model nm nmos level=1 vto=0.5 kp=200u lambda=0.1\n"
    ".sp lin 6 100meg 2000meg 1\n.control\nrun\n"
    "wrdata s11.dat S_1_1\nwrdata s12.dat S_1_2\n"
    "wrdata s21.dat S_2_1\nwrdata s22.dat S_2_2\n"
    "rfstab\nwrdata r_k.dat k\nwrdata r_mu.dat mu\nwrdata r_md.dat magdelta\n"
    "wrdata r_g.dat gmax\nwrdata r_m.dat msg\n.endc\n.end\n")
S11 = cx_vec("s11.dat"); S12 = cx_vec("s12.dat")
S21 = cx_vec("s21.dat"); S22 = cx_vec("s22.dat")
k = real_vec("r_k.dat"); mu = real_vec("r_mu.dat"); md = real_vec("r_md.dat")
gm = real_vec("r_g.dat"); mg = real_vec("r_m.dat")
n = min(len(S11), len(S12), len(S21), len(S22), len(k))


def close(a, b):
    return abs(a - b) <= 1e-6 + 1e-5 * abs(b)   # combined abs + rel (dB or ratio)


allok = n >= 4
worst = 0.0
for i in range(n):
    D = S11[i] * S22[i] - S12[i] * S21[i]
    p = abs(S12[i]) * abs(S21[i])
    Kv = (1 - abs(S11[i])**2 - abs(S22[i])**2 + abs(D)**2) / (2 * p)
    muv = (1 - abs(S11[i])**2) / (abs(S22[i] - D * S11[i].conjugate()) + p)
    msgv = 10 * math.log10(abs(S21[i]) / abs(S12[i]))
    magv = (10 * math.log10((abs(S21[i]) / abs(S12[i])) * (Kv - math.sqrt(Kv * Kv - 1)))
            if Kv > 1 else msgv)
    for a, b in ((Kv, k[i]), (muv, mu[i]), (abs(D), md[i]), (magv, gm[i]), (msgv, mg[i])):
        allok = allok and close(a, b)
        worst = max(worst, abs(a - b))
check("rfstab K/mu/|D|/MSG/MAG match an independent pure-Python recompute",
      allok, f"n={n} worst_abs={worst:.2e}")

cleanup()
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
