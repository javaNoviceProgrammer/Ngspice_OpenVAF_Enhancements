#!/usr/bin/env python3
"""Enhancement-484: a converged flag is not a correct answer.

Enhancement-483 made the harmonic-balance bound reachable (`set qpss_tol`) and
taught the Newton loop to recognise a stalled residual. It left a hole. The STALL
path reports what it settled for -- "STALLED above tol ... after a 532224607x
reduction" -- but the ORDINARY tolerance path reported nothing at all. So a deck
that loosened the bound far enough had its solution accepted with a clean
`converged in 3 iterations` and no hint that anything was wrong.

It can be very wrong. On the two-tone FET amplifier below, `set qpss_tol=1e-1` at
K=4 accepts a residual that came down by only ~100x, and the third-order products
land about 6 dB out -- silently. That is worse than the failure E-483 fixed,
because a refusal is honest and a wrong number is not.

So the reduction is now reported on the ordinary path too, whenever the accepted
residual rests on a poor one:

    QPSS-HB: WARNING -- accepted at |F| = 4.982e-02, only a 101x reduction from
    5.042e+00. tol = 1.0e-01 was loose enough to stop early; the harmonics may be
    badly wrong. Tighten qpss_tol, or reduce K1/K2.

`QP_LOWRED_WARN` is deliberately a DIFFERENT constant from `QP_STALL_ACCEPT`:
one decides whether to accept a stalled residual at all, this one decides whether
to believe an accepted one. It is calibrated on measurement and not on taste,
which is what [3] and [4] pin: a ~101x reduction puts OIP3 6 dB out, while a
~55000x reduction agrees with the K=2 answer to 0.01 dB. A warning that fires on
a good answer is one people learn to ignore -- Enhancement-445's note -- so the
bar sits between the two measured cases, and [4] fails if it drifts onto the good
one.

This suite does NOT test that `hb 4 4` gives a right answer, because it does not.
The Newton step degrades as harmonics are added on this device (reduction 5.3e8x
at K=2, 7.8e4x at K=3, 1.5e2x at K=4) for reasons that are invariant to drive
level, every model parameter tried, the passive network, the topology and the DFT
oversampling. That is an open question in `qp_build_matrix`. What this
enhancement guarantees is narrower and worth having on its own: **when the solver
cannot give a correct answer, it does not quietly give a wrong one.**
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

AMP = """.model MF NMF (vto=-0.95 beta=0.24 lambda=0.09 alpha=4.0 b=0.8
+ rd=0.25 rs=0.125 cgs=0.8p cgd=0.16p pb=0.7 is=1n)
Vdd  dd 0 DC 5
Vgg  gg 0 DC -0.43
Lc   dd drain 1m
Lg   gg gate  1m
Z1   drain gate 0 MF
V3   rf rfi DC 0 SIN(0 20m 1.9G)
V4   rfi 0 DC 0 SIN(0 20m 1.91G)
R2   rf n1 50
C1   n1 gate 1u
C2   drain out 1u
R1   out 0 50"""

DIODE = """V1 in 0 DC 0.55 SIN(0.55 0.0003 1.0G)
V2 x in SIN(0 0.0003 1.3G)
R1 x a 50.0
D1 a 0 DMOD
.model DMOD D(IS=1e-14 N=1)"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(body, ctl, tag, timeout=300):
    path = os.path.join(HERE, f"_ht_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hbtrust {tag}\n{body}\n.control\noption noacct\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "-r", os.devnull, path], capture_output=True,
                       text=True, timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
    try:
        os.remove(path)
    except OSError:
        pass
    return r.returncode, (r.stdout + r.stderr)


def spectrum(out, node="out"):
    d = {}
    for line in out.splitlines():
        m = re.match(r"\s*" + re.escape(node) + r"\s+\(\s*(-?\d+),\s*(-?\d+)\)"
                     r"\s+[\d.eE+-]+\s+([\d.eE+-]+)", line)
        if m:
            d[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))
    return d


def oip3(sp):
    f1, im3 = sp.get((1, 0)), sp.get((2, -1))
    if not f1 or not im3:
        return None
    dbm = lambda v: 10.0 * math.log10(v * v) + 10.0
    return dbm(f1) + (dbm(f1) - dbm(im3)) / 2.0


