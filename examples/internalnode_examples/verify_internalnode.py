#!/usr/bin/env python3
"""Enhancement-608: a device's internal node can be named by .ic, .nodeset,
.tf and .pz -- and a job bound to one stays bound across a setup.

N2 of the 2026-09-10 integration hunt. A device builds its internal nodes
(`n1#mid` for a Verilog-A `electrical mid`, `d1#internal` for a diode with
rs) at setup, after the deck is parsed. Two things went wrong around that:

  * A `.tf`/`.pz` card naming such a node had the deck reader make a node of
    that name ahead of the device (E-429's inp_analysis_node), and the device
    then built a SECOND node under the same name beside it: the deck's node
    floated ("held only by gmin", singular-matrix warnings, an operating
    point that needed gmin stepping), `.print op v(n1#mid)` printed its 0,
    and E-429 refused the .tf output as a node "no device connects to". A
    `.ic`/`.nodeset` on the name was simply refused ("on non-existent
    node, ignored").
  * Interactively, `tf v(n1#mid) v1` typed after an `op` bound to the live
    internal node, and the run's own unsetup/setup FREED and rebuilt it: the
    job read freed memory and reported a transfer function of -5e-4 for a
    divider's mid node (0.75), with the same number as output impedance.

Now the device ADOPTS a parse-time node of its internal node's name
(CKTmkSignal), which unsetup leaves in place; a device-local node retired at
unsetup is kept by name and REVIVED as the same struct at the next setup;
and a `.ic`/`.nodeset` on `<instance>#<node>` is kept by name and placed by
CKTsetup once the node exists, a suffix the device does not build reported
there.

Checks (OSDI rc2/rr2 devices, and the built-in diode):
  [1] batch: .tf on n1#mid gives 0.75 and 375 ohm; one node of the name;
      no floating-node or singular warnings; .print op v(n1#mid) = 0.75
  [2] interactive: op, then tf v(n1#mid) v1: 0.75 / 375 ohm (was -5e-4);
      a second tf and an op after it agree
  [3] .ic v(n1#mid)=0.3 under tran uic: the node starts at 0.3
  [4] .nodeset v(n1#mid) is accepted, the op converges to the same point
  [5] .pz with n1#mid as output: the pole at -1/(RC); .noise at d1#internal
  [6] a mistyped suffix: reported once, naming the instance; no node made
  [7] a name that is no instance's: refused as before
  [8] the diode's d1#internal in a .tf: no duplicate, the value right
  [9] sweep: 20 op runs interactively keep one node of the name (the
      retired node is revived, not duplicated)

Enhancement-681 (N1 of the 2026-09-21 hunt): the adoption above also caught a
DEVICE line that named `n1#mid` -- the netlist's node and the model's internal
node became one node in silence (a source wired to `n1#mid` drove the model's
internal node; a BJT's `q1#base` drawn to 3 V put 1e35 A through the source).
CKTmkSignal now says so once, naming the node, the internal node and the
instance (or the source, for a `v1#branch` name); the adoption itself is kept.
  [10] a device line naming n1#mid: the warning, once, and the merged node
       (the source wins: v(n1#mid) is the source's value)
  [10] ...printed once across op, op, tran and sens
  [11] a device line naming v1#branch: the branch-current wording, once
  [12] E-608's own cards (.tf ahead of the device, .ic, the diode's .tf)
       stay silent

Enhancement-688 (F6 of the 2026-09-21 hunt): an internal node the model
COLLAPSED (`V(a, ai) <+ 0` with rs = 0) has no node of its own, and a
`.nodeset`/`.ic` on it was refused with "n1 has no internal node 'ai'" -- the
wrong reason -- while a `.save` said "nothing of that name". The two are one
node: the entry is applied to the node it collapsed into, with a Note, and the
save warning names that node.
  [13] .nodeset v(n1#ai) on a collapsed node: the Note names 'a', the op
       converges to the same point; .ic v(n1#ai) under uic starts v(a) at it
  [14] .save v(n1#ai): the warning names 'a' and suggests v(a); a name that is
       no internal node keeps the old refusal

Enhancement-690 (F8 of the 2026-09-21 hunt): an internal node could not be the
output of `sens`, `pz`, `tf` or `noise` typed as the FIRST analysis of a
session -- nothing is set up yet, so the node is not in the parser's table,
and E-426's rule for a command refused it as a typo ("no such node: n1#mid")
while the same commands after an `op` ran. A name whose part before the '#'
is an OSDI instance and whose suffix that module DECLARES is entered as a
parse-time node the device adopts (E-608); a suffix it does not declare is
refused as before, with nothing left behind; a built-in device's node (no
declaration to check) keeps the limit and the message says what to do. A
collapsed internal node is bound to the node it collapsed into (a synthetic
short, as a collapse merge is) or, after a setup, resolved to it. `sens` and
`pz` refuse a phantom output as `tf` and `noise` have since E-429.
  [15] sens/pz/tf/noise v(n1#mid) as the first commands: the same numbers as
       after an op
  [16] a mistyped suffix as the first command: refused, and the next command
       on the real node still runs (no phantom left); the BJT's q1#base keeps
       the refusal, with the hint, and runs after an op
  [17] a collapsed n1#ai: tf on it as the first command measures at 'a' with
       the Note and no floating-node warning; typed after an op it is
       resolved to 'a'; v(n1#ai) reads v(a)
  [18] a mistyped suffix in a .sens/.pz CARD: refused as a phantom (the sens
       used to print a table of -0.0)

Enhancement-692: the E-690 test above fetched every internal node of every
OSDI instance by number at every setup (CKTnum2nod walks the node list from
its head) and, for a collapsed one, walked the list again by name --
instances x internal nodes x circuit nodes, nine seconds before a photonic
chip's sweep started. The candidate deck nodes (a '#' in the name, no device
line naming them) are collected once per setup, an empty set in almost every
deck, and matched to instances by name.
  [19] 1000 instances of a 40-internal-node module (42k nodes): the op runs
       within 1 s, and four times the instances cost less than eight times
       the 250-instance run (it was 1.5 s and a 14x ratio)
"""
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="internalnode_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(name, src):
    with open(os.path.join(WORK, name + ".va"), "w") as f:
        f.write(src)
    r = subprocess.run([VAF, os.path.join(WORK, name + ".va"), "-o", os.path.join(WORK, name + ".osdi")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


compile_va("rr2", '`include "disciplines.vams"\nmodule rr2(p, n);\ninout p, n; electrical p, n, mid;\n'
                  'parameter real r = 1k from (0:inf);\nanalog begin\n  I(p,mid) <+ V(p,mid)/(r/2);\n'
                  '  I(mid,n) <+ V(mid,n)/(r/2);\nend\nendmodule\n')
compile_va("rc2", '`include "disciplines.vams"\nmodule rc2(p, n);\ninout p, n; electrical p, n, mid;\n'
                  'parameter real r = 1k from (0:inf);\nparameter real c = 1n from (0:inf);\n'
                  'analog begin\n  I(p,mid) <+ V(p,mid)/r;\n  I(mid,n) <+ ddt(c*V(mid,n));\nend\nendmodule\n')

PRE = ".control\npre_osdi rr2.osdi\npre_osdi rc2.osdi\n.endc\n"
DIV = "v1 in 0 dc 1 ac 1\nn1 in out rm\nr2 out 0 1k\n.model rm rr2 r=1k\n"


def run(body, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* internalnode {tag}\n{PRE}{body}\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def val(out, name):
    m = re.findall(rf"^{re.escape(name)} = ([-+.\deE]+)", out, re.M)
    return [float(x) for x in m]


def close(a, b, tol=1e-3):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


BAD = ("held only by gmin", "singular matrix", "does not exist", "gmin stepping failed", "aborted")
print("Enhancement-608: internal nodes in .ic/.nodeset/.tf/.pz, and jobs bound to them\n")

# ------------------------------------------------------------- [1] ---
out = run(DIV + ".tf v(n1#mid) v1\n.op\n.print op v(n1#mid) v(out)", "t1")
tf = val(out, "transfer_function")
zo = val(out, "output_impedance_at_v(n1#mid)")
check("[1] batch .tf on the internal node: 0.75 and 375 ohm (was refused, the node duplicated)",
      tf and close(tf[0], 0.75) and zo and close(zo[0], 375.0)
      and not any(b in out for b in BAD), out[-400:])
check("[1] ...one node of the name in the op listing, and .print op v(n1#mid) = 0.75",
      out.count("n1#mid   ") == 1 and re.search(r"^0\s+7\.5000\d+e-01\s+5\.0000\d+e-01", out, re.M),
      out[-400:])

# ------------------------------------------------------------- [2] ---
out = run(DIV + ".control\nop\ntf v(n1#mid) v1\nprint transfer_function output_impedance_at_v(n1#mid)\n"
          "tf v(n1#mid) v1\nprint transfer_function\nop\nprint v(n1#mid)\n.endc", "t2")
tf = val(out, "transfer_function")
zo = val(out, "output_impedance_at_v(n1#mid)")
check("[2] interactive: op, then tf on the internal node: 0.75 / 375 ohm (was -5e-4, freed memory)",
      len(tf) == 2 and close(tf[0], 0.75) and close(tf[1], 0.75) and zo and close(zo[0], 375.0)
      and val(out, "v(n1#mid)") == [0.75], out[-400:])

# ------------------------------------------------------------- [3] ---
out = run("v1 in 0 dc 1\nn1 in 0 rcm\n.model rcm rc2 r=1k c=1n\n.ic v(n1#mid)=0.3\n"
          ".tran 1n 20n uic\n.print tran v(n1#mid)", "t3")
first = re.search(r"^0\s+\S+\s+([-+.\deE]+)", out, re.M)
check("[3] .ic v(n1#mid)=0.3 under tran uic: the node starts at 0.3 (was 'non-existent node, ignored')",
      first and close(float(first.group(1)), 0.3, 1e-2) and "non-existent" not in out, out[-300:])

# ------------------------------------------------------------- [4] ---
out = run(DIV + ".nodeset v(n1#mid)=0.7\n.op\n.print op v(n1#mid)", "t4")
check("[4] .nodeset v(n1#mid) accepted; the op converges to 0.75",
      "non-existent" not in out and re.search(r"^0\s+7\.5000\d+e-01", out, re.M)
      and not any(b in out for b in BAD), out[-300:])

# ------------------------------------------------------------- [5] ---
out = run("v1 in 0 dc 1 ac 1\nn1 in 0 rcm\nd1 in dout dm\nr2 dout 0 1k\n.model rcm rc2 r=1k c=1n\n"
          ".model dm d rs=10 is=1e-14\n.pz in 0 n1#mid 0 vol pol\n.noise v(d1#internal) v1 dec 1 1k 10k\n"
          ".print pz all\n.print noise onoise_total", "t5")
pole = re.search(r"^0\s+(-[.\deE+]+),", out, re.M)
tot = re.search(r"^0\s+([.\deE+-]+)\s*$", out.split("Integrated Noise")[-1], re.M) if "Integrated Noise" in out else None
check("[5] .pz with the internal node as output: the pole at -1/(RC) = -1e6; .noise at d1#internal > 0",
      pole and close(float(pole.group(1)), -1e6) and tot and float(tot.group(1)) > 1e-9
      and not any(b in out for b in BAD), out[-400:])

# ------------------------------------------------------------- [6] ---
out = run("v1 in 0 dc 1\nn1 in 0 rcm\n.model rcm rc2 r=1k c=1n\n.ic v(n1#mdi)=0.3\n.op\n.print op v(n1#mid)", "t6")
check("[6] a mistyped suffix: reported once, naming the instance; no floating node made",
      out.count("IC on non-existent node - n1#mdi, ignored") == 1 and "(n1 has no internal node 'mdi')" in out
      and "n1#mdi   " not in out and not any(b in out for b in BAD), out[-400:])

# ------------------------------------------------------------- [7] ---
out = run("v1 in 0 dc 1\nn1 in 0 rcm\n.model rcm rc2 r=1k c=1n\n.nodeset v(nosuch#mid)=0.3\n.op\n.print op v(n1#mid)", "t7")
check("[7] a name that is no instance's: refused as before",
      "Nodeset on non-existent node - nosuch#mid, ignored" in out and "Please check line" in out, out[-300:])

# ------------------------------------------------------------- [8] ---
DIODE = "v1 in 0 dc 1 ac 1\nd1 in dout dm\nr2 dout 0 1k\n.model dm d rs=10 is=1e-14\n"
out = run(DIODE + ".tf v(d1#internal) v1\n.op", "t8")
tf = val(out, "transfer_function")
check("[8] the diode's d1#internal in a batch .tf: the value near 1 (rs into 1k), nothing refused",
      tf and 0.98 < tf[0] < 1.0 and not any(b in out for b in BAD), out[-400:])
out = run(DIODE + ".control\nop\ntf v(d1#internal) v1\nprint transfer_function\n"
          "save v(d1#internal)\nop\ndisplay\nprint v(d1#internal)\n.endc", "t8b")
tf = val(out, "transfer_function")
vi = val(out, "v(d1#internal)")
check("[8] ...and interactively: one vector of the name after op, the node near 1, the tf agrees",
      out.count("d1#internal   ") == 1 and vi and 0.98 < vi[0] < 1.0 and tf and 0.98 < tf[0] < 1.0
      and not any(b in out for b in BAD), out[-400:])

# ------------------------------------------------------------- [9] ---
out = run(DIV + ".control\nlet k = 0\nrepeat 20\n  op\n  let k = k + 1\nend\nprint v(n1#mid)\ndisplay\n.endc", "t9")
check("[9] 20 op runs: the internal node is revived each time, one vector of the name, still 0.75",
      val(out, "v(n1#mid)") == [0.75] and out.count("n1#mid   ") == 1 and "Internal Error" not in out,
      out[-300:])

# ------------------------------------------------------------ [10] ---
WARN = "Warning: node 'n1#mid' is named on a device line and is also the internal node 'mid' of instance n1;"
out = run(DIV + "vx n1#mid 0 dc 0.5\n.control\nop\nprint v(n1#mid) v(out)\n.endc", "t10")
check("[10] a device line naming n1#mid: the collision is said once, naming node, internal node and instance",
      out.count(WARN) == 1 and "the two are one node" in out and "Rename the netlist node" in out,
      out[-500:])
vm, vo = val(out, "v(n1#mid)"), val(out, "v(out)")
check("[10] ...and the merge itself is pinned: v(n1#mid) is the source's 0.5, v(out) = 0.5*1k/(500+1k)",
      vm and close(vm[0], 0.5) and vo and close(vo[0], 1.0 / 3.0), f"{vm} {vo}")
out = run(DIV + "vx n1#mid 0 dc 0.5\n.control\nop\nop\ntran 1u 2u\nsens v(out)\n.endc", "t10b")
check("[10] ...printed once across op, op, tran and sens (the re-setups find the adopted node)",
      out.count("Warning: node '") == 1, f"{out.count(chr(87) + 'arning: node')} warnings")

# ------------------------------------------------------------ [11] ---
out = run("v1 in 0 dc 1\nr1 in out 1k\nr2 out 0 1k\nrz v1#branch 0 1k\n.control\nop\nprint v(out)\n.endc", "t11")
check("[11] a device line naming v1#branch: the branch-current wording, once",
      out.count("Warning: node 'v1#branch' is named on a device line and is also the branch-current unknown of source v1;") == 1
      and "wired into that source's current" in out, out[-500:])

# ------------------------------------------------------------ [12] ---
quiet = [run(DIV + ".tf v(n1#mid) v1\n.op", "t12a"),
         run("v1 in 0 dc 1\nn1 in 0 rcm\n.model rcm rc2 r=1k c=1n\n.ic v(n1#mid)=0.3\n.tran 1n 5n uic", "t12b"),
         run(DIV + ".nodeset v(n1#mid)=0.7\n.op", "t12c"),
         run(DIODE + ".tf v(d1#internal) v1\n.op", "t12d")]
check("[12] E-608's own cards (.tf ahead of the device, .ic, .nodeset, the diode's .tf) raise no collision warning",
      not any("Warning: node '" in q for q in quiet), "|".join(q[-120:] for q in quiet if "Warning: node '" in q))

# ------------------------------------------------------------ [13] ---
compile_va("col", '`include "disciplines.vams"\nmodule col(a, c);\ninout a, c; electrical a, c, ai;\n'
                  'parameter real rs = 0 from [0:inf);\nparameter real r = 1k from (0:inf);\n'
                  'analog begin\n  if (rs > 0) I(a, ai) <+ V(a, ai) / rs; else V(a, ai) <+ 0;\n'
                  '  I(ai, c) <+ V(ai, c) / r;\nend\nendmodule\n')
COL = "i1 0 a dc 1m\nn1 a 0 mcol\n.model mcol col\n"
out = run(COL + ".nodeset v(n1#ai)=0.5\n.control\npre_osdi col.osdi\nop\nprint v(a)\n.endc", "t13")
check("[13] .nodeset on a collapsed internal node: applied to 'a' with a Note, no 'non-existent', the op at 1.0",
      "Note: Nodeset on n1#ai: the model collapses n1's internal node 'ai' into 'a', so it is applied to 'a'." in out
      and "non-existent" not in out and val(out, "v(a)") == [1.0], out[-400:])
out = run("v1 in 0 dc 1\nr1 in a 1k\nn1 a 0 mcol\nc1 a 0 1n\n.model mcol col\n.ic v(n1#ai)=0.3\n"
          ".control\npre_osdi col.osdi\ntran 1n 20n uic\nprint v(a)[0]\n.endc", "t13b")
first = val(out, "v(a)[0]")
check("[13] ...and .ic v(n1#ai)=0.3 under tran uic starts v(a) at 0.3 (was ignored: 'has no internal node')",
      "Note: IC on n1#ai:" in out and first and close(first[0], 0.3, 1e-2), out[-300:])

# ------------------------------------------------------------ [14] ---
out = run(COL + ".save v(a) v(n1#ai) v(n1#zz)\n.control\npre_osdi col.osdi\nop\nprint v(a)\n.endc", "t14")
check("[14] .save v(n1#ai): the warning names 'a' and suggests v(a); n1#zz keeps 'nothing of that name'; the op runs",
      "Warning: save 'n1#ai': the model collapses n1's internal node 'ai' into 'a'," in out
      and "save v(a) instead" in out
      and "Warning: save 'n1#zz': nothing of that name is in this analysis" in out
      and val(out, "v(a)") == [1.0], out[-500:])

# ------------------------------------------------------------ [15] ---
FIRST = ("sens v(n1#mid)\nprint r2\npz in 0 n1#mid 0 vol pz\nprint pole(1)\ntf v(n1#mid) v1\n"
         "print transfer_function output_impedance_at_v(n1#mid)\nnoise v(n1#mid) v1 lin 2 1k 2k\nprint onoise_total\n")
ref = run(DIV + "c3 out 0 1n\n.control\nop\n" + FIRST + ".endc", "t15ref")
out = run(DIV + "c3 out 0 1n\n.control\n" + FIRST + ".endc", "t15a")
def _vals(o):
    return [val(o, k)[:1] for k in ("r2", "transfer_function", "output_impedance_at_v(n1#mid)", "onoise_total")]
check("[15] sens, pz, tf and noise on n1#mid as the FIRST commands of the session: the same numbers as after an op "
      "(were 'no such node: n1#mid', every one aborted)",
      _vals(out) == _vals(ref) and all(_vals(ref)) and "pole(1)" in out and "no such node" not in out
      and "aborted" not in out, f"{_vals(out)} vs {_vals(ref)} {out[-300:]}")
out = run(DIV + "c3 out 0 1n\n.control\nnoise v(n1#mid) v1 lin 2 1k 2k\nprint onoise_total\n.endc", "t15b")
check("[15] ...noise first, alone", val(out, "onoise_total")[:1] == _vals(ref)[3] and "no such node" not in out, out[-300:])

# ------------------------------------------------------------ [16] ---
out = run(DIV + ".control\nsens v(n1#mdi)\nprint n1_r\ntf v(n1#mid) v1\nprint transfer_function\nop\nprint v(n1#mid)\n.endc", "t16a")
check("[16] a mistyped suffix as the first command: 'no such node: n1#mdi', nothing left behind -- the tf on the real "
      "node right after it gives 0.75 and the op has no floating-node warning",
      "no such node: n1#mdi" in out and "sens simulation(s) aborted" in out
      and val(out, "transfer_function") == [0.75] and val(out, "v(n1#mid)") == [0.75]
      and "held only by gmin" not in out and "singular" not in out, out[-500:])
BJT = "vcc c 0 dc 5 ac 1\nrc c col 1k\nvb bb 0 dc 0.7\nq1 col bb 0 qq\n.model qq npn(is=1e-15 bf=100 rb=100)\n"
out = run(BJT + ".control\nsens v(q1#base)\nprint rc\nop\nsens v(q1#base)\nprint rc\n.endc", "t16b")
rcs = val(out, "rc")
check("[16] ...the BJT's q1#base (no declaration to check) keeps the refusal as the first command, now with the hint, "
      "and runs after an op",
      "no such node: q1#base (a device's internal node exists once the circuit is set up" in out
      and len(rcs) == 1 and rcs[0] != 0.0, out[-500:])

# ------------------------------------------------------------ [17] ---
out = run(COL + ".control\npre_osdi col.osdi\ntf v(n1#ai) i1\nprint transfer_function\nop\nprint v(n1#ai) v(a)\n.endc", "t17a")
check("[17] a collapsed n1#ai as the FIRST command's output: tf = 1000 (dv(a)/di1), the 'two are one node' Note, no "
      "floating-node or singular warning; v(n1#ai) after the op reads v(a) = 1",
      val(out, "transfer_function") == [1000.0]
      and "Note: n1#ai names n1's internal node 'ai', which the model collapses into 'a'; the two are one node." in out
      and "held only by gmin" not in out and "singular" not in out
      and val(out, "v(n1#ai)") == [1.0] and val(out, "v(a)") == [1.0], out[-500:])
out = run(COL + ".control\npre_osdi col.osdi\nop\ntf v(n1#ai) i1\nprint transfer_function\n.endc", "t17b")
check("[17] ...typed after an op: resolved to 'a' with the Note, tf = 1000 (was 'no such node')",
      val(out, "transfer_function") == [1000.0]
      and "Note: n1#ai: the model collapses n1's internal node 'ai' into 'a', so the analysis output is taken there." in out
      and "no such node" not in out, out[-400:])

# ------------------------------------------------------------ [18] ---
out = run(DIV + ".sens v(n1#mdi)\n.pz in 0 n1#mdi 0 vol pz\n.print sens n1_r\n.control\nrun\n.endc", "t18")
check("[18] a mistyped suffix in a .sens and a .pz CARD: both refused as a node no device connects to (the sens used "
      "to print a table of -0.0)",
      "Sensitivity output node V(n1#mdi) does not exist (no device connects to it)" in out
      and "Pole-zero output node n1#mdi does not exist (no device connects to it)" in out
      and not re.search(r"^0\s+-0\.0", out, re.M), out[-500:])

# ------------------------------------------------------------ [19] ---
K = 40
_nodes = ", ".join(f"m{k}" for k in range(1, K + 1))
_body = ["I(p, m1) <+ V(p, m1) / r;"] + [f"I(m{k}, m{k + 1}) <+ V(m{k}, m{k + 1}) / r;" for k in range(1, K)] \
        + [f"I(m{K}, n) <+ V(m{K}, n) / r;"]
compile_va("many", '`include "disciplines.vams"\nmodule many(p, n);\n  inout p, n; electrical p, n, ' + _nodes
           + ';\n  parameter real r = 1 from (0:inf);\n  analog begin\n    ' + "\n    ".join(_body)
           + '\n  end\nendmodule\n')


def many_deck(n):
    lines = [".model mm many", "v1 in 0 dc 1"] + [f"n{i} in a{i} mm" for i in range(n)] \
            + [f"r{i} a{i} 0 1k" for i in range(n)] + [".control", "pre_osdi many.osdi", "op", "print v(a1)", ".endc"]
    return "\n".join(lines)


def timed_run(body, tag):
    t0 = time.perf_counter()
    out = run(body, tag)
    return time.perf_counter() - t0, out


timed_run(many_deck(250), "t19w")           # warm-up: the first load of many.osdi
t250, out250 = timed_run(many_deck(250), "t19a")
t1000, out1000 = timed_run(many_deck(1000), "t19b")
check("[19] 1000 instances of a 40-internal-node module (42k nodes): the op runs within 1 s (was 1.5 s), the value right",
      t1000 < 1.0 and close(val(out1000, "v(a1)")[0] if val(out1000, "v(a1)") else None, 1e3 / (1e3 + 41.0), 1e-6)
      and close(val(out250, "v(a1)")[0] if val(out250, "v(a1)") else None, 1e3 / (1e3 + 41.0), 1e-6),
      f"t(1000) = {t1000:.3f} s, t(250) = {t250:.3f} s")
check("[19] ...four times the instances cost less than eight times the 250-instance run (the setup is linear; it was a 14x ratio)",
      t250 > 0 and t1000 / t250 < 8.0, f"ratio {t1000 / t250:.1f}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
