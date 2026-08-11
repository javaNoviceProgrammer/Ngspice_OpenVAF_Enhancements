#!/usr/bin/env python3
"""Enhancement-439: a successful klu_refactor is not necessarily a usable one.

`klu_refactor` reuses the pivot ordering chosen by the last full `klu_factor`
and only refills the values -- it performs no pivoting and no singularity test.
When the values have drifted to a numerically singular configuration it fills
the LU with zero (or NaN) pivots, returns SUCCESS, and leaves status = KLU_OK.
The next `klu_solve` returns NaN, and NaN neither converges nor trips any
singularity check, so the Newton loop and every rung of CKTop's homotopy ladder
run to their full iteration budgets on a factorization already known to be bad.

The canonical trigger is a node with NO DC path -- the midpoint of two series
capacitors. That row has no diagonal entry at all, so `LoadGmin_CSC` cannot
apply Gmin to it ("Not all the elements on the diagonal are present"), and once
gmin stepping ramps down far enough the reused pivot order goes singular.

Measured before the fix: KLU failed after 33,911 iterations having produced NaN,
while SPARSE solved the same circuit in 289. This suite pins the split closed
and -- just as importantly -- pins that healthy circuits are untouched, since
the fix adds a check to every refactor.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, solver, timeout=180):
    solver_line = "option klu\n" if solver == "klu" else ""
    deck = (f"klusingular {tag}\n{body}\n.control\noption noacct\n{solver_line}"
            f"{ctl}\nrusage everything\n.endc\n.end\n")
    p = os.path.join(HERE, f"_ks_{tag}_{solver}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    out = r.stdout + r.stderr
    v = re.search(r"v\(nb\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)
    it = re.search(r"Total iterations\s*=\s*(\d+)", out)
    return dict(out=out,
                v=float(v.group(1)) if v else None,
                it=int(it.group(1)) if it else None,
                failed=bool(re.search(r"(?i)operating point could not be simulated",
                                      out)),
                nan=bool(re.search(r"\bnan\b", out)))


# The midpoint of two series capacitors has no DC path. The divider it sits
# beside is well determined and must read exactly 0.5 either way.
FLOAT = """V1 in 0 dc 1
C1 in mid 1u
C2 mid 0 1u
R1 in nb 1k
R2 nb 0 1k"""

print("Enhancement-439: KLU must not accept a singular refactor\n")

print("a node with no DC path -- KLU used to fail where SPARSE succeeded")
rs = run(FLOAT, "op\nprint v(nb)", "float", "sparse")
rk = run(FLOAT, "op\nprint v(nb)", "float", "klu")
check("[E-439] SPARSE solves it (the reference behaviour)",
      not rs["failed"] and rs["v"] is not None and abs(rs["v"] - 0.5) < 1e-9,
      f"v(nb)={rs['v']} iters={rs['it']}")
check("[E-439] KLU now solves it too",
      not rk["failed"] and rk["v"] is not None and abs(rk["v"] - 0.5) < 1e-9,
      f"v(nb)={rk['v']} iters={rk['it']}")
check("[E-439] ...to the same answer as SPARSE",
      rs["v"] is not None and rk["v"] is not None
      and abs(rs["v"] - rk["v"]) <= 1e-9,
      f"sparse={rs['v']} klu={rk['v']}")
check("[E-439] no NaN reaches the output",
      not rk["nan"])
# The old failure burned 33,911 iterations; the rescue costs about what SPARSE
# costs. A generous bound catches a regression without being brittle.
check("[E-439] and it costs a comparable number of iterations, not 100x",
      rk["it"] is not None and rs["it"] is not None and rk["it"] < 4 * rs["it"],
      f"klu={rk['it']} sparse={rs['it']}")

print("\nthe rescue survives with each convergence aid disabled")
for tag, name, opt in (("nogmin", "no gmin stepping", "option gminsteps=0\n"),
                       ("nosrc", "no source stepping", "option srcsteps=0\n"),
                       ("noaids", "neither", "option gminsteps=0 srcsteps=0\n")):
    r = run(FLOAT, opt + "op\nprint v(nb)", "aid" + tag, "klu")
    check(f"[E-439] KLU still solves it with {name}",
          not r["failed"] and r["v"] is not None and abs(r["v"] - 0.5) < 1e-9,
          f"v(nb)={r['v']} iters={r['it']}")

print("\nCONTROLS -- healthy circuits must be untouched by the added check")
HEALTHY = [
    ("plain divider", "V1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k", 0.5),
    ("diode", "V1 in 0 dc 0.7\nR1 in nb 1k\nD1 nb 0 dm\n.model dm d(is=1e-14)", None),
    ("mos inverter", "Vdd vdd 0 dc 5\nVin a 0 dc 2.5\nM1 nb a 0 0 nm w=2u l=1u\n"
                     "R1 vdd nb 20k\n.model nm nmos(level=1 vto=1 kp=100u)", None),
]
for name, body, expect in HEALTHY:
    a = run(body, "op\nprint v(nb)", "h" + name.split()[0], "sparse")
    b = run(body, "op\nprint v(nb)", "h" + name.split()[0], "klu")
    same = (a["v"] is not None and b["v"] is not None
            and abs(a["v"] - b["v"]) <= 1e-9 * max(1.0, abs(a["v"])))
    check(f"[E-439] {name}: both solvers agree", same,
          f"sparse={a['v']} klu={b['v']}")
    check(f"[E-439] {name}: iteration count unchanged between solvers",
          a["it"] is not None and b["it"] is not None and abs(a["it"] - b["it"]) <= 2,
          f"sparse={a['it']} klu={b['it']}")
    if expect is not None:
        check(f"[E-439] {name}: analytic value", abs(b["v"] - expect) < 1e-9,
              f"{b['v']} vs {expect}")

# A transient exercises the refactor path hard -- that is where the added check
# runs, so it must not change the result there either.
print("\nthe refactor path under a transient is unaffected")
TR = ("V1 in 0 dc 0 sin(0 1 1k)\nRin in n1 100\n"
      + "\n".join(f"R{i} n{i} n{i+1} 100\nD{i} n{i} 0 dm" for i in range(1, 30))
      + "\nRend n30 0 100\nRnb n1 nb 1\nRnb2 nb 0 1e12\n.model dm d(is=1e-14)")
a = run(TR, "tran 20u 400u\nmeas tran m MAX v(n1)", "tr", "sparse")
b = run(TR, "tran 20u 400u\nmeas tran m MAX v(n1)", "tr", "klu")
ma = re.search(r"^\s*m\s*=\s*(\S+)", a["out"], re.M)
mb = re.search(r"^\s*m\s*=\s*(\S+)", b["out"], re.M)
check("[E-439] a 30-diode transient gives the same answer on both solvers",
      bool(ma) and bool(mb) and ma.group(1) == mb.group(1),
      f"sparse={ma.group(1) if ma else '?'} klu={mb.group(1) if mb else '?'}")

for junk in os.listdir(HERE):
    if junk.startswith("_ks_"):
        os.remove(os.path.join(HERE, junk))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
