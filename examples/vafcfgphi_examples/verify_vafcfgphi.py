#!/usr/bin/env python3
"""verify_vafcfgphi.py -- Enhancement-310: a constant-branch fold left an SSA-invalid phi.

`simplify_cfg`'s `const_fold_terminator`, when it folds a constant branch and removes the
dead edge, can leave a block orphaned. The orphan sweep in `simplify_bb` normally fixes the
phis in that block's successors -- but only when the block has no live results (a guard for
`mir_autodiff`'s not-yet-placed instructions). So an orphan whose values are still
referenced in place survives, and a phi in one of its successors keeps an edge naming a
value that was only reachable through the deleted edge: an SSA-invalid phi.

That tripped `debug_assert!(cx.func.validate())` at `sim_back/src/lib.rs`. It was NOT a
shipped crash (a `debug_assert`, so release compiled the model without error) and, as this
suite checks, NOT a miscompile either.

Found by grammar-based middle/back-end fuzzing (the same campaign as E-307/308/309), then
delta-debugged and sanitised to clean, convergent math so the output is well-defined.

The fix declines the fold in exactly this case: when removing the edge would orphan a block
that still has live results. Declining an optimisation is always output-preserving, so the
model's numbers are unchanged; the branch is folded later once the block can be cleaned up
safely.

Note on what this suite can and cannot show. The defect was benign and ASSERTIONS-ONLY: the
shipped (release) compiler never crashed and, as proven during the fix, produced bit-identical
output to a valid-MIR reference. So a suite driven by the release binary passes on BOTH the
pre-fix and post-fix compilers -- it cannot "fail on the pre-fix binary" the way the crash
suites do. The authoritative before/after evidence is elsewhere: an assertions-enabled build
panics at `sim_back/lib.rs` before the fix and compiles cleanly after, and the whole 332-model
corpus produces bit-identical output pre/post. What this suite guards is FORWARD correctness:
the model reduces (kk=0, at DC) to a linear conductance -- I(p,n) = g*(0.5 + ra + rb + V(p,n))
with ra=1, rb=2 fixed by the branch -- so its DC response must stay finite and exactly linear.
A future change that turned this into an actual miscompile would break that linearity.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    osdi = os.path.join(HERE, name.replace(".va", ".osdi"))
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi],
                           capture_output=True, text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if "has crashed" in out or "panicked at" in out:
        return False, "COMPILER CRASH"
    if r.returncode != 0:
        return False, f"exit {r.returncode}"
    return os.path.exists(osdi), "compiled"


def ngspice(deck, name):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


print("Enhancement-310: constant-branch fold left an SSA-invalid phi (validate assert)")

ok, verdict = compile_va("cfgphi_repro.va")
check("reproducer compiles (tripped the validate debug_assert before)", ok, verdict)

if ok:
    # I(p,n) = g*(0.5 + ra + rb + V(p,n)), ra=1, rb=2 -> g*(3.5 + V(p,n)).
    # A DC sweep of Vp with V(n) pinned near 0 (1k to ground) reads the device current.
    # Two sweep points suffice to pin down slope (= g) and offset.
    out = ngspice("""* linear-conductance check over many points
v1 p 0 dc 0.6
v2 m 0 dc 0.3
n1 p n m md
.model md fz
r1 n 0 1k
.control
pre_osdi cfgphi_repro.osdi
dc v1 0.1 1.0 0.05
wrdata _o.dat i(v1)
.endc
.end
""", "_c.cir")
    finite = "nan" not in out.lower() and "singular" not in out.lower()
    check("simulates to a finite operating point", finite)
    p = os.path.join(HERE, "_o.dat")
    rows = []
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            if len(f) >= 2:
                try:
                    rows.append((float(f[0]), float(f[1])))
                except ValueError:
                    pass
    if len(rows) >= 4:
        # The DC response must be EXACTLY linear: every consecutive slope equal to the
        # first, to machine precision. A miscompiled branch (wrong ra/rb on some path)
        # would introduce a kink -- a slope that changes partway through the sweep.
        slopes = [(rows[k + 1][1] - rows[k][1]) / (rows[k + 1][0] - rows[k][0])
                  for k in range(len(rows) - 1)]
        s0 = slopes[0]
        max_dev = max(abs(s - s0) for s in slopes)
        check("DC response is exactly linear (no kink) -- forward miscompile guard",
              all(abs(y) < 1 for _, y in rows) and max_dev <= 1e-9 * abs(s0),
              f"slope={s0:.6e}, max deviation {max_dev:.2e}")
    else:
        check("output rows present", False, f"{len(rows)} rows")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
