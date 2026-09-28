#!/usr/bin/env python3
"""Enhancement-752: a built-in PRBS (pseudo-random bit sequence) source.

    Vtx tx 0 PRBS(v1 v2 tbit [td [tr [tf [order [seed]]]]])
    Itx 0 rx PRBS(0 1m 100p)

The bits come from a Fibonacci linear-feedback shift register with the standard
maximal-length taps (ITU-T O.150 for 7, 9, 11, 15, 23 and 31; Xilinx XAPP052 for
the other lengths 2..31), seeded with all ones unless a seed is given, so PRBS7
repeats every 127 bits with 64 ones, PRBS31 every 2^31 - 1. Bit k occupies
[td + k*tbit, td + (k+1)*tbit); a transition starts at the bit boundary and takes
tr or tf (0 or omitted: the analysis's step, as PULSE does); v1 is held before td.
Every corner is a breakpoint, a run of equal bits has none, and the value is a
pure function of time, so a rejected step and a re-run reproduce the stream.

Checks:
  [1] the stream is the reference LFSR's, bit for bit, on both source types;
      period 127, 64 ones, longest runs 7 ones and 6 zeros
  [2] every transition's start and end is a time point; the edge is linear
  [3] order 9 (period 511), a given seed (a rotation of the same cycle), order 15,
      and PRBS31 for ten thousand bits at 10 Gb/s
  [4] omitted edges take one step; the delay holds v1 and shifts the stream
  [5] a dc value serves the operating point, the stream starts at v1
  [6] eight refusals by name, on the voltage and the current source
  [7] `alter` re-reads the list; two runs in one session are identical
  [8] the taps table: every register length 2..20 gives a full period in Python
  [9] PRBS7 at 2 Gb/s through an RC channel gives an open eye to E-207's `eye`
 [10] PAM4(v1 v2 tsym ...): the same register two bits per symbol, Gray coded as
      IEEE 802.3 clause 120 defines PRBS13Q (order 13 is its x^13+x^12+x^2+x+1)
      and PRBS31Q; the 8191-symbol period and its 2047/2048/2048/2048 balance,
      the current source, edges between levels, the level spacing, refusals in
      the keyword's own words, an alter from prbs to pam4
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers  # noqa: E402
check_both_solvers(__file__)

import numpy as np  # noqa: E402

checks = passed = 0
GENERATED = ["_p.cir", "_p.dat", "_p2.dat"]


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def run(deck, timeout=300):
    open(os.path.join(HERE, "_p.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_p.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def data(name="_p.dat"):
    p = os.path.join(HERE, name)
    d = np.loadtxt(p) if os.path.exists(p) else None
    if d is not None and d.ndim == 1:
        d = d.reshape(1, -1)
    return d


TAPS = {2: [2, 1], 3: [3, 2], 4: [4, 3], 5: [5, 3], 6: [6, 5], 7: [7, 6], 8: [8, 6, 5, 4],
        9: [9, 5], 10: [10, 7], 11: [11, 9], 12: [12, 6, 4, 1], 13: [13, 12, 2, 1],
        14: [14, 5, 3, 1], 15: [15, 14], 16: [16, 15, 13, 4], 17: [17, 14], 18: [18, 11],
        19: [19, 6, 2, 1], 20: [20, 17], 21: [21, 19], 22: [22, 21], 23: [23, 18],
        24: [24, 23, 22, 17], 25: [25, 22], 26: [26, 6, 2, 1], 27: [27, 5, 2, 1],
        28: [28, 25], 29: [29, 27], 30: [30, 6, 4, 1], 31: [31, 28]}


def lfsr(order, nbits, seed=None):
    """The reference: register r_1..r_n with r_1 the newest bit; new = XOR of the
    tap positions; the output is the new bit."""
    mask = (1 << order) - 1
    st = (mask if seed is None else seed) & mask
    out = []
    for _ in range(nbits):
        nb = 0
        for tp in TAPS[order]:
            nb ^= (st >> (tp - 1)) & 1
        st = ((st << 1) | nb) & mask
        out.append(nb)
    return out


def sample_bits(t, v, tbit, nbits, td=0.0, vmid=0.5):
    return [int(np.interp(td + (k + 0.5) * tbit, t, v) > vmid) for k in range(nbits)]


def longest_run(bits, val):
    best = cur = 0
    for b in bits:
        cur = cur + 1 if b == val else 0
        best = max(best, cur)
    return best


print("Enhancement-752: the PRBS source")

# ------------------------------------------------------------------- [1]
print("\n[1] the stream, bit for bit, on both source types")
out = run("""* prbs
Vtx tx 0 PRBS(0 1 1n 0 50p 50p 7)
Rl tx 0 1k
Itx 0 ix PRBS(0 1m 1n 0 50p 50p 7)
Ri ix 0 1k
.control
set numdgt=10
tran 10p 260n
wrdata _p.dat v(tx) v(ix)
.endc
.end
""")
d = data()
ok = d is not None and d.shape[1] >= 4
check("[1] PRBS7 on a voltage and a current source runs (wrdata has both)", ok, out[-160:].replace("\n", " ") if not ok else "")
ref = lfsr(7, 254)
if ok:
    t, v, i = d[:, 0], d[:, 1], d[:, 3]
    got = sample_bits(t, v, 1e-9, 254)
    goti = sample_bits(t, i, 1e-9, 254, vmid=0.5e-3)
    check("[1] the voltage source's 254 bits are the reference LFSR's (x^7 + x^6 + 1, all-ones seed)", got == ref,
          f"first mismatch at bit {next((k for k in range(254) if got[k] != ref[k]), -1)}")
    check("[1] the current source's stream is the same", goti == ref)
    per = got[:127]
    check("[1] period 127, 64 ones, longest run 7 ones and 6 zeros", got[:127] == got[127:254] and sum(per) == 64
          and longest_run(per + per, 1) == 7 and longest_run(per + per, 0) == 6,
          f"ones={sum(per)} run1={longest_run(per + per, 1)} run0={longest_run(per + per, 0)}")
    check("[1] the levels are exactly v1 and v2 (0 and 1)", abs(v.max() - 1.0) < 1e-9 and abs(v.min()) < 1e-9, f"{v.min()} {v.max()}")
    # -------------------------------------------------------------- [2]
    print("\n[2] corners are breakpoints, edges are linear")
    ts = set(np.round(t, 15))
    trans = [k for k in range(1, 254) if ref[k] != ref[k - 1]]
    present = all((round(k * 1e-9, 15) in ts) and (round(k * 1e-9 + 50e-12, 15) in ts) for k in trans)
    check(f"[2] every transition's start and end ({len(trans)} of them) is a time point", present)
    k = trans[0]
    mid = np.interp(k * 1e-9 + 25e-12, t, v)
    check("[2] the first rising edge is linear: v1 at the boundary, halfway at tr/2, v2 at tr",
          abs(np.interp(k * 1e-9, t, v)) < 1e-9 and abs(mid - 0.5) < 1e-6 and abs(np.interp(k * 1e-9 + 50e-12, t, v) - 1) < 1e-9, f"mid={mid}")
    kf = next(k for k in trans if ref[k] == 0)
    midf = np.interp(kf * 1e-9 + 25e-12, t, v)
    check("[2] a falling edge likewise, over tf", abs(np.interp(kf * 1e-9, t, v) - 1) < 1e-9 and abs(midf - 0.5) < 1e-6, f"mid={midf}")
    runs = [k for k in range(1, 254) if ref[k] == ref[k - 1]]
    worst = 0.0
    for k in runs[:80]:
        m = (t >= k * 1e-9) & (t <= (k + 1) * 1e-9)
        worst = max(worst, float(np.abs(v[m] - ref[k]).max()))
    check("[2] a bit that repeats its predecessor is flat for its whole period, boundary included (no glitch, no edge)", worst < 1e-12, f"{worst:.2e}")

# ------------------------------------------------------------------- [3]
print("\n[3] order and seed")
out = run("""* prbs9
Vtx tx 0 PRBS(0 1 100p 0 10p 10p 9)
Rl tx 0 1k
.control
tran 5p 103n
wrdata _p.dat v(tx)
.endc
.end
""")
d = data()
if d is not None:
    got = sample_bits(d[:, 0], d[:, 1], 100e-12, 1022)
    ref9 = lfsr(9, 1022)
    check("[3] order 9: 1022 bits are the reference's (x^9 + x^5 + 1) and the period is 511",
          got == ref9 and got[:511] == got[511:1022] and sum(got[:511]) == 256)
else:
    check("[3] order 9 runs", False, out[-160:])
out = run("""* seed
Vtx tx 0 PRBS(0 1 1n 0 50p 50p 7 1)
Rl tx 0 1k
.control
tran 10p 130n
wrdata _p.dat v(tx)
.endc
.end
""")
d = data()
if d is not None:
    got = sample_bits(d[:, 0], d[:, 1], 1e-9, 127)
    ref1 = lfsr(7, 127, seed=1)
    cyc = lfsr(7, 254)
    rot = any(cyc[s:s + 127] == got for s in range(127))
    check("[3] seed 1: the reference with that register, and a rotation of the all-ones cycle", got == ref1 and rot and got != ref[:127])
else:
    check("[3] seed 1 runs", False, out[-160:])
out = run("""* prbs15
Vtx tx 0 PRBS(-0.5 0.5 200p 0 20p 20p 15)
Rl tx 0 1k
.control
tran 10p 60.2n
wrdata _p.dat v(tx)
.endc
.end
""")
d = data()
if d is not None:
    got = sample_bits(d[:, 0], d[:, 1], 200e-12, 300, vmid=0.0)
    check("[3] order 15 with levels -0.5/0.5: the first 300 bits are the reference's (x^15 + x^14 + 1)", got == lfsr(15, 300))
else:
    check("[3] order 15 runs", False, out[-160:])
t0 = time.time()
out = run("""* prbs31 10 Gb/s
Vtx tx 0 PRBS(0 1 100p 0 20p 20p 31)
Rl tx 0 1k
.control
tran 5p 1000.1n
wrdata _p.dat v(tx)
.endc
.end
""")
dt = time.time() - t0
d = data()
if d is not None:
    got = sample_bits(d[:, 0], d[:, 1], 100e-12, 10000)
    check(f"[3] PRBS31 at 10 Gb/s: ten thousand bits are the reference's (x^31 + x^28 + 1), {dt:.1f} s for the run", got == lfsr(31, 10000) and dt < 60,
          f"first mismatch {next((k for k in range(10000) if got[k] != lfsr(31, 10000)[k]), -1)}")
else:
    check("[3] PRBS31 runs", False, out[-160:])

# ------------------------------------------------------------------- [4]
print("\n[4] defaults and the delay")
out = run("""* defaults
Vtx tx 0 PRBS(0 1 1n)
Rl tx 0 1k
Vd td 0 PRBS(0 1 1n 3n 50p 50p)
Rd td 0 1k
.control
tran 10p 20n
wrdata _p.dat v(tx) v(td)
.endc
.end
""")
d = data()
if d is not None:
    t, v, w = d[:, 0], d[:, 1], d[:, 3]
    check("[4] tr and tf omitted: the first rising edge (bit 6) takes one step, 10 ps",
          abs(np.interp(6e-9, t, v)) < 1e-9 and abs(np.interp(6.01e-9, t, v) - 1) < 1e-6 and abs(np.interp(6.005e-9, t, v) - 0.5) < 1e-3)
    check("[4] td=3n: v1 is held to 3 ns and bit 6 begins at 9 ns",
          abs(np.interp(2.9e-9, t, w)) < 1e-9 and abs(np.interp(8.99e-9, t, w)) < 1e-9 and abs(np.interp(9.05e-9, t, w) - 1) < 1e-9
          and sample_bits(t, w, 1e-9, 17, td=3e-9) == ref[:17])
else:
    check("[4] runs", False, out[-160:])

# ------------------------------------------------------------------- [5]
print("\n[5] a dc value and the operating point")
out = run("""* dc
Vtx tx 0 dc 0.3 PRBS(0 1 1n 0 50p 50p)
Rl tx 0 1k
.control
set numdgt=10
op
print v(tx)
tran 10p 2n
print v(tx)[0]
.endc
.end
""")
vals = re.findall(r"v\(tx\)(?:\[0\])?\s*=\s*([-+0-9.e]+)", out)
check("[5] `dc 0.3 PRBS(0 1 ...)`: the op reads 0.3 and the transient starts at v1 = 0",
      len(vals) == 2 and abs(float(vals[0]) - 0.3) < 1e-9 and abs(float(vals[1])) < 1e-9, f"{vals}")

# ------------------------------------------------------------------- [6]
print("\n[6] refusals by name")
CASES = [("PRBS(0 1)", "needs at least v1, v2 and the bit time"),
         ("PRBS(0 1 0)", "bit time 0 is not positive"),
         ("PRBS(0 1 -1n)", "bit time -1e-09 is not positive"),
         ("PRBS(0 1 1n -1n)", "delay -1e-09 is negative"),
         ("PRBS(0 1 1n 0 2n)", "rise time 2e-09 is longer than the bit time 1e-09"),
         ("PRBS(0 1 1n 0 50p 3n)", "fall time 3e-09 is longer than the bit time 1e-09"),
         ("PRBS(0 1 1n 0 50p 50p 32)", "order 32 is not a register length between 2 and 31"),
         ("PRBS(0 1 1n 0 50p 50p 7 0)", "seed 0 is not a positive integer"),
         ("PRBS(0 1 1n 0 50p 50p 7 128)", "seed 128 is not a positive integer with a nonzero low 7 bits")]
for spec, msg in CASES:
    out = run(f"* refuse\nVtx tx 0 {spec}\nRl tx 0 1k\n.control\ntran 10p 2n\nmeas tran vm max v(tx)\n.endc\n.end\n")
    check(f"[6] `{spec}` is refused: \"{msg}\"", f"voltage source vtx: prbs {msg}" in out and "vm " not in out.replace("vm  ", "vm "),
          out[-200:].replace("\n", " ") if f"prbs {msg}" not in out else "")
out = run("* refuse\nItx 0 tx PRBS(0 1m 0)\nRl tx 0 1k\n.control\ntran 10p 2n\n.endc\n.end\n")
check("[6] the current source refuses with its own name", "current source itx: prbs bit time 0 is not positive" in out)

# ------------------------------------------------------------------- [7]
print("\n[7] alter and reproducibility")
out = run("""* alter
Vtx tx 0 PRBS(0 1 1n 0 50p 50p 7)
Rl tx 0 1k
.control
tran 10p 20n
wrdata _p.dat v(tx)
tran 10p 20n
wrdata _p2.dat v(tx)
alter @vtx[prbs] = [ 0 1 2n 0 50p 50p 7 ]
tran 10p 30n
wrdata _p.dat v(tx)
.endc
.end
""")
d2 = data("_p2.dat")
d = data()
if d is not None and d2 is not None:
    check("[7] two runs in one session give the same stream (the register is re-armed per run)",
          sample_bits(d2[:, 0], d2[:, 1], 1e-9, 20) == ref[:20] and d2.shape[0] > 100)
    check("[7] `alter @vtx[prbs] = [ 0 1 2n ... ]`: the next run has 2 ns bits (bit 6 begins at 12 ns)",
          sample_bits(d[:, 0], d[:, 1], 2e-9, 15) == ref[:15] and abs(np.interp(11.9e-9, d[:, 0], d[:, 1])) < 1e-9)
else:
    check("[7] runs", False, out[-160:])

# ------------------------------------------------------------------- [8]
print("\n[8] the taps table")
full = True
for n in range(2, 21):
    mask = (1 << n) - 1
    st = mask
    period = 0
    while True:
        nb = 0
        for tp in TAPS[n]:
            nb ^= (st >> (tp - 1)) & 1
        st = ((st << 1) | nb) & mask
        period += 1
        if st == mask or period > mask:
            break
    if period != mask:
        full = False
        print(f"    order {n}: period {period}, expected {mask}")
check("[8] every register length 2..20 runs the full 2^n - 1 period from the all-ones seed (the same taps the source uses)", full)

# ------------------------------------------------------------------- [9]
print("\n[9] an eye through a channel")
out = run("""* eye
Vtx tx 0 PRBS(0 1 0.5n 0 20p 20p 7)
Rc tx rx 250
Cc rx 0 1p
.control
tran 2p 70n
eye v(rx) -ui 0.5n -tstart 3n
print eye_height eye_width eye_jitter_rms
.endc
.end
""")
vals = {m.group(1): float(m.group(2)) for m in re.finditer(r"(eye_\w+)\s*=\s*([-+0-9.e]+)", out)}
check("[9] PRBS7 at 2 Gb/s through a 250 ps RC channel: E-207's `eye` sees an open eye (height > 0.2 V, width > 0.2 ns)",
      vals.get("eye_height", 0) > 0.2 and vals.get("eye_width", 0) > 0.2e-9, f"{vals}")

# ------------------------------------------------------------------- [10]
print("\n[10] PAM4")


def pam4_ref(order, nsym, seed=None):
    bits = lfsr(order, 2 * nsym, seed)
    gray = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3}
    return [gray[(bits[2 * k], bits[2 * k + 1])] for k in range(nsym)]


def sample_levels(t, v, tsym, nsym, v1=0.0, span=1.0, td=0.0):
    return [int(round((np.interp(td + (k + 0.5) * tsym, t, v) - v1) / span)) for k in range(nsym)]


out = run("""* prbs13q
Vtx tx 0 PAM4(0 3 100p 0 10p 10p 13)
Rl tx 0 1k
.control
tran 5p 1638.25n
wrdata _p.dat v(tx)
.endc
.end
""")
d = data()
r13 = pam4_ref(13, 16382)
if d is not None:
    t, v = d[:, 0], d[:, 1]
    got = sample_levels(t, v, 100e-12, 16382)
    check("[10] PAM4 order 13 is PRBS13Q: 16382 symbols are the reference's (x^13 + x^12 + x^2 + x + 1, two bits per symbol, Gray)",
          got == r13, f"first mismatch at symbol {next((k for k in range(16382) if got[k] != r13[k]), -1)}")
    per = got[:8191]
    counts = [per.count(L) for L in range(4)]
    check("[10] the symbol period is 8191 (odd bit period: two bit periods per symbol period) and the levels count 2047, 2048, 2048, 2048",
          got[:8191] == got[8191:16382] and counts == [2047, 2048, 2048, 2048], f"{counts}")
    lv = sorted(set(np.round([np.interp((k + 0.5) * 1e-10, t, v) for k in range(2000)], 9)))
    check("[10] the four levels are v1, v1 + span/3, v1 + 2 span/3, v2 exactly (0, 1, 2, 3 here) at the symbol centres",
          lv == [0.0, 1.0, 2.0, 3.0], f"{lv[:6]}")
    trans = [k for k in range(1, 400) if r13[k] != r13[k - 1]]
    kr = next(k for k in trans if r13[k] > r13[k - 1]); kf = next(k for k in trans if r13[k] < r13[k - 1])
    okr = abs(np.interp(kr * 1e-10, t, v) - r13[kr - 1]) < 1e-9 and abs(np.interp(kr * 1e-10 + 5e-12, t, v) - (r13[kr - 1] + r13[kr]) / 2) < 1e-6 and abs(np.interp(kr * 1e-10 + 1e-11, t, v) - r13[kr]) < 1e-9
    okf = abs(np.interp(kf * 1e-10, t, v) - r13[kf - 1]) < 1e-9 and abs(np.interp(kf * 1e-10 + 5e-12, t, v) - (r13[kf - 1] + r13[kf]) / 2) < 1e-6 and abs(np.interp(kf * 1e-10 + 1e-11, t, v) - r13[kf]) < 1e-9
    check(f"[10] a transition between any two levels is linear over tr (up, {r13[kr - 1]}->{r13[kr]}) or tf (down, {r13[kf - 1]}->{r13[kf]}), whatever the step", okr and okf)
else:
    check("[10] PAM4 order 13 runs", False, out[-160:])
out = run("""* pam4 isrc + levels
Itx 0 ix PAM4(0 3m 100p 0 10p 10p 13)
Ri ix 0 1k
Vs vs 0 PAM4(-0.6 0.6 100p 0 10p 10p 7)
Rs vs 0 1k
.control
tran 5p 50.05n
wrdata _p.dat v(ix) v(vs)
.endc
.end
""")
d = data()
if d is not None:
    t, vi, vs = d[:, 0], d[:, 1], d[:, 3]
    check("[10] the current source's PAM4 is the same stream (500 symbols)", sample_levels(t, vi, 100e-12, 500) == r13[:500])
    lv = sorted(set(np.round([np.interp((k + 0.5) * 1e-10, t, vs) for k in range(400)], 9)))
    check("[10] v1 = -0.6, v2 = 0.6: the levels at the symbol centres are -0.6, -0.2, 0.2, 0.6",
          len(lv) == 4 and max(abs(a - b) for a, b in zip(lv, [-0.6, -0.2, 0.2, 0.6])) < 1e-9, f"{lv[:6]}")
    check("[10] ...and its symbols are PRBS7's pairs, Gray coded", sample_levels(t, vs, 100e-12, 400, v1=-0.6, span=0.4) == pam4_ref(7, 400))
else:
    check("[10] PAM4 on the current source runs", False, out[-160:])
out = run("""* prbs31q
Vtx tx 0 PAM4(0 3 100p 0 10p 10p 31)
Rl tx 0 1k
.control
tran 5p 300.05n
wrdata _p.dat v(tx)
.endc
.end
""")
d = data()
if d is not None:
    check("[10] PAM4 order 31 is PRBS31Q: 3000 symbols are the reference's (x^31 + x^28 + 1)", sample_levels(d[:, 0], d[:, 1], 100e-12, 3000) == pam4_ref(31, 3000))
else:
    check("[10] PAM4 order 31 runs", False, out[-160:])
for spec, msg in (("PAM4(0 1)", "pam4 needs at least v1, v2 and the symbol time"),
                  ("PAM4(0 1 0)", "pam4 symbol time 0 is not positive"),
                  ("PAM4(0 1 100p 0 200p)", "pam4 rise time 2e-10 is longer than the symbol time 1e-10")):
    out = run(f"* refuse\nVtx tx 0 {spec}\nRl tx 0 1k\n.control\ntran 10p 2n\n.endc\n.end\n")
    check(f"[10] `{spec}` is refused in the keyword's words: \"{msg}\"", f"voltage source vtx: {msg}" in out, out[-200:].replace("\n", " ") if msg not in out else "")
out = run("""* alter to pam4
Vtx tx 0 PRBS(0 3 100p 0 10p 10p 13)
Rl tx 0 1k
.control
tran 5p 20.05n
wrdata _p2.dat v(tx)
alter @vtx[pam4] = [ 0 3 100p 0 10p 10p 13 ]
tran 5p 20.05n
wrdata _p.dat v(tx)
.endc
.end
""")
d = data(); d2 = data("_p2.dat")
if d is not None and d2 is not None:
    two = sorted(set(np.round([np.interp((k + 0.5) * 1e-10, d2[:, 0], d2[:, 1]) for k in range(200)], 6)))
    four = sorted(set(np.round([np.interp((k + 0.5) * 1e-10, d[:, 0], d[:, 1]) for k in range(200)], 6)))
    check("[10] `alter @vtx[pam4] = [...]` turns a PRBS source into a PAM4 one for the next run (two levels, then four)",
          two == [0.0, 3.0] and four == [0.0, 1.0, 2.0, 3.0]
          and sample_levels(d[:, 0], d[:, 1], 100e-12, 200) == r13[:200], f"levels {two[:4]} -> {four[:6]}")
else:
    check("[10] alter to pam4 runs", False, out[-160:])

for f in GENERATED:
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
