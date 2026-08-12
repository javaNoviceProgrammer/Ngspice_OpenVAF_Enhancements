#!/usr/bin/env python3
"""Enhancement-443: bracketed index LISTS, for nodes and for instances alike.

Enhancement-221 gave a node field `base[lo:hi]` and Enhancement-441 gave an
instance name the same. Both now also read an explicit list, and the two written
together:

    base[lo:hi]        a range           a[0:3]   -> 0 1 2 3
    base[i,j,k]        a list            a[1,3,5] -> 1 3 5
    base[lo:hi,k,...]  both              a[0:1,7] -> 0 1 7

which means every reading those two enhancements established carries over
unchanged -- a list on a node field binds consecutive terminals, a list on an
instance name makes one card per element, and a node list on an array instance
is taken IN STEP with it:

    X1      a[1,3,5,7] sub   -> one instance, four terminals
    R[1,3,5] a 0 1k          -> three resistors named r[1], r[3], r[5]
    R[1,3,5] a[2,4,6] 0 1k   -> r[1] a[2] .. r[3] a[4] .. r[5] a[6]

The indices are used in WRITTEN order -- neither sorted nor deduplicated --
because the order is what binds nodes to terminals.

The one rule that keeps every existing netlist reading the way it did: a lone
`a[2]` is NOT a list. It is a scalar bus bit and stays a node name.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ix_"):
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


def run(body, ctl, tag, cards="", timeout=120):
    deck = (f"idxlist {tag}\n{body}\n{cards}\n.control\noption noacct\n"
            f"set numdgt=10\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_ix_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def cards_of(out):
    return [ln.split(":", 1)[1].strip()
            for ln in out.splitlines() if re.match(r"^\s*\d+\s*:", ln)]


def v(out, node):
    m = re.search(r"v\(" + re.escape(node) + r"\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)",
                  out, re.I)
    return float(m.group(1)) if m else None


print("Enhancement-443: index lists\n")

# ------------------------------------------------------------ node lists -----
print("a list in a NODE field binds consecutive terminals (the E-221 reading)")
SUB4 = (".subckt sub p q r s\nR1 p 0 1k\nR2 q 0 2k\nR3 r 0 4k\nR4 s 0 8k\n.ends")
rc, out = run("V1 in 0 dc 1\nX1 a[1,3,5,7] sub\n" + SUB4,
              "listing e\nop", "nodelist")
L = cards_of(out)
check("[E-443] a[1,3,5,7] binds the four ports to those four bits",
      all(f"r.x1.r{k+1} a[{b}] 0" in " ".join(L)
          for k, b in enumerate((1, 3, 5, 7))),
      f"{[ln for ln in L if ln.startswith('r.x1')]}")

rc, out = run("V1 in 0 dc 1\nX1 a[0:1,7] sub3\n"
              ".subckt sub3 p q r\nR1 p 0 1k\nR2 q 0 2k\nR3 r 0 4k\n.ends",
              "listing e\nop", "mixed")
L = cards_of(out)
check("[E-443] a range and a list together: a[0:1,7]",
      all(f"a[{b}] 0" in " ".join(L) for b in (0, 1, 7)),
      f"{[ln for ln in L if ln.startswith('r.x1')]}")

rc, out = run("V1 in 0 dc 1\nX1 a[5,3,1] sub3\n"
              ".subckt sub3 p q r\nR1 p 0 1k\nR2 q 0 2k\nR3 r 0 4k\n.ends",
              "listing e\nop", "order")
L = " ".join(cards_of(out))
check("[E-443] the written ORDER is kept, not sorted",
      "r.x1.r1 a[5] 0 1k" in L and "r.x1.r3 a[1] 0 4k" in L,
      f"{[ln for ln in cards_of(out) if ln.startswith('r.x1')]}")

# ------------------------------------------------------- instance lists ------
print("\na list on the INSTANCE NAME makes one card per element (E-441)")
rc, out = run("V1 in 0 dc 1\nRs in a 250\nR[1,3,5] a 0 1k",
              "listing e\nop\nprint v(a)", "instlist")
L = cards_of(out)
check("[E-443] R[1,3,5] makes exactly r[1], r[3], r[5]",
      sorted(ln for ln in L if ln.startswith("r[")) ==
      ["r[1] a 0 1k", "r[3] a 0 1k", "r[5] a 0 1k"],
      f"{[ln for ln in L if ln.startswith('r[')]}")
# three 1k in parallel is 333.3 against Rs=250 -> 0.5714...
want = (1000.0 / 3) / (250.0 + 1000.0 / 3)
check("[E-443] and they are three real devices in parallel",
      v(out, "a") is not None and abs(v(out, "a") - want) < 1e-9,
      f"v(a)={v(out,'a')} want {want:.10f}")

rc, out = run("V1 in 0 dc 1\nRs in a 250\nR[0:1,7] a 0 1k",
              "listing e\nop", "instmixed")
L = cards_of(out)
check("[E-443] the mixed form works on an instance too: R[0:1,7]",
      sorted(ln for ln in L if ln.startswith("r[")) ==
      ["r[0] a 0 1k", "r[1] a 0 1k", "r[7] a 0 1k"],
      f"{[ln for ln in L if ln.startswith('r[')]}")

# ------------------------------------------------------------- in step ------
print("\na node list on an array instance is taken IN STEP with it")
rc, out = run("V1 in 0 dc 1\nRs in x 100\n"
              "Ra2 x a[2] 1k\nRa4 x a[4] 2k\nRa6 x a[6] 4k\n"
              "R[1,3,5] a[2,4,6] 0 1k",
              "listing e\nop\nprint v(a[2]) v(a[4]) v(a[6])", "instep")
L = cards_of(out)
check("[E-443] element i takes list entry i",
      all(f"r[{n}] a[{b}] 0 1k" in L
          for n, b in ((1, 2), (3, 4), (5, 6))),
      f"{[ln for ln in L if ln.startswith('r[')]}")
# each rung is Ra in series with a 1k to ground; check one analytically
vx = 1.0 / (1 / 2000. + 1 / 3000. + 1 / 5000.)
vx = vx / (100.0 + vx)
check("[E-443] ...and the circuit it builds is the analytic one",
      v(out, "a[2]") is not None
      and abs(v(out, "a[2]") - vx * 1000.0 / 2000.0) < 1e-8,
      f"v(a[2])={v(out,'a[2]')} want {vx * 0.5:.10f}")

# the two spellings may be mixed across the line
rc, out = run("V1 in 0 dc 1\nR[0:2] a[1,3,5] 0 1k", "listing e", "crossmix")
L = cards_of(out)
check("[E-443] a range name with a list node field pairs positionally",
      all(f"r[{n}] a[{b}] 0 1k" in L for n, b in ((0, 1), (1, 3), (2, 5))),
      f"{[ln for ln in L if ln.startswith('r[')]}")

# ---------------------------------------------------------- wrapped refs -----
print("\nwrapped references on a card expand too (the E-408 path)")
BUS = ("V1 in 0 dc 1\n"
       + "\n".join(f"R{b} in a[{b}] 1k\nRg{b} a[{b}] 0 1k" for b in (0, 1, 3, 5)))
for tag, ref, want_bits in (("wlist", "v(a[1,3,5])", {1, 3, 5}),
                            ("wrange", "v(a[0:1])", {0, 1}),
                            ("wmixed", "v(a[0:1,5])", {0, 1, 5}),
                            ("wscalar", "v(a[3])", {3})):
    rc, out = run(BUS, "op\ndisplay", tag, cards=f".save {ref}")
    got = {int(m) for m in re.findall(r"a\[(\d+)\]", out)}
    check(f"[E-443] .save {ref} saves exactly {sorted(want_bits)}",
          got == want_bits, f"{sorted(got)}")

# ------------------------------------------------------------- refusals -----
print("\nwhat must be refused or reported")
rc, out = run("V1 in 0 dc 1\nR[1,3,5] a[2,4] 0 1k", "op", "mismatch")
check("[E-443] a length mismatch names both and rejects the deck",
      rc != 0 and "has 3 elements but" in out and "has 2" in out, f"rc={rc}")

# A malformed list is not harmless: the stray comma re-tokenises the line and
# ngspice built a resistor with no value from it, warning only that the value
# was "too small". Say what actually happened.
for tag, tok in (("trail", "a[1,]"), ("lead", "a[,1]"), ("double", "a[1,,2]"),
                 ("colons", "a[1:2:3]"), ("empty", "a[]")):
    rc, out = run(f"V1 in 0 dc 1\nR1 in {tok} 1k", "op", "bad" + tag)
    check(f"[E-443] {tok} is reported, not silently used as a node name",
          "looks like an index list" in out, "")

# ---------------------------------------------------------- CONTROLS --------
print("\nCONTROLS -- everything that worked before must be untouched")
rc, out = run("V1 in 0 dc 1\nR1 in a[2] 1k\nR2 a[2] 0 1k",
              "listing e\nop\nprint v(a[2])", "scalarbit")
L = cards_of(out)
check("[E-443] a lone a[2] is still a scalar bit, NOT a one-element list",
      "r1 in a[2] 1k" in L and abs(v(out, "a[2]") - 0.5) < 1e-9,
      f"{[ln for ln in L if ln.startswith('r')]}")
check("[E-443] ...and it warns about nothing",
      "looks like an index list" not in out, "")
rc, out = run("V1 in 0 dc 1\nR1 in mem[addr] 1k\nR2 mem[addr] 0 1k", "op",
              "nonnum")
check("[E-443] a non-numeric bracketed name is left alone, and quiet",
      rc == 0 and "looks like an index list" not in out, f"rc={rc}")
rc, out = run("V1 in 0 dc 1\nX1 bus[0:3] sub\n"
              ".subckt sub p q r s\nR1 p 0 1k\nR2 q 0 1k\nR3 r 0 1k\n"
              "R4 s 0 1k\n.ends", "listing e\nop", "e221")
L = " ".join(cards_of(out))
check("[E-443] E-221's plain range is unchanged",
      all(f"bus[{b}] 0 1k" in L for b in range(4)), "")
rc, out = run("V1 in 0 dc 1\nRs in a 250\nR[0:3] a 0 1k",
              "listing e\nop\nprint v(a)", "e441")
check("[E-443] E-441's plain range instance is unchanged",
      len([ln for ln in cards_of(out) if ln.startswith("r[")]) == 4
      and abs(v(out, "a") - 0.5) < 1e-9, f"v(a)={v(out,'a')}")

# E-411 warns that a DESCENDING RANGE reverses the binding. A list has no
# direction to mistake -- the order is written out -- so it must stay quiet.
rc, out = run("V1 in 0 dc 1\nX1 a[1:0] sb\n"
              ".subckt sb p q\nR1 p 0 1k\nR2 q 0 1k\n.ends", "op", "desc")
check("[E-443] E-411 still warns for a descending RANGE",
      "descending bus range" in out, "")
rc, out = run("V1 in 0 dc 1\nX1 a[3,1] sb\n"
              ".subckt sb p q\nR1 p 0 1k\nR2 q 0 1k\n.ends", "op", "desclist")
check("[E-443] ...and stays quiet for a list, which has no direction to mistake",
      "descending bus range" not in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