def reduction(out):
    m = re.search(r"only a (\d+)x reduction", out)
    return int(m.group(1)) if m else None


print("Enhancement-484: a converged flag is not a correct answer\n")

# the trustworthy reference: K=2 converges on its own merits under E-483
rc, o_ref = run(AMP, "qpss v(out) 1.9G 1.91G hb 2 2", "ref")
ref = oip3(spectrum(o_ref))
check("[0] the K=2 reference converges and yields an OIP3", ref is not None,
      f"{ref:.3f} dBm" if ref else "missing")
check("[0] ...on its own merits, with no low-reduction warning",
      "WARNING -- accepted" not in o_ref, "trustworthy baseline")

# ---------------------------------------- the silent wrong answer, made loud --
print("\na bound loose enough to stop early is now called out")
rc, o_bad = run(AMP, "set qpss_tol=1e-1\nqpss v(out) 1.9G 1.91G hb 4 4", "bad")
check("[1] the run that stops early is WARNED", "WARNING -- accepted" in o_bad,
      f"{reduction(o_bad)}x reduction")
check("[2] ...naming the residual it accepted",
      re.search(r"accepted at \|F\| = [\d.]+e-0?2", o_bad) is not None, "residual named")
check("[2] ...the reduction it rests on", reduction(o_bad) is not None
      and reduction(o_bad) < 1000, f"{reduction(o_bad)}x")
check("[2] ...the bound that let it stop", re.search(r"tol = 1\.0e-01", o_bad) is not None,
      "tol named")
check("[2] ...and what to do about it",
      "Tighten qpss_tol" in o_bad and "reduce K1/K2" in o_bad, "remedy given")

bad = oip3(spectrum(o_bad))
check("[3] and the warning is EARNED -- that answer really is wrong",
      bad is not None and ref is not None and abs(bad - ref) > 1.0,
      f"{bad:.3f} vs {ref:.3f} dBm = {abs(bad-ref):.2f} dB out" if bad and ref else "missing")

# ------------------------------------------- the calibration, from the other side --
print("\nand it does NOT fire on an answer that is good")
rc, o_ok = run(AMP, "set qpss_tol=1e-3\nqpss v(out) 1.9G 1.91G hb 3 3", "ok33")
ok33 = oip3(spectrum(o_ok))
check("[4] the K=3 run at a looser bound is NOT warned",
      "WARNING -- accepted" not in o_ok, "silent")
check("[4] ...because its answer really is right",
      ok33 is not None and ref is not None and abs(ok33 - ref) < 0.05,
      f"{ok33:.3f} vs {ref:.3f} dBm = {abs(ok33-ref):.3f} dB" if ok33 and ref else "missing")
check("[4] ...which is what calibrates the threshold: the warned case reduced "
      "far less than this one",
      reduction(o_bad) is not None and reduction(o_bad) < 55000,
      f"{reduction(o_bad)}x warned, this one was not")

# ------------------------------------------------- no new noise anywhere else --
print("\nnothing else starts warning")
rc, o_d = run(DIODE, "set numdgt=12\nqpss v1#branch 1.0G 1.3G hb 5 5", "diode")
check("[5] the diode two-tone deck converges and is not warned",
      "converged in" in o_d and "WARNING -- accepted" not in o_d, "clean")
check("[5] E-483's stall report is untouched where it applied",
      "STALLED above tol" in o_ref, "K=2 still reports its stall")
check("[5] ...and the two messages are distinct paths",
      "WARNING -- accepted" not in o_ref and "STALLED above tol" not in o_bad,
      "no overlap")

# ------------------------------------------------------ output stays parseable --
print("\nthe warning does not disturb the result")
check("[6] the spectrum table is still emitted alongside the warning",
      len(spectrum(o_bad)) >= 10, f"{len(spectrum(o_bad))} mixes printed")
check("[6] ...and the fundamentals are still there to read",
      spectrum(o_bad).get((1, 0)) is not None, "f1 present")

for f in os.listdir(HERE):
    if f.startswith("_ht_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
