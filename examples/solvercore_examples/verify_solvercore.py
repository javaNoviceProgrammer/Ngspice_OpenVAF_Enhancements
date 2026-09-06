#!/usr/bin/env python3
"""
verify_solvercore.py -- the solver-core defects of the 2026-09-06 bug hunt
(docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md), pinned on BOTH solvers:

  F1  a node nothing conducts to (only a current source, or a controlled-current-
      source output) made KLU return wrong voltages for every other node, silently
  F8  the same node numbered last was OUTSIDE the matrix under both solvers: the RHS
      vectors were one short (Sparse wrote past them) and the injected current came
      back as the node's voltage, accumulating across a dc sweep
  F2  .ic/.nodeset on a node without a diagonal element (stacked sources, inductor
      nodes) aborted every analysis under KLU as "out of memory"
  F3  .option rshunt was absent from ac / noise / sp under KLU
  F4  an AC interrupted by a breakpoint inside `sweep` left the devices bound to
      the complex arrays; the next point's operating point came out NaN
  F7  KLU's AC lost accuracy across a wide sweep because every point reused the
      first frequency's pivot order with no check (26 dB, 613 dB with pivrel=1)

Now: both solvers agree, name the floating node ("singular matrix: check node",
"connected to nothing that conducts"), hold it at I/gmin, and the wide-range
ladder matches a 70-digit reference at every printed point.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
from decimal import Decimal as D, getcontext

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def ngspice(deck, name="_o.cir"):
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def scalars(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w\(\)\[\]#@.,-]+)\s*=\s*([-+0-9.eE]+)", line)
        if m:
            try:
                vals[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return vals


def rows(out):
    """Index-table rows of a `print` of vectors: {index: [col1, col2, ...]}."""
    table = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and re.match(r"^\d+$", parts[0].strip()):
            try:
                table[int(parts[0])] = [float(p) for p in parts[1:] if p.strip()]
            except ValueError:
                pass
    return table


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


# ---- the 70-digit reference for the wide-range ladder (Thomas algorithm) ------
RS = [1, 1e3, 1e6, 1e9, 10, 1e4, 1e7, 1e2, 1e5, 1e8]
CS = [1e-6, 1e-9, 1e-12, 1e-15, 1e-18, 1e-7, 1e-10, 1e-13, 1e-16, 1e-8]


def ladder_vdb(f):
    getcontext().prec = 70
    PI = D("3.14159265358979323846264338327950288419716939937510582097494459")
    cadd = lambda a, b: (a[0] + b[0], a[1] + b[1])
    csub = lambda a, b: (a[0] - b[0], a[1] - b[1])
    cmul = lambda a, b: (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])

    def cdiv(a, b):
        d = b[0] * b[0] + b[1] * b[1]
        return ((a[0] * b[0] + a[1] * b[1]) / d, (a[1] * b[0] - a[0] * b[1]) / d)
    n = 10
    w = 2 * PI * D(repr(f))
    g = [D(1) / D(repr(r)) for r in RS]
    y = [(D(0), w * D(repr(c))) for c in CS]
    diag, off = [], []
    for k in range(n):
        dk = cadd((g[k], D(0)), y[k])
        if k + 1 < n:
            dk = cadd(dk, (g[k + 1], D(0)))
        if k == n - 1:
            dk = cadd(dk, (D("1e-12"), D(0)))
        diag.append(dk)
        off.append((-g[k + 1], D(0)) if k + 1 < n else None)
    b = [(g[0], D(0))] + [(D(0), D(0))] * (n - 1)
    cp, dp = [None] * n, [None] * n
    cp[0] = cdiv(off[0], diag[0])
    dp[0] = cdiv(b[0], diag[0])
    for k in range(1, n):
        den = csub(diag[k], cmul(off[k - 1], cp[k - 1]))
        if k < n - 1:
            cp[k] = cdiv(off[k], den)
        dp[k] = cdiv(csub(b[k], cmul(off[k - 1], dp[k - 1])), den)
    x = [None] * n
    x[n - 1] = dp[n - 1]
    for k in range(n - 2, -1, -1):
        x[k] = csub(dp[k], cmul(cp[k], x[k + 1]))
    import math
    m = x[n - 1]
    return 10 * math.log10(float(m[0] * m[0] + m[1] * m[1]))


def ladder_deck(extra_option="", control="ac dec 2 1m 1t\nlet m = vdb(n10)\nprint m[24] m[30]"):
    lines = ["* wide dynamic range RC ladder", f".option {extra_option}" if extra_option else "* no extra option",
             "v1 in 0 dc 0 ac 1"]
    prev = "in"
    for k, (r, c) in enumerate(zip(RS, CS), 1):
        lines += [f"r{k} {prev} n{k} {r}", f"c{k} n{k} 0 {c}"]
        prev = f"n{k}"
    lines += [f"rl {prev} 0 1e12", ".control", control, ".endc", ".end"]
    return "\n".join(lines) + "\n"


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[F1] a node nothing conducts to: the rest of the circuit stays right, the node is named")
    out = ngspice("* floating middle node\nv1 n1 0 1\nr1 n1 n2 1k\ni1 0 nx 1m\nr2 n2 0 1k\nr3 n1 n3 1k\nr4 n3 0 1k\n"
                  ".control\nop\nprint v(n1) v(n2) v(n3) v(nx) i(v1)\n.endc\n.end\n")
    v = scalars(out)
    check("op: v(n1)=1, v(n2)=v(n3)=0.5, i(v1)=-1mA", near(v.get("v(n1)"), 1, 1e-9) and near(v.get("v(n2)"), .5, 1e-9)
          and near(v.get("v(n3)"), .5, 1e-9) and near(v.get("i(v1)"), -1e-3, 1e-12), f"{v}")
    check("the floating node reads I/gmin (>1e8 V), not a phantom 1 V/A", v.get("v(nx)", 0) > 1e8, f"v(nx)={v.get('v(nx)')}")
    check("setup names it: 'connected to nothing that conducts'", "connected to nothing that conducts" in out)
    check("the solver names it: 'singular matrix:  check node nx'", "check node nx" in out)
    out = ngspice("* CCCS output into a floating node\nv1 n1 0 1\nr1 n1 n2 1k\nf1 0 nx v1 1\nr2 n2 0 1k\nr3 n1 n3 1k\nr4 n3 0 1k\n"
                  ".control\nop\nprint v(n1) v(n2) v(n3) v(nx)\n.endc\n.end\n")
    v = scalars(out)
    check("CCCS output: v(n1)=1, v(n2)=v(n3)=0.5 (was 0/0/0 under KLU)", near(v.get("v(n1)"), 1, 1e-9)
          and near(v.get("v(n2)"), .5, 1e-9) and near(v.get("v(n3)"), .5, 1e-9), f"{v}")
    out = ngspice("* two floating nodes\nv1 n1 0 1\nr1 n1 n2 1k\ni1 0 nx 1m\nr2 n2 0 1k\ni2 0 ny 1m\nr3 n1 n3 1k\nr4 n3 0 1k\n"
                  ".control\nop\nprint v(n1) v(n2) v(n3)\n.endc\n.end\n")
    v = scalars(out)
    check("two floating nodes (the multi-gap map): 1 / 0.5 / 0.5 (was 1e-3 / 0 / 9e81)", near(v.get("v(n1)"), 1, 1e-9)
          and near(v.get("v(n2)"), .5, 1e-9) and near(v.get("v(n3)"), .5, 1e-9), f"{v}")
    out = ngspice("* monitor inside a subcircuit\n.subckt stage in out\nr1 in out 1k\nr2 out 0 1k\nbmon 0 imon i = v(in)*1e-3\n.ends\n"
                  "v1 a 0 1\nx1 a b stage\nr3 a c 1k\nr4 c 0 1k\n.control\nop\nprint v(a) v(b) v(c)\n.endc\n.end\n")
    v = scalars(out)
    check("forgotten monitor load inside a subcircuit: 1 / 0.5 / 0.5 and 'check node x1.imon'",
          near(v.get("v(a)"), 1, 1e-9) and near(v.get("v(b)"), .5, 1e-9) and near(v.get("v(c)"), .5, 1e-9)
          and "x1.imon" in out, f"{v}")

    print("[F8] the floating node numbered LAST: inside the matrix, RHS vectors cover it, no pass-through")
    out = ngspice("* trailing floating node\ni1 0 n1 1m\nr1 n1 0 1k\nr2 n1 n2 1k\nr3 n2 0 1k\ni2 0 nx 2m\n"
                  ".control\nop\nprint v(n1) v(n2) v(nx)\n.endc\n.end\n")
    v = scalars(out)
    check("op: v(n1)=2/3, v(n2)=1/3, v(nx)=I/gmin (was 2e-3 = the current read as volts)",
          near(v.get("v(n1)"), 2 / 3, 1e-6) and near(v.get("v(n2)"), 1 / 3, 1e-6) and v.get("v(nx)", 0) > 1e8, f"{v}")
    out = ngspice("* trailing floating node, dc sweep\ni1 0 n1 1m\nr1 n1 0 1k\nr2 n1 n2 1k\nr3 n2 0 1k\ni2 0 nx 2m\n"
                  ".control\ndc i2 0 4m 1m\nprint v(nx) v(n2)\n.endc\n.end\n")
    t = rows(out)
    r2, r4 = (t.get(2) or [None, None, None]), (t.get(4) or [None, None, None])
    check("dc sweep: v(nx) scales with the current, 4mA/2mA = 2 (was the running sum, ratio 3.33)",
          len(r2) >= 3 and len(r4) >= 3 and r2[1] and abs(r4[1] / r2[1] - 2.0) < 1e-6 and near(r4[2], 1 / 3, 1e-6),
          f"2mA -> {r2[1:] if len(r2) > 1 else r2}, 4mA -> {r4[1:] if len(r4) > 1 else r4}")

    print("[F2] .ic / .nodeset on a node without a diagonal element runs (was 'out of memory' under KLU)")
    out = ngspice("* stacked sources, nodeset on the tap\nv1 a 0 1\nv2 b a 1\nr1 b 0 1k\n.nodeset v(a)=1\n.control\nop\nprint v(a) v(b)\n.endc\n.end\n")
    v = scalars(out)
    check("stacked supplies with .nodeset on the tap: 1 V / 2 V", near(v.get("v(a)"), 1, 1e-9) and near(v.get("v(b)"), 2, 1e-9), f"{v}")
    out = ngspice("* .ic between two inductors\nv1 in 0 dc 1 pulse(0 1 0 1n 1n 10u 20u)\nl1 in mid 1u\nl2 mid out 1u\nr1 out 0 1k\nc1 out 0 1n\n"
                  ".ic v(mid)=0.5\n.nodeset v(out)=0.2\n.control\ntran 10n 1u\nop\nprint v(mid) v(out)\n.endc\n.end\n")
    v = scalars(out)
    check(".ic on an inductor-only node, tran then op: v(mid)=v(out)=1 and no abort",
          near(v.get("v(mid)"), 1, 1e-6) and near(v.get("v(out)"), 1, 1e-6) and "out of memory" not in out, f"{v}")
    out = ngspice("* .ic on a VCVS output feeding an inductor\nv1 in 0 dc 1\ne1 x 0 in 0 2\nl1 x out 1u\nr1 out 0 1k\n.ic v(x)=2\n"
                  ".control\nop\nprint v(x) v(out)\n.endc\n.end\n")
    v = scalars(out)
    check(".ic on a VCVS output node: 2 V / 2 V", near(v.get("v(x)"), 2, 1e-9) and near(v.get("v(out)"), 2, 1e-9), f"{v}")

    print("[F3] .option rshunt reaches the small-signal analyses (was absent under KLU)")
    out = ngspice("* rshunt in ac\n.option rshunt=1k\nv1 in 0 dc 0 ac 1\nc1 in out 1n\nr0 in 0 1k\n.control\nac lin 1 1k 1k\nprint vm(out)\n.endc\n.end\n")
    v = scalars(out)
    check("ac: |v(out)| = wRC = 6.283e-3 (was 1.0, the unloaded capacitor)", near(v.get("vm(out)"), 6.283061e-3, 6e-5), f"{v}")
    out = ngspice("* rshunt in noise\n.option rshunt=1k\nv1 s 0 dc 0 ac 1\nrs s in 1k\nc1 in out 1n\n.control\n"
                  "noise v(out) v1 dec 10 100 10k\nprint onoise_total\n.endc\n.end\n")
    v = scalars(out)
    check("noise: onoise_total = 7.365e-9 (was 4.05e-7, 55x)", near(v.get("onoise_total"), 7.364735e-9, 1.5e-10), f"{v}")
    out = ngspice("* rshunt in sp\n.option rshunt=1k\nvp in 0 dc 0 ac 1 portnum 1 z0 50\nc1 in x 1n\n.control\nsp lin 1 1k 1k\nprint mag(s_1_1)\n.endc\n.end\n")
    v = scalars(out)
    check("sp: |S11| = 0.814 (was 1.000, an open)", near(v.get("mag(s_1_1)"), 0.8140556, 8e-3), f"{v}")

    print("[F4] an AC interrupted by a breakpoint inside `sweep` leaves the next point sound")
    out = ngspice("* paused ac inside a sweep\nv1 in 0 dc 1 ac 1\nr1 in out 1k\nr2 out 0 1k\nc1 out 0 1n\n.control\n"
                  "stop when frequency > 500\nsweep @r1[resistance] lin 3 1k 3k -analysis ac dec 5 100 10k -output g=mag(v(out))\n"
                  "print g\n.endc\n.end\n")
    t = rows(out)
    g = [t.get(i, [None])[0] for i in range(3)]
    check("three points recorded 0.5 / 0.333 / 0.25 (point 2 was NaN under KLU)",
          near(g[0], .5, 2e-4) and near(g[1], 1 / 3, 2e-4) and near(g[2], .25, 2e-4) and "did not converge" not in out, f"g={g}")

    print("[F7] a wide-range ladder against a 70-digit reference (the reused pivot order is now checked)")
    ref9, ref12 = ladder_vdb(1e9), ladder_vdb(1e12)
    for opt, label in (("", "default pivrel"), ("pivrel=1", "pivrel=1 (was 613 dB off at 1 THz)")):
        v = scalars(ngspice(ladder_deck(opt)))
        check(f"{label}: vdb(n10) at 1 GHz and 1 THz within 0.05 dB of {ref9:.2f} / {ref12:.2f}",
              near(v.get("m[24]"), ref9, 0.05) and near(v.get("m[30]"), ref12, 0.05), f"{v}")

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
