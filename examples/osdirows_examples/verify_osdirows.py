#!/usr/bin/env python3
"""
verify_osdirows.py -- an OSDI instance's internal rows: their names and kinds after
a node collapse (Enhancement-836), a model's terminal-to-ground short that another
short or a voltage source already makes (Enhancement-837), and a row no value
reaches (Enhancement-838). End to end through the committed openvaf-r + ngspice,
on both solvers. F1 of the 2026-10-10 robustness and correctness campaign: 14 of
the 92 corpus models had stopped reaching an operating point.

  1. Enhancement-836: OSDIsetup created each internal row with the name, the kind
     (voltage or current) and the nodeset initializer of descriptor node i, where
     i is the row's index AFTER collapsing -- a different node once anything below
     it collapsed. rth.va with r1 = 0 collapses a1 into p: the row of a2 was named
     n1#a1 and carried a2's 0.5 V, and the 0 V branch of terminal t was a VOLTAGE
     node named n1#a2. Now: n1#a2 = 0.5, no n1#a1 vector (it is p), n1#flow(t) a
     current, and the singular-matrix message names the row it means.
  2. Enhancement-837: rth.va ties terminal t to ground itself (`V(t) <+ 0`, the
     shape of `Temp(t) <+ 0` with self-heating off). Two instances on one thermal
     net stamped that equation twice -- parallel ideal sources, a singular matrix,
     which the gmin E-734 stopped leaking had hidden. The second is dropped; sens
     (a second DEVsetup on the set-up circuit) keeps the decision; a voltage
     source on the same net is named, since its value is the deck's to move.
  3. Enhancement-838: dead.va writes its internal node x only when mode = 1. With
     mode = 0 the pattern still holds x's entries and every value is 0: no
     factorization survives, the dc-path walk (which reads the pattern) cannot see
     it, and every homotopy failed. Now the reorder finds the empty row, holds it
     with the dc-path conductance and says so; dcpath=warn and off are honoured.
Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

MODELS = ("rth", "dead")


def compile_va(m):
    r = subprocess.run([OPENVAF, f"{m}.va", "-o", f"{m}.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, f"{m}.osdi")), r.stdout + r.stderr


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def values(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w()#.@\[\],\-]+)\s*=\s*(-?[\d.]+e[-+]\d+|-?[\d.]+)\s*$", line)
        if m:
            vals.setdefault(m.group(1).lower(), float(m.group(2)))
    return vals


def iters(out):
    m = re.search(r"Total iterations\s*=\s*(\d+)", out)
    return int(m.group(1)) if m else None


def deck(title, body, ctl="op", prints="", opts="", model="rth"):
    return (f"* {title}\n.control\npre_osdi {model}.osdi\n.endc\n{opts}{body}\n.control\nset numdgt=10\n"
            f"{ctl}\n{'print ' + prints if prints else ''}\nrusage totiter\n.endc\n.end\n")


def near(a, b, rel=1e-6, ab=0.0):
    return a is not None and b is not None and abs(a - b) <= max(rel * max(abs(a), abs(b)), ab)


SING = "singular matrix"
LOOP = "voltage source 'vt' holds the same node"
DEAD = "node 'n1#x' is dead at this point (its row is all zero: no current reaches it); 1e-12 S installed to hold it"


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[0] the OSDI probes compile")
    for m in MODELS:
        built, log = compile_va(m)
        check(f"openvaf-r {m}.va", built, "" if built else log.strip().splitlines()[0])
    if not ok:
        print("\nSOME FAILED"); sys.exit(1)

    print("[1] Enhancement-836: rows named and typed after the node they stand for")
    rc, out = ngspice(deck("collapsed a1", "v1 p 0 1\nn1 p 0 0 mm\n.model mm rth r1=0",
                           ctl="op\nprint all\ndisplay"))
    v = values(out)
    check("r1 = 0 (a1 collapses into p): the midpoint row is n1#a2 = 0.5 V -- it was named n1#a1",
          near(v.get("n1#a2"), 0.5) and "n1#a1" not in v, f"n1#a2={v.get('n1#a2')} n1#a1={v.get('n1#a1')}")
    check("the display lists n1#a2 as a voltage and no n1#a1",
          re.search(r"n1#a2\s*:\s*voltage", out) is not None and "n1#a1" not in out)
    rc, out = ngspice(deck("no collapse", "v1 p 0 1\nn1 p 0 0 mm\n.model mm rth r1=1k", ctl="op\nprint all"))
    v = values(out)
    check("(control) r1 = 1k, nothing collapses: n1#a1 = 2/3 V, n1#a2 = 1/3 V",
          near(v.get("n1#a1"), 2 / 3) and near(v.get("n1#a2"), 1 / 3), f"{v.get('n1#a1')} {v.get('n1#a2')}")
    rc, out = ngspice(deck("flow row", "v1 p 0 1\nn1 p 0 tt mm\nit 0 tt dc 1m\n.model mm rth r1=0",
                           ctl="op\nprint all\ndisplay"))
    v = values(out)
    check("t on a lone net with 1 mA into it: the model's 0 V branch is n1#flow(t), a CURRENT, = 1 mA, v(tt) = 0 "
          "-- it was a voltage node named n1#a2",
          near(v.get("n1#flow(t)"), 1e-3) and near(v.get("tt"), 0.0, ab=1e-12)
          and re.search(r"n1#flow\(t\)\s*:\s*current", out) is not None and "n1#a2 = 1" not in out,
          f"n1#flow(t)={v.get('n1#flow(t)')} tt={v.get('tt')}")
    rc, out = ngspice(deck("save collapsed", "v1 p 0 1\nn1 p 0 0 mm\n.model mm rth r1=0", ctl="save v(n1#a1) v(p)\nop"))
    check("save v(n1#a1) after the collapse names the node that carries it (Enhancement-688) -- the wrongly named row "
          "used to stand in for it",
          "collapses n1's internal node 'a1'" in out and "into 'p'" in out, out[-200:] if "into 'p'" not in out else "")

    print("[2] Enhancement-837: a model's terminal short made twice, or beside a voltage source")
    rc, out = ngspice(deck("two share tt", "v1 p 0 1\nn1 p 0 tt mm\nn2 p 0 tt mm\n.model mm rth r1=0",
                           prints="i(v1) v(tt)"))
    v = values(out)
    check("two instances on one thermal net: converges, i(v1) = -1 mA, no singular matrix -- the second short is the "
          "same equation and is dropped", rc == 0 and near(v.get("i(v1)"), -1e-3) and SING not in out
          and iters(out) is not None and iters(out) <= 5, f"i(v1)={v.get('i(v1)')} iterations={iters(out)}")
    rc, out = ngspice(deck("three share tt", "v1 p 0 1\nn1 p 0 tt mm\nn2 p 0 tt mm\nn3 p 0 tt mm\nit 0 tt dc 1m\n"
                           ".model mm rth r1=0", ctl="op\nprint all"))
    v = values(out)
    flows = {k: x for k, x in v.items() if k.endswith("#flow(t)")}
    check("three instances and 1 mA into the net: one instance's branch carries it all (the first set up -- "
          "instances are kept last-parsed first), the other two have none",
          rc == 0 and len(flows) == 1 and near(list(flows.values())[0], 1e-3)
          and near(v.get("v1#branch"), -1.5e-3), f"flows={flows} v1#branch={v.get('v1#branch')}")
    rc, out = ngspice(deck("vt holds tt", "v1 p 0 1\nn1 p 0 tt mm\nvt tt 0 0\n.model mm rth r1=0", prints="i(v1)"))
    check("a 0 V source on the same net: refused as before, but the warning names the source, the terminal and the "
          "row, and the singular row is n1#flow(t)",
          LOOP in out and "terminal 't' (node 'tt')" in out and "check node n1#flow(t)" in out
          and "i(v1) =" not in out, out[-300:] if LOOP not in out else "")
    rc, out = ngspice(deck("two on ground", "v1 p 0 1\nn1 p 0 0 mm\nn2 p 0 0 mm\n.model mm rth r1=0", prints="i(v1)"))
    v = values(out)
    check("(control) t on ground for both: Enhancement-401 drops the shorts, silent, i(v1) = -1 mA",
          near(v.get("i(v1)"), -1e-3) and SING not in out and "holds the same node" not in out, f"{v.get('i(v1)')}")
    rc, out = ngspice(deck("sens shared", "v1 in 0 1\nrs in p 1k\nn1 p 0 tt mm\nn2 p 0 tt mm\n.model mm rth r1=0",
                           ctl="op\nprint v(p)\nsens v(p)\nprint rs"))
    v = values(out)
    check("sens (a second DEVsetup on the set-up circuit) keeps the decision: no node allocated, d v(p)/d rs = "
          "-Rp/(Rp+rs)^2 = -2.5e-4 with Rp = 1k",
          rc == 0 and near(v.get("v(p)"), 0.5) and near(v.get("rs"), -2.5e-4, 1e-4)
          and "Internal Error" not in out, f"v(p)={v.get('v(p)')} rs={v.get('rs')} rc={rc}")
    rc, out = ngspice(deck("dc and ac shared", "v1 p 0 dc 1 ac 1\nn1 p 0 tt mm\nn2 p 0 tt mm\n.model mm rth r1=0",
                           ctl="dc v1 0 1 0.5\nprint i(v1)[2]\nac lin 1 1k 1k\nprint mag(i(v1))"))
    v = values(out)
    check("a dc sweep and an ac on the shared net run: i(v1) = -1 mA at 1 V, |i(v1)| = 1 mA at 1 kHz",
          near(v.get("i(v1)[2]"), -1e-3) and near(v.get("mag(i(v1))"), 1e-3) and SING not in out,
          f"{v.get('i(v1)[2]')} {v.get('mag(i(v1))')}")

    print("[3] Enhancement-838: a row no value reaches is held at the reorder")
    rc, out = ngspice(deck("dead x", "v1 p 0 1\nn1 p 0 mm\n.model mm dead mode=0", prints="i(v1)", model="dead"))
    v = values(out)
    check("mode = 0: x is named dead and held with 1e-12 S, i(v1) = -1 mA in a few iterations -- every homotopy "
          "failed before", rc == 0 and DEAD in out and SING not in out and near(v.get("i(v1)"), -1e-3)
          and iters(out) is not None and iters(out) <= 5, f"i(v1)={v.get('i(v1)')} iterations={iters(out)}")
    rc, out = ngspice(deck("live x", "v1 p 0 1\nn1 p 0 mm\n.model mm dead mode=1", prints="i(v1)", model="dead"))
    v = values(out)
    check("(control) mode = 1: x is live, silent, i(v1) = -1.5 mA",
          "is dead" not in out and near(v.get("i(v1)"), -1.5e-3), f"{v.get('i(v1)')}")
    rc, out = ngspice(deck("dead warn", "v1 p 0 1\nn1 p 0 mm\n.model mm dead mode=0", prints="i(v1)",
                           opts=".option dcpath=warn\n", model="dead"))
    check("dcpath=warn: named, nothing installed, the operating point is refused",
          "nothing installed under this .option dcpath" in out and "is dead" in out and "i(v1) =" not in out)
    rc, out = ngspice(deck("dead error", "v1 p 0 1\nn1 p 0 mm\n.model mm dead mode=0", prints="i(v1)",
                           opts=".option dcpath=error\n", model="dead"))
    check("dcpath=error: named the same way, nothing installed, refused",
          "nothing installed under this .option dcpath" in out and "is dead" in out and "i(v1) =" not in out)
    rc, out = ngspice(deck("dead off", "v1 p 0 1\nn1 p 0 mm\n.model mm dead mode=0", prints="i(v1)",
                           opts=".option dcpath=off\n", model="dead"))
    check("dcpath=off: no word, nothing installed, refused", "is dead" not in out and "i(v1) =" not in out)
    rc, out = ngspice(deck("dead gshunt", "v1 p 0 1\nn1 p 0 mm\n.model mm dead mode=0", prints="i(v1)",
                           opts=".option gshunt=1e-12\n", model="dead"))
    v = values(out)
    check("gshunt puts a conductance on every diagonal: nothing to find, silent, i(v1) = -1 mA",
          "is dead" not in out and near(v.get("i(v1)"), -1e-3), f"{v.get('i(v1)')}")
    rc, out = ngspice(deck("dead ac tran", "v1 p 0 dc 1 ac 1\nn1 p 0 mm\n.model mm dead mode=0",
                           ctl="ac lin 1 1k 1k\nprint mag(i(v1))\ntran 1u 10u\nprint i(v1)[length(i(v1))-1]",
                           model="dead"))
    v = values(out)
    check("ac and tran on the held node run: |i(v1)| = 1 mA, i(v1) = -1 mA at the end",
          near(v.get("mag(i(v1))"), 1e-3) and near(v.get("i(v1)[length(i(v1))-1]"), -1e-3) and SING not in out,
          f"{v.get('mag(i(v1))')} {v.get('i(v1)[length(i(v1))-1]')}")

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
