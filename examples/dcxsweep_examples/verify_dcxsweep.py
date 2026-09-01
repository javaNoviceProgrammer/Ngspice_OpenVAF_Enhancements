#!/usr/bin/env python3
"""Enhancement-534: `.dc` learns the rest of the parameter surface, and scales.

The sweep variables the `sweep`/`altermod` family established now have a dc
arm: MODEL parameters (`@mod[p]`, the dotted subcircuit spelling
`@x1.rmod[p]`), and the wildcard families `@*[p]` (every model with p),
`@#*[p]` / `@*[[p]]` (every instance with p), `@*:leaf[p]` (every model named
leaf). And the point scales: `dc <knob> lin|dec|oct N start stop`, generated
exactly the way the sweep command generates them. Targets are set through the
DEV tables directly -- the MACHINE-write path, so an osdimc nominal is never
recentered (E-531) -- with one CKTtemp per point and the E-495 collapse guard
armed, however many targets move.

Pinned here besides the features themselves: the classic triple is unchanged
byte-for-byte; the parameter-sweep overshoot slack is now RELATIVE, so a
saturation-current sweep to 5e-14 stops AT 5e-14 instead of running five
times past it (latent in E-62 since tiny parameters became sweepable);
integer parameters refuse the fractional lin/dec/oct generators and keep
E-427's whole-number rule; a collapse-gated model parameter is refused with
the E-495 message; and every knob returns to its nominal afterwards.
"""

import atexit
import math
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
        if junk.startswith("_dcx_"):
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


