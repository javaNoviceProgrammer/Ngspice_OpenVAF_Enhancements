#!/usr/bin/env python3
"""Enhancement-223: XSPICE a-device model-type validation (MIFgetMod).

Fuzzing the netlist parser (Enhancement-222) left one residual crash, in XSPICE
rather than the netlist parser: an `a' device (XSPICE code-model instance) whose
model name happens to match a NON-code-model `.model' (e.g. a diode) reached
MIFgetMod (xspice/mif/mifgetmod.c), which processed that model AS a code model --
casting its model struct to MIFmodel, reading the device's XSPICE DEVpublic fields
(param/conn), and matching the `.model' parameters through the MIF path. For a
non-code-model those fields are unset and the model struct is not a MIFmodel, so
this read unrelated memory as the wrong type -> SIGSEGV. The bug bit hardest when
the non-code-model's parameter keywords collide with the a-device's (a diode has
`is'/`n'), so the parameter loop dereferenced the type-confused structures.

Fix: a code model is exactly a device that carries a code-model evaluation
function (DEVpublic.cm_func, set by cmpp for every code model and left NULL by
every built-in SPICE device). MIFgetMod now rejects a model whose device is not a
code model with a clean "model X is not a code model" error, before any code-model
processing. Legitimate code-model a-devices are unaffected (cm_func != NULL).

Each crash-guard check asserts the pathological deck now yields a clean, bounded
outcome (no signal/abort, no hang). The regression check confirms a real code
model still parses, binds, and simulates.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

checks = passed = 0
D = tempfile.mkdtemp(prefix="xspicemodel223_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))


def run(deck, name="f.cir", timeout=30):
    p = os.path.join(D, name)
    with open(p, "w") as f:
        f.write(deck)
    wd = tempfile.mkdtemp(dir=D)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=timeout, cwd=wd, errors="replace")
    except subprocess.TimeoutExpired:
        return "", None  # HANG
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def is_crash(rc):
    # ngspice -b returns 0 (ok) or 1 (clean error); a signal is rc < 0 (Python)
    # or rc >= 128 on the shell convention. None == timeout (hang).
    return rc is None or rc < 0 or (rc is not None and rc >= 128 and rc != 142)


def val(out, node):
    m = re.search(rf"{re.escape(node)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


# ---- crash-guard: a-device referencing a NON-code-model must be a clean error ----
# Each of these previously crashed (SIGSEGV) inside MIFgetMod; each must now exit
# cleanly with the "not a code model" diagnostic and no segfault/hang.
bad = {
    "diode model with colliding params (is/n) -- the original fuzz repro class":
        "* t\n.model dm d(is=1e-14 n=1)\na1 1 0 dm\nV1 1 0 1\n.op\n.end\n",
    "diode model, no params":
        "* t\n.model dm d\na1 1 0 dm\nV1 1 0 1\n.op\n.end\n",
    "BJT model with colliding params (is/bf)":
        "* t\n.model qm npn(is=1e-16 bf=100)\na1 1 0 2 qm\nV1 1 0 1\n.op\n.end\n",
    "resistor model":
        "* t\n.model rm r(rsh=10)\na1 1 0 rm\nV1 1 0 1\n.op\n.end\n",
    "bus-expanded a-device -> diode model inside a subckt (E-221 x E-222 repro)":
        "* t\n.model dm d(is=1e-14 n=1)\n.subckt rect a b\n a[0:0] D1 a b dm\n"
        "Rb b 0 1k\n.ends\nV1 a 0 sin(0 1 1k)\nX1 a b rect\n.tran 1u 1m\n.end\n",
    "a-device -> undefined model (never registered)":
        "* t\na1 1 0 nope\nV1 1 0 1\n.op\n.end\n",
}
for name, deck in bad.items():
    out, rc = run(deck)
    crashed = is_crash(rc)
    # a clean rejection either names it as not-a-code-model or otherwise errors out
    named = ("not a code model" in out) or ("unable to find definition" in out) or \
            ("Invalid model type" in out) or ("Unknown device type" in out)
    check(f"[crash-guard] {name} -> clean error, no crash",
          (not crashed) and named, f"rc={rc}, no-diag" if not named else f"rc={rc}")

# ---- regression: a legitimate code-model a-device still works ----
# adc_bridge is a real XSPICE code model (cm_func != NULL); the analog divider node
# must still solve to 0.5 and the event-driven bridge must bind without error.
good = """* E-223 legitimate code-model a-device (adc_bridge)
V1 in 0 DC 1
R1 in a 1k
R2 a 0 1k
aconv [a] [dout] adc
.model adc adc_bridge(in_low=0.4 in_high=0.6)
.control
op
print v(a)
.endc
.end
"""
out, rc = run(good)
va = val(out, "v(a)")
check("[regression] legitimate adc_bridge code model binds + simulates without error",
      (not is_crash(rc)) and rc == 0 and "aborted" not in out.lower(),
      f"rc={rc}: {out.strip()[-160:]}")
check("[regression] analog node still solves to the divider value v(a) = 0.5",
      va is not None and abs(va - 0.5) < 1e-6, f"v(a)={va}")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
