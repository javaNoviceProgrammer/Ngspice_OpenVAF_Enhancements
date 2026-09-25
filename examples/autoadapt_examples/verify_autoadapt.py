#!/usr/bin/env python3
"""Enhancement-463: `.option autoadapt` -- inject a two-bus-port adapter automatically.

A device is often needed *between* two others that share a bus node:

    N1 a b mymodel1                 N1 a b_f mymodel1
    N2 b c mymodel2       ->        N2 b_r c mymodel2
                                    n_adapt1_ b_f b_r amod

Writing the right-hand form by hand means renaming the shared node on both
instances and keeping the two halves consistent. With the option set, the deck
is written as the left-hand form and ngspice performs the split.

WHERE IT RUNS. Between INPpas1 and INPpas2 (spiceif.c). pas1 has just built the
model table, so a line's PORT STRUCTURE -- and therefore "is this token a bus
node, and how wide?" -- is knowable; a textual pass in inpcom.c cannot answer
that. Subcircuits are already flattened, so "inside a subcircuit" needs no
separate path. And INP2N has not run, so the rewrite is at the TOKEN level and
`.option autobus` then expands all three lines: the bus handling is not extra
work, it is a consequence of the seam.

THE RULES, and why each is a refusal rather than a guess:

  * a candidate must occur EXACTLY TWICE in the deck, both times as a bus-port
    token on an OSDI line of equal width. A node also touched by a resistor is
    three occurrences and is refused -- splitting it would silently orphan the
    resistor;
  * the device whose PORT INDEX is higher gets `_f`. Not deck order: a SPICE
    deck is order-independent and making a reordering change the circuit would
    be a far worse bug than the one this feature fixes;
  * both occurrences on ONE device is an error, not a self-loop;
  * an instance OF THE ADAPTER is never a candidate, so the pass is idempotent.
    Without that guard a deck already carrying adapters had them adapted in
    turn -- `b_f` becoming `b_f_f`/`b_f_r` with a second adapter between, and
    the answer moving from 0.7590 to 0.7647.

Every value check below is a DIFFERENTIAL against the same circuit with the
adapter written out by hand.
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
        if junk.startswith("_aa_"):
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


MODELS = (".model mymodel1 chan r0=1k\n.model mymodel2 chan r0=2k\n"
          ".model amod adapter ra=50\n.model amod2 adapt2 ra=50\n.model m2 chan2 r0=1k\n"
          ".model mx mixed r0=1k\n")
DRIVE = "V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4))
LOAD = "\n".join(f"Rg{k} c[{k}] 0 100" for k in range(4))
PRINT = "op\nprint " + " ".join(f"v(a[{k}])" for k in range(4)) + " v(c[0]) v(c[3])"


def run(body, tag, ctl=PRINT, opts=".option autobus\n"):
    deck = (f"adapter injection test {tag}\n{opts}{body}\n{MODELS}.control\n"
            f"pre_osdi adapt.osdi\noption noacct\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_aa_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=120, errors="replace")
    return r.returncode, r.stdout + r.stderr


def vals(out):
    return [v for _n, v in re.findall(
        r"v\(([^)]+)\)\s*=\s*(-?[\d.]+(?:e[-+]?\d+)?)", out, re.I)]


r = subprocess.run([OPENVAF, "adapt.va", "-o", "adapt.osdi"], cwd=HERE,
                   capture_output=True, text=True)
print("Enhancement-463: .option autoadapt\n")
check("[E-463] the Verilog-A models compile",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "adapt.osdi")),
      (r.stdout + r.stderr).strip()[:60])

# Enhancement-466: the per-node reporting is opt-in now, so the checks below
# that read what the feature DID ask for it explicitly. The quiet default
# and the off-words are covered by adaptquiet_examples.
AUTO = ".option autoadapt=debug adapter=amod\n"

# ------------------------------------------------- the differential ----------
print("\nthe injected deck is the hand-written one")
HAND = (f"{DRIVE}\n{LOAD}\nN1 a b_f mymodel1\nN2 b_r c mymodel2\n"
        "n_a1_ b_f b_r amod")
SHORT = f"{DRIVE}\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2"
rc_h, out_h = run(HAND, "hand")
rc_a, out_a = run(SHORT, "auto", opts=".option autobus\n" + AUTO)
vh, va = vals(out_h), vals(out_a)
check("[E-463] the hand-written reference runs", rc_h == 0 and len(vh) == 6,
      f"rc={rc_h} {len(vh)} nodes")
check("[E-463] the auto-injected deck reads BIT-IDENTICAL to it",
      rc_a == 0 and vh == va and len(va) == 6, f"{va}")
check("[E-463] ...on a ladder where every bit differs",
      len(set(va)) == len(va), f"{sorted(set(va))}")
check("[E-463] and it reports what it did", "b split" in out_a, "")

print("\nthe forward side comes from the PORT INDEX, not the deck order")
check("[E-463] b_f is the higher-index port (n1 port 1), b_r the lower",
      "b_f (n1 port 1)" in out_a and "b_r (n2 port 0)" in out_a, "")
REORDER = f"{DRIVE}\n{LOAD}\nN2 b c mymodel2\nN1 a b mymodel1"
_rc, out_r = run(REORDER, "reorder", opts=".option autobus\n" + AUTO)
check("[E-463] reversing the two instance lines changes nothing",
      vals(out_r) == va, f"{vals(out_r)}")

print("\ninside a subcircuit, where the shared node is local")
SUB = ("V1 in 0 dc 1\nX1 in pair\n.subckt pair in\n"
       + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4)) + "\n"
       + "\n".join(f"Rg{k} c[{k}] 0 100" for k in range(4))
       + "\nN1 a b mymodel1\nN2 b c mymodel2\n.ends")
SUBP = ("op\nprint " + " ".join(f"v(x1.a[{k}])" for k in range(4))
        + " v(x1.c[0]) v(x1.c[3])")
rc_s, out_s = run(SUB, "sub", ctl=SUBP, opts=".option autobus\n" + AUTO)
check("[E-463] a local shared bus node inside a subcircuit is adapted",
      "x1.b split" in out_s, "")
check("[E-463] ...to the same answer as the flat circuit",
      rc_s == 0 and vals(out_s) == vh, f"{vals(out_s)}")

# ------------------------------------------------------- idempotence ---------
print("\nrunning it on a deck that already has adapters changes nothing")
rc_i, out_i = run(HAND, "idem", opts=".option autobus\n" + AUTO)
check("[E-463] no adapter is injected around an existing adapter",
      "split" not in out_i, out_i[out_i.find("autoadapt"):][:60])
check("[E-463] ...and the answer is the hand-written one, unmoved",
      vals(out_i) == vh, f"{vals(out_i)}")

# ------------------------------------------------------ the refusals ---------
print("\nwhat it refuses, and says so")
_rc, out = run(f"{DRIVE}\nRb0 b[0] 0 1k\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2",
               "third", opts=".option autobus\n" + AUTO)
check("[E-463] a node also touched by a resistor is not adapted",
      ("not exactly twice" in out or "is also used by" in out)   # E-593 names the line
      and "split" not in out.split("not exactly twice" if "not exactly twice" in out else "is also used by")[0],
      "")
_rc, out = run(f"{DRIVE}\nN1 b b mymodel1\n" + "\n".join(f"Rg{k} b[{k}] 0 100" for k in range(4)),
               "selfloop", opts=".option autobus\n" + AUTO)
check("[E-463] the same node on both ports of one device is an error",
      "appears on both ports" in out, "")
_rc, out = run(f"{DRIVE}\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2\nN3 b c mymodel2",
               "three", opts=".option autobus\n" + AUTO)
check("[E-463] a node on three OSDI ports is reported, not guessed at",
      "more than two" in out, "")
_rc, out = run(SHORT, "noautobus", opts=AUTO)
check("[E-463] autoadapt without autobus is an error, not a no-op",
      "requires .option autobus" in out, "")
_rc, out = run(SHORT, "nomodel", opts=".option autobus\n.option autoadapt adapter=nosuch\n")
check("[E-463] an adapter model that does not exist is reported",
      "not defined in this deck" in out, "")
_rc, out = run(SHORT, "notadapter", opts=".option autobus\n.option autoadapt adapter=mx\n")
check("[E-463] an adapter that is not two BUS ports is reported",
      ("exactly two bus ports" in out or "has a port of width 1" in out), "")   # E-592 wording
W2 = ("V1 in 0 dc 1\nRs0 in a[0] 1k\nRs1 in a[1] 1k\n"
      "Rg0 c[0] 0 100\nRg1 c[1] 0 100\nN1 a b m2\nN2 b c m2")
_rc, out = run(W2, "width", ctl="op", opts=".option autobus\n" + AUTO)
check("[E-463] a 2-bit node against a 4-bit adapter is reported",
      "adapter model 'amod' has 4-bit ports" in out, "")
_rc, out = run(f"{DRIVE}\nN1 a s mx\nN2 a s mx\nRs s 0 1k", "scalar", ctl="op",
               opts=".option autobus\n" + AUTO)
check("[E-463] a shared SCALAR node is never adapted",
      "s split" not in out, "")

# ------------------------------------------------------------ `.adapt` -------
print("\n`.adapt` restricts the node set, by whole token")
_rc, out = run(SHORT + "\n.adapt b", "adaptb", opts=".option autobus\n" + AUTO)
check("[E-463] `.adapt b` selects b", "b split" in out, "")
_rc, out = run(SHORT + "\n.adapt bb", "adaptbb", opts=".option autobus\n" + AUTO)
check("[E-463] `.adapt bb` does NOT select b (no substring match)",
      "split" not in out, "")
_rc, out = run(SUB + "\n.adapt b", "adaptsub", ctl=SUBP, opts=".option autobus\n" + AUTO)
check("[E-463] `.adapt b` matches the local name of x1.b in a subcircuit",
      "x1.b split" in out, "")

print("\nmore than one shared node in one deck")
MULTI = (f"{DRIVE}\n" + "\n".join(f"Rg{k} d[{k}] 0 100" for k in range(4))
         + "\nN1 a b mymodel1\nN2 b c mymodel2\nN3 c d mymodel1")
_rc, out = run(MULTI, "multi", ctl="op\nprint v(a[0]) v(d[3])",
               opts=".option autobus\n" + AUTO)
check("[E-463] two shared nodes give two adapters, uniquely named",
      out.count("split") == 2 and "n_adapt1_" in out and "n_adapt2_" in out, "")

print("\na user instance already named n_adapt1_ (Enhancement-724, five-options dig F8)")
USER = (f"{DRIVE}\n{LOAD}\nN1 a b mymodel1\nN2 b c mymodel2\nn_adapt1_ x y mymodel1\n"
        + "\n".join(f"Rx{k} x[{k}] 0 1k\nRy{k} y[{k}] 0 1k" for k in range(4)))
HAND = (f"{DRIVE}\n{LOAD}\nN1 a b_f mymodel1\nN2 b_r c mymodel2\nNA b_f b_r amod\nn_adapt1_ x y mymodel1\n"
        + "\n".join(f"Rx{k} x[{k}] 0 1k\nRy{k} y[{k}] 0 1k" for k in range(4)))
_rc, out = run(USER, "user1", opts=".option autobus\n" + AUTO)
_rc2, ref = run(HAND, "user1ref", opts=".option autobus\n")
check("[E-724] the injection skips a name the deck already uses: the adapter is n_adapt2_, the deck runs, the value is the hand-written one "
      "(was 'device already exists, bail out' on the user's line)",
      "already exists" not in out and "adapter n_adapt2_" in out and vals(out) == vals(ref) and len(vals(ref)) == 6,
      out[-160:].replace("\n", "|"))

print("\nthe tie: the shared node at the same port index on both devices (Enhancement-729, five-options dig F1)")
# `b` at port 0 of n1 and of n2: the port rule has nothing to decide by. It
# used to fall back to deck order, in silence outside =debug, so reversing
# the two lines put the other device on the adapter's p side. Now the
# instance names decide (the one that sorts first forward), whatever the deck
# order, the choice is said in every mode, and `.adapt b:n2` names the other.
# With the asymmetric adapter amod2 the two orientations read differently.
AUTO2 = ".option autoadapt=debug adapter=amod2\n"
TIE = f"{DRIVE}\n{LOAD}\nN1 b a mymodel1\nN2 b c mymodel2"
TIE_REV = f"{DRIVE}\n{LOAD}\nN2 b c mymodel2\nN1 b a mymodel1"
HAND_N1 = f"{DRIVE}\n{LOAD}\nN1 b_f a mymodel1\nN2 b_r c mymodel2\nn_a1_ b_f b_r amod2"
HAND_N2 = f"{DRIVE}\n{LOAD}\nN1 b_r a mymodel1\nN2 b_f c mymodel2\nn_a1_ b_f b_r amod2"
_rc, out_u = run(TIE, "tie_unadapted")
_rc, out_h1 = run(HAND_N1, "tie_hand_n1")
_rc, out_h2 = run(HAND_N2, "tie_hand_n2")
vu, v1, v2 = vals(out_u), vals(out_h1), vals(out_h2)
check("[E-729] the two hand-written orientations of the asymmetric adapter read differently (the control)",
      len(v1) == 6 and len(v2) == 6 and v1 != v2 and vu != v1 and vu != v2, f"{v1[4:]} {v2[4:]} {vu[4:]}")
NOTE = ("Note: autoadapt: node 'b' sits at port 0 on both n1 and n2, so the port rule cannot orient the adapter; "
        "n1 takes the forward side (b_f, the adapter's first port) by name order, whatever the deck order -- "
        "`.adapt b:n2` puts n2 there instead, or split the node by hand.")
_rc, out = run(TIE, "tie_debug", opts=".option autobus\n" + AUTO2)
check("[E-729] the tie goes to n1 by name order, said, with the way to make the other choice: the hand-written n1 answer",
      NOTE in out and "b_f (n1 port 0)" in out and "falling back" not in out and vals(out) == v1, out[-300:].replace("\n", "|"))
_rc, out = run(TIE_REV, "tie_rev", opts=".option autobus\n" + AUTO2)
check("[E-729] ...and the two lines the other way round give the same n1 answer (deck order used to decide: 0.2890173 against 0.2881844)",
      NOTE in out and "b_f (n1 port 0)" in out and vals(out) == v1, f"{vals(out)[4:]}")
_rc, out = run(TIE_REV, "tie_quiet", opts=".option autobus\n.option autoadapt adapter=amod2\n")
check("[E-729] ...said in the quiet default mode too", NOTE in out and vals(out) == v1, out[-300:].replace("\n", "|"))
_rc, out = run(TIE + "\n.adapt b:n2", "tie_n2", opts=".option autobus\n" + AUTO2)
check("[E-729] `.adapt b:n2` names n2 the forward device: the hand-written n2 answer, no note",
      "b_f (n2 port 0)" in out and vals(out) == v2 and "Note: autoadapt" not in out, f"{vals(out)[4:]}")
_rc, out = run(TIE_REV + "\n.adapt b:n2", "tie_n2_rev", opts=".option autobus\n" + AUTO2)
check("[E-729] ...whatever the deck order", vals(out) == v2, f"{vals(out)[4:]}")
_rc, out = run(TIE + "\n.adapt b:n9", "tie_n9", opts=".option autobus\n" + AUTO2)
check("[E-729] `.adapt b:n9`, a device that is not one of the two: an error, not adapted",
      "Error: autoadapt: .adapt b:n9 names a device that is not one of the two sharing 'b' (n1 and n2); not adapted" in out
      and "b split" not in out and vals(out) == vu, out[-300:].replace("\n", "|"))
# without a tie the port rule stands, and an explicit name beats it
SHORT_N2 = f"{DRIVE}\n{LOAD}\nN1 a b_r mymodel1\nN2 b_f c mymodel2\nn_a1_ b_f b_r amod2"
_rc, out_s = run(SHORT, "short_a2", opts=".option autobus\n" + AUTO2)
_rc, out_s2 = run(SHORT + "\n.adapt b:n2", "short_n2", opts=".option autobus\n" + AUTO2)
_rc, out_hs2 = run(SHORT_N2, "short_hand_n2")
check("[E-729] no tie: the port rule puts n1 (port 1) forward with no note, and `.adapt b:n2` names n2 forward instead -- the hand-written n2 answer",
      "b_f (n1 port 1)" in out_s and "Note: autoadapt" not in out_s and "b_f (n2 port 0)" in out_s2 and vals(out_s2) == vals(out_hs2)
      and vals(out_s2) != vals(out_s) and len(vals(out_s2)) == 6, f"{vals(out_s)[4:]} {vals(out_s2)[4:]}")
_rc, out = run(TIE + "\n.adapt b:n2, nosuch", "tie_n2_nosuch", opts=".option autobus\n" + AUTO2)
check("[E-729] `.adapt b:n2, nosuch`: b adapted with n2 forward, the stray name reported (E-467), the colon form parsed as a member",
      "b_f (n2 port 0)" in out and vals(out) == v2 and ".adapt names 'nosuch'" in out, out[-300:].replace("\n", "|"))

print("\nwhat must not change")
_rc, out = run(SHORT, "off")
check("[E-463] with the option off the deck is untouched",
      "split" not in out and "autoadapt" not in out, "")
_rc, out = run(SHORT, "known", opts=".option autobus\n" + AUTO)
check("[E-463] `autoadapt`/`adapter` are registered, so E-438 does not flag them",
      "unknown option" not in out.lower(), "")
_rc, out = run(SHORT, "unknown",
               opts=".option autobus\n" + AUTO + ".option nosuchopt=1\n")
check("[E-463] ...and a genuinely unknown option IS still flagged (control)",
      "nosuchopt" in out.lower(), "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
