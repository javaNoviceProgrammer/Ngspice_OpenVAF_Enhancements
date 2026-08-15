#!/usr/bin/env python3
"""Enhancement-462: `.option autobus=kicad` -- the bit spelling a schematic can write.

Enhancement-444 names the terminals of an expanded bus port `a[0]` .. `a[4]`,
copying the bracket text from the model's own terminal name. That is the right
name everywhere except the one place a bus port is most useful: a schematic.

KiCad's SPICE exporter rewrites every `[` and `]` in a net name to `_`. A sheet
labelling a wire `AA[0]` puts `/AA_0_` in the netlist -- measured, and the rule
keeps multi-digit indices intact (`ZA[10]` -> `/ZA_10_`). Its *internal* net name
is still `/AA[0]`, which the `kicadxml` export shows, so the rewrite belongs to
the SPICE exporter alone. The consequence was that under KiCad the bits of a bus
port could not be:

  * labelled on the sheet -- the label made a DIFFERENT node, and the bit floated
  * wired to ordinary parts -- a resistor on `AA[0]` landed on `/AA_0_`
  * plotted from the simulator's signal list, which is built from schematic nets

so the only workable sheet was one where every net was a whole bus, joining bus
device to bus device.

`.option autobus=kicad` changes the generated SPELLING and nothing else. The
indices still come from the model's terminal names, so a port declared `[4:1]`
still expands 1..4; only `[k]` becomes `_k_`.

Every check that matters is a DIFFERENTIAL: the same circuit written in the two
spellings must give bit-identical answers, and each spelling must produce only
its own node names -- an expansion that quietly emitted both, or neither, would
otherwise pass a value check on the nodes that happened to exist.
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
        if junk.startswith("_kab_"):
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
    deck = (f"autobus kicad {tag}\n{body}\n{cards}\n.control\noption noacct\n"
            f"set numdgt=8\npre_osdi kbus.osdi\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_kab_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def vals(out):
    """the printed v(...) VALUES in order -- names differ between spellings"""
    return [v for _n, v in re.findall(
        r"v\(([^)]+)\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)]


def missing(out, node):
    return ("not available" in out and node.lower() in out.lower())


r = subprocess.run([OPENVAF, "kbus.va", "-o", "kbus.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-462: .option autobus=kicad\n")
check("[E-462] the Verilog-A models compile",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "kbus.osdi")),
      (r.stdout + r.stderr).strip()[:60])


def ladder(node, bits, rng=None):
    """drive every bit through 1k from a common node, so all bits differ"""
    rng = rng if rng is not None else range(bits)
    return ("V1 in 0 dc 1\nRs in x 100\nRb b 0 1\n"
            + "\n".join(f"R{k} x {node % k} 1k" for k in rng))


def prints(node, rng):
    return "op\nprint " + " ".join(f"v({node % k})" for k in rng)


# ------------------------------------------------- the spelling differential --
print("\nthe two spellings are the same circuit")
BRK, KIC = "a[%d]", "a_%d_"
rc_b, out_b = run(ladder(BRK, 5) + "\nN1 a b kb", prints(BRK, range(5)), "brk",
                  cards=".option autobus\n.model kb kbus r=1k")
rc_k, out_k = run(ladder(KIC, 5) + "\nN1 a b kb", prints(KIC, range(5)), "kic",
                  cards=".option autobus=kicad\n.model kb kbus r=1k")
vb, vk = vals(out_b), vals(out_k)
check("[E-462] the default a[k] spelling works (the reference)",
      rc_b == 0 and len(vb) == 5, f"rc={rc_b} {len(vb)} nodes")
check("[E-462] `autobus=kicad` reads BIT-IDENTICAL to it",
      rc_k == 0 and vb == vk and len(vk) == 5, f"{vk}")
check("[E-462] ...on a ladder where all five bits differ",
      len(set(vk)) == 5, f"{sorted(vk)}")

print("\neach spelling produces ONLY its own node names")
# Asked for an absent `a[0]`, ngspice reports `vector a is not available`: with no
# such NODE it falls back to reading the brackets as an index into a vector `a`.
# So absence has to be checked by the absence of a VALUE, not by the message text.
_rc, out = run(ladder(KIC, 5) + "\nN1 a b kb", "op\nprint v(a[0])", "kicnobrk",
               cards=".option autobus=kicad\n.model kb kbus r=1k")
check("[E-462] in kicad mode the bracket node a[0] does not exist",
      vals(out) == [] and "not available" in out.lower(), f"{vals(out)}")
_rc, out = run(ladder(BRK, 5) + "\nN1 a b kb", "op\nprint v(a_0_)", "brknokic",
               cards=".option autobus\n.model kb kbus r=1k")
check("[E-462] in default mode the underscore node a_0_ does not exist",
      vals(out) == [] and "not available" in out.lower(), f"{vals(out)}")

print("\nthe index text is the MODEL's, only its punctuation changes")
rc_b, out_b = run(ladder(BRK, 12) + "\nN1 a b kw", prints(BRK, range(12)), "wbrk",
                  cards=".option autobus\n.model kw kwide r=1k")
rc_k, out_k = run(ladder(KIC, 12) + "\nN1 a b kw", prints(KIC, range(12)), "wkic",
                  cards=".option autobus=kicad\n.model kw kwide r=1k")
check("[E-462] a MULTI-DIGIT index keeps its digits: a[10] -> a_10_",
      rc_k == 0 and vals(out_b) == vals(out_k) and len(vals(out_k)) == 12,
      f"{len(vals(out_k))} bits")
check("[E-462] ...and a_10_ really is one of them, not a_1_ plus stray text",
      "v(a_10_)" in out_k.lower() and "v(a_11_)" in out_k.lower(), "")
rng41 = (1, 2, 3, 4)
rc_b, out_b = run(ladder(BRK, 0, rng41) + "\nN1 a b ko", prints(BRK, rng41), "obrk",
                  cards=".option autobus\n.model ko koff r=1k")
rc_k, out_k = run(ladder(KIC, 0, rng41) + "\nN1 a b ko", prints(KIC, rng41), "okic",
                  cards=".option autobus=kicad\n.model ko koff r=1k")
check("[E-462] a bus declared [4:1] expands to a_1_..a_4_, matching brackets",
      rc_k == 0 and vals(out_b) == vals(out_k) and len(vals(out_k)) == 4,
      f"{vals(out_k)}")
check("[E-462] ...and never invents a_0_",
      "v(a_0_)" not in out_k.lower(), "")

# ---------------------------------------------- the two-pin schematic shape --
print("\ntwo bus ports -- the KiCad two-pin symbol")
TWO_B = ("V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
         + "\n" + "\n".join(f"Rg{k} b[{k}] 0 100" for k in range(4))
         + "\nN1 a b k2")
TWO_K = ("V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a_{k}_ 1k" for k in range(4))
         + "\n" + "\n".join(f"Rg{k} b_{k}_ 0 100" for k in range(4))
         + "\nN1 a b k2")
rc_b, out_b = run(TWO_B, prints("a[%d]", range(4)), "2brk",
                  cards=".option autobus\n.model k2 kbus2 r=1k")
rc_k, out_k = run(TWO_K, prints("a_%d_", range(4)), "2kic",
                  cards=".option autobus=kicad\n.model k2 kbus2 r=1k")
check("[E-462] both ports expand, and read identically to the bracket form",
      rc_k == 0 and vals(out_b) == vals(out_k) and len(vals(out_k)) == 4,
      f"{vals(out_k)}")
check("[E-462] ...with ORDINARY parts wired straight to the bits",
      "singular" not in out_k.lower() and "not connected" not in out_k.lower(), "")

# ------------------------------------------------------------ the off words --
print("\nthe off spellings are still off, and still off in this mode")
for spell in (".option autobus=0", ".option noautobus", ".option autobus=false",
              ".option autobus=no", ".option autobus=off"):
    _rc, out = run(ladder(KIC, 5) + "\nN1 a b kb", "op", "off" + re.sub(r"\W", "", spell),
                   cards=spell + "\n.model kb kbus r=1k")
    check(f"[E-462] `{spell}` leaves the line under-connected",
          "not connected" in out.lower(), "")

# --------------------------------------------------------- a bad style word --
print("\na style that does not exist is REPORTED, not silently ignored")
_rc, out = run(ladder(KIC, 5) + "\nN1 a b kb", "op\nprint v(a_0_)", "badstyle",
               cards=".option autobus=kicad2\n.model kb kbus r=1k")
check("[E-462] `autobus=kicad2` warns about the unknown style",
      "unknown autobus style" in out.lower(), "")
# It falls back to the default spelling, so the deck still SOLVES -- the bus binds
# to fresh a[k] nodes and every a_k_ is left dangling at the source voltage. That
# silent-but-wrong answer is exactly why the warning above has to exist: without
# it the only symptom is a number that looks plausible.
check("[E-462] ...and falls back, leaving a_0_ unbound at the source voltage",
      vals(out) == ["1.00000000e+00"] and vals(out) != [vk[0]], f"{vals(out)}")
for onword in ("true", "yes", "on"):
    _rc, out = run(ladder(BRK, 5) + "\nN1 a b kb", prints(BRK, range(5)),
                   "on" + onword, cards=f".option autobus={onword}\n.model kb kbus r=1k")
    check(f"[E-462] `autobus={onword}` is an ON word: default spelling, no warning",
          len(vals(out)) == 5 and "unknown autobus style" not in out.lower(), "")

# ------------------------------------------------------------- untouched -----
print("\nwhat the option must NOT change")
rc_f, out_f = run(ladder(BRK, 5) + "\nN1 a[0] a[1] a[2] a[3] a[4] b kb",
                  prints(BRK, range(5)), "explicit",
                  cards=".option autobus=kicad\n.model kb kbus r=1k")
check("[E-462] a fully spelled-out line is unaffected by the style",
      rc_f == 0 and vals(out_f) == vb, f"{vals(out_f)}")

# A subcircuit binds through the FORMALS the .subckt line declares
# (`e449_expand_bus_port`), which synthesises no name at all -- so it has no
# spelling to choose and must behave the same in either mode.
SUB = ("V1 in 0 dc 1\nRs in x 100\nRb bb 0 1\n"
       + "\n".join(f"R{k} x n{k} 1k" for k in range(5))
       + "\nX1 " + " ".join(f"n{k}" for k in range(5)) + " bb sub\n"
       ".subckt sub a[0] a[1] a[2] a[3] a[4] b\nN1 a b kb\n.ends\n")
SUBP = "op\nprint " + " ".join(f"v(n{k})" for k in range(5))
rc_1, out_1 = run(SUB, SUBP, "subbrk", cards=".option autobus\n.model kb kbus r=1k")
rc_2, out_2 = run(SUB, SUBP, "subkic", cards=".option autobus=kicad\n.model kb kbus r=1k")
check("[E-462] inside a .subckt the formals bind, identically in both modes",
      rc_1 == 0 and rc_2 == 0 and vals(out_1) == vals(out_2) and len(vals(out_2)) == 5,
      f"{vals(out_2)}")
check("[E-462] ...and that is the SAME answer the top-level form gives",
      vals(out_2) == vb, f"{vals(out_2)}")

# E-438's option checker must know the name AND accept the value
_rc, out = run(ladder(KIC, 5) + "\nN1 a b kb", "op", "known",
               cards=".option autobus=kicad\n.model kb kbus r=1k")
check("[E-462] `.option autobus=kicad` is not reported as an unknown option",
      "unknown option" not in out.lower(), "")
_rc, out = run(ladder(KIC, 5) + "\nN1 a b kb", "op", "unknown",
               cards=".option autobus=kicad\n.option nosuchopt=1\n.model kb kbus r=1k")
check("[E-462] ...and a genuinely unknown option IS still flagged (control)",
      "nosuchopt" in out.lower(), "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
