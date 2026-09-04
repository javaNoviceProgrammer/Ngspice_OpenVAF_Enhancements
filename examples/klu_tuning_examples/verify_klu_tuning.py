#!/usr/bin/env python3
"""
verify_klu_tuning.py -- verifies Enhancement-152: user control of KLU's matrix
reordering and scaling, beyond the hard-coded defaults.

This build's KLU linear solver previously ran on its compiled-in defaults (AMD
fill-reducing ordering, max row scaling, BTF permutation on). Enhancement-152
exposes them as `.option`s so they can be tuned:

    .option klu klu_ordering=amd|colamd     fill-reducing ordering
    .option klu klu_scale=none|sum|max      matrix row scaling
    .option klu klu_btf=on|off              block-triangular-form permutation
    .option klu_memgrow_factor=<f>          KLU work-array growth (bugfix: was a no-op)

This is a KLU-only feature, so every deck sets `.option klu` and the verifier
runs under KLU directly (no dual-solver harness).

Checks (a resistor grid -- a matrix big enough that AMD and COLAMD differ):

  [1] every ordering/scaling/BTF setting gives the PHYSICALLY IDENTICAL solution
      (agree to ~1e-10 relative) -- the knobs are safe.
  [2] the knobs actually REACH KLU: AMD vs COLAMD, and scale=max vs scale=none,
      change the factorization arithmetic, so the full-precision result differs in
      its last digits (a tiny, deterministic, nonzero relative difference).
  [3] an invalid value (klu_ordering=foo, ...) is rejected with a warning.
  [4] the compiled-in defaults are unchanged: a plain `.option klu` equals
      `klu_ordering=amd klu_scale=max klu_btf=on` bit-for-bit.
  [5] a wide-dynamic-range (badly-scaled) network solves correctly under every
      scaling mode.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

SCRATCH = tempfile.mkdtemp(prefix="klu_verify_")
_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run(deck):
    with open(os.path.join(SCRATCH, "_k.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_k.cir"], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def grid_body(n=12, r=100.0):
    """A 2-D resistor grid: 1 A injected at one corner, opposite corner grounded."""
    L = [f"iin n_0_0 0 dc 1", f"vg n_{n-1}_{n-1} 0 dc 0"]
    k = 0
    for i in range(n):
        for j in range(n):
            if i + 1 < n:
                k += 1; L.append(f"r{k} n_{i}_{j} n_{i+1}_{j} {r:g}")
            if j + 1 < n:
                k += 1; L.append(f"r{k} n_{i}_{j} n_{i}_{j+1} {r:g}")
    return "\n".join(L)


BODY = grid_body()


def solve(opts, probe="n_3_5"):
    """Return the full-precision v(probe) of the grid under the given klu options."""
    log = run(f"""* KLU tuning probe
{BODY}
.control
  set numdgt=17
  option klu {opts}
  op
  print v({probe})
