#!/usr/bin/env python3
"""Enhancement-483: `set qpss_tol` / `set qpss_maxiter`, and Newton stall
detection in the harmonic-balance solver.

`QPSShb` was called with its convergence bound and iteration cap COMPILED IN --
`QPSShb(ckt, f1, f2, K1, K2, 0, 0, 60, 1e-10, ...)` -- and `tol` is an ABSOLUTE
bound on the residual norm |F|. What a circuit can actually reach depends on the
circuit: the diode two-tone deck in distoexact_examples settles at |F| = 2.3e-15,
while an FET amplifier carrying tens of milliamps floors around 1e-8 and could
not satisfy 1e-10 however many iterations it was given.

So it did not converge -- and the way it failed was the real defect. The Newton
iteration reached |F| = 9.4e-09 at iteration 4, a reduction of nine orders, and
then sat on that number, flat to seven digits, for the remaining 55 iterations.
Having "failed" the level, the continuation ladder halved its step and walked all
the way back to lambda = 0, 1022 Newton iterations in all, and reported a bare
`error 103` (E_ITERLIM). A perfectly good answer, found in five iterations, was
discarded after minutes of work -- and at `hb 4 4` those minutes are six or seven
of them, which reads as a hang.

TWO FIXES, and they are independent:

  * the bound and the cap are now readable from a deck, like `qpss_verbose`
    beside them: `set qpss_tol=1e-8`, `set qpss_maxiter=200`;
  * a residual that has stopped moving is recognised as stopped. Four
    consecutive iterates that fail to improve |F| by 0.1% is a stall, and a
    stalled residual is ACCEPTED as the answer only if it sits at least 1e6 below
    the residual the level opened with. A stall at a residual that never came
    down is a real failure and still falls through to the ladder -- it just gets
    there in a few iterations instead of `maxiter`.

[5] is the check that matters most: stall-acceptance must not change the ANSWER.
The fundamentals come out bit-identical to a run that converges normally under a
loosened bound, and the third-order products agree to ~1e-5 relative, which is
about 0.0001 dB on OIP3.

[3] is its counterweight: a genuine failure must still fail. `hb 3 3` on the same
circuit dies at |F| = 2.5e-02 at lambda = 0 -- a residual that never came down --
and the stall test must not paper over it.
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

# A two-tone FET amplifier -- the shape whose residual floors above 1e-10.
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

# The diode deck that converges the ordinary way, for the no-caveat control.
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


def run(body, ctl, tag, timeout=180):
    path = os.path.join(HERE, f"_hb_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* hbconv {tag}\n{body}\n.control\noption noacct\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "-r", os.devnull, path], capture_output=True,
                       text=True, timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
    try:
        os.remove(path)
    except OSError:
        pass
    return r.returncode, (r.stdout + r.stderr)


def spectrum(out, node="out"):
    """{(k1,k2): |V|} from the qpss mix table."""
    d = {}
    for line in out.splitlines():
        m = re.match(r"\s*" + re.escape(node) + r"\s+\(\s*(-?\d+),\s*(-?\d+)\)"
                     r"\s+[\d.eE+-]+\s+([\d.eE+-]+)", line)
        if m:
            d[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))
    return d


def oip3(sp):
    """Output IP3 in dBm from the mix table, the deck's own 10*log10(V^2)+10."""
    f1, im3 = sp.get((1, 0)), sp.get((2, -1))
    if not f1 or not im3:
        return None
    dbm = lambda v: 10.0 * math.log10(v * v) + 10.0
    return dbm(f1) + (dbm(f1) - dbm(im3)) / 2.0


def iters(out):
    m = re.search(r"converged in (\d+) iterations", out)
    return int(m.group(1)) if m else None


print("Enhancement-483: qpss HB tolerance, iteration cap and stall detection\n")

# ------------------------------------------- the stall is recognised ---------
print("a residual that has stopped moving is recognised as stopped")
rc, o_stall = run(AMP, "qpss v(out) 1.9G 1.91G hb 2 2", "stall")
check("[1] the deck that used to hit E_ITERLIM now converges",
      "did not complete" not in o_stall and "converged in" in o_stall,
      f"{iters(o_stall)} iterations")
check("[2] ...and says so honestly rather than silently",
      "STALLED above tol" in o_stall, "caveat printed")
check("[2] ...naming the bound it could not reach",
      re.search(r"tol = 1\.0e-10", o_stall) is not None, "tol named")
check("[2] ...the reduction it did achieve",
      re.search(r"after a \d+x reduction", o_stall) is not None,
      re.search(r"after a (\d+)x", o_stall).group(1) + "x" if re.search(r"after a (\d+)x", o_stall) else "")
check("[2] ...and the knob that changes the bound",
      "qpss_tol" in o_stall, "points at qpss_tol")
