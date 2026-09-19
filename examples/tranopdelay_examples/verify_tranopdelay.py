#!/usr/bin/env python3
"""Enhancement-671: a delay survives the "Transient op" operating point.

The 2026-09-19 hunt's F1. When plain Newton, gmin stepping and source
stepping all fail and CKTop reaches its last rung -- optran.c's short
transient with the sources frozen ("Note: Transient op started") -- every
`absdelay` and every `transition` with a delay in every loaded OSDI model
lost its delay for the whole transient that followed: read into a variable
the delayed value was 0 at every point, contributed it passed its input
through undelayed, and an `idt` of a delayed signal integrated 0.

Cause: the fallback frees the shared accepted-timepoint list dctran.c had
reset, the OSDI stamp re-creates it and OSDIaccept fills ~100 points with the
fallback's own times and the frozen operating point, and nothing reset it
before the real transient: its first Newton solve (MODEINITTRAN) found a
non-NULL list with the index at the fallback's last point and kept it, so the
real times were appended AFTER the fallback's -- a non-monotonic timeline
whose first microsecond was the operating point. absdelay_lookup's binary
search over it returned the operating point (0) or whatever it fell on.

Fix (ngspice-46/src/osdi/osdiload.c): at MODEINITTRAN the timeline starts
over at index 0, whatever it holds. Gmin and source stepping never ran a
transient and were unaffected; `uic` skips the operating point.

Checks (per solver):
  a  the delay-only model alone (plain Newton): delayed step at 2 us -- the reference
  b  the same model with an ideal inductor across the source (forces the Transient op):
     the delayed step is at 2 us, 0 before it, 1 after it
  c  the delay contributed directly (fallback forced by a second instance so the
     source current is the model's alone): 1 mA before 2 us and 2 mA after
  d  `transition` with a 0.5 us delay and a 1 us rise under the fallback: the ramp
     runs from 1.5 us to 2.5 us
  e  an `idt` of a delayed signal (ic 0) forces the fallback on its own and now
     integrates the delayed pulse (2e-6 V.s after it)
  f  the fallback forced by a SECOND instance (an idt without ic) leaves the
     first instance's delay intact
  g  `uic` (no operating point) is unchanged
  h  `last_crossing`, which shares the timeline, still reads the negative
     sentinel before the edge and the crossing time after it, under the fallback
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="tranopdelay_")
A = "@"

DEL_VA = '''`include "disciplines.vams"
module m(a,b); inout a,b; electrical a,b;
(*desc="delayed input"*) real del;
(*desc="last crossing of V-0.5"*) real lx;
analog begin
 del = absdelay(V(a,b), 1u);
 lx = last_crossing(V(a,b) - 0.5, +1);
 I(a,b) <+ V(a,b)/1e3;
end
endmodule
'''
CONTRIB_VA = '''`include "disciplines.vams"
module mc(a,b); inout a,b; electrical a,b;
analog begin
 I(a,b) <+ V(a,b)/1e3 + absdelay(V(a,b), 1u)/1e3;
end
endmodule
'''
TRANS_VA = '''`include "disciplines.vams"
module mt(a,b); inout a,b; electrical a,b;
(*desc="delayed ramp"*) real tr;
analog begin
 tr = transition(V(a,b) > 0.5 ? 1.0 : 0.0, 0.5u, 1u);
 I(a,b) <+ V(a,b)/1e3;
end
endmodule
'''
IDTDEL_VA = '''`include "disciplines.vams"
module mi(a,b); inout a,b; electrical a,b;
(*desc="integral of the delayed input"*) real y;
analog begin
 y = idt(absdelay(V(a,b), 1u), 0.0);
 I(a,b) <+ V(a,b)/1e3;
end
endmodule
'''
IDT_VA = '''`include "disciplines.vams"
module mj(a,b); inout a,b; electrical a,b;
(*desc="undefined at dc"*) real it;
analog begin
 it = idt(1.0);
 I(a,b) <+ V(a,b)/1e3;
end
endmodule
'''


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(src, tag):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(f"compile of {tag} failed")
    return os.path.join(WORK, f"{tag}.osdi")


def run(tag, osdis, elements, saves, meas, tran="0.5u 4u", src="v1 a 0 dc 0 pulse(0 1 1u 1n 1n 10u 20u)"):
    """Run a deck and return (measured values by name, the full output)."""
    path = os.path.join(WORK, f"{tag}.cir")
    ctl = "\n".join(f"pre_osdi {o}" for o in osdis)
    ms = "\n".join(f"meas tran {name} find {vec} at={t}" for name, vec, t in meas)
    with open(path, "w") as f:
        f.write(f"* tranopdelay {tag}\n.control\nset noinit\n{ctl}\n.endc\n{src}\n{elements}\n"
                f".save {saves}\n.tran {tran}\n.control\nrun\n{ms}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300, cwd=WORK)
    out = p.stdout + p.stderr
    vals = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "=":
            try:
                vals[parts[0]] = float(parts[2])
            except ValueError:
                pass
    return vals, out


def near(v, target, tol):
    return v is not None and abs(v - target) <= tol


o_del = compile_va(DEL_VA, "del")
o_con = compile_va(CONTRIB_VA, "con")
o_trn = compile_va(TRANS_VA, "trn")
o_idl = compile_va(IDTDEL_VA, "idl")
o_idt = compile_va(IDT_VA, "idt")

DELSAVE = f"{A}n1[del] {A}n1[lx]"
DELMEAS = [("d15", f"{A}n1[del]", "1.5u"), ("d25", f"{A}n1[del]", "2.5u"), ("d40", f"{A}n1[del]", "4u"),
           ("x05", f"{A}n1[lx]", "0.5u"), ("x40", f"{A}n1[lx]", "4u")]

# ---------------------------------------------------------------- [a] ---
v, out = run("newton", [o_del], "n1 a 0 mm\n.model mm m", DELSAVE, DELMEAS)
check("[a] plain Newton reference: the delayed step is 0 at 1.5 us, 1 at 2.5 us and 4 us",
      near(v.get("d15"), 0.0, 1e-6) and near(v.get("d25"), 1.0, 1e-3) and near(v.get("d40"), 1.0, 1e-3),
      f"d15={v.get('d15')} d25={v.get('d25')} d40={v.get('d40')}")
check("[a] ...and the operating point took no fallback", "Transient op started" not in out)

# ---------------------------------------------------------------- [b] ---
v, out = run("fallback", [o_del], "n1 a 0 mm\n.model mm m\nl1 a 0 1m", DELSAVE, DELMEAS)
check("[b] an ideal inductor across the source forces the Transient op", "Transient op started" in out and "Transient op finished" in out)
check("[b] ...and the delayed step is still at 2 us: 0 at 1.5 us, 1 at 2.5 us and 4 us (was 0 throughout)",
      near(v.get("d15"), 0.0, 1e-6) and near(v.get("d25"), 1.0, 1e-3) and near(v.get("d40"), 1.0, 1e-3),
      f"d15={v.get('d15')} d25={v.get('d25')} d40={v.get('d40')}")

# ---------------------------------------------------------------- [h] ---
check("[h] last_crossing under the fallback: the negative sentinel at 0.5 us, the 1 us edge after it",
      v.get("x05") is not None and v["x05"] < 0 and near(v.get("x40"), 1.0005e-6, 2e-9),
      f"x05={v.get('x05')} x40={v.get('x40')}")

# ---------------------------------------------------------------- [c] ---
v, out = run("contrib", [o_con, o_idt], "n1 a 0 mm\n.model mm mc\nr2 x 0 1k\nn2 x 0 mmj\n.model mmj mj", "i(v1)",
             [("i15", "i(v1)", "1.5u"), ("i25", "i(v1)", "2.5u"), ("i40", "i(v1)", "4u")])
check("[c] the delay contributed directly, under the fallback (forced by a second instance): 1 mA before 2 us, 2 mA after (was 1 mA throughout: undelayed)",
      "Transient op started" in out and near(v.get("i15"), -1e-3, 2e-6) and near(v.get("i25"), -2e-3, 2e-6) and near(v.get("i40"), -2e-3, 2e-6),
      f"i15={v.get('i15')} i25={v.get('i25')} i40={v.get('i40')}")

# ---------------------------------------------------------------- [d] ---
v, out = run("trans", [o_trn], "n1 a 0 mm\n.model mm mt\nl1 a 0 1m", f"{A}n1[tr]",
             [("t15", f"{A}n1[tr]", "1.5u"), ("t20", f"{A}n1[tr]", "2u"), ("t30", f"{A}n1[tr]", "3u")])
check("[d] transition(x, 0.5u, 1u) under the fallback: 0 at 1.5 us, mid-ramp at 2 us, 1 at 3 us (was 0 throughout)",
      "Transient op started" in out and near(v.get("t15"), 0.0, 5e-2) and near(v.get("t20"), 0.5, 1e-1) and near(v.get("t30"), 1.0, 1e-2),
      f"t15={v.get('t15')} t20={v.get('t20')} t30={v.get('t30')}")

# ---------------------------------------------------------------- [e] ---
v, out = run("idtdel", [o_idl], "n1 a 0 mm\n.model mm mi", f"{A}n1[y]",
             [("y15", f"{A}n1[y]", "1.5u"), ("y40", f"{A}n1[y]", "4u")],
             src="v1 a 0 dc 0 pulse(0 1 1u 1n 1n 2u 20u)")
check("[e] idt(absdelay(V, 1u), 0) forces the fallback by itself (singular at the operating point)",
      "Transient op started" in out)
check("[e] ...and integrates the delayed 2 us pulse: 0 at 1.5 us, 2e-6 V.s at 4 us (was 0 throughout)",
      near(v.get("y15"), 0.0, 1e-8) and near(v.get("y40"), 2e-6, 4e-8), f"y15={v.get('y15')} y40={v.get('y40')}")

# ---------------------------------------------------------------- [f] ---
v, out = run("second", [o_del, o_idt], "n1 a 0 mm\n.model mm m\nr2 x 0 1k\nn2 x 0 mmj\n.model mmj mj", DELSAVE, DELMEAS)
check("[f] the fallback forced by a second instance (idt without ic): the first instance's delay is intact",
      "Transient op started" in out and near(v.get("d15"), 0.0, 1e-6) and near(v.get("d25"), 1.0, 1e-3) and near(v.get("d40"), 1.0, 1e-3),
      f"d15={v.get('d15')} d25={v.get('d25')} d40={v.get('d40')}")

# ---------------------------------------------------------------- [g] ---
v, out = run("uic", [o_del], "n1 a 0 mm\n.model mm m\nl1 a 0 1m", DELSAVE, DELMEAS, tran="0.5u 4u uic")
check("[g] uic (no operating point, no fallback): the delayed step at 2 us as before",
      "Transient op started" not in out and near(v.get("d15"), 0.0, 1e-6) and near(v.get("d25"), 1.0, 1e-3) and near(v.get("d40"), 1.0, 1e-3),
      f"d15={v.get('d15')} d25={v.get('d25')} d40={v.get('d40')}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
