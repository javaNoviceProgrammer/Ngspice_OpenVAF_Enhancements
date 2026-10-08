#!/usr/bin/env python3
"""Enhancement-813 (F22 of the 2026-10-08 ngspice + OSDI hunt): OSDIload's
bias-point capture no longer reads past the end of the solution vector.

E-677 captures the operating point at the MODEINITSMSIG load -- which DCop issues
at the end of every `op`, not only before an ac -- so that a later @(final_step)
can evaluate at the bias. It copied CKTmaxEqNum + 1 doubles out of CKTrhsOld,
which NIreinit allocates with SMPmatSize + 1 = CKTmaxEqNum: one double past the
end, at every `op` and at the bias point of every ac and noise analysis of a
circuit with an OSDI device (a dc sweep, a transient, tf and sens issue no such
load and were clean). The read
usually fell in the allocator's rounding and the value was never used; whenever
the vector's length filled its slot exactly it was a read past the block -- a
fault under macOS Guard Malloc (DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib),
and in principle a crash. The hunt met it first with an OSDI internal node, then
with no internal node beside built-in R, C and D: what mattered was the length.

The decks run under Guard Malloc where it exists (macOS), which faults at the
overrunning access, so a regression fails every time; elsewhere they run plainly
and only the values are checked.

  [1] a module with an internal node: op, dc, ac, noise, tran, tf, sens --
      clean, and the right answers
  [2] a module without one beside built-in R, C and D (op and dc), and a noisy
      module inside a subcircuit: the decks that faulted while the D slips were
      verified
  [3] the circuit's size swept through both parities of the vector length: one
      to eight extra built-in nodes beside the module
  [4] E-677 still holds: @(final_step) after an ac evaluates at the bias point
      (0.2 V), not the small-signal solution (1 V)
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

GMALLOC = "/usr/lib/libgmalloc.dylib"
GUARD = sys.platform == "darwin" and os.path.exists(GMALLOC)
WORK = tempfile.mkdtemp(prefix="guardmalloc_")
checks = passed = 0

MODELS = {
    "vi": """module v_internal(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin
  I(a,mid) <+ 1e-3*V(a,mid);
  I(mid,b) <+ 1e-3*V(mid,b) + ddt(1p*V(mid,b));
end
endmodule
""",
    "gr": """module gr(a, b);
inout a, b; electrical a, b;
analog I(a,b) <+ 1e-3*V(a,b);
endmodule
""",
    "nr": """module nr(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
analog begin
  I(a,b) <+ V(a,b)/r;
  I(a,b) <+ white_noise(4*1.380649e-23*$temperature/r, "thermal");
end
endmodule
""",
    "fs": """module fs(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin
  I(a,mid) <+ 1e-3*V(a,mid);
  I(mid,b) <+ 1e-3*V(mid,b);
  @(final_step) $strobe("FINALV %.4f", V(a,b));
end
endmodule
""",
}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


for name, src in MODELS.items():
    va = os.path.join(WORK, f"{name}.va")
    with open(va, "w") as f:
        f.write('`include "disciplines.vams"\n' + src)
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, f"{name}.osdi")],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(models, body, ctl, tag):
    """returncode (negative: killed by a signal) and output"""
    pre = "".join(f"pre_osdi {m}.osdi\n" for m in models)
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* guardmalloc {tag}\n.control\n{pre}.endc\n{body}\n.control\n{ctl}\n.endc\n.end\n")
    env = dict(os.environ)
    if GUARD:
        env["DYLD_INSERT_LIBRARIES"] = GMALLOC
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, env=env, errors="replace")
    return p.returncode, p.stdout + p.stderr


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r" = (\S+)", out, re.M)
    return float(m.group(1).rstrip(",")) if m else None


print("Enhancement-813: the bias-point capture reads within the solution vector"
      + (" (under Guard Malloc)" if GUARD else " (no Guard Malloc here: plain runs, values only)") + "\n")

# ------------------------------------------------------------- [1] ---
print("[1] a module with an internal node, through every analysis")
B1 = "v1 1 0 dc 1 ac 1\nn1 1 0 vm\n.model vm v_internal"
out_cases = [
    ("op", "op\nprint v(1) v(n1#mid) i(v1)",
     lambda o: val(o, "v(n1#mid)") == 0.5 and val(o, "i(v1)") == -5e-4),
    ("dc", "dc v1 0 1 0.5\nprint v(n1#mid)[2]", lambda o: val(o, "v(n1#mid)[2]") == 0.5),
    ("ac", "ac lin 3 1k 1meg\nprint vm(n1#mid)[0]", lambda o: abs((val(o, "vm(n1#mid)[0]") or 0) - 0.5) < 1e-3),
    ("noise", "noise v(1) v1 lin 2 1k 2k\nsetplot noise1\nprint inoise_spectrum[0]",
     lambda o: val(o, "inoise_spectrum[0]") is not None),
    ("tran", "tran 1n 100n\nprint v(n1#mid)[10]", lambda o: abs((val(o, "v(n1#mid)[10]") or 0) - 0.5) < 1e-3),
    ("tf", "tf v(n1#mid) v1\nprint all", lambda o: "transfer_function" in o),
    ("sens", "sens v(n1#mid)\nprint all", lambda o: "v1" in o),
]
for an, ctl, good in out_cases:
    rc, out = run(["vi"], B1, ctl, f"vi_{an}")
    check(f"[1] {an}: clean (rc 0) and the right answer", rc == 0 and good(out), f"rc={rc} {out[-300:]}")

# ------------------------------------------------------------- [2] ---
print("[2] the decks that faulted while the D slips were verified")
rc, out = run(["gr"], "v1 1 0 dc 0.6 ac 1\nr1 1 2 1k\nc1 2 0 1n\nd1 2 0 dm\n.model dm d is=1e-14\n"
              "n1 1 0 grm\n.model grm gr", "op\nprint i(v1)\ndc v1 0 0.6 0.3", "rcd")
check("[2] no internal node, beside built-in R, C and D: op and dc clean",
      rc == 0 and val(out, "i(v1)") is not None, f"rc={rc} {out[-300:]}")
rc, out = run(["nr"], "v1 1 0 dc 0 ac 1\nr1 1 2 1k\nx1 2 0 sub\n.subckt sub a b\nn1 a b nrm\n"
              ".model nrm nr r=1k\n.ends", "noise v(2) v1 lin 1 1k 1k 1\nsetplot noise1\n"
              "print onoise_n.x1.n1_thermal", "subnoise")
check("[2] a noisy module inside a subcircuit: noise clean, its contribution 2.04e-9",
      rc == 0 and abs((val(out, "onoise_n.x1.n1_thermal") or 0) / 2.0357e-9 - 1) < 1e-3,
      f"rc={rc} {out[-300:]}")

# ------------------------------------------------------------- [3] ---
print("[3] both parities of the vector length")
bad = []
for k in range(1, 9):
    extra = "".join(f"r{j} 1 x{j} 1k\nc{j} x{j} 0 1n\n" for j in range(k))
    rc, out = run(["vi"], f"v1 1 0 1\n{extra}n1 1 0 vm\n.model vm v_internal", "op\nprint v(n1#mid)",
                  f"len{k}")
    if rc != 0 or val(out, "v(n1#mid)") != 0.5:
        bad.append((k, rc))
check("[3] one to eight extra built-in nodes beside the module: every op clean, v(n1#mid) = 0.5",
      not bad, f"{bad}")

# ------------------------------------------------------------- [4] ---
print("[4] E-677: the final step after an ac still sees the bias point")
rc, out = run(["fs"], "v1 1 0 dc 0.2 ac 1\nn1 1 0 fsm\n.model fsm fs", "ac lin 2 1k 2k", "final")
fin = re.findall(r"FINALV (\S+)", out)
check("[4] @(final_step) after the ac reads V = 0.2 (the bias), not 1 (the ac solution)",
      rc == 0 and fin and float(fin[-1]) == 0.2, f"rc={rc} {fin}")

print(f"\n    {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
