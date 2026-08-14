#!/usr/bin/env python3
"""Enhancement-456: `analog initial` ran on every evaluation, not once.

LRM 5.2: "The analog initial block is executed once for each analysis." Its
statements were instead lowered into the front of the eval function, concatenated
with the main analog block, so they re-ran on every evaluation and overwrote
whatever the model had accumulated between timesteps.

That destroyed the one thing the construct exists for. A peak detector
initialised with `analog initial begin peak = 0.0; end` did not hold its peak --
it FOLLOWED THE INPUT BACK DOWN (0.4 at 8 us on an input that had already
reached 1.0), and a counter never left zero. The identical models with the
initialisation written as `@(initial_step) peak = 0.0;` inside the main block
worked correctly, and so did the models with no initialisation at all. Nothing
was reported either way.

The fix gates the initial block on `ParamKind::IsInitialStep` -- the flag
`@(initial_step)` already uses, true on an instance's first evaluation of an
analysis. Measured: it fires once for an `op`, once for a whole `tran`, ONCE for
an entire dc sweep however many points it has, twice for `op` then `dc`, and once
per instance. That is the LRM's baseline rule.

The `_ref` twins here are the oracle. They are the same models written the way
that always worked, and every fixed model must reproduce their numbers exactly --
a check that "it holds a peak now" would pass on a model that merely held the
WRONG value.

The gate is emitted ONLY when a module actually has an initial block. Without
that guard every model picks up an `IsInitialStep` parameter and an empty
conditional it never asked for, which showed up at once as a 32-byte change in a
MEXTRAM model that has no initial block at all.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
WORK = tempfile.gettempdir()
OSDI = os.path.join(WORK, "_ai.osdi")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def tran(model, times, tag):
    """Run `model` on a 0->1->0 ramp; return v(out) at each requested time."""
    deck = os.path.join(WORK, f"_ai_{tag}.cir")
    meas = "\n".join(f"meas tran m{i} FIND v(out) AT={t}u" for i, t in enumerate(times))
    with open(deck, "w") as f:
        f.write(f"""* analoginit {tag}
V1 in 0 PWL(0 0 5u 1 10u 0)
N1 in out {model}
.model {model} {model}()
Rl out 0 1e12
.control
pre_osdi {OSDI}
tran 0.5u 10u
{meas}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True,
                       timeout=300, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    got = []
    for i in range(len(times)):
        m = re.search(rf"^\s*m{i}\s*=\s*([-\d.eE+]+)", out, re.M)
        got.append(float(m.group(1)) if m else None)
    return got


def opvars(model, names, tag):
    deck = os.path.join(WORK, f"_ai_{tag}.cir")
    with open(deck, "w") as f:
        f.write(f"""* analoginit {tag}
V1 in 0 dc 1
Rs in mid 1k
N1 mid 0 {model}
.model {model} {model}()
.control
pre_osdi {OSDI}
op
print {" ".join(f"@n1[{n}]" for n in names)}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True,
                       timeout=300, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    res = []
    for n in names:
        m = re.search(rf"@n1\[{re.escape(n)}\]\s*=\s*([-\d.eE+]+)", out)
        res.append(float(m.group(1)) if m else None)
    return res


print("Enhancement-456: `analog initial` runs once, not every evaluation\n")
r = subprocess.run([OPENVAF, os.path.join(HERE, "analoginit.va"), "-o", OSDI],
                   capture_output=True, text=True, timeout=600, cwd=HERE)
check("[E-456] the models compile", r.returncode == 0 and os.path.isfile(OSDI),
      (r.stdout + r.stderr).strip().splitlines()[0][:60] if r.returncode else "")

# --------------------------------------------------------------- peak hold ---
# The input reaches 1.0 at 5us then falls back to 0. A peak detector must HOLD
# 1.0 after that; the broken one tracked the input down.
print("\na peak detector holds its peak")
TIMES = (2.0, 5.0, 8.0, 9.5)
init = tran("peak_init", TIMES, "pk_i")
ref = tran("peak_ref", TIMES, "pk_r")
check("[E-456] the reference (@(initial_step)) holds 1.0 after the peak",
      ref[2] is not None and abs(ref[2] - 1.0) < 1e-6 and abs(ref[3] - 1.0) < 1e-6, f"{ref}")
check("[E-456] `analog initial` holds 1.0 too, instead of tracking the input down",
      init[2] is not None and abs(init[2] - 1.0) < 1e-6 and abs(init[3] - 1.0) < 1e-6, f"{init}")
check("[E-456] ...and matches the reference at every probe", init == ref, f"{init} vs {ref}")

# ----------------------------------------------------------------- counter ---
print("\na counter accumulates across timesteps")
CT = (1.5, 3.5, 6.5, 9.5)
cinit = tran("count_init", CT, "ct_i")
cref = tran("count_ref", CT, "ct_r")
check("[E-456] the reference counts up", cref[0] is not None and cref[-1] > cref[0], f"{cref}")
check("[E-456] `analog initial` counts up too, instead of staying at 0",
      cinit[0] is not None and cinit[-1] > cinit[0], f"{cinit}")
check("[E-456] ...and matches the reference at every probe", cinit == cref, f"{cinit} vs {cref}")

# ------------------------------------------- the initial value still lands ---
print("\nthe initialised value still reaches the main block")
x, y = opvars("carry_init", ["x", "y"], "carry")
check("[E-456] x keeps the value the initial block gave it",
      x is not None and abs(x - 5.0) < 1e-9, f"x={x}")
check("[E-456] ...and the body computes from it every evaluation (y = 2x)",
      y is not None and abs(y - 10.0) < 1e-9, f"y={y}")

# ----------------------------------------- multiple initial blocks compose ---
print("\nmultiple initial blocks still execute as if concatenated (LRM 5.2)")
g, = opvars("order_init", ["g"], "order")
check("[E-456] two initial blocks compose in source order (g = 1m then g+1m)",
      g is not None and abs(g - 2e-3) < 1e-12, f"g={g}")

for junk in os.listdir(WORK):
    if junk.startswith("_ai"):
        try:
            os.remove(os.path.join(WORK, junk))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
