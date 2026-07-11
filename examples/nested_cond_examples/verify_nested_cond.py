#!/usr/bin/env python3
"""
verify_nested_cond.py -- Enhancement-147: nested conditional (?:) expressions no
longer take exponential time to compile.

openvaf-r's body validator fell through from the `Select` (ternary) arm to a generic
`walk_child_exprs`, re-validating both branches a second time; a chain of N nested
`?:` was therefore validated 2^N times. A depth ~30 chain -- easily produced by
macros -- hung the compiler. The fix returns from the `Select` arm (like the `Call`
and `Path` arms), making validation O(N).

Checks:
  [1] deeply nested `?:` chains compile in bounded, roughly LINEAR time (depth 20,
      40, 80, 160) -- pre-fix, depth 40 already hung (>30 s); 2^160 is astronomical.
  [2] compile time grows ~linearly, not exponentially (t(160) < 20 * t(20)).
  [3] a nested-ternary model still compiles to a valid .osdi and computes the
      correct piecewise value in ngspice (correctness preserved).
"""
import os, re, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))

HDR = '`include "disciplines.vams"\n'
def nested_module(depth):
    e = "0.0"
    for i in range(depth):
        e = f"(V(a,b)>{i}?{i}*V(a,b):{e})"
    return HDR + "module m(a,b); inout a,b; electrical a,b;\nanalog I(a,b)<+" + e + ";\nendmodule\n"

def compile_time(depth, timeout=40):
    p = os.path.join(tempfile.gettempdir(), f"nc_{depth}.va")
    with open(p, "w") as f:
        f.write(nested_module(depth))
    out = p.replace(".va", ".osdi")
    t = time.time()
    try:
        r = subprocess.run([OPENVAF, p, "-o", out], capture_output=True, text=True, timeout=timeout)
        dt = time.time() - t
        ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        dt, ok = float("inf"), False
    for q in (p, out):
        if os.path.exists(q):
            os.remove(q)
    return dt, ok

print("Enhancement-147: nested conditional (?:) validation is O(N), not O(2^N)")

# [1] deep chains compile in bounded time
times = {}
for d in (20, 40, 80, 160):
    dt, ok = compile_time(d)
    times[d] = dt
    check(f"nested ?: depth {d} compiles (<30 s)  [{dt:.2f}s]", ok and dt < 30.0,
          f"{dt:.2f}s ok={ok}")

# [2] growth is ~linear, not exponential
lin = all(times[d] < float("inf") for d in times)
ratio = times[160] / max(times[20], 1e-3)
check(f"compile time grows ~linearly (t160/t20 = {ratio:.1f}, must be < 20 and finite)",
      lin and ratio < 20.0, f"ratio={ratio:.1f}")

# [3] correctness: a nested-ternary model compiles and computes the right value
osdi = os.path.join(HERE, "pwl_conductance.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "pwl_conductance.va"), "-o", osdi],
                   capture_output=True, text=True, timeout=60)
check("nested-ternary model compiles to a valid .osdi", r.returncode == 0 and os.path.exists(osdi),
      r.stderr[-300:])

if os.path.exists(osdi):
    # g(V=2.5) is in the (2,3] band -> 1/3k; I = g*V = 2.5/3000 = 8.3333e-4
    deck = ("nested ternary conductance check\n"
            "Vt a 0 dc 2.5\nN1 a 0 pwlmod\n.model pwlmod pwl_conductance\n"
            ".control\n"
            f"pre_osdi {osdi}\n"
            "dc Vt 2.5 2.5 1\n"
            "let ii = abs(i(vt))\nprint ii\n.endc\n.end\n")
    p = os.path.join(HERE, "_nc.cir")
    with open(p, "w") as f:
        f.write(deck)
    o = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=60)
    os.remove(p)
    txt = o.stdout + o.stderr
    m = re.search(r"(?im)^\s*ii\s*=\s*([-\d.eE+]+)", txt)
    ival = float(m.group(1)) if m else None
    expect = 2.5 / 3000.0
    check(f"nested-ternary model computes the right piecewise value (I(2.5V)={ival})",
          ival is not None and abs(ival - expect) / expect < 1e-3, str(ival))
    os.remove(osdi)
else:
    check("nested-ternary model computes the right piecewise value", False)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