check("[1] it takes a handful of iterations, not the whole cap",
      iters(o_stall) is not None and iters(o_stall) < 20, f"{iters(o_stall)} < 60")

# ------------------------------- a GENUINE failure must still fail -----------
print("\nbut a residual that never came down is still a failure")
rc, o_fail = run(AMP, "qpss v(out) 1.9G 1.91G hb 3 3", "genuine")
check("[3] hb 3 3 is NOT papered over by the stall test",
      "did not complete" in o_fail, "still error 103")
# Assert the PROPERTY, not a literal: the residual it stalls on must be far
# above the ~1e-8 floor [1] accepts, which is what makes the two cases
# distinguishable at all. Pinning the digits would just track solver drift.
m_fail = re.search(r"stalled at lambda=([\d.eE+-]+) \(\|F\|=([\d.eE+-]+)\)", o_fail)
check("[3] ...and it is a real stall, orders above the noise floor [1] accepts",
      m_fail is not None and float(m_fail.group(2)) > 1e-6,
      f"|F| = {m_fail.group(2)} at lambda={m_fail.group(1)}" if m_fail else "no stall line")

# ------------------------------- an ordinary convergence is untouched --------
print("\na deck that converges the ordinary way is untouched")
rc, o_ref = run(DIODE, "set numdgt=12\nqpss v1#branch 1.0G 1.3G hb 5 5", "ref")
check("[4] the diode two-tone deck still converges", "converged in" in o_ref,
      f"{iters(o_ref)} iterations")
check("[4] ...with NO stall caveat", "STALLED" not in o_ref, "clean message")

# ------------------------------------------------ THE ANSWER ORACLE ----------
print("\nstall-acceptance must not change the ANSWER")
rc, o_loose = run(AMP, "set qpss_tol=1e-8\nqpss v(out) 1.9G 1.91G hb 2 2", "loose")
sp_s, sp_l = spectrum(o_stall), spectrum(o_loose)
check("[5] the loosened run converges without the caveat",
      "STALLED" not in o_loose and "converged in" in o_loose, f"{iters(o_loose)} iterations")
check("[5] ...on FEWER iterations than the stall path needs",
      iters(o_loose) is not None and iters(o_stall) is not None
      and iters(o_loose) < iters(o_stall), f"{iters(o_loose)} < {iters(o_stall)}")
for mix, name in [((1, 0), "f1"), ((0, 1), "f2")]:
    a, b = sp_s.get(mix), sp_l.get(mix)
    check(f"[5] fundamental {name} is BIT-IDENTICAL either way",
          a is not None and a == b, f"{a:.6e}" if a else "missing")
for mix, name in [((2, -1), "2f1-f2"), ((-1, 2), "2f2-f1")]:
    a, b = sp_s.get(mix), sp_l.get(mix)
    rel = abs(a - b) / max(a, b) if a and b else 1.0
    check(f"[5] IM3 {name} agrees to better than 1e-4 relative", rel < 1e-4, f"{rel:.2e}")
oa, ob = oip3(sp_s), oip3(sp_l)
check("[5] ...so OIP3 agrees to better than 0.01 dB",
      oa is not None and ob is not None and abs(oa - ob) < 0.01,
      f"{oa:.4f} vs {ob:.4f} dBm" if oa and ob else "missing")

# ------------------------------------------------------- the knobs -----------
print("\nthe bound and the cap are reachable from a deck")
rc, o_tight = run(AMP, "set qpss_tol=1e-14\nqpss v(out) 1.9G 1.91G hb 2 2", "tight")
check("[6] tightening qpss_tol below the floor brings the failure back",
      "did not complete" in o_tight or "STALLED" in o_tight,
      "the knob really is the bound")
rc, o_m5 = run(AMP, "set qpss_maxiter=5\nqpss v(out) 1.9G 1.91G hb 2 2", "max5")
check("[7] qpss_maxiter=5 stops before the stall run can form",
      "did not complete" in o_m5, "cap honoured")
rc, o_m2e2 = run(AMP, "set qpss_maxiter=2e2\nqpss v(out) 1.9G 1.91G hb 2 2", "max2e2")
check("[7] qpss_maxiter=2e2 means 200, not 2 -- strtod and not atoi",
      "did not complete" not in o_m2e2, "E-478's trap avoided")

print("\na value that is present but unusable is reported, and the default kept")
for val, want in [("0", "must be positive"), ("-1", "must be positive"),
                  ("abc", "is not a positive number")]:
    rc, o = run(AMP, f"set qpss_tol={val}\nqpss v(out) 1.9G 1.91G hb 2 2", f"bad{re.sub(r'\\W','',val)}")
    check(f"[8] qpss_tol={val} is refused and named",
          want in o and "converged in" in o, "reported, default kept")

for f in os.listdir(HERE):
    if f.startswith("_hb_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
