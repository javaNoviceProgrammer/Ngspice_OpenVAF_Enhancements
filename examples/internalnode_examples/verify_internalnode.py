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
"""
import os
import re
import subprocess
import sys
import tempfile

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

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
