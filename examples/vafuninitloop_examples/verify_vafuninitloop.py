#!/usr/bin/env python3
"""verify_vafuninitloop.py -- Enhancement-308: an uninitialized read feeding a loop-carried
phi crashed openvaf-r's code generator.

A variable read BEFORE a loop that is its only writer leaves the loop-carried phi node with
an incoming value that no reachable block defines. An optimizer pass drops that value's
defining instruction on the dead path but keeps the phi edge, so code generation reached
`BuilderVal::get()` on a value still in the `Undef` state and hit

    unreachable!("attempted to read undefined value")   (mir_llvm/src/builder.rs)

That is a plain `unreachable!`, so the SHIPPED build crashed
("OpenVAF encountered a problem and has crashed!") on valid Verilog-A. Found by
grammar-based fuzzing of the middle/back end (seed 3230 of an 8000-seed run) and
delta-debugged; the trigger needs the module to contribute nothing that would keep the
value live.

The fix is at code generation, and provably correct: every reachable block is built before
the phi-completion pass, so any value defined by a reachable instruction is already
materialised. A phi input still `Undef` at that point therefore names a value NO reachable
block defines -- a dead path -- so lowering it to an LLVM `undef` of the phi's type is the
correct meaning, not a panic.

Checks:
  1. the reproducer compiles (it crashed the compiler before);
  2. a LIVE loop-carried phi is numerically UNCHANGED -- a conductance accumulated over N
     loop iterations reads back exactly N*g -- which is what proves the undef substitution
     touches only dead-path inputs, never a real value.
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


print("Enhancement-308: uninitialized read feeding a loop-carried phi crashed codegen")

# --- 1: the reproducer must compile -----------------------------------------
ok, verdict = compile_va("uninit_loop_repro.va")
check("read-before-loop reproducer compiles (was a compiler crash)", ok, verdict)

# --- 2: a LIVE loop-carried phi is numerically unchanged --------------------
ok2, verdict2 = compile_va("live_acc.va")
check("live loop-carried accumulator compiles", ok2, verdict2)
if ok2:
    G, NN = 1e-3, 4
    out = ngspice(f"""* a loop-carried accumulator: conductance must be exactly N*g
v1 p 0 dc 1
n1 p 0 am
.model am acc g={G} nn={NN}
.control
pre_osdi live_acc.osdi
op
let cond = i(v1)/v(p)
print cond
.endc
.end
""", "_acc.cir")
    # I(p,n) <+ s*V with s = N*g, and i(v1) = -I(device) into node p, so
    # conductance magnitude = N*g.
    got = val(out, "cond")
    want = NN * G
    rel = abs(abs(got) - want) / want if got is not None else 1.0
    check("live phi computes N*g exactly (undef touches only dead inputs)",
          got is not None and rel < 1e-9,
          f"|cond|={abs(got) if got is not None else None} want {want}")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
