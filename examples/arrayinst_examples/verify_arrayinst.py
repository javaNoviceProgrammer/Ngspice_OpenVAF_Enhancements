#!/usr/bin/env python3
"""Enhancement-441: array instances -- `R[0:3] a b r=1k` is four resistors.

A schematic tool writes a repeated device as one symbol with a range on its
reference designator, and the netlist that falls out of that is

    R[0:3]  a b         r=1k    -> R[0] a b r=1k ... R[3] a b r=1k
    N[0:3]  a[0:3] b    model   -> N[0] a[0] b model ... N[3] a[3] b model
    N[0:3]  a[0:3] a[1:4] model -> N[0] a[0] a[1] model ... N[3] a[3] a[4] model

The range on the instance NAME is what selects this reading, and that is the
whole of the rule. Enhancement-221 already gave a range in a NODE field a
different and equally useful meaning -- one device with a wide port,
`X1 bus[0:3] sub` -> `X1 bus[0] bus[1] bus[2] bus[3] sub` -- and decks rely on
it, so the two cannot both apply to one line and the instance name decides:

    name is a range   N cards; a node range is indexed IN STEP with the instance
    name is scalar    one card; a node range expands in place, exactly as before

Every structural check below is paired with an electrical one against a value
worked out by hand, because a wrong expansion still produces a circuit that
simulates -- it just answers the wrong question. Four 1k resistors in parallel
against a 250 ohm source read exactly 0.5; a single one would read 0.8.
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

# See verify_sensrestore.py: check_both_solvers rewrites each deck and restores
# it at exit, which re-creates anything deleted at the end of main. Registering
# here, before the first deck is written, puts this cleanup last.
import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ai_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

# The .osdi is a build artifact (examples/**/*.osdi is gitignored), so compile it
# here from the committed source, as every other Verilog-A example does.
OSDI = "arrayres.osdi"
_vaf = subprocess.run([OPENVAF, "arrayres.va", "-o", OSDI], cwd=HERE,
                      capture_output=True, text=True)
_have_osdi = _vaf.returncode == 0 and os.path.isfile(os.path.join(HERE, OSDI))

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, timeout=180):
    deck = (f"arrayinst {tag}\n{body}\n.control\noption noacct\nset numdgt=10\n"
            f"{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_ai_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def v(out, node):
    m = re.search(r"v\(" + re.escape(node) + r"\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)",
                  out, re.I)
    return float(m.group(1)) if m else None


def cards(out):
    """the element lines of an expanded listing"""
    return [ln.split(":", 1)[1].strip()
            for ln in out.splitlines() if re.match(r"^\s*\d+\s*:", ln)]


print("Enhancement-441: array instances\n")

# ------------------------------------------------------------------ form 1 ---
print("R[0:3] a b r=1k -- four devices, scalar fields shared")
rc, out = run("V1 in 0 dc 1\nRs in a 250\nR[0:3] a 0 1k",
              "listing e\nop\nprint v(a)", "par")
L = cards(out)
check("[E-441] four cards are produced, one per index",
      sum(1 for ln in L if re.fullmatch(r"r\[\d\] a 0 1k", ln)) == 4,
      f"{[ln for ln in L if ln.startswith('r[')]}")
check("[E-441] and they are in parallel: 4x1k against 250 reads 0.5, not 0.8",
      v(out, "a") is not None and abs(v(out, "a") - 0.5) < 1e-9,
      f"v(a)={v(out,'a')}")

# ------------------------------------------------------------------ form 2 ---
print("\nN[0:3] a[0:3] b model -- a node range is taken IN STEP")
LADDER = ("V1 in 0 dc 1\nRs in x 100\n"
          "Ra0 x a[0] 1k\nRa1 x a[1] 2k\nRa2 x a[2] 4k\nRa3 x a[3] 8k\n")
rc, out = run(LADDER + "R[0:3] a[0:3] 0 1k",
              "listing e\nop\nprint v(a[0]) v(a[1]) v(a[2]) v(a[3])", "step")
L = cards(out)
check("[E-441] element i takes bit i",
      all(f"r[{i}] a[{i}] 0 1k" in L for i in range(4)),
      f"{[ln for ln in L if ln.startswith('r[')]}")
# each rung is Ra_i in series with the array element to ground
vx = 1.0 / (1/2000. + 1/3000. + 1/5000. + 1/9000.)
vx = vx / (100.0 + vx)
RUNGS = (1000.0, 2000.0, 4000.0, 8000.0)
for i, ra in enumerate(RUNGS):
    want = vx * 1000.0 / (ra + 1000.0)
    got = v(out, f"a[{i}]")
    check(f"[E-441] v(a[{i}]) is the analytic divider value ({want:.8f})",
          got is not None and abs(got - want) < 1e-8, f"{got}")

# ------------------------------------------------------------------ form 3 ---
print("\nN[0:3] a[0:3] a[1:4] model -- a chain")
rc, out = run("V1 in 0 dc 1\nRs in a[0] 1k\nR[0:3] a[0:3] a[1:4] 1k\n"
              "Rend a[4] 0 1k", "listing e\nop\nprint v(a[0]) v(a[4])", "chain")
L = cards(out)
check("[E-441] element i spans bit i to bit i+1",
      all(f"r[{i}] a[{i}] a[{i+1}] 1k" in L for i in range(4)),
      f"{[ln for ln in L if ln.startswith('r[')]}")
check("[E-441] 1k + 4x1k + 1k in series: v(a[0]) = 5/6",
      v(out, "a[0]") is not None and abs(v(out, "a[0]") - 5.0/6.0) < 1e-9,
      f"{v(out,'a[0]')}")
check("[E-441] ...and v(a[4]) = 1/6",
      v(out, "a[4]") is not None and abs(v(out, "a[4]") - 1.0/6.0) < 1e-9,
      f"{v(out,'a[4]')}")

# --------------------------------------------------------------- Verilog-A ---
print("\nthe same for a Verilog-A device -- arrayres with r=1k IS a 1k resistor,")
print("so it must reproduce the resistor answers exactly")
check("[E-441] the Verilog-A model compiles", _have_osdi,
      _vaf.stderr.strip()[-160:] if not _have_osdi else "")
if _have_osdi:
    rc, out = run(LADDER + "N[0:3] a[0:3] 0 arrayres\n.model arrayres arrayres r=1k",
                  f"pre_osdi {OSDI}\nlisting e\nop\n"
                  "print v(a[0]) v(a[1]) v(a[2]) v(a[3])", "va")
    L = cards(out)
    check("[E-441] four OSDI instances, each on its own bit",
          all(f"n[{i}] a[{i}] 0 arrayres" in L for i in range(4)),
          f"{[ln for ln in L if ln.startswith('n[')]}")
    for i, ra in enumerate(RUNGS):
        want = vx * 1000.0 / (ra + 1000.0)
        got = v(out, f"a[{i}]")
        check(f"[E-441] Verilog-A v(a[{i}]) equals the resistor answer",
              got is not None and abs(got - want) < 1e-8, f"{got}")

# ---------------------------------------------------- the deciding rule ------
print("\nthe instance name decides which reading applies")
rc, out = run("V1 in 0 dc 1\nX1 bus[0:3] sub\n"
              ".subckt sub p0 p1 p2 p3\nR0 p0 0 1k\nR1 p1 0 2k\n"
              "R2 p2 0 4k\nR3 p3 0 8k\n.ends\n"
              "Rd0 in bus[0] 1k\nRd1 in bus[1] 1k\n"
              "Rd2 in bus[2] 1k\nRd3 in bus[3] 1k",
              "op\nprint v(bus[0]) v(bus[3])", "e221")
check("[E-441] a SCALAR-named device still gets E-221's wide-port expansion",
      v(out, "bus[0]") is not None and abs(v(out, "bus[0]") - 0.5) < 1e-9
      and abs(v(out, "bus[3]") - 8.0/9.0) < 1e-9,
      f"bus[0]={v(out,'bus[0]')} bus[3]={v(out,'bus[3]')}")

rc, out = run("V1 in 0 dc 1\nRs in a 250\nX[0:3] a 0 sub\n"
              ".subckt sub p n\nR1 p n 1k\n.ends", "op\nprint v(a)", "xarr")
check("[E-441] X[0:3] instantiates the subcircuit four times",
      v(out, "a") is not None and abs(v(out, "a") - 0.5) < 1e-9, f"v(a)={v(out,'a')}")

rc, out = run("V1 in 0 dc 1\nRs in a 250\nX1 a 0 sub\n"
              ".subckt sub p n\nR[0:3] p n 1k\n.ends", "op\nprint v(a)", "insub")
check("[E-441] an array instance inside a .subckt body works",
      v(out, "a") is not None and abs(v(out, "a") - 0.5) < 1e-9, f"v(a)={v(out,'a')}")

# ------------------------------------------------------------- descending ----
print("\ndescending ranges pair positionally")
rc, out = run("V1 in 0 dc 1\nRs in a[0] 1k\nR[3:0] a[3:0] a[4:1] 1k\n"
              "Rend a[4] 0 1k", "listing e\nop\nprint v(a[0])", "desc")
L = cards(out)
check("[E-441] a descending name pairs with a descending node range",
      all(f"r[{i}] a[{i}] a[{i+1}] 1k" in L for i in range(4)),
      f"{[ln for ln in L if ln.startswith('r[')]}")
check("[E-441] ...and is electrically the same chain as the ascending form",
      v(out, "a[0]") is not None and abs(v(out, "a[0]") - 5.0/6.0) < 1e-9,
      f"{v(out,'a[0]')}")

# --------------------------------------------------------------- refusals ----
print("\nwhat is refused -- and must STOP the run, not warn and carry on")
rc, out = run("V1 in 0 dc 1\nR[0:3] a[0:1] 0 1k\nRs in a[0] 1k",
              "op\nprint v(a[0])", "mismatch")
# an earlier version printed the error and let the line through; ngspice then
# built ONE resistor literally named `r[0:3]` and completed the run
check("[E-441] a width mismatch is named and the deck is rejected",
      rc != 0 and "has 4 elements but" in out and v(out, "a[0]") is None,
      f"rc={rc}")
rc, out = run("V1 a 0 dc 1\nA[0:2] %vd(a 0) %vd(o 0) m\n"
              ".model m gain(gain=2)\nRo o 0 1k", "op\nprint v(o)", "xspice")
check("[E-441] an XSPICE A-device array is refused, with the reason",
      rc != 0 and "not available for XSPICE" in out, f"rc={rc}")

# -------------------------------------------------------------- addressing ---
print("\nthe elements must be reachable afterwards")
BASE = "V1 in 0 dc 1\nRs in a 250\nR[0:3] a 0 1k"
rc, out = run(BASE, "op\nprint @r[2][resistance]", "read")
m = re.search(r"@r\[2\]\[resistance\]\s*=\s*(\S+)", out, re.I)
check("[E-441] print @r[2][resistance] resolves the bracketed name",
      bool(m) and abs(float(m.group(1)) - 1000.0) < 1e-6,
      f"{m.group(1) if m else None}")
rc, out = run(BASE, "op\nprint v(a)\nalter @r[1][resistance]=1meg\nop\nprint v(a)",
              "alter")
vs = re.findall(r"v\(a\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)
# three 1k in parallel (333.33) beside a 1meg, against Rs = 250
want = 1.0 / (3/1000. + 1/1e6)
want = want / (250.0 + want)
check("[E-441] alter @r[1][resistance] changes exactly that element",
      len(vs) >= 2 and abs(float(vs[0]) - 0.5) < 1e-9
      and abs(float(vs[1]) - want) < 1e-8, f"{vs} want {want:.10f}")
rc, out = run(BASE, "sweep @r[0][resistance] 1k 1meg 999k -analysis op -output v(a)\n"
                    "print sweep1.v(a)", "sweep")
check("[E-441] sweep @r[0][resistance] runs over the element",
      rc == 0 and "over 2 points" in out, f"rc={rc}")

# ------------------------------------------------------- deeper hierarchy ----
print("\nsubcircuit hierarchy")
rc, out = run("V1 in 0 dc 1\nRs in a 125\nX1 a 0 sub\nX2 a 0 sub\n"
              ".subckt sub p n\nR[0:3] p n 1k\n.ends",
              "listing e\nop\nprint v(a)", "twice")
L = cards(out)
check("[E-441] a subckt containing an array, instantiated twice, gives 8 "
      "uniquely-named devices",
      sum(1 for ln in L if re.match(r"r\.x[12]\.r\[\d\] a 0 1k", ln)) == 8,
      f"{len([ln for ln in L if ln.startswith('r.x')])} cards")
check("[E-441] ...and 8x1k in parallel (125) against Rs=125 reads 0.5",
      v(out, "a") is not None and abs(v(out, "a") - 0.5) < 1e-9, f"v(a)={v(out,'a')}")

rc, out = run("V1 in 0 dc 1\nRs in a 125\nX1 a 0 outer\n"
              ".subckt outer p n\nX[0:1] p n inner\n.ends\n"
              ".subckt inner p n\nR[0:1] p n 1k\n.ends",
              "listing e\nop\nprint v(a)", "nested")
L = cards(out)
check("[E-441] arrays nest: an array of subckts each containing an array",
      sum(1 for ln in L if re.match(r"r\.x1\.x\[\d\]\.r\[\d\] a 0 1k", ln)) == 4,
      f"{[ln for ln in L if ln.startswith('r.x1')]}")
check("[E-441] ...and 4x1k (250) against Rs=125 reads 2/3",
      v(out, "a") is not None and abs(v(out, "a") - 2.0/3.0) < 1e-9,
      f"v(a)={v(out,'a')}")

HIER = ("V1 in 0 dc 1\nRs in a 250\nX1 a 0 sub\n"
        ".subckt sub p n\nR[0:3] p mid[0:3] 1k\nRt[0:3] mid[0:3] n 1k\n.ends")
rc, out = run(HIER, "op\nprint v(x1.mid[2]) @r.x1.r[2][resistance]", "hieracc")
m = re.search(r"@r\.x1\.r\[2\]\[resistance\]\s*=\s*(\S+)", out, re.I)
check("[E-441] an array element's internal node reads hierarchically",
      v(out, "x1.mid[2]") is not None
      and abs(v(out, "x1.mid[2]") - 1.0/3.0) < 1e-9, f"{v(out,'x1.mid[2]')}")
check("[E-441] and so does its parameter, as @r.x1.r[2][resistance]",
      bool(m) and abs(float(m.group(1)) - 1000.0) < 1e-6,
      f"{m.group(1) if m else None}")

# ------------------------------------------- the rest of the .control surface -
print("\nthe remaining .control paths that split @name[param]")
# .dc on an array element -- the CARD and the command both failed fatally with
# "not in the circuit" until the split was taught the bracketed name
DCB = "V1 in 0 dc 1\nRs in x 250\nR[0:3] x 0 1k"
rc, out = run(DCB, "dc @r[3][resistance] 1k 9k 4k\nprint v(x)", "dcsweep")
rows = re.findall(r"^\d+\s+\S+\s+(\S+)", out, re.M)
# three fixed 1k beside the swept one, against Rs = 250
wants = [1.0/(3/1000. + 1/r3) for r3 in (1000., 5000., 9000.)]
wants = [w/(250.0 + w) for w in wants]
check("[E-441] dc sweeping an array element runs and moves only that element",
      len(rows) >= 3 and all(abs(float(rows[i]) - wants[i]) < 1e-7 for i in range(3)),
      f"{rows[:3]} want {[f'{w:.8f}' for w in wants]}")
rc, out = run(DCB.replace("R[0:3] x 0 1k", "R1 x 0 1k\nR[0:3] x 0 4k"),
              "save @r[1][i] @r1[i] v(x)\nop\nprint @r[1][i] @r1[i] v(x)", "save")
# a save list that matches nothing loses the WHOLE plot, so this must resolve
rp = 1.0/(1/1000. + 4/4000.)
vx = rp/(250.0 + rp)
m1 = re.search(r"@r\[1\]\[i\]\s*=\s*(\S+)", out, re.I)
check("[E-441] save @r[1][i] resolves (an unresolved save loses the whole plot)",
      bool(m1) and abs(abs(float(m1.group(1))) - vx/4000.) < 1e-12,
      f"{m1.group(1) if m1 else None}")

# --------------------------------------------------------------- controls ----
print("\nCONTROLS -- the established accessor forms and plain decks")
rc, out = run("V1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k",
              "op\nprint v(nb) @r1[resistance]", "plain")
m = re.search(r"@r1\[resistance\]\s*=\s*(\S+)", out, re.I)
check("[E-441] an ordinary @dev[param] is unchanged",
      rc == 0 and abs(v(out, "nb") - 0.5) < 1e-9
      and bool(m) and abs(float(m.group(1)) - 1000.0) < 1e-6,
      f"v(nb)={v(out,'nb')} r1={m.group(1) if m else None}")
rc, out = run("V1 in 0 dc 1\nR1 in a[2] 1k\nR2 a[2] 0 1k", "op\nprint v(a[2])",
              "scalarbit")
check("[E-441] a scalar bus bit a[2] is still an ordinary node",
      rc == 0 and abs(v(out, "a[2]") - 0.5) < 1e-9, f"v(a[2])={v(out,'a[2]')}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
