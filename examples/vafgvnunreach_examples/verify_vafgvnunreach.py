#!/usr/bin/env python3
"""verify_vafgvnunreach.py -- Enhancement-309: GVN crashed on a user in an unreachable block.

Global value numbering, when an instruction's congruence class changes, re-queues every
instruction that USES it. It looked up each user's position with

    self.dfs_map.inst_to_dfs[inst].unwrap_unchecked()

but `DFSMapping::populate` only numbers instructions reachable through `cfg_postorder`, so a
user living in an UNREACHABLE block has no DFS id. `unwrap_unchecked` then hit
`PackedOption::unwrap()` and panicked under debug-assertions; in release it returned the
reserved sentinel id, which `touched_insts.insert` used as an out-of-range BitSet index --
either way the SHIPPED compiler crashed ("OpenVAF encountered a problem and has crashed!").

Found by the same grammar-based middle/back-end fuzzer as E-307/E-308 (seed 6716). The fix
skips users with no DFS id -- they are not in the GVN work list, so re-queuing them is a
no-op -- exactly as `get_rank` in the same file already tolerates the identical `None`.

Checks:
  1. the reproducer compiles (it crashed the compiler before);
  2. a common-subexpression-heavy model that GVN actively optimises still computes the
     exact closed-form result, proving the fix does not disturb the pass.
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


def val(out, vec):
    m = re.search(rf"^{re.escape(vec)}\s*=\s*([-\d.eE+]+)", out, re.M | re.I)
    return float(m.group(1)) if m else None


print("Enhancement-309: GVN crashed on a user instruction in an unreachable block")

# --- 1: the reproducer must compile -----------------------------------------
ok, verdict = compile_va("gvn_unreach_repro.va")
check("GVN unreachable-user reproducer compiles (was a compiler crash)", ok, verdict)

# --- 2: GVN still optimises reachable code correctly ------------------------
ok2, verdict2 = compile_va("gvn_cse.va")
check("common-subexpression model compiles", ok2, verdict2)
if ok2:
    G, V = 1e-3, 2.0
    out = ngspice(f"""* GVN must fold the CSEs and still give d = 4*V*g + (V*g)^2
v1 p 0 dc {V}
n1 p 0 gm
.model gm gvn g={G}
.control
pre_osdi gvn_cse.osdi
op
print -i(v1)
.endc
.end
""", "_cse.cir")
    got = val(out, "-i(v1)")
    want = 4 * V * G + (V * G) ** 2
    rel = abs(got - want) / want if got is not None else 1.0
    check("GVN-optimised result is exact (d = 4*V*g + (V*g)^2)",
          got is not None and rel < 1e-9,
          f"got {got if got is None else format(got,'.9g')} want {want:.9g}")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