.endc
.end
""")
    m = re.search(rf"v\(n_3_5\)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log)
    return float(m.group(1)) if m else float("nan"), log


print("Enhancement-152: KLU matrix reordering + scaling controls\n")

# --- reference (defaults) -------------------------------------------------
ref, _ = solve("")
settings = {
    "klu_ordering=amd":  None, "klu_ordering=colamd": None,
    "klu_scale=none": None, "klu_scale=sum": None, "klu_scale=max": None,
    "klu_btf=on": None, "klu_btf=off": None,
}
for s in settings:
    settings[s], _ = solve(s)

# --- [1] physical invariance ---------------------------------------------
print("[1] every setting gives the same physical solution")
worst = max(abs(v - ref) / abs(ref) for v in settings.values())
check("all settings agree with the default to ~1e-10", worst < 1e-9,
      f"max relative spread = {worst:.1e}")

# --- [2] the knobs reach KLU (last-digit arithmetic changes) --------------
print("[2] the knobs reach KLU (change the factorization arithmetic)")
d_ord = abs(settings["klu_ordering=colamd"] - settings["klu_ordering=amd"]) / abs(ref)
d_scl = abs(settings["klu_scale=none"] - settings["klu_scale=max"]) / abs(ref)
check("AMD vs COLAMD change the roundoff (0 < diff < 1e-9)", 0.0 < d_ord < 1e-9,
      f"relative diff = {d_ord:.1e}")
check("scale=max vs scale=none change the roundoff (0 < diff < 1e-9)", 0.0 < d_scl < 1e-9,
      f"relative diff = {d_scl:.1e}")

# --- [3] invalid values rejected -----------------------------------------
print("[3] invalid option values are rejected")
_, log = solve("klu_ordering=foo klu_scale=bar klu_btf=maybe")
check("klu_ordering=foo warns", "unknown klu_ordering" in log)
check("klu_scale=bar warns", "unknown klu_scale" in log)
check("klu_btf=maybe warns", "unknown klu_btf" in log)

# --- [4] defaults unchanged ----------------------------------------------
print("[4] the compiled-in defaults are unchanged")
explicit, _ = solve("klu_ordering=amd klu_scale=max klu_btf=on")
check("plain `.option klu` == amd/max/btf-on bit-for-bit", explicit == ref,
      f"{explicit!r} vs {ref!r}")

# --- [5] wide-dynamic-range network solves under every scaling ------------
print("[5] a badly-scaled network solves correctly under every scaling mode")
ok = True
for sc in ("none", "sum", "max"):
    log = run(f"""* wide-dynamic-range network; v(out) analytic = 0.5
V1 in 0 dc 1
R1 in out 1e9
R2 out 0  1e9
Rp1 in a 1e-3
Rp2 a 0  1e-3
.control
  option klu klu_scale={sc}
  op
  print v(out)
.endc
.end
""")
    m = re.search(r"v\(out\)\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log)
    v = float(m.group(1)) if m else float("nan")
    if abs(v - 0.5) > 1e-9:
        ok = False
    print(f"      scale={sc}: v(out) = {v}")
check("v(out) = 0.5 under none/sum/max scaling", ok)

import shutil
# --- 2026-09-04 large-circuit sweep, F3: rusage's KLU non-zero accounting ----
# A one-way chain (each stage's current source is controlled by the previous
# node) is block-triangular: KLU's BTF puts every coupling entry in its
# off-diagonal-block array (`nzoff`) and the LU of the singleton blocks holds
# only the diagonal. `rusage` computed the fill-in as lnz + unz - nz, which
# counts the diagonal twice and the off-block entries never: a chain with no
# fill-in at all reported "fill-in non-zeroes = -1002". In Sparse mode this
# KLU build also reported "total non-zeroes = 0" on every deck.
print("[F3] rusage non-zero accounting under KLU, and the Sparse-mode total")
def chain_deck(solver, n=200):
    L = ["* one-way chain", f".option {solver}", "vin s0 0 dc 1"]
    for i in range(1, n + 1):
        L += [f"g{i} s{i} 0 s{i-1} 0 1m", f"r{i} s{i} 0 1k"]
    L += [".control", "op", "rusage all", ".endc", ".end"]
    return "\n".join(L) + "\n"
import re as _re
def nz(log):
    g = lambda k: int(_re.search(rf"Circuit {k} non-zeroes = (-?\d+)", log).group(1))
    return g("original"), g("fill-in"), g("total")
o, f, tot = nz(run(chain_deck("klu")))
check("KLU: a block-triangular chain reports a non-negative fill-in",
      f >= 0, f"(fill-in {f}; was -{2 * 200 + 2})")
check("KLU: total non-zeroes = original + fill-in", tot == o + f,
      f"({tot} vs {o} + {f})")
o2, f2, tot2 = nz(run(chain_deck("sparse")))
check("Sparse mode in this KLU build reports a total, not 0", tot2 > 0 and tot2 == o2 + f2,
      f"({tot2} = {o2} + {f2})")
shutil.rmtree(SCRATCH, ignore_errors=True)


print()
if _fail:
    print(f"RESULT: {_fail} check(s) FAILED")
    sys.exit(1)
print("RESULT: all checks passed")
