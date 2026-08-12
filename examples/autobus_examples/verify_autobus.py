#!/usr/bin/env python3
"""Enhancement-444: `.option autobus` -- connect a Verilog-A bus port by name.

A Verilog-A `inout [0:4] a` compiles to five OSDI terminals named `a[0]` ..
`a[4]`, so the netlist has always had to spell all five out:

    N1 a[0] a[1] a[2] a[3] a[4] b busdev

But the model already knows its own shape: `dev->termNames[]` holds exactly
those names, and Enhancement-402 was already reading that table to report which
terminals a short line left unconnected. With the option set, a line that
supplies one token per PORT rather than one per TERMINAL is expanded using the
model's own bit indices:

    .option autobus
    N1 a b busdev        ->    N1 a[0] a[1] a[2] a[3] a[4] b busdev

so `a[2]` elsewhere in the deck binds to the same node.

It is OPT-IN because a short instance line already means something: it leaves
trailing terminals unconnected, which is the `$port_connected` idiom that
BSIMSOI, BSIM-CMG/IMG/BULK, BSIM6 and PSP-HV rely on. Every check below that
matters is a differential -- the expanded form against the same circuit written
out in full, and the option off against the option on.
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
        if junk.startswith("_ab_"):
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


MODELS = ("busdev", "busoff", "busopt", "bustwo")
compiled = {}
for m in MODELS:
    r = subprocess.run([OPENVAF, f"{m}.va", "-o", f"{m}.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    compiled[m] = r.returncode == 0 and os.path.isfile(os.path.join(HERE, f"{m}.osdi"))


def run(body, ctl, tag, model, cards="", timeout=120):
    deck = (f"autobus {tag}\n{body}\n{cards}\n.control\noption noacct\n"
            f"set numdgt=8\npre_osdi {model}.osdi\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_ab_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def volts(out):
    """every printed v(...) value, keyed by node"""
    return dict(re.findall(r"v\(([^)]+)\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)",
                           out, re.I))


print("Enhancement-444: .option autobus\n")
check("[E-444] the Verilog-A models compile", all(compiled.values()),
      f"{[m for m, ok in compiled.items() if not ok]}")

# ------------------------------------------------------------- the feature ---
# A 5-bit bus and a scalar. The ladder makes every bit read a different voltage,
# so a mis-ordered or mis-indexed expansion cannot pass by coincidence.
LADDER = ("V1 in 0 dc 1\nRs in x 100\nRb b 0 1\n"
          + "\n".join(f"R{k} x a[{k}] 1k" for k in range(5)))
FULL = "N1 a[0] a[1] a[2] a[3] a[4] b busdev"
SHORT = "N1 a b busdev"
PRINT = "op\nprint " + " ".join(f"v(a[{k}])" for k in range(5))

print("\none token per port expands to one per terminal")
rc_f, out_f = run(LADDER + "\n" + FULL, PRINT, "full", "busdev",
                  cards=".model busdev busdev r=1k")
rc_s, out_s = run(LADDER + "\n" + SHORT, PRINT, "short", "busdev",
                  cards=".option autobus\n.model busdev busdev r=1k")
vf, vs = volts(out_f), volts(out_s)
check("[E-444] the explicit form works (the reference)",
      rc_f == 0 and len(vf) == 5, f"rc={rc_f} {len(vf)} nodes")
check("[E-444] `N1 a b` with the option reads BIT-IDENTICAL to it",
      rc_s == 0 and vf == vs and len(vs) == 5, f"{vs}")
# and the five bits really are different, so the comparison has content
check("[E-444] ...on a ladder where all five bits differ",
      len(set(vs.values())) == 5, f"{sorted(vs.values())}")

print("\nthe indices come from the MODEL, not assumed 0..n-1")
LAD2 = ("V1 in 0 dc 1\nRs in x 100\nRb b 0 1\n"
        + "\n".join(f"R{k} x a[{k}] 1k" for k in (1, 2, 3, 4)))
P2 = "op\nprint " + " ".join(f"v(a[{k}])" for k in (1, 2, 3, 4))
rc_f, out_f = run(LAD2 + "\nN1 a[1] a[2] a[3] a[4] b busoff", P2, "offfull",
                  "busoff", cards=".model busoff busoff r=1k")
rc_s, out_s = run(LAD2 + "\nN1 a b busoff", P2, "offshort", "busoff",
                  cards=".option autobus\n.model busoff busoff r=1k")
check("[E-444] a bus declared [4:1] expands to a[1]..a[4], matching explicit",
      rc_s == 0 and volts(out_f) == volts(out_s) and len(volts(out_s)) == 4,
      f"{volts(out_s)}")

print("\ntwo bus ports on one device")
LAD3 = ("V1 in 0 dc 1\nRs in x 100\nRc c 0 1\n"
        + "\n".join(f"Rp{k} x p[{k}] 1k" for k in range(2))
        + "\n" + "\n".join(f"Rq{k} x q[{k}] 1k" for k in range(3)))
P3 = "op\nprint v(p[0]) v(p[1]) v(q[0]) v(q[1]) v(q[2])"
rc_f, out_f = run(LAD3 + "\nN1 p[0] p[1] q[0] q[1] q[2] c bustwo", P3, "twofull",
                  "bustwo", cards=".model bustwo bustwo r=1k")
rc_s, out_s = run(LAD3 + "\nN1 p q c bustwo", P3, "twoshort", "bustwo",
                  cards=".option autobus\n.model bustwo bustwo r=1k")
check("[E-444] `N1 p q c` fills both buses, matching the explicit form",
      rc_s == 0 and volts(out_f) == volts(out_s) and len(volts(out_s)) == 5,
      f"{volts(out_s)}")

print("\nthe token name is what gets indexed")
rc, out = run(LADDER.replace("a[", "foo[") + "\nN1 foo b busdev",
              "op\nprint " + " ".join(f"v(foo[{k}])" for k in range(5)),
              "rename", "busdev",
              cards=".option autobus\n.model busdev busdev r=1k")
check("[E-444] `N1 foo b` binds foo[0]..foo[4]",
      rc == 0 and len(volts(out)) == 5, f"{volts(out)}")

# ------------------------------------------------------- OPT-IN is the point --
print("\nCOMPATIBILITY -- the option is opt-in precisely so these do not move")
rc, out = run(LADDER + "\n" + SHORT, "op", "nooption", "busdev",
              cards=".model busdev busdev r=1k")
check("[E-444] without the option a short line is still under-connected",
      "4 of the 6 terminals" in out and "terminal 3 ('a[2]') is absent" in out,
      "")

# $port_connected: three SCALAR ports, two tokens. Port count (3) never equals
# the token count (2), so this can never be mistaken for the bus shorthand --
# with the option on OR off.
POPT = ("V1 in 0 dc 1\nRs in nb 1k\nN1 nb 0 busopt")
rc_a, out_a = run(POPT, "op\nprint v(nb)", "pcoff", "busopt",
                  cards=".model busopt busopt r=1k")
rc_b, out_b = run(POPT, "op\nprint v(nb)", "pcon", "busopt",
                  cards=".option autobus\n.model busopt busopt r=1k")
check("[E-444] the $port_connected idiom is untouched by the option",
      volts(out_a) == volts(out_b)
      and "1 of the 3 terminals" in out_a and "1 of the 3 terminals" in out_b,
      f"off={volts(out_a)} on={volts(out_b)}")

# the explicit form must not be expanded twice when the option is on
rc, out = run(LADDER + "\n" + FULL, PRINT, "fullopt", "busdev",
              cards=".option autobus\n.model busdev busdev r=1k")
check("[E-444] a fully spelled-out line is unaffected by the option",
      rc == 0 and volts(out) == vf, f"{volts(out)}")

# Enhancement-438 reports an unrecognised name on a .options card. `autobus`
# must be registered, or every deck using it would carry a spurious warning --
# and the control proves the check has teeth.
rc, out = run(LADDER + "\n" + SHORT, "op", "knownopt", "busdev",
              cards=".option autobus\n.model busdev busdev r=1k")
check("[E-444] `.option autobus` is registered, so E-438 does not flag it",
      "unknown option 'autobus'" not in out, "")
rc, out = run(LADDER + "\n" + FULL, "op", "unknownopt", "busdev",
              cards=".option notanoption\n.model busdev busdev r=1k")
check("[E-444] ...and an unregistered name IS still flagged (control)",
      "unknown option 'notanoption'" in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
