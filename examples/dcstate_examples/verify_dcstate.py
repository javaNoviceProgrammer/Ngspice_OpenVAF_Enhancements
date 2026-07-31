#!/usr/bin/env python3
"""Enhancement-380: a `.dc` sweep must not inherit integration coefficients.

Found by cross-analysis STATE fuzzing with a NUMERIC oracle -- for every ordered
pair of analyses, `result(B after A)` must equal `result(B alone)`. Earlier rounds
of that campaign used ASan and so could only see memory damage; this asserts the
ANSWER, and caught a silent 45% error.

THE DEFECT. `dioload.c` gates its charge branch on

    MODEDCTRANCURVE | MODETRAN | MODEAC | MODEINITSMSIG

so a charge-storing device DOES take that path during a `.dc` sweep, ending in
`NIintegrate()`, which returns `geq = CKTag[0] * cap`. In a fresh session
`CKTag[]` has never been computed, so it is zero, `geq` is zero, and charge
contributes nothing to a DC sweep -- the correct behaviour. But `CKTag[]` is plain
circuit state and `dctrcurv.c` never initialised it, so after any analysis that
drives the transient machinery it still held that analysis' coefficients, where
`ag[0] ~ 1/delta` is large. The sweep then added a spurious `geq = ag[0]*cap` to
every charge-storing device.

    op          ->  0.16666666452   correct  (v(mid) = V1/3 exactly)
    pss ; dc    ->  0.09391732333   44% low, silently

THE ACCEPT HALF IS THE POINT OF THIS FILE. The fix touches the DC sweep's
convergence path, so most of what follows checks that ordinary sweeps are
untouched: linear and nonlinear, single- and multi-point, nested, repeated, and
sweeps of circuits that genuinely carry charge. A fix that zeroed too much would
break continuation and show up here.

TWO DEAD ENDS, recorded so they are not re-tried:
  * `CKTmode` leaking `MODEINITSMSIG` out of PSS -- real (PSS sets it ~20 times
    and never restores it) but not the channel: `dctrcurv.c` fully reassigns
    `CKTmode` at the head of the sweep.
  * The state-ring rotation pulling stale `CKTstates[]` into `CKTstate0`. This
    was implemented and instrumented to prove it ran; the answer was UNCHANGED.
    The stale value is the coefficient, not the stored charge.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

# v(mid) = V1 * (1k||1k)/(1k + 1k||1k) = V1/3 exactly, and the diode across it
# draws a negligible current at these biases. The 1p junction capacitance is what
# makes the device carry charge -- with cjo=0 the defect cannot arise at all.
NET = """dcstate
V1 in 0 dc 0.5 sin(0.5 0.05 1meg)
V2 out 0 dc 0
Rs in mid 1k
Rv mid 0 1k
Cv mid 0 1n
Rl mid out 1k
D1 mid 0 dm
.model dm d(is=1e-14 n=1 rs=0 cjo=1p tt=0)
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, tag, net=NET):
    p = os.path.join(HERE, "_dcs_%s.cir" % tag)
    open(p, "w").write(net + ".control\noption noacct\nset numdgt=12\n"
                       + body + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def sweep_vals(out):
    """The v(mid) column of a printed sweep."""
    return [float(m.group(2)) for m in
            re.finditer(r"^\s*\d+\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$", out, re.M)]


EXACT = {0.0: 0.0, 0.5: 1.0 / 6.0, 1.0: 1.0 / 3.0}   # v(mid) = V1/3


def main():
    # ---- 1. the defect itself: a preceding transient-machinery analysis -------
    ref = sweep_vals(run("dc V1 0 1 0.5\nprint v(mid)", "ref"))
    check("baseline: dc alone matches the exact divider V1/3", len(ref) == 3
          and all(abs(v - EXACT[round(i * 0.5, 1)]) < 2e-6 for i, v in enumerate(ref)),
          "%s" % ["%.9f" % v for v in ref])

    for name, first in (("pss", "pss 1meg 2u 0 512 5 50 3u"),
                        ("tran", "tran 50n 5u"),
                        ("envelope", "envelope mid 1meg 20u")):
        got = sweep_vals(run("%s\ndc V1 0 1 0.5\nprint v(mid)" % first, "a_" + name))
        ok = len(got) == len(ref) and all(abs(a - b) <= 1e-9 * max(abs(a), 1.0)
                                          for a, b in zip(ref, got))
        dev = (max(abs(a - b) / max(abs(a), 1e-30) for a, b in zip(ref, got))
               if len(got) == len(ref) else float("nan"))
        check("dc after %-8s equals dc alone" % name, ok,
              "max rel dev %.2e" % dev if len(got) == len(ref)
              else "%d vs %d points" % (len(ref), len(got)))

    # the diode's own operating point must stay self-consistent: gd = id/(n*Vt)
    out = run("pss 1meg 2u 0 512 5 50 3u\ndc V1 1 1 1\n"
              "print @d1[vd] @d1[id] @d1[gd]", "cons")
    g = {k: float(v) for k, v in re.findall(r"@d1\[(\w+)\]\s*=\s*([-+0-9.eE]+)", out)}
    ok = g and abs(g.get("gd", 0) - g.get("id", 0) / 0.025852) <= 0.02 * abs(
        g.get("gd", 1))
    check("after pss the diode's gd is consistent with its own id", ok,
          "gd=%.4g  id/(n*Vt)=%.4g" % (g.get("gd", 0), g.get("id", 0) / 0.025852)
          if g else "no operating point")

    # ---- 2. THE ACCEPT HALF: ordinary sweeps must be untouched ---------------
    # a fine nonlinear sweep genuinely relies on point-to-point continuation
    fine = sweep_vals(run("dc V1 0 1 0.05\nprint v(mid)", "fine"))
    check("a 21-point sweep still tracks V1/3 at every point",
          len(fine) == 21 and all(abs(v - (i * 0.05) / 3.0) < 2e-5
                                  for i, v in enumerate(fine)),
          "%d points, max dev %.2e" % (len(fine),
              max(abs(v - (i * 0.05) / 3.0) for i, v in enumerate(fine))) if fine else "none")

    # a single-point sweep, and a repeated sweep in one session
    # a one-point sweep prints as a SCALAR, not an indexed table
    m1 = re.search(r"^v\(mid\)\s*=\s*([-+0-9.eE]+)",
                   run("dc V1 0.5 0.5 0.1\nprint v(mid)", "one"), re.M)
    check("single-point sweep is correct",
          m1 is not None and abs(float(m1.group(1)) - 1 / 6) < 2e-6,
          "%.9f" % float(m1.group(1)) if m1 else "none")
    twice = sweep_vals(run("dc V1 0 1 0.5\ndc V1 0 1 0.5\nprint v(mid)", "twice"))
    check("a second sweep in the same session repeats the first",
          len(twice) == 3 and all(abs(a - b) < 1e-12 for a, b in zip(ref, twice)),
          "identical" if len(twice) == 3 else "%d points" % len(twice))

    # a genuinely charge-dominated circuit swept normally: a forward-biased
    # diode where the junction capacitance is large. If the fix over-cleared,
    # this is where a DC sweep would start disagreeing with its own .op.
    bignet = NET.replace("cjo=1p", "cjo=100p")
    sw = sweep_vals(run("dc V1 0 1 0.5\nprint v(mid)", "bigc", bignet))
    op = run("op\nprint v(mid)", "bigcop", bignet)
    m = re.search(r"^v\(mid\)\s*=\s*([-+0-9.eE]+)", op, re.M)
    # the sweep and the .op are two different solve paths, so they agree to
    # ngspice's convergence tolerance rather than to the last bit
    check("a 100x larger junction capacitance does not change the DC answer",
          len(sw) == 3 and m and abs(sw[1] - float(m.group(1))) < 1e-7,
          "sweep@0.5=%.9f  op=%.9f  (delta %.1e)"
          % (sw[1], float(m.group(1)), abs(sw[1] - float(m.group(1))))
          if sw and m else "none")

    # nested sweep (two sources) still works
    out = run("dc V1 0 1 0.5 V2 0 0.2 0.2\nprint v(mid)", "nest")
    nv = sweep_vals(out)
    check("a nested two-source sweep still runs", len(nv) >= 6,
          "%d points" % len(nv))

    # and the op is unchanged by all of this
    m = re.search(r"^v\(mid\)\s*=\s*([-+0-9.eE]+)",
                  run("op\nprint v(mid)", "op"), re.M)
    check("a plain .op is unaffected", m and abs(float(m.group(1)) - 1/6) < 2e-6,
          "%.9f" % float(m.group(1)) if m else "none")

    for j in os.listdir(HERE):
        if j.startswith("_dcs_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
