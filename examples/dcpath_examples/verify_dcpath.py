#!/usr/bin/env python3
"""
verify_dcpath.py -- `.option dcpath`: gmin installed where a node has no DC path to
ground, Spectre's topology check for ngspice (Enhancement-575), end-to-end through
the committed openvaf-r + ngspice on both solvers.

At setup the nodes are joined by every DC-conducting device path -- built-in types
from a per-type table of DC-connected terminal groups, OSDI models from the
non-zero resistive entries of their Jacobian pattern (an entry AND its transpose:
a controlled contribution's (out, in) is a dependency, not a path), XSPICE code
models from their port kinds -- and the graph is walked from ground. A voltage node
the walk does not reach gets a diagonal and `gmin` on it on every load of every
analysis, and the message names it.

  1. the Enhancement-569 shapes and the Enhancement-570 capacitor-coupled gate are
     found in three iterations with the message, on the same values
  2. what must stay silent: a DC path through every built-in kind, an OSDI resistive
     port, R||C, and a matrix-less circuit (E-492's note stands)
  3. the four modes and the value: gmin (default), <G>, warn, error, off, nodcpath,
     a bare `dcpath`, and `.option gmin` moving hold AND junction where `dcpath=<G>`
     moves the hold alone
  4. transient: under the default (`dcpath=dc`, Enhancement-595) the held node is
     released once the run leaves DC and stays flat; `dcpath=all` (Enhancement-575's
     whole-run hold) decays with C/gmin; `dcpath=warn` is flat
  5. ac on a held node runs; `.option rshunt` keeps its own numbers (the walk stands
     down: every node has a path then)
  6. the message cap: five named, then a count
  9. Enhancement-595, the hold outside DC: the message says which nodes are released;
     a node with no reactive path (a current source into a lone node, an isolated
     transformer secondary) is held in every mode; a zero-valued capacitor or a
     ddt() with a zero coefficient keeps the hold in tran; ac at 0.1 Hz is the exact
     divider under the default and the gmin-bent value under `dcpath=all`, on both
     solvers (Sparse read only the real part of the AC row before this);
     `dcpathall` combines with a value; an unknown word is refused by name

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

MODELS = ("vprobe", "vddt", "vres", "vrc", "th_rth", "th_pwr", "vdiff", "zddt")


def compile_va(m):
    r = subprocess.run([OPENVAF, f"{m}.va", "-o", f"{m}.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, f"{m}.osdi")), r.stdout + r.stderr


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=120)
    return r.stdout + r.stderr


def values(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w()#.@\[\]]+)\s*=\s*(-?[\d.]+e[-+]\d+|-?[\d.]+)\s*$", line)
        if m:
            try:
                vals[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return vals


def iters(out):
    m = re.search(r"Total iterations\s*=\s*(\d+)", out)
    return int(m.group(1)) if m else None


def deck(title, body, ctl="op", prints="", opts="", pre=""):
    return (f"* {title}\n{opts}{body}\n.control\n{pre}set numdgt=10\n{ctl}\n"
            f"{'print ' + prints if prints else ''}\nrusage totiter\n.endc\n.end\n")


def near(a, b, rel=1e-6):
    return a is not None and b is not None and abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


HELD = "no DC path from node '{}' to ground; gmin (1e-12 S) installed to provide one"
SING = "singular matrix"


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

    print("[1] the floating shapes: named, held, three iterations")
    out = ngspice(deck("bsrc reads x", "v1 a 0 1\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", prints="v(x) v(c)"))
    v = values(out)
    check("a B-source reads x and nothing else touches it: x named, v(x)=0, v(c)=0, 3 iterations",
          HELD.format("x") in out and near(v.get("v(x)"), 0, 1e-9) and near(v.get("v(c)"), 0, 1e-9)
          and iters(out) is not None and iters(out) <= 5, f"iterations={iters(out)}")
    out = ngspice(deck("current source", "v1 a 0 1\nr1 a 0 1k\ni1 0 x 1n", prints="v(x)"))
    v = values(out)
    check("a current source into a lone node: x named, v(x) = I/gmin = 1e3", HELD.format("x") in out
          and near(v.get("v(x)"), 1e3) and iters(out) <= 5, f"v(x)={v.get('v(x)')} iterations={iters(out)}")
    out = ngspice(deck("capacitor node", "v1 a 0 1\nr1 a 0 1k\nc1 a x 1p\nc2 x 0 1p", prints="v(x)"))
    v = values(out)
    check("a node reached only through capacitors (E-570's shape): x named, v(x)=0, no singular report, 3 iterations",
          HELD.format("x") in out and near(v.get("v(x)"), 0, 1e-9) and SING not in out and iters(out) <= 5,
          f"iterations={iters(out)}")
    out = ngspice(deck("mos gate", "vdd d 0 3\nrd d dd 1k\nm1 dd g 0 0 nm w=10u l=1u\nc1 g 0 1p\n.model nm nmos level=1 vto=0.7 kp=100u",
                       prints="v(g) v(dd)"))
    v = values(out)
    check("a MOS1 gate held only by a capacitor: g named, v(g)=0, v(dd)=3, no singular report",
          HELD.format("g") in out and near(v.get("v(g)"), 0, 1e-9) and near(v.get("v(dd)"), 3) and SING not in out
          and iters(out) <= 5, f"iterations={iters(out)}")
    out = ngspice(deck("xspice gain input", "v1 a 0 1\nr1 a 0 1k\na1 x y gainm\n.model gainm gain(gain=2)\nry y 0 1k", prints="v(x) v(y)"))
    v = values(out)
    check("an XSPICE gain whose input port touches nothing: x named, its output y is a path (not named)",
          HELD.format("x") in out and "node 'y'" not in out and near(v.get("v(x)"), 0, 1e-9) and iters(out) <= 5, "")
    out = ngspice(deck("osdi probed", "v1 a 0 1\nr1 a 0 1k\nn1 x c mp\n.model mp vprobe\nrc c 0 1k", prints="v(x) v(c)", pre="pre_osdi vprobe.osdi\n"))
    v = values(out)
    check("an OSDI module that only probes its port x (V(out) <+ 2*V(in)): x named, 3 iterations (the (out,in) entry is a dependency, not a path)",
          HELD.format("x") in out and near(v.get("v(x)"), 0, 1e-9) and iters(out) <= 5, f"iterations={iters(out)}")
    out = ngspice(deck("osdi ddt", "v1 a 0 1\nr1 a 0 1k\nn1 a x md\n.model md vddt", prints="v(x)", pre="pre_osdi vddt.osdi\n"))
    v = values(out)
    check("an OSDI ddt()-only contribution (flags REACT|RESIST_CONST, resistive part a constant zero): x named",
          HELD.format("x") in out and near(v.get("v(x)"), 0, 1e-9) and iters(out) <= 5, f"iterations={iters(out)}")

    print("[2] what stays silent")
    body = ("v1 a 0 1\nl1 a m 1u\nl2 m mm 1u\nrm mm 0 1k\nvq q 0 2\nrs a s 1k\ns1 s t a 0 sw on\n.model sw sw ron=1 roff=1e9 vt=0.5\n"
            "rt t 0 1k\nm1 dd g 0 0 nm w=10u l=1u\nrg g 0 1meg\nvdd dd 0 3\nj1 jd jg 0 nj\nvjd jd 0 1\nrjg jg 0 1k\n"
            "q1 qc qb 0 qm\nvqc qc 0 2\nrqb qb 0 10k\nd1 da 0 dm\nvda da 0 0.5\ne1 eo 0 a 0 2\nre eo 0 1k\ng1 0 go a 0 1m\nrgo go 0 1k\n"
            "t1 ta 0 tb 0 z0=50 td=1n\nvta ta 0 1\nrtb tb 0 50\n.model nm nmos level=1\n.model nj njf\n.model qm npn\n.model dm d")
    out = ngspice(deck("built-ins", body, prints="v(m) v(q) v(t) v(g) v(eo) v(go) v(tb)"))
    v = values(out)
    check("inductors, a source-held node, a switch, a gate resistor, JFET/BJT/diode, E and G sources, a lossless line: no message, values right",
          "no DC path" not in out and near(v.get("v(m)"), 1) and near(v.get("v(q)"), 2) and near(v.get("v(eo)"), 2)
          and near(v.get("v(go)"), 1) and near(v.get("v(tb)"), 1) and near(v.get("v(g)"), 0, 1e-9), f"{v}")
    out = ngspice(deck("osdi resistive", "v1 a 0 1\nr1 a 0 1k\nn1 a x mr\n.model mr vres\nn2 x 0 mr", prints="v(x)", pre="pre_osdi vres.osdi\n"))
    check("an OSDI resistive contribution is a path: v(x)=0.5, silent", "no DC path" not in out and near(values(out).get("v(x)"), 0.5), "")
    out = ngspice(deck("osdi rc", "v1 a 0 1\nr1 a 0 1k\nn1 a x mrc\n.model mrc vrc\nn2 x 0 mrc", prints="v(x)", pre="pre_osdi vrc.osdi\n"))
    check("an OSDI V/R + ddt(C*V) contribution (flags RESIST|REACT) is a path: v(x)=0.5, silent",
          "no DC path" not in out and near(values(out).get("v(x)"), 0.5), "")
    out = ngspice(deck("no matrix", "i1 0 a 1m", prints="v(a)"))
    check("a circuit with no matrix at all keeps E-492's single note; the walk does not run", "no DC path" not in out, "")

    print("[3] the modes and the value")
    cap = "v1 a 0 1\nr1 a 0 1k\nc1 a x 1p\nc2 x 0 1p"
    out = ngspice(deck("warn", cap, prints="v(x)", opts=".option dcpath=warn\n"))
    v = values(out)
    check("dcpath=warn: named with 'nothing installed', nothing held -- the singular reports and the ladder as before",
          "no DC path from node 'x' to ground (.option dcpath=warn: nothing installed)" in out and SING in out
          and iters(out) is not None and iters(out) > 50, f"iterations={iters(out)}")
    out = ngspice(deck("error", cap, prints="v(x)", opts=".option dcpath=error\n"))
    check("dcpath=error: refused, naming the node and the count",
          "Error: no DC path from node 'x' to ground (.option dcpath=error)" in out
          and "1 node with no DC path to ground" in out and iters(out) in (None, 0), "")
    out = ngspice(deck("off", cap, prints="v(x)", opts=".option dcpath=off\n"))
    check("dcpath=off: no message at all, Enhancement-566's run", "no DC path" not in out and SING in out, "")
    out = ngspice(deck("nodcpath", cap, prints="v(x)", opts=".option nodcpath\n"))
    check("`.option nodcpath` is the same off", "no DC path" not in out and SING in out and "unknown option" not in out, "")
    out = ngspice(deck("bare", cap, prints="v(x)", opts=".option dcpath\n"))
    check("a bare `.option dcpath` is the default hold", HELD.format("x") in out and "unknown option" not in out, "")
    src = "v1 a 0 1\nr1 a 0 1k\ni1 0 x 1n"
    out = ngspice(deck("value", src, prints="v(x)", opts=".option dcpath=1n\n"))
    v = values(out)
    check("dcpath=1n: '1e-09 S installed', v(x) = 1n/1n = 1", "1e-09 S installed to provide one (.option dcpath)" in out
          and near(v.get("v(x)"), 1.0), f"v(x)={v.get('v(x)')}")
    out = ngspice(deck("zero", src, prints="v(x)", opts=".option dcpath=0\n"))
    check("dcpath=0 installs nothing and says so (taken as warn)", "installs nothing; taking it as dcpath=warn" in out
          and "nothing installed" in out, "")
    dio = "vd da 0 -1\nd1 da 0 dm\n.model dm d is=1e-14\nv1 a 0 1\nr1 a 0 1k\ni1 0 x 1n"
    out = ngspice(deck("gmin default", dio, prints="v(x) i(vd)"))
    v0 = values(out)
    out1 = ngspice(deck("gmin=1n", dio, prints="v(x) i(vd)", opts=".option gmin=1n\n"))
    v1 = values(out1)
    out = ngspice(deck("dcpath=1n", dio, prints="v(x) i(vd)", opts=".option dcpath=1n\n"))
    v2 = values(out)
    check("`.option gmin=1n` moves the hold AND the diode's reverse leakage: v(x) 1e3 -> 1, i(vd) ~1e-12 -> ~1e-9, 'gmin (1e-09 S) installed'",
          near(v0.get("v(x)"), 1e3) and near(v1.get("v(x)"), 1.0) and abs(v0.get("i(vd)", 0)) < 2e-12
          and abs(v1.get("i(vd)", 0)) > 5e-10 and "gmin (1e-09 S) installed" in out1,
          f"v(x)={v0.get('v(x)')}->{v1.get('v(x)')} i(vd)={v0.get('i(vd)')}->{v1.get('i(vd)')}")
    check("`.option dcpath=1n` moves the hold alone: v(x)=1, the diode's leakage unchanged",
          near(v2.get("v(x)"), 1.0) and abs(v2.get("i(vd)", 0)) < 2e-12, f"v(x)={v2.get('v(x)')} i(vd)={v2.get('i(vd)')}")

    print("[4] transient: released outside DC by default (E-595); `dcpath=all` leaks with C/gmin")
    tr = "v1 a 0 1\nr1 a 0 1k\nc1 a x 1p\nc2 x 0 1p\n.ic v(x)=1"
    ctl = "tran 0.01 0.5 uic\nmeas tran vx1 find v(x) at=0.1\nmeas tran vx2 find v(x) at=0.5"
    out = ngspice(deck("default flat", tr, ctl=ctl))
    v = values(out)
    check("default (dcpath=dc): the capacitor carries the node in tran, nothing leaks: v(x) stays at 1.5",
          near(v.get("vx1"), 1.5, 1e-3) and near(v.get("vx2"), 1.5, 1e-3), f"vx1={v.get('vx1')} vx2={v.get('vx2')}")
    out = ngspice(deck("decay", tr, ctl=ctl, opts=".option dcpath=all\n"))
    v = values(out)
    e1, e2 = 1.5 * math.exp(-0.1 / 2.0), 1.5 * math.exp(-0.5 / 2.0)
    check("dcpath=all: 2 pF from 1.5 V (the source step couples 0.5 V in) through 1 pS, tau = 2 s: v(x)=1.4268 at 0.1 s, 1.1682 at 0.5 s",
          near(v.get("vx1"), e1, 2e-3) and near(v.get("vx2"), e2, 2e-3), f"vx1={v.get('vx1')} vx2={v.get('vx2')}")
    out = ngspice(deck("flat", tr, ctl=ctl, opts=".option dcpath=warn\n"))
    v = values(out)
    check("with dcpath=warn nothing leaks: v(x) stays at 1.5", near(v.get("vx1"), 1.5, 1e-3) and near(v.get("vx2"), 1.5, 1e-3),
          f"vx1={v.get('vx1')} vx2={v.get('vx2')}")

    print("[5] ac on a held node, and rshunt")
    out = ngspice(deck("ac", "v1 a 0 dc 1 ac 1\nr1 a 0 1k\nc1 a x 1p\nc2 x 0 1p", ctl="ac lin 1 1k 1k", prints="vm(x)"))
    check("ac on the capacitor-coupled node runs: vm(x) = 0.5 (the divider), no singular report",
          near(values(out).get("vm(x)"), 0.5, 1e-6) and SING not in out, f"{values(out).get('vm(x)')}")
    out = ngspice(deck("rshunt", "v1 a 0 1\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", prints="v(x) v(c)", opts=".option rshunt=1e12\n"))
    check("with `.option rshunt` every node has a path: the walk stands down, no message, 3 iterations",
          "no DC path" not in out and iters(out) is not None and iters(out) <= 5, f"iterations={iters(out)}")

    print("[9] Enhancement-595: the hold outside DC")
    cap = "v1 a 0 1\nr1 a 0 1k\nc1 a x 1p\nc2 x 0 1p"
    RELEASED = "held at DC only -- tran and ac release it while a reactive path carries the node"
    out = ngspice(deck("suffix", cap, prints="v(x)"))
    check("the message says the node is released outside DC", HELD.format("x") + "; " + RELEASED in out, "")
    out = ngspice(deck("all", cap, prints="v(x)", opts=".option dcpath=all\n"))
    check("dcpath=all: the same message without the suffix", HELD.format("x") in out and RELEASED not in out, "")
    out = ngspice(deck("dcpathall", cap, prints="v(x)", opts=".option dcpath=1n dcpathall\n"))
    check("`.option dcpath=1n dcpathall`: the value and the whole-run hold combine",
          "1e-09 S installed to provide one (.option dcpath)" in out and RELEASED not in out, "")
    ctl = "tran 0.0001 0.005 uic\nmeas tran vx1 find v(x) at=1m\nmeas tran vx2 find v(x) at=2m"
    out = ngspice(deck("dcpathall decay", tr, ctl=ctl, opts=".option dcpath=1n dcpathall\n"))
    v = values(out)
    check("...and the transient leaks with C/G, tau = 2 ms: 0.9098 at 1 ms, 0.5518 at 2 ms",
          near(v.get("vx1"), 1.5 * math.exp(-0.5), 2e-3) and near(v.get("vx2"), 1.5 * math.exp(-1.0), 2e-3),
          f"vx1={v.get('vx1')} vx2={v.get('vx2')}")
    out = ngspice(deck("bogus", cap, prints="v(x)", opts=".option dcpath=bogus\n"))
    check("an unknown word is refused by name and the default used",
          "dcpath=bogus is not gmin, warn, error, off, dc, all or a conductance; using dcpath=gmin" in out
          and HELD.format("x") in out, "")
    src = "v1 in 0 1\nr1 in 0 1k\ni1 0 x 1p"
    out = ngspice(deck("lone node tran", src, ctl="tran 1u 10u\nmeas tran vx find v(x) at=5u"))
    check("a current source into a lone node has no reactive path: held in tran too, v(x) = 1 pA / 1 pS = 1 V, no suffix",
          near(values(out).get("vx"), 1.0, 1e-3) and RELEASED not in out and SING not in out, f"vx={values(out).get('vx')}")
    sec = "v1 in 0 dc 0 ac 1 sin(0 1 1k)\nr1 in a 1\nl1 a 0 1m\nl2 p q 1m\nk1 l1 l2 0.9\nc3 p q 1n"
    out = ngspice(deck("secondary", sec, ctl="tran 10u 1m\nmeas tran vp find v(p) at=0.25m\nmeas tran vq find v(q) at=0.25m"))
    v = values(out)
    check("an isolated secondary with a capacitor across it is an island: p and q held in every mode, the transient runs symmetric",
          HELD.format("p") in out and HELD.format("q") in out and RELEASED not in out and SING not in out
          and v.get("vp") is not None and abs(v.get("vp", 0)) > 0.01 and near(v.get("vp"), -v.get("vq", 0), 1e-6),
          f"vp={v.get('vp')} vq={v.get('vq')}")
    zc = "v1 in 0 dc 1 sin(1 0.5 1k)\nr1 in a 1k\nc1 a x 0"
    out = ngspice(deck("zero cap", zc, ctl="tran 10u 1m\nmeas tran vx find v(x) at=0.5m"))
    check("a zero-valued capacitor to a lone node: released by the walk, but the tran stamp finds the diagonal zero and holds; no singular report",
          SING not in out and near(values(out).get("vx"), 0.0, 1e-9) or (SING not in out and abs(values(out).get("vx", 1)) < 1e-9),
          f"vx={values(out).get('vx')}")
    zd = "v1 in 0 dc 1 sin(1 0.5 1k)\nr1 in a 1k\nn1 a x zm\n.model zm zddt c=0"
    out = ngspice(deck("zero ddt", zd, ctl="tran 10u 1m\nmeas tran vx find v(x) at=0.5m", pre="pre_osdi zddt.osdi\n"))
    check("an OSDI ddt() with a zero coefficient: the same, no singular report",
          SING not in out and abs(values(out).get("vx", 1)) < 1e-9, f"vx={values(out).get('vx')}")
    acd = "v1 a 0 dc 1 ac 1\nr1 a 0 1k\nc1 a x 1p\nc2 x 0 1p"
    out = ngspice(deck("ac released", acd, ctl="ac lin 1 0.1 0.1", prints="vm(x)"))
    check("ac at 0.1 Hz under the default: the exact divider 0.5 (released; the same under Sparse, which read only the real part of the row before)",
          near(values(out).get("vm(x)"), 0.5, 1e-6) and SING not in out, f"{values(out).get('vm(x)')}")
    out = ngspice(deck("ac held", acd, ctl="ac lin 1 0.1 0.1", prints="vm(x)", opts=".option dcpath=all\n"))
    check("ac at 0.1 Hz under dcpath=all: 0.39124, the divider bent by 1 pS against 1.26 pS of 2 pF",
          near(values(out).get("vm(x)"), 0.391239, 1e-4), f"{values(out).get('vm(x)')}")

    print("[8] OSDI voltage contributions: a branch to an implicit ground, and a branch between two nodes")
    out = ngspice(deck("osdi driven out", "v1 a 0 1\nn1 a c mp\n.model mp vprobe", prints="v(c)", pre="pre_osdi vprobe.osdi\n"))
    v = values(out)
    check("V(out) <+ 2*V(in) with NOTHING else on out: the contribution is a branch to ground, out is a path -- silent, v(c)=2",
          "no DC path" not in out and near(v.get("v(c)"), 2.0) and iters(out) <= 5, f"v(c)={v.get('v(c)')} {iters(out)}")
    out = ngspice(deck("osdi chain", "v1 a 0 1\nn1 a b mp\nn2 b c mp\nn3 c d mp\n.model mp vprobe", prints="v(d)", pre="pre_osdi vprobe.osdi\n"))
    v = values(out)
    check("a probe-and-drive chain of three (ports driven by single-ended contributions): silent, v(d)=8",
          "no DC path" not in out and near(v.get("v(d)"), 8.0) and iters(out) <= 5, f"v(d)={v.get('v(d)')} {iters(out)}")
    out = ngspice(deck("osdi diff", "v1 a 0 1\nr1 a 0 1k\nn1 p q md\n.model md vdiff", prints="v(p) v(q)", pre="pre_osdi vdiff.osdi\n"))
    v = values(out)
    check("V(p,n) <+ 1 between two nodes nothing else touches: a branch between them, not to ground -- both named, v(p)-v(q)=1 held by gmin",
          HELD.format("p") in out and HELD.format("q") in out and v.get("v(p)") is not None and v.get("v(q)") is not None
          and near(v["v(p)"] - v["v(q)"], 1.0, 1e-6) and iters(out) <= 8, f"v(p)={v.get('v(p)')} v(q)={v.get('v(q)')} {iters(out)}")

    print("[7] an OSDI thermal port")
    th = "v1 a 0 1\nn1 a 0 t1 mm\n.model mm {}"
    out = ngspice(deck("thermal rth", th.format("th_rth"), prints="v(a) v(t1)", pre="pre_osdi th_rth.osdi\n"))
    v = values(out)
    check("a thermal port with the model's own rth (Pwr(dt) <+ Temp(dt)/rth - P) on a lone net: a path, silent, T = P*rth",
          "no DC path" not in out and SING not in out and near(v.get("v(t1)"), 0.09996, 1e-3) and iters(out) <= 6,
          f"v(t1)={v.get('v(t1)')} iterations={iters(out)}")
    out = ngspice(deck("thermal pwr", th.format("th_pwr"), prints="v(a) v(t1)", pre="pre_osdi th_pwr.osdi\n"))
    check("a pure power source (Pwr(dt) <+ -P, no rth): the pattern is the rth one -- P depends on T through I -- so it is NOT held; "
          "the run stays singular and names t1 as before (the rth belongs in the model or the netlist)",
          "no DC path" not in out and "check node t1" in out, "")

    print("[6] the message cap")
    body = "v1 a 0 1\nr1 a 0 1k\n" + "".join(f"i{k} 0 x{k} 1n\n" for k in range(7))
    out = ngspice(deck("seven", body, prints="v(x0) v(x6)"))
    check("seven floating nodes: five named, then '... and 2 more nodes without a DC path to ground'",
          out.count("no DC path from node") == 5 and "and 2 more nodes without a DC path" in out
          and near(values(out).get("v(x6)"), 1e3), "")

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
