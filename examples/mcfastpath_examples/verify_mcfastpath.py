#!/usr/bin/env python3
"""Enhancement-346: random draws on the fast `.param` path, and the MC tier.

TWO THINGS, ONE MECHANISM.

**The bug.** The fast `.param` sweep only re-evaluated brace expressions that
MENTION the swept name. numparam inlines a `.param`'s expression into the device
line during preprocessing, so `.param rv = agauss(...)` + `R2 a b {rv}` arrives
as `r2 a b {(agauss(...))}` -- no swept name in it, so it was skipped and left
FROZEN, while the reset path re-drew it at every point. Measured on a 5-point
sweep: reset gave rv = 1097.7, 1015.2, 952.5, 988.7, 969.2; the fast path gave
1161.1 five times. That silently violated the fast path's guarantee that results
never change, only speed.

**The feature.** Once random expressions are captured and re-drawn, Monte Carlo
needs nothing more: a sample is a re-draw plus an in-place push, no re-source.

Exactness rests on consuming the RNG stream exactly as re-sourcing did:
  * random binds are evaluated in DECK ORDER (only they consume the RNG, so the
    stream matches even though deterministic binds are reordered for caching);
  * they are NEVER served from the by-expression-text cache -- two devices with
    identical random text must draw independently, as re-sourcing gives them;
  * a Monte Carlo sample boundary (`mc_sample_advance()`) is raised per pass. A
    re-source signalled that via `nupa_signal(NUPADECKCOPY)`; skipping the
    re-source skipped it, which is why `-lhs` disagreed while plain draws matched.

  [1] `montecarlo` arms the fast path and matches a hand-rolled RESET-loop
      oracle exactly, same seed -- an independent reference, not a golden number
  [2] `-lhs` is stratified and reproducible (the sample-boundary fix)
  [3] the same seed twice gives the same yield
  [4] two devices with identical random text draw INDEPENDENTLY
  [5] a sweep with a random `.param` now re-draws it per point (it was frozen)
  [6] a random reaching a structural slot still falls back to reset
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

ARMED = "montecarlo: fast path armed"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DIVIDER = ".param rv = agauss(1000, 300, 3)\nV1 in 0 dc 1\nRk in m 1k\nR2 m 0 {rv}\n"


def run(name, body, control, timeout=600):
    p = os.path.join(HERE, "_%s.cir" % name)
    with open(p, "w") as f:
        f.write("t %s\n%s.control\n%s\n.endc\n.end\n" % (name, body, control))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.returncode, r.stdout + r.stderr


def yield_of(out):
    m = re.search(r"yield\s*:\s*[\d.]+%\s*\((\d+) / (\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


ORACLE = ("setseed 7\nlet npass = 0\nlet i = 0\n"
          "while i < 200\n  reset\n  op\n"
          "  if (v(m) < 0.52) & (v(m) > 0.48)\n    let npass = npass + 1\n  end\n"
          "  let i = i + 1\nend\necho ORACLE $&npass")
MC = "montecarlo 200 -analysis op -spec v(m) -max 0.52 -min 0.48 -seed 7"


def main():
    # [1] the fast MC command vs an independent reset-loop oracle
    rc, out = run("cmp", DIVIDER, MC)
    y = yield_of(out)
    rc2, out2 = run("oracle", DIVIDER, ORACLE)
    m = re.search(r"^ORACLE\s+(\d+)", out2, re.M)
    oracle = int(m.group(1)) if m else None
    rc = rc or rc2
    check("montecarlo arms the fast path and matches a reset-loop oracle exactly",
          rc == 0 and ARMED in out and y is not None and oracle is not None
          and y[0] == oracle,
          f"fast {y[0] if y else '?'}/{y[1] if y else '?'} vs reset-loop {oracle}")

    # [2] -lhs: stratified and reproducible. Before the sample-boundary fix the
    # sampler never stepped to the next stratified point, so this yield was wrong
    # (measured 239/400 where the reset path gave 258/400 on the E-188 deck).
    ys = []
    for k in range(2):
        rc, out = run("lhs%d" % k, DIVIDER, MC.replace("montecarlo 200",
                                                       "montecarlo 200 -lhs"))
        ys.append(yield_of(out))
    check("`-lhs` is stratified and reproducible across runs",
          rc == 0 and ys[0] is not None and ys[0] == ys[1],
          f"{ys[0]} then {ys[1]}")

    # [3] determinism of the plain path
    rc, out2 = run("det", DIVIDER, MC)
    check("the same seed gives the same yield",
          rc == 0 and yield_of(out2) == y, f"{yield_of(out2)} vs {y}")

    # [4] identical random TEXT must not share a draw. Two resistors both
    # {rv}: if the cache served the second from the first they would be equal,
    # and v(m) would be pinned at exactly 0.5 for every sample.
    body = (".param rv = agauss(1000, 300, 3)\nV1 in 0 dc 1\n"
            "Rk in m {rv}\nR2 m 0 {rv}\n")
    rc, out = run("indep", body,
                  "montecarlo 100 -analysis op -spec v(m) -max 0.5001 "
                  "-min 0.4999 -seed 7")
    yi = yield_of(out)
    # independent draws => v(m) almost never lands inside that narrow window
    check("two devices with identical random text draw independently",
          rc == 0 and yi is not None and yi[0] < yi[1] // 2,
          f"{yi[0]}/{yi[1]} inside a +/-0.0001 window around 0.5")

    # [5] the sweep bug: a random .param must re-draw at every point
    body = (".param k = 1\n.param rv = agauss(1000, 300, 3)\n"
            "V1 in 0 dc 1\nRk in mid {k*1k}\nR2 mid 0 {rv}\n")
    rc, out = run("sweep", body,
                  "setseed 7\nset numdgt=10\n"
                  "sweep k lin 5 1 5 -analysis op -output v(mid)\nprint v(mid)")
    vals = [float(x) for x in
            re.findall(r"^\s*\d+\s+([-\d.]+e[-+]\d+)\s*$", out, re.M)]
    # v = rv/(k*1000 + rv)  =>  rv = v*k*1000/(1-v)
    rvs = [v * (k + 1) * 1000.0 / (1.0 - v) for k, v in enumerate(vals)]
    spread = (max(rvs) - min(rvs)) if rvs else 0.0
    check("a sweep re-draws a random `.param` at every point (it was frozen)",
          rc == 0 and len(rvs) == 5 and spread > 1.0,
          f"rv per point {[round(r, 1) for r in rvs]}")

    # [6] a random reaching a structural slot must fall back to reset
    body = (".param tt = agauss(27, 5, 3)\n.temp 27\nV1 in 0 dc 1\n"
            "Rk in m 1k\nR2 m 0 1k\n.param dummy = {tt}\n")
    rc, out = run("struct", body,
                  "montecarlo 20 -analysis op -spec v(m) -max 1 -min 0 -seed 7")
    check("a random in a structural slot still falls back to the reset path",
          rc == 0 and ARMED not in out and yield_of(out) is not None,
          "did not arm" if ARMED not in out else "ARMED (should not)")

    # the committed deck must arm and report the same count as the oracle above
    r = subprocess.run([NGSPICE, "-b", "mcfastpath.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    t = r.stdout + r.stderr
    yd = yield_of(t)
    check("the committed deck arms and agrees with the reset-loop oracle",
          r.returncode == 0 and "SURVIVED" in t and ARMED in t
          and yd is not None and oracle is not None and yd[0] == oracle,
          f"rc={r.returncode} mc={yd} oracle={oracle}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
