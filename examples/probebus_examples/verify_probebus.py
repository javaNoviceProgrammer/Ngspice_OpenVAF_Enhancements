#!/usr/bin/env python3
"""Enhancement-628: `.probe alli` on a bus device -- KiCad's default probe no
longer floats a Verilog-A bus port.

F11 of the 2026-09-12 hunt. KiCad adds `.probe alli` to every run. The pass
counted the node tokens of `N2 /mid /out vares` (two 4-bit bus ports in autobus
shorthand), took the device for a two-terminal one and spliced its measuring
source into the second token: `n2 /mid probe_int_/out_n2 vares` plus a source
from `probe_int_/out_n2` to `/out`. Autobus then expanded the invented base
into four bits nothing else touched, the source sat on the plain node, and the
bits floated -- 0 V on every output, gmin on every bit, and E-572's warning
about a plain node the pass itself had made. A subcircuit call whose formal is
a bus base inside (`.subckt va_res_block in out`, `N2 /mid out vares` in it)
failed the same way through the X line.

The pass now leaves OSDI lines and subcircuit calls to a second pass that runs
once `pre_osdi` has registered the modules and `.option autobus` is resolved
(both come after the deck read). There a shorthand line is written out against
its model's ports, in the deck's spelling, and every terminal gets its own
source; an X line keeps its base token (the subcircuit expands it) and gets one
source per bit the formal stands for inside, found through nested calls too.
Each terminal current is a vector named by the model's terminal (`n2:n_3_`)
or the formal and bit (`x1:out_3_`); a two-terminal scalar device or a
two-formal plain subcircuit keeps `<inst>#branch`.

Checks:
  [1] the example5 cascade under autobus=kicad with .probe alli: 1..4 V on
      the outputs, no warning, n2:n_k_#branch = -k mA, n2:p_k_ = 0
  [2] the same through va_res_block (X1 /in /out): x1:out_k_#branch = -k mA
  [3] the default bracket spelling, and a call nested two deep
  [4] a scalar OSDI device and a two-formal plain subcircuit keep n5#branch /
      x3#branch; a written-out OSDI line gets the model's terminal names
  [5] without .probe alli nothing changes (the reference values)
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
WORK = tempfile.mkdtemp(prefix="probebus_")
A = "@"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


for name, src in (("va_res", open(os.path.join(HERE, "va_res.va")).read()),
                  ("rr", '`include "disciplines.vams"\nmodule rr(p, n);\ninout p, n; electrical p, n;\n'
                         'parameter real r = 1k from (0:inf);\nanalog I(p,n) <+ V(p,n)/r;\nendmodule\n')):
    with open(os.path.join(WORK, name + ".va"), "w") as f:
        f.write(src)
    r = subprocess.run([VAF, os.path.join(WORK, name + ".va"), "-o", os.path.join(WORK, name + ".osdi")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(body, tag, ctl="op\nprint alli"):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* probebus {tag}\n{body}\n.control\npre_osdi va_res.osdi\npre_osdi rr.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def vals(out):
    return {n: float(v) for n, v in re.findall(r"^(\S+) = (-?[\d.]+e[-+]\d+)", out, re.M)}


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


KIC = (".model vares va_res R_ohm=1k\n.option autobus=kicad\n.probe alli\n"
       "V1 /in_0_ 0 DC 1u\nV2 /in_1_ 0 DC 2u\nV3 /in_2_ 0 DC 3u\nV4 /in_3_ 0 DC 4u\n"
       "RL0 /out_0_ 0 1k\nRL1 /out_1_ 0 1k\nRL2 /out_2_ 0 1k\nRL3 /out_3_ 0 1k\n")
print("Enhancement-628: .probe alli on a bus device\n")

# ------------------------------------------------------------- [1] ---
out = run(KIC + "N1 /in /mid vares\nN2 /mid /out vares", "t1",
          "op\nprint v(/out_0_) v(/out_1_) v(/out_2_) v(/out_3_)\nprint alli")
v = vals(out)
check("[1] the example5 cascade under autobus=kicad with .probe alli: 1..4 V on the outputs, no warning at all",
      all(close(v.get(f"v(/out_{k}_)"), float(k + 1)) for k in range(4)) and "Warning: instance" not in out
      and "no DC path" not in out, f"{ {k: v.get(k) for k in v if k.startswith('v(')} } {out[-300:]}")
check("[1] ...each terminal current is a vector by the model's terminal: n2:n_k_#branch = -(k+1) mA, n2:p_k_ = 0; n1 alike",
      all(close(v.get(f"n2:n_{k}_#branch"), -(k + 1) * 1e-3) for k in range(4))
      and all(close(v.get(f"n2:p_{k}_#branch"), 0.0) for k in range(4))
      and all(f"n1:n_{k}_#branch" in v and f"n1:p_{k}_#branch" in v for k in range(4))
      and "n2#branch" not in v, f"{ {k: v[k] for k in v if k.startswith('n2')} }")

# ------------------------------------------------------------- [2] ---
out = run(KIC + ".subckt va_res_block in out\nN1 in /mid vares\nN2 /mid out vares\n.ends\nX1 /in /out va_res_block",
          "t2", "op\nprint v(/out_3_)\nprint alli")
v = vals(out)
check("[2] the same through va_res_block (X1 /in /out, the formal a bus base inside): 4 V, x1:out_k_#branch = -(k+1) mA, "
      "x1:in_k_ = 0, no warning",
      close(v.get("v(/out_3_)"), 4.0) and all(close(v.get(f"x1:out_{k}_#branch"), -(k + 1) * 1e-3) for k in range(4))
      and all(close(v.get(f"x1:in_{k}_#branch"), 0.0) for k in range(4)) and "Warning: instance" not in out
      and "x1#branch" not in v, f"{ {k: v[k] for k in v if k.startswith('x1') or k.startswith('v(')} } {out[-200:]}")

# ------------------------------------------------------------- [3] ---
BRK = (".model vares va_res R_ohm=1k\n.option autobus\n.probe alli\n"
       "V1 in[0] 0 DC 1u\nV2 in[1] 0 DC 2u\nV3 in[2] 0 DC 3u\nV4 in[3] 0 DC 4u\n"
       "N1 in out vares\nRL0 out[0] 0 1k\nRL3 out[3] 0 1k\n"
       ".subckt outer a b\nX9 a b inner\n.ends\n.subckt inner p q\nN7 p q vares\n.ends\n"
       "X2 in out2 outer\nR9 out2[3] 0 1k\n")
out = run(BRK, "t3", "op\nprint v(out[3]) v(out2[3])\nprint alli")
v = vals(out)
check("[3] the default bracket spelling: out[3] = 4 mV, n1:n_3_#branch = -4 uA; a call nested two deep (outer -> inner) "
      "resolves the formal's width: x2:b_3_#branch = -4 uA",
      close(v.get("v(out[3])"), 4e-3) and close(v.get("v(out2[3])"), 4e-3)
      and close(v.get("n1:n_3_#branch"), -4e-6) and close(v.get("x2:b_3_#branch"), -4e-6)
      and all(f"x2:a_{k}_#branch" in v for k in range(4)) and "Warning: instance" not in out,
      f"{ {k: v[k] for k in v if k.startswith(('x2', 'n1:n_3', 'v('))} } {out[-200:]}")

# ------------------------------------------------------------- [4] ---
out = run(".model rm rr r=1k\n.model vares va_res R_ohm=1k\n.option autobus\n.probe alli\n"
          "V1 a 0 DC 1\nN5 a sc rm\nRsc sc 0 1k\n.subckt plain a b\nR1 a b 1k\n.ends\nX3 a pl plain\nRpl pl 0 1k\n"
          "V2 b[0] 0 DC 1u\nN6 b[0] b[1] b[2] b[3] c[0] c[1] c[2] c[3] vares\nRc c[0] 0 1k", "t4",
          "op\nprint v(sc) v(pl) v(c[0])\nprint alli")
v = vals(out)
check("[4] a scalar OSDI device keeps n5#branch (0.5 mA), a two-formal plain subcircuit x3#branch; a written-out OSDI "
      "line gets the model's terminal names (n6:n_0_#branch = -1 uA)",
      close(v.get("n5#branch"), 5e-4) and close(v.get("x3#branch"), 5e-4) and "n5:p#branch" not in v
      and close(v.get("n6:n_0_#branch"), -1e-6) and close(v.get("v(c[0])"), 1e-3),
      f"{ {k: v[k] for k in v if k.startswith(('n5', 'x3', 'n6:n_0', 'v('))} } {out[-200:]}")

# ------------------------------------------------------------- [5] ---
out = run(KIC.replace(".probe alli\n", "") + "N1 /in /mid vares\nN2 /mid /out vares", "t5",
          "op\nprint v(/out_0_) v(/out_3_)")
v = vals(out)
check("[5] without .probe alli the same deck reads the same outputs (the reference)",
      close(v.get("v(/out_0_)"), 1.0) and close(v.get("v(/out_3_)"), 4.0), f"{v}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
