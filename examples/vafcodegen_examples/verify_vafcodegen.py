#!/usr/bin/env python3
"""verify_vafcodegen.py -- Enhancements 286-293: eight openvaf-r optimizer/code-generator
defects found by a targeted robustness campaign against the committed compiler.

Five of the eight aborted the compile outright; two produced LLVM IR that the module
verifier rejects; one produced a wrong memory offset. What made the last three durable is
that every check that would have caught them -- the MIR verifier and the LLVM module
verifier -- sits behind a `debug_assert!`, so a release build carried the malformed
function or the bad offset forward without a word:

  [286] constfold.va    -- folding `5/0` (or `5%0`, `i32::MIN/-1`, an out-of-range shift)
                           EVALUATED the operation inside the compiler, so openvaf-r died
                           with an internal error. A runtime zero divisor was always
                           accepted, so a literal one must be too.
  [287] orphanblock.va  -- a noise operator in an `if` CONDITION lets the optimizer fold
                           the branch; folding it orphaned a block, but the sweep never
                           re-ran, leaving a phi edge naming a value reachable only
                           through the deleted edge -- a broken-SSA function.
  [288] hypotclog2.va   -- `hypot` declared with ONE parameter but called with two.
  [289] hypotclog2.va   -- `llvm.ctlz` needs its type suffix (`llvm.ctlz.i32`); it backs
                           `$clog2`.
  [290] tempacstim.va   -- `$temperature` as an operator argument took a struct-GEP handed
                           the FIELD type instead of the instance struct, so the offset
                           came out as a flat `5*sizeof(double)` rather than
                           `offsetof(instance, temperature)`. The shipped compiler died
                           with SIGSEGV (exit 139) optimizing this model.
  [291] casemax.va      -- `max`/`min`/`abs` in a `case` DEFAULT arm left the case's
                           fall-through block unsealed ("block N is not sealed").
  [292] ssprune.va      -- small-signal pruning indexed a map with a key its own replay
                           never inserted ("no entry found for key").
  [294] staleuse.va     -- rewriting a `Branch` (one value operand) into a `Jump` (none) by
                           overwriting the instruction left the condition's entry in the use
                           list, naming an operand the instruction no longer has.
  [293] seconderiv.va   -- one analog operator nested DIRECTLY inside another
                           (`ddt(ddt(x))`): the inner operator's result was deleted while a
                           later linear contribution still named it OUTSIDE the data-flow
                           graph, where the rewrite could not reach it.

Where a fix changes a NUMBER, this checks the number against closed form rather than
against the old binary. Two of them (288/289, 287) do not change any number on this
platform -- invalid IR that LLVM happened to lower as intended, and a malformed function
the release build tolerated -- so for those the assertions below are forward regression
guards, and the authoritative check is that an assertions-enabled compiler now accepts
the module.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    """Compile <name>.va next to this script; return (ok, verdict)."""
    osdi = os.path.join(HERE, name.replace(".va", ".osdi"))
    try:
        r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi],
                           capture_output=True, text=True, timeout=90, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode is not None and r.returncode < 0:
        return False, f"CRASH (signal {-r.returncode})"
    if r.returncode == 139:
        return False, "SIGSEGV"
    if "panicked at" in out or "has crashed" in out or r.returncode == 101:
        return False, "ICE"
    if r.returncode != 0:
        return False, f"exit {r.returncode}"
    return os.path.exists(osdi), "compiled"


def ngspice(deck, name):
    """Run a deck (first line is the TITLE) from HERE; return stdout+stderr."""
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


def value(out, vec):
    m = re.search(rf"^{re.escape(vec)}\s*=\s*([-\d.eE+]+)", out, re.M)
    return float(m.group(1)) if m else None


print("Enhancements 286-293: openvaf-r optimizer / code-generator defects")

# ---------------------------------------------------------------- [286]
print("\n[286] constant-folding an integer div/rem by zero killed the compiler")
ok, verdict = compile_va("constfold.va")
check("`5/0`, `5%0`, `i32::MIN/-1`, `1<<40` compile (were an internal error)",
      ok, verdict)

# ---------------------------------------------------------------- [287]
print("\n[287] a folded-away branch orphaned a block, leaving a stale phi edge")
ok, verdict = compile_va("orphanblock.va")
check("noise in an `if` condition + branch-dependent variables compile", ok, verdict)
if ok:
    out = ngspice("* E-287 orphaned block\nv1 a 0 dc 1\nn1 a 0 om\n.model om orphanblock()\n"
                  ".control\npre_osdi orphanblock.osdi\nop\nprint i(v1)\n.endc\n.end\n",
                  "_ob.cir")
    i = value(out, "i(v1)")
    # the model is a 1 kOhm resistor plus a term that is 0 in the large-signal domain
    check("and simulate: I == V/1k", i is not None and abs(i - (-1e-3)) < 1e-9,
          f"i(v1)={i}")

# ---------------------------------------------------------------- [288]/[289]
print("\n[288]/[289] `hypot` arity and `llvm.ctlz` mangling -- invalid LLVM IR")
ok, verdict = compile_va("hypotclog2.va")
check("model using runtime-argument `hypot` and `$clog2` compiles", ok, verdict)
if ok:
    out = ngspice("* E-288/289 hypot + clog2\nv1 a 0 dc 0\nn1 a 0 hm\n"
                  ".model hm hypotclog2(px=3 py=4 pn=100)\n"
                  ".control\npre_osdi hypotclog2.osdi\nop\nprint i(v1)\n.endc\n.end\n",
                  "_hc.cir")
    i = value(out, "i(v1)")
    # hypot(3,4) = 5 exactly; $clog2(100) = 7  ->  12
    check("hypot(3,4) + $clog2(100) == 12 exactly",
          i is not None and abs(i - (-12.0)) < 1e-12, f"i(v1)={i} expect=-12")

# ---------------------------------------------------------------- [290]
print("\n[290] `$temperature` as an operator argument used the wrong struct-GEP type")
ok, verdict = compile_va("tempacstim.va")
check("ac_stim(\"ac\", $temperature, 0) compiles (shipped died with SIGSEGV)",
      ok, verdict)
if ok:
    out = ngspice("* E-290 ac_stim magnitude from $temperature\nNDUT out nm\nR1 out 0 1\n"
                  ".model nm tempacstim\n.control\npre_osdi tempacstim.osdi\n"
                  "ac lin 1 1k 1k\nprint mag(v(out))\n.endc\n.end\n", "_ta.cir")
    v = value(out, "mag(v(out))")
    # AC magnitude is $temperature itself: nominal 300.15 K across a 1 ohm load
    check("and reads back the nominal temperature, 300.15 K",
          v is not None and abs(v - 300.15) < 1e-3, f"mag(v(out))={v} expect=300.15")

# ---------------------------------------------------------------- [291]
print("\n[291] `max`/`min`/`abs` in a `case` default arm left a block unsealed")
ok, verdict = compile_va("casemax.va")
check("case with `max` in its default arm compiles", ok, verdict)
if ok:
    for vbias, expect, which in ((2.0, 7.0, "default arm -> max(3,7)"),
                                 (5.0, 11.0, "item arm -> 11")):
        out = ngspice(f"* E-291 case default + max, V={vbias}\nv1 a 0 dc {vbias}\n"
                      f"n1 a 0 cm\n.model cm casemax()\n.control\npre_osdi casemax.osdi\n"
                      f"op\nprint i(v1)\n.endc\n.end\n", "_cm.cir")
        i = value(out, "i(v1)")
        check(f"V={vbias}: {which}", i is not None and abs(i - (-expect)) < 1e-12,
              f"i(v1)={i} expect={-expect}")

# ---------------------------------------------------------------- [292]
print("\n[292] small-signal pruning indexed a key its own replay never inserted")
ok, verdict = compile_va("ssprune.va")
check("noise routed through idt into nested laplace_nd coefficients compiles",
      ok, verdict)

# ---------------------------------------------------------------- [293]
print("\n[293] one analog operator nested directly inside another")
ok, verdict = compile_va("seconderiv.va")
check("`ddt(ddt(V))` compiles", ok, verdict)
if ok:
    # In AC a ddt is j*omega, so a second derivative is (j*omega)^2 = -omega^2:
    # |I| must track omega^2 exactly, over decades.
    out = ngspice("* E-293 second time derivative in AC\nv1 a 0 dc 0 ac 1\nn1 a 0 dm\n"
                  ".model dm seconderiv()\n.control\npre_osdi seconderiv.osdi\n"
                  "ac dec 1 1 1000\nprint mag(i(v1))\n.endc\n.end\n", "_sd.cir")
    rows = re.findall(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", out, re.M)
    good = len(rows) == 4
    detail = []
    for f_s, mag_s in rows:
        f, mag = float(f_s), float(mag_s)
        w2 = (2.0 * 3.141592653589793 * f) ** 2
        rel = abs(mag - w2) / w2
        good = good and rel < 1e-6
        detail.append(f"{f:g}Hz:{rel:.1e}")
    check("|I| == omega^2 across 1 Hz .. 1 kHz", good, " ".join(detail) or "no rows")

    # and the formulation that ALREADY compiled (a scaled inner ddt) must agree
    out = ngspice("* E-293 nested vs scaled-nested second derivative\n"
                  "v1 a 0 dc 0 ac 1\nn1 a 0 dm\n.model dm seconderiv()\n"
                  "v2 c 0 dc 0 ac 1\nn2 c 0 dx\n.model dx seconderiv2x()\n"
                  ".control\npre_osdi seconderiv.osdi\nac lin 1 1 1\n"
                  "print mag(i(v1)) mag(i(v2))\n.endc\n.end\n", "_sd2.cir")
    a, b = value(out, "mag(i(v1))"), value(out, "mag(i(v2))")
    check("`ddt(2*ddt(V))` (the path that already worked) is exactly 2x",
          a and b and abs(b - 2.0 * a) < 1e-9 * max(1.0, abs(b)),
          f"nested={a} scaled={b}")

    # Transient: chained ddt is unusable under the DEFAULT trapezoidal integration
    # (a non-decaying Nyquist-rate ring -- trapezoidal is A-stable but not L-stable) and
    # fine under Gear, which is L-stable. This guards the workaround the docs recommend.
    out = ngspice("* E-293 second derivative in transient under Gear\n"
                  ".options method=gear\nv1 a 0 dc 0 sin(0 1 1)\nn1 a 0 dm\n"
                  ".model dm seconderiv()\n.control\npre_osdi seconderiv.osdi\n"
                  "tran 100u 0.63\nmeas tran ii find i(v1) at=0.625\n"
                  "meas tran vv find v(a) at=0.625\n.endc\n.end\n", "_sg.cir")
    ii, vv = value(out, "ii"), value(out, "vv")
    w2 = (2.0 * 3.141592653589793) ** 2
    rel = abs(ii / vv - w2) / w2 if (ii is not None and vv) else None
    check("transient under `.options method=gear` matches omega^2 (the documented "
          "workaround)", rel is not None and rel < 0.01,
          f"i/v={ii / vv:.5f} expect={w2:.5f} rel={rel:.2e}" if rel is not None else "no data")

# ---------------------------------------------------------------- [294]
print("\n[294] Branch->Jump rewrite left the condition in the use list")
ok, verdict = compile_va("staleuse.va")
check("a `$fatal` arm guarded by a parameter compare compiles", ok, verdict)
if ok:
    out = ngspice("* E-294 stale use after branch-to-jump rewrite\nv1 a 0 dc 1\n"
                  "n1 a 0 sm\n.model sm staleuse(p=1)\n.control\npre_osdi staleuse.osdi\n"
                  "op\nprint i(v1)\n.endc\n.end\n", "_su.cir")
    i = value(out, "i(v1)")
    check("and simulates: I == V/1k", i is not None and abs(i - (-1e-3)) < 1e-9,
          f"i(v1)={i}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