def run_deck(deck, tag, timeout=300):
    p = os.path.join(HERE, f"_dcx_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def cols(fname):
    rows = []
    with open(os.path.join(HERE, fname)) as f:
        for line in f:
            if line.strip():
                rows.append(list(map(float, line.split())))
    return rows


def closeall(rows, want, rel=1e-6):
    if len(rows) != len(want):
        return False
    for r, w in zip(rows, want):
        for a, b in zip(r, w):
            if abs(a - b) > rel * max(abs(b), 1e-30):
                return False
    return True


DIV = """V1 in 0 2
X1 in mid divcell
R2 mid 0 1k
.subckt divcell a b
.model rmod r rsh=100
R1 a b rmod w=1u l=10u
.ends
"""


def deck(body, extra=""):
    return "dcx probe\n" + extra + DIV + ".control\noption noacct\n" + body + "\n.endc\n.end\n"


# ---- scales on a classic source -------------------------------------------
print("scales: lin/dec/oct generate the sweep command's own point sets:")

out = run_deck(deck("dc V1 lin 5 0 1\nwrdata _dcx_lin.csv v(mid)\n"
                    "dc V1 dec 2 0.1 10\nwrdata _dcx_dec.csv v(mid)\n"
                    "dc V1 oct 1 1 8\nwrdata _dcx_oct.csv v(mid)"), "sc")
lin = cols("_dcx_lin.csv")
check("[1] lin 5: five points, both endpoints exact",
      len(lin) == 5 and lin[0][0] == 0.0 and lin[-1][0] == 1.0
      and abs(lin[2][0] - 0.5) < 1e-15)
dec = cols("_dcx_dec.csv")
want_x = [0.1 * (10 ** (k / 2.0)) for k in range(5)]
check("[2] dec 2 over 0.1..10: five points on the exact half-decade grid",
      len(dec) == 5 and all(abs(r[0] - w) < 1e-9 * w for r, w in zip(dec, want_x)))
oct_ = cols("_dcx_oct.csv")
check("[3] oct 1 over 1..8: 1,2,4,8",
      len(oct_) == 4 and all(abs(r[0] - w) < 1e-12 * w
                             for r, w in zip(oct_, [1.0, 2.0, 4.0, 8.0])))

# ---- model parameters, subcircuits, wildcards -----------------------------
print("model parameters, subcircuit spellings, wildcards:")

# rsh -> R1 = 10 squares; v(mid) = 2*1000/(R1+1000)
want = [[float(r), 2000.0 / (10 * r + 1000.0)] for r in (50, 100, 150)]
out = run_deck(deck("dc @x1.rmod[rsh] lin 3 50 150\nwrdata _dcx_dm.csv v(mid)\n"
                    "dc @*:rmod[rsh] lin 3 50 150\nwrdata _dcx_nw.csv v(mid)\n"
                    "dc @*[rsh] lin 3 50 150\nwrdata _dcx_mw.csv v(mid)\n"
                    "dc @x1.r1[resistance] lin 3 500 1500\nwrdata _dcx_ir.csv v(mid)\n"
                    "print @x1:rmod[rsh] @r.x1.r1[resistance]"), "mp")
check("[4] the dotted subcircuit-local model (`@x1.rmod[rsh]`) sweeps, on the "
      "closed form", closeall(cols("_dcx_dm.csv"), want))
check("[5] the named-model wildcard (`@*:rmod[rsh]`) matches the same copy",
      closeall(cols("_dcx_nw.csv"), want))
check("[6] the every-model wildcard (`@*[rsh]`)",
      closeall(cols("_dcx_mw.csv"), want))
want_i = [[float(r), 2000.0 / (r + 1000.0)] for r in (500, 1000, 1500)]
check("[7] the subcircuit instance parameter (E-410 spelling) still sweeps",
      closeall(cols("_dcx_ir.csv"), want_i))
check("[8] ...and every knob is back at its nominal afterwards",
      re.search(r"@x1:rmod\[rsh\]\s*=\s*1\.0*e\+0?2", out) is not None
      and re.search(r"@r\.x1\.r1\[resistance\]\s*=\s*1\.0*e\+0?3", out) is not None)

out = run_deck(deck("dc @#*[resistance] lin 3 500 1500\nwrdata _dcx_iw.csv v(mid)"),
               "iw")
# both resistors move together: v(mid) = 2*R/(R+R) = 1.0 at every point
iw = cols("_dcx_iw.csv")
check("[9] the every-instance wildcard (`@#*[resistance]`) moves both halves "
      "(ratio-invariant divider stays at 1.0)",
      len(iw) == 3 and all(abs(r[1] - 1.0) < 1e-9 for r in iw))

# ---- the relative overshoot slack -----------------------------------------
print("tiny magnitudes: the overshoot slack is relative now:")

out = run_deck("""dcx tiny
V1 in 0 5
R1 in mid 1k
R2 mid 0 1k
D1 mid 0 dm
.model dm d(is=1e-14)
.control
option noacct
dc @dm[is] 1e-14 5e-14 1e-14
wrdata _dcx_tiny.csv v(mid)
.endc
.end
""", "tiny")
tiny = cols("_dcx_tiny.csv")
check("[10] `dc @dm[is] 1e-14 5e-14 1e-14` is FIVE points ending at 5e-14 "
      "(used to run to 2.7e-13 -- five times past stop -- under the absolute "
      "slack)", len(tiny) == 5 and abs(tiny[-1][0] - 5e-14) < 1e-20)

# ---- OSDI models: machine writes, guards, integers ------------------------
print("OSDI model parameters: guards and integer rules:")

r = subprocess.run([OPENVAF, os.path.join(HERE, "dcxosdi.va"), "-o",
                    os.path.join(HERE, "_dcx_osdi.osdi")], cwd=HERE,
                   capture_output=True, text=True, timeout=600)
check("[11] the collapse-gated OSDI model compiles", r.returncode == 0)

OS = """dcx osdi
V1 a 0 1
N1 a 0 mm
.model mm dcxosdi
.control
option noacct
pre_osdi _dcx_osdi.osdi
"""
out = run_deck(OS + "dc @mm[g] lin 3 1e-3 3e-3\nwrdata _dcx_og.csv i(v1)\n"
                    "print @mm[g]\n.endc\n.end\n", "og")
og = cols("_dcx_og.csv")
check("[12] an OSDI model parameter sweeps on the closed form",
      len(og) == 3 and all(abs(r[1] + r[0]) < 1e-9 for r in og))
check("[13] ...and is restored (an osdimc-style nominal is never recentered: "
      "this is the machine-write path)",
      re.search(r"@mm\[g\]\s*=\s*1\.0*e-0?3", out) is not None)

out = run_deck(OS + "dc @mm[rd] 0 2000 500\n.endc\n.end\n", "ord")
check("[14] a collapse-gated OSDI model parameter is refused with the E-495 "
      "message (the `sweep` command is the instrument for it)",
      "changes a device's node collapse" in out and "sweep" in out)

out = run_deck("""dcx bjt guard
Vcc c 0 5
V1 b 0 0.7
Q1 c b 0 qm
.model qm npn bf=100 rc=1
.control
option noacct
dc @qm[rc] lin 3 0 10
.endc
.end
""", "bjtg")
check("[14b] a BUILT-IN node-building model parameter (BJT rc) is refused up "
      "front -- E-503's own table, consulted at dc resolution",
      "builds internal nodes at setup time" in out)
out = run_deck("""dcx bjt safe
Vcc c 0 5
V1 b 0 0.7
Q1 c b 0 qm
.model qm npn bf=100 rc=1
.control
option noacct
dc @qm[bf] lin 3 50 150
wrdata _dcx_bf.csv i(vcc)
.endc
.end
""", "bjts")
check("[14c] ...while a safe parameter of the same device (bf) sweeps",
      len(cols("_dcx_bf.csv")) == 3)

out = run_deck(OS + "dc @mm[nseg] lin 3 1 3\n.endc\n.end\n", "oint")
check("[15] an integer parameter refuses the fractional lin/dec/oct "
      "generators", "integer parameter" in out and "fractional" in out)
out = run_deck(OS + "dc @mm[nseg] 1 3 1\nwrdata _dcx_oi.csv i(v1)\n.endc\n.end\n",
               "oint2")
oi = cols("_dcx_oi.csv")
check("[16] ...and sweeps over whole numbers (E-427's rule kept)",
      len(oi) == 3 and abs(oi[2][1] + 3e-3) < 1e-9)

# ---- nesting and the classic form -----------------------------------------
print("nesting, and the classic triple untouched:")

out = run_deck(deck("dc @x1.rmod[rsh] lin 2 50 150 V1 lin 2 1 2\n"
                    "wrdata _dcx_nest.csv v(mid)"), "nest")
nest = cols("_dcx_nest.csv")
want_n = []
for v1 in (1.0, 2.0):
    for r in (50.0, 150.0):
        want_n.append([r, v1 * 1000.0 / (10 * r + 1000.0)])
check("[17] nesting: a model knob inside a source sweep, four exact points",
      closeall(nest, want_n))

out = run_deck(deck("dc V1 0 1 0.5\nwrdata _dcx_cl.csv v(mid)"), "cl")
cl = cols("_dcx_cl.csv")
check("[18] the classic triple is unchanged (3 points, exact endpoints)",
      len(cl) == 3 and cl[0][0] == 0.0 and cl[-1][0] == 1.0)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
