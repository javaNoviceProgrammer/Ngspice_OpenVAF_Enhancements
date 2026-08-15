#!/usr/bin/env python3
"""Enhancement-464: a bus FORMAL and a LOCAL bus on the same OSDI instance line.

Inside a subcircuit declared with BIT-LEVEL formals, an instance could carry one
of each:

    .subckt s a[0] a[1] a[2] a[3]
    N1 a b mymodel1        <- `a` is a bus formal, `b` is a local bus

Enhancement-449 expands `a` into the caller's four actuals, because the formals
`a[0]`..`a[3]` exist. `b` has no formals, so it stayed ONE token. The line then
carried five node tokens where autobus needs two (one per port) or eight (one
per terminal) -- it is neither, so INP2N expanded nothing and the tokens bound
POSITIONALLY: `a[0..3]` correctly, `x1.b` onto `b[0]`, and the top three bits
dangling.

Measured before the fix, against the same circuit flattened by hand:

    inside the subcircuit   v = 1.0          "3 of the 8 terminals ... not connected"
    hand-flattened          v = 0.5238095

It warned, but the warning named the missing terminals rather than the cause,
and the deck still ran and answered wrongly.

THE FIX. Once any port on the line has been expanded from formals the line
cannot still be in shorthand, so every remaining bus port is expanded at the
same point -- to `x1.b[k]`, exactly the node INP2N would have produced, and the
same node that a `b[0]` written elsewhere in the subcircuit translates to. The
bit spelling comes from the one shared helper, so `.option autobus=kicad`
(Enhancement-462) stays consistent.

Only MIXED lines change. Where no formal expands, or the model cannot be
resolved at flattening time, the previous path runs untouched -- pinned below,
and by Enhancement-449's own suite.

Every check is a differential: the subcircuit form must equal the same circuit
written flat, on a ladder where all four bits read differently.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_bm_"):
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


def run(body, tag, ctl, opts=".option autobus\n"):
    deck = (f"bus formal plus local bus {tag}\n{opts}{body}\n"
            ".model mymodel1 chan r0=1k\n.model mymodel2 chan r0=2k\n"
            ".model msc busscal r0=1k\n"
            f".control\npre_osdi busmix.osdi\noption noacct\nset numdgt=8\n{ctl}\n"
            ".endc\n.end\n")
    p = os.path.join(HERE, f"_bm_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=120, errors="replace")
    return r.returncode, r.stdout + r.stderr


def vals(out):
    return [v for _n, v in re.findall(
        r"v\(([^)]+)\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)]


r = subprocess.run([OPENVAF, "busmix.va", "-o", "busmix.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-464: a bus formal and a local bus on one line\n")
check("[E-464] the Verilog-A models compile",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "busmix.osdi")),
      (r.stdout + r.stderr).strip()[:60])

DRIVE = "V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in n{k} 1k" for k in range(4))
TIE = "\n".join(f"Rb{k} {{}}[{k}] 0 100" for k in range(4))

# ------------------------------------------------------- the defect ---------
print("\none device: bus formal + local bus")
FLAT = ("V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
        + "\nN1 a b mymodel1\n" + TIE.format(*["b"] * 4).replace("{}", "b"))
SUB = (DRIVE + "\nX1 " + " ".join(f"n{k}" for k in range(4)) + " s\n"
       ".subckt s a[0] a[1] a[2] a[3]\nN1 a b mymodel1\n"
       + "\n".join(f"Rb{k} b[{k}] 0 100" for k in range(4)) + "\n.ends")
rc_f, out_f = run(FLAT, "flat1", "op\nprint v(a[0]) v(a[1]) v(a[2]) v(a[3])")
rc_s, out_s = run(SUB, "sub1", "op\nprint v(n0) v(n1) v(n2) v(n3)")
vf, vs = vals(out_f), vals(out_s)
check("[E-464] the flat reference runs", rc_f == 0 and len(vf) == 4, f"{vf}")
check("[E-464] the subcircuit form gives the SAME four voltages",
      rc_s == 0 and vs == vf and len(vs) == 4, f"{vs}")
check("[E-464] ...on a ladder where all four differ", len(set(vs)) == 4, "")
check("[E-464] and no terminal is left unconnected",
      "not connected" not in out_s and "absent" not in out_s, "")

print("\ntwo devices sharing a local bus, both with bus formals")
FLAT2 = ("V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
         + "\n" + "\n".join(f"Rg{k} c[{k}] 0 100" for k in range(4))
         + "\nN1 a b mymodel1\nN2 b c mymodel2")
SUB2 = (DRIVE + "\n" + "\n".join(f"Rg{k} m{k} 0 100" for k in range(4))
        + "\nX1 " + " ".join(f"n{k}" for k in range(4)) + " "
        + " ".join(f"m{k}" for k in range(4)) + " pair\n"
        ".subckt pair a[0] a[1] a[2] a[3] c[0] c[1] c[2] c[3]\n"
        "N1 a b mymodel1\nN2 b c mymodel2\n.ends")
rc_f, out_f = run(FLAT2, "flat2", "op\nprint v(a[0]) v(a[3]) v(c[0]) v(c[3])")
rc_s, out_s = run(SUB2, "sub2", "op\nprint v(n0) v(n3) v(m0) v(m3)")
check("[E-464] both mixed lines expand, matching the flat circuit",
      rc_s == 0 and vals(out_s) == vals(out_f) and len(vals(out_s)) == 4,
      f"{vals(out_s)}")
check("[E-464] ...with no under-connected warning",
      "not connected" not in out_s, "")

print("\nthe same under `.option autobus=kicad` (E-462)")
rc_k, out_k = run(SUB.replace("b[", "b_").replace("] 0 100", "_ 0 100"), "kicad",
                  "op\nprint v(n0) v(n1) v(n2) v(n3)",
                  opts=".option autobus=kicad\n")
check("[E-464] the kicad bit spelling is used for the local bus too",
      rc_k == 0 and vals(out_k) == vf, f"{vals(out_k)}")

# --------------------------------------------------- what must not change ---
print("\nwhat the fix must leave alone")
BASE = (DRIVE + "\nX1 n s2\n.subckt s2 a\nN1 a b mymodel1\n"
        + "\n".join(f"Rb{k} b[{k}] 0 100" for k in range(4)) + "\n.ends")
BASEDRV = ("V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in n[{k}] 1k" for k in range(4))
           + "\nX1 n s2\n.subckt s2 a\nN1 a b mymodel1\n"
           + "\n".join(f"Rb{k} b[{k}] 0 100" for k in range(4)) + "\n.ends")
rc_b, out_b = run(BASEDRV, "basefml", "op\nprint v(n[0]) v(n[1]) v(n[2]) v(n[3])")
check("[E-464] a bus-BASE formal (`.subckt s2 a`) still works, unchanged",
      rc_b == 0 and vals(out_b) == vf, f"{vals(out_b)}")
LOCAL = ("V1 in 0 dc 1\nX1 in s3\n.subckt s3 in\n"
         + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
         + "\nN1 a b mymodel1\n"
         + "\n".join(f"Rb{k} b[{k}] 0 100" for k in range(4)) + "\n.ends")
rc_l, out_l = run(LOCAL, "alllocal", "op\nprint v(x1.a[0]) v(x1.a[1]) v(x1.a[2]) v(x1.a[3])")
check("[E-464] an all-LOCAL subcircuit line is untouched",
      rc_l == 0 and vals(out_l) == vf, f"{vals(out_l)}")
FMLONLY = (DRIVE + "\n" + "\n".join(f"Rg{k} m{k} 0 100" for k in range(4))
           + "\nX1 " + " ".join(f"n{k}" for k in range(4)) + " "
           + " ".join(f"m{k}" for k in range(4)) + " s4\n"
           ".subckt s4 a[0] a[1] a[2] a[3] b[0] b[1] b[2] b[3]\n"
           "N1 a b mymodel1\n.ends")
rc_o, out_o = run(FMLONLY, "fmlonly", "op\nprint v(n0) v(n3)")
check("[E-464] a line whose ports are ALL formals is untouched",
      rc_o == 0 and len(vals(out_o)) == 2 and "not connected" not in out_o,
      f"{vals(out_o)}")

print("\na bus formal beside a SCALAR port")
SCAL = (DRIVE + "\nRs s 0 1k\nX1 " + " ".join(f"n{k}" for k in range(4))
        + " s s5\n.subckt s5 a[0] a[1] a[2] a[3] sc\nN1 a sc msc\n.ends")
FSCAL = ("V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
         + "\nRs s 0 1k\nN1 a s msc")
rc_c, out_c = run(SCAL, "scal", "op\nprint v(n0) v(n3)")
rc_d, out_d = run(FSCAL, "fscal", "op\nprint v(a[0]) v(a[3])")
check("[E-464] a scalar port on a mixed line stays a single node",
      rc_c == 0 and vals(out_c) == vals(out_d) and len(vals(out_c)) == 2,
      f"{vals(out_c)}")

print("\nwith autobus OFF nothing here applies")
rc_n, out_n = run(SUB, "nobus", "op", opts="")
check("[E-464] autobus off leaves the old behaviour exactly as it was",
      "not connected" in out_n, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
