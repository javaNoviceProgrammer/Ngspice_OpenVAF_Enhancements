#!/usr/bin/env python3
"""Enhancement-526: analog behavior and contributions, audited against
Accellera VAMS-2023 clause 5, then fixed.

What this suite pins, each against the quoted clause:

  * 5.6.8.1 with 5.5.4 -- a contribution between local and hierarchical
    nets creates "a new unnamed branch ... in the module containing the
    direct contribution statements", distinct from any branch the child
    itself has between the same nodes. The textual flattening aliased
    the parent's V(p, c1.mid) <+ onto the child's own unnamed branch:
    the retention rule then DISCARDED the child's flow contribution
    (warning L022 on fully legal code) and the child's mirror probe read
    the merged potential-source current (1.0 mA) instead of its own flow
    source (0.5 mA). Each hierarchical target now gets its own
    synthesized named branch; the transform composes exactly with
    #(.$mfactor(n)) scaling.
  * 5.6.7 / 5.6.5 -- "Indirect branch contributions shall not be used in
    conditional or looping statements, unless the conditional expression
    is a constant expression", and no contribution belongs in an event
    control. Both placements compiled silently and left the constraint
    equation as 0 = 0 on the guarded-off path -- a singular matrix. Both
    are compile errors now; the constant-condition carve-out passes.
  * 5.6.7.2 -- "Once a value is indirectly assigned to a branch, it
    cannot be contributed to using the branch contribution operator <+."
    The mix compiled with the direct value silently absorbed by the
    implicit unknown; it is an error naming both statements now.
  * 5.5.2 -- a vector signal-access index "must be a constant
    expression", which includes parameters: V(in[width-2]) folds at
    elaboration and freezes `width` structural (see also the extended
    vafconstidx suite).

Deliberate relaxations re-pinned as shipped extensions: contributions in
runtime loops (LRM 5.9 allows them only in the genvar analog_for),
do-while, the generalized indirect-equality LHS, and out-of-scope
named-block variable writes -- all documented in the compliance doc now.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lb_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_file(name):
    osdi = os.path.join(HERE, f"_lb_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lb_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmcontrib\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\n{ctl}\nquit\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def num(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def close(a, b, rel=1e-6):
    return a is not None and abs(a - b) <= rel * max(abs(b), 1e-30)


# ---- [1] hierarchical contribution branch identity (5.6.8.1) ---------------
print("hierarchical contributions create their own branch (LRM 5.6.8.1):")
rc, out, osdi = compile_file("hier3.va")
check("hier3.va compiles", rc == 0)
check("...with NO spurious L022 'contributed as both' warning",
      "L022" not in out and "discarded" not in out, "")
if rc == 0:
    sim = run(".model m1 hier3()\nvs p 0 dc 1.0\nnh p 0 mir m1\nvmeas mir 0 dc 0",
              "op\nprint i(vmeas)", "h3", osdi)
    check("the child's mirror reads its OWN flow source: 0.5 mA "
          "(the merged branch used to read 1.0 mA)",
          close(num(sim, "i(vmeas)"), -0.5e-3), f"{num(sim, 'i(vmeas)')}")

rc, out, osdi = compile_file("mfhier.va")
check("mfhier.va (hier contribution under #(.$mfactor(2))) compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 DC 1.0\nN1 in 0 mm\n.model mm mfhier",
              "op\nprint i(v1)", "mfh", osdi)
    check("the 6.3.6 transform composes: per-copy 1.5 mA x 2 = 3 mA exactly",
          close(num(sim, "i(v1)"), -3e-3), f"{num(sim, 'i(v1)')}")

# ---- [2] indirect-assignment placement rules (5.6.7 / 5.6.5) ---------------
print("\nindirect-assignment placement (LRM 5.6.7/5.6.5):")
rc, out, _ = compile_file("indirect_cond.va")
check("under a non-constant `if`: compile error (was a runtime singular "
      "matrix)", rc != 0 and "indirect" in out and "conditions" in out,
      next((l for l in out.splitlines() if "error" in l), "")[:70])
rc, out, _ = compile_file("indirect_ev.va")
check("inside @(initial_step): compile error", rc != 0 and "events" in out,
      next((l for l in out.splitlines() if "error" in l), "")[:70])

rc, out, _ = compile_file("indirect_mix.va")
check("direct <+ onto an indirectly-assigned branch: the 5.6.7.2 error",
      rc != 0 and "indirect branch assignment" in out,
      next((l for l in out.splitlines() if "error" in l), "")[:70])

va = os.path.join(HERE, "_lb_cc.va")
with open(va, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module cc(out, pin, nin); inout out, pin, nin;\n"
            "  electrical out, pin, nin;\n"
            "  analog if (1) V(out): V(pin,nin) == 0;\nendmodule\n")
rc, out, _ = compile_file("_lb_cc.va")
check("the constant-condition carve-out still passes", rc == 0, "")

# ---- [3] the legal indirect forms still solve exactly ----------------------
print("\nlegal indirect assignment (the LRM's op-amp construct):")
rc, out, osdi = compile_file("opamp.va")
check("opamp.va compiles", rc == 0)
if rc == 0:
    sim = run("Vin in 0 dc 1.3\nnop out in out m1\n.model m1 opamp()",
              "op\nprint v(out)", "fol", osdi)
    check("follower: v(out) = 1.3 exactly", close(num(sim, "v(out)"), 1.3),
          f"{num(sim, 'v(out)')}")
    sim = run("Vin in 0 dc 1.0\nR1 in minus 1k\nR2 minus out 2k\n"
              "nop out minus 0 m1\n.model m1 opamp()",
              "op\nprint v(out) v(minus)", "inv", osdi)
    vminus = num(sim, "v(minus)")
    check("inverting amp: v(out) = -2.0 with a 0 V virtual ground",
          close(num(sim, "v(out)"), -2.0)
          and vminus is not None and abs(vminus) < 1e-9,
          f"out={num(sim, 'v(out)')} minus={vminus}")

# ---- [4] parameter vector indices (5.5.2) ----------------------------------
print("\nparameter expressions as vector signal indices (LRM 5.5.2):")
rc, out, osdi = compile_file("vecbranch_par.va")
check("V(in[width-2]) compiles (was 'index must be a constant')", rc == 0,
      "" if rc == 0 else out.strip().splitlines()[0][:60])
if rc == 0:
    sim = run("V0 b0 0 dc 0.1\nV1 b1 0 dc 0.2\nV2 b2 0 dc 0.4\nV3 b3 0 dc 0.8\n"
              "N1 out b0 b1 b2 b3 mm\nR1 out 0 1k\n.model mm vecbranch_par",
              "op\nprint v(out)", "vbp", osdi)
    check("width=4 selects in[2]: v(out) = 0.4", close(num(sim, "v(out)"), 0.4),
          f"{num(sim, 'v(out)')}")

# ---- [5] the shipped extensions stay shipped -------------------------------
print("\ndeliberate relaxations (documented extensions):")
rc, out, osdi = compile_file("loopcontrib.va")
check("contributions inside a runtime for-loop still compile (LRM 5.9 "
      "relaxation)", rc == 0)
if rc == 0:
    sim = run("V1 p 0 DC 2\nN1 p 0 mm\n.model mm loopcontrib",
              "op\nprint i(v1)", "lc", osdi)
    check("...and accumulate per iteration: 3 segments at +2 V give 6 mA",
          close(num(sim, "i(v1)"), -6e-3), f"{num(sim, 'i(v1)')}")
rc, out, _ = compile_file("dowhile.va")
check("do-while still compiles (non-LRM extension, now documented)", rc == 0)
rc, out, _ = compile_file("indirect_lhs.va")
check("a general expression on the indirect equality LHS still compiles "
      "(generalized-equation extension)", rc == 0)
rc, out, osdi = compile_file("namedscope_w.va")
check("an out-of-scope named-block variable WRITE still compiles "
      "(documented relaxation)", rc == 0)

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
