#!/usr/bin/env python3
"""Enhancement-449: `.option autobus` across a subcircuit boundary.

Enhancement-444 lets one node name stand for a whole Verilog-A bus port. It
does that in INP2N, because that is where the model -- and so the bus width --
is known. Inside a `.subckt` that is too late: flattening has already run and it
substitutes FORMALS, so a definition declaring `a[0:4]` has the five formals
a[0]..a[4] and a device line writing the bare `a` matched none of them. It
became the local node `x1.a`, which INP2N then expanded into x1.a[0]..x1.a[4] --
five fresh floating nodes, the device connected to nothing.

Nothing was reported, because every terminal DID receive a node, so E-402's
under-connected warning had nothing to say. Turning the option ON therefore
REMOVED the diagnostic the same deck gets with it off.

Every check is a differential against the flat, fully-written-out instance: the
ladder makes all five bits read a different voltage, so a mis-ordered or
mis-bound expansion cannot pass by coincidence.
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
        if junk.startswith("_sb_"):
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


MODELS = ("subbus", "subdesc", "subtwo")
compiled = {}
for m in MODELS:
    r = subprocess.run([OPENVAF, f"{m}.va", "-o", f"{m}.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    compiled[m] = r.returncode == 0 and os.path.isfile(os.path.join(HERE, f"{m}.osdi"))


def run(body, model, tag, opt=True, ctl=None, timeout=120):
    """body is the netlist below the ladder; returns (rc, out)."""
    cards = (".option autobus\n" if opt is True else
             (opt + "\n" if isinstance(opt, str) else ""))
    cards += f".model {model} {model} r=1k"
    deck = (f"subbus {tag}\n{LADDER}\n{body}\n{cards}\n.control\noption noacct\n"
            f"set numdgt=8\npre_osdi {model}.osdi\n{ctl or PRINT}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_sb_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


# five bits, each reading a different voltage, plus the scalar return
LADDER = ("V1 in 0 dc 1\nRs in x 100\nRb b 0 1\n"
          + "\n".join(f"R{k} x n{k} 1k" for k in range(5)))
PRINT = "op\nprint " + " ".join(f"v(n{k})" for k in range(5))
ACT = " ".join(f"n{k}" for k in range(5))          # the five actuals, in order
BITS = " ".join(f"a[{k}]" for k in range(5))       # a[0] .. a[4]


def bits(out):
    return [v for _, v in sorted(
        re.findall(r"v\(n(\d)\)\s*=\s*(-?[\d.]+e[-+]\d+)", out, re.I))]


def nodes(out):
    return sorted(l.strip().split()[0] for l in out.splitlines()
                  if re.match(r"\s+\S+\s+: voltage", l))


print("Enhancement-449: autobus across a subcircuit boundary\n")
check("[E-449] the bus models compile", all(compiled.values()),
      f"{[m for m, ok in compiled.items() if not ok]}")

# ------------------------------------------------------------- the feature ---
print("the reference, and the fix")
rc, out = run(f"N1 {ACT} b subbus", "subbus", "flat", opt=False)
REF = bits(out)
check("[E-449] flat, fully written out (the reference)",
      rc == 0 and len(REF) == 5 and len(set(REF)) == 5, f"{REF}")

rc, out = run(f".subckt bs a[0:4] b\nN1 {BITS} b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "subexp")
check("[E-449] subckt with the device written out (control)",
      rc == 0 and bits(out) == REF, f"{bits(out)}")

rc, out = run(f".subckt bs a[0:4] b\nN1 a b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "subshort")
check("[E-449] `.subckt a[0:4]` + `N1 a b` reads BIT-IDENTICAL to it",
      rc == 0 and bits(out) == REF, f"{bits(out)}")

rc, out = run(f".subckt bs {BITS} b\nN1 a b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "subshort2")
check("[E-449] ...and so does a port list written out bit by bit",
      rc == 0 and bits(out) == REF, f"{bits(out)}")

rc, out = run(f".subckt inner a[0:4] b\nN1 a b subbus\n.ends\n"
              f".subckt outer a[0:4] b\nXi {BITS} b inner\n.ends\n"
              f"X1 {ACT} b outer", "subbus", "nested")
check("[E-449] ...and through two levels of subcircuit",
      rc == 0 and bits(out) == REF, f"{bits(out)}")

rc, out = run(f".subckt bs a[0:4] b\nN1 a b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "plural", opt=".options autobus")
check("[E-449] the plural `.options` spelling works too",
      rc == 0 and bits(out) == REF, f"{bits(out)}")

# ------------------------------------------------------------------ order ---
# The compiled model orders a bus port's terminals by ASCENDING index whatever
# direction the Verilog-A declared -- `inout [4:0] a` still yields a[0]..a[4] --
# and the instance line is positional, so the bits must leave the expander in
# that order. A DESCENDING .subckt declaration therefore binds in reverse, which
# is E-411's rule (the written order decides) one level up.
print("\nbit order")
rc, out = run(f".subckt bs a[4:0] b\nN1 a b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "descdecl")
check("[E-449] a DESCENDING .subckt declaration binds in reverse (E-411)",
      rc == 0 and bits(out) == REF[::-1], f"{bits(out)}")

rc, out = run(f"N1 {ACT} b subdesc", "subdesc", "descflat", opt=False)
REFD = bits(out)
rc, out = run(f".subckt bs a[0:4] b\nN1 a b subdesc\n.ends\nX1 {ACT} b bs",
              "subdesc", "descmodel")
check("[E-449] a model declared `[4:0]` still matches its own flat form",
      rc == 0 and len(REFD) == 5 and bits(out) == REFD, f"{bits(out)}")

# ------------------------------------------------------- several bus ports ---
print("\nseveral ports on one device")
LADDER2 = ("V1 in 0 dc 1\n" + "\n".join(f"R{k} in n{k} 1k" for k in range(5))
           + "\nRc nc 0 1")
_L, LADDER = LADDER, LADDER2
_P, PRINT = PRINT, ("op\nprint " + " ".join(f"v(n{k})" for k in range(5))
                    + " v(nc)")
rc, out = run(f"N1 {ACT} nc subtwo", "subtwo", "twoflat", opt=False)
REF2 = bits(out)
rc, out = run(f".subckt s a[0:1] b[0:2] c\nN1 a b c subtwo\n.ends\n"
              f"X1 {ACT} nc s", "subtwo", "twoshort")
check("[E-449] two bus ports and a scalar, all by name",
      rc == 0 and len(REF2) == 5 and bits(out) == REF2, f"{bits(out)}")
LADDER, PRINT = _L, _P

# ------------------------------------------------- nothing else may change ---
print("\nwhat must NOT change")
rc, out = run(f".subckt bs a[0:4] b\nN1 a b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "nooption", opt=False)
check("[E-449] with the option OFF the shorthand is still not expanded",
      rc == 0 and len(set(bits(out))) == 1, f"{bits(out)}")
check("[E-449] ...and E-402 still reports the unconnected terminals",
      "are not connected" in out)

rc, out = run(f".subckt bs a[0:4] b\nRx a[0] a 1k\nRy a 0 1k\n.ends\n"
              f"X1 {ACT} b bs", "subbus", "localnode",
              ctl="op\ndisplay")
check("[E-449] a bare bus-base name on an R line stays a LOCAL node",
      rc == 0 and "x1.a" in nodes(out), f"{nodes(out)}")

rc, out = run(f".subckt bs a a[0:1]\nRx a 0 1k\n.ends\nX1 nc n0 n1 bs",
              "subbus", "exactwins", ctl="op\ndisplay")
check("[E-449] a scalar formal `a` beside a bus `a[0:1]` wins for `a`",
      rc == 0 and "x1.a" not in nodes(out), f"{nodes(out)}")

rc, out = run(f".subckt bs a[0:4] b\nN1 {BITS} b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "explicitopt")
check("[E-449] the written-out form is unaffected by the option (control)",
      rc == 0 and bits(out) == REF, f"{bits(out)}")

# A token that cannot carry an index is still reported rather than expanded.
#
# Only ground is checked here. Writing ONE BIT of the bus -- `N1 a[0] b` inside
# a subcircuit whose port is `a[0:4]` -- is a different defect and NOT one this
# enhancement introduces or fixes: `a[0]` is a formal, so flattening resolves it
# to the actual `n0`, and INP2N then sees one token per port and expands that
# into the floating n0[0]..n0[4]. It is byte-identical before and after this
# change, because by then nothing distinguishes it from a legitimate top-level
# line whose bus base happens to be called `n0`. E-445 guarded the two spellings
# it could recognise (ground, an already-bracketed token); this one is not
# recognisable at either end, and belongs to its own investigation.
rc, out = run(f".subckt bs a[0:4] b\nN1 0 b subbus\n.ends\nX1 {ACT} b bs",
              "subbus", "badgnd", ctl="op")
check("[E-449] ground as a bus token is still diagnosed",
      "are not connected" in out or "cannot be" in out)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
