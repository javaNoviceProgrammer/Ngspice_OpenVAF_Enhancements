#!/usr/bin/env python3
"""Enhancement-592: autoadapt says which adapter rule failed, and a `.ic` or
`.nodeset` on a bit of a split node is explained.

  F4  one compound test printed one message for three faults; a scalar or
      `[0:0]` adapter read "must have exactly two bus ports of equal width
      (found 2 port(s), widths 1/1)" -- refused with the rule unstated.
  F5  `.ic v(x[2])=0.5` on a split bus got ngspice's generic "IC on
      non-existent node" while `.save v(x[2])` got the split explained: the
      two cards resolve their nodes in pass 3, before the split check runs.

Checks:
  [1] a scalar adapter: the width-1 message with the bus-only rule
  [2] a [0:0] adapter: the same
  [3] a three-port adapter: "exactly two bus ports (found 3)"
  [4] ports of widths 5 and 3: "different widths (5 and 3)"
  [5] a 5-bit adapter still splits the bus (values)
  [6] .ic v(x[2])=0.5 on the split bus: the split message naming x_f[2]/x_r[2]
  [7] .nodeset v(x[2])=0.5: the same for .nodeset
  [8] .ic v(x_f[2])=0.5 is accepted and holds in a `tran uic`
  [9] .ic v(nosuch)=1 keeps the generic message
  [10] .ic on an autobus bit without a split is unchanged
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
WORK = tempfile.mkdtemp(prefix="adaptmsg_")
HDR = '`include "disciplines.vams"\n'
MODELS = {
    "busdev": """module busdev(a, b);
inout [0:4] a; inout b; electrical [0:4] a; electrical b;
parameter real g = 1e-3;
genvar i;
analog for (i = 0; i <= 4; i = i + 1) I(a[i], b) <+ g * (i + 1) * V(a[i], b);
endmodule
""",
    "amod": "module amod(p, n); inout p, n; electrical p, n; parameter real r = 10; analog I(p,n) <+ V(p,n)/r; endmodule\n",
    "amod0": "module amod0(p, n); inout [0:0] p, n; electrical [0:0] p, n; parameter real r = 10; analog I(p[0],n[0]) <+ V(p[0],n[0])/r; endmodule\n",
    "amod5": """module amod5(p, n);
inout [0:4] p, n; electrical [0:4] p, n;
parameter real r = 10;
genvar i;
analog for (i = 0; i <= 4; i = i + 1) I(p[i], n[i]) <+ V(p[i], n[i])/r;
endmodule
""",
    "amod53": """module amod53(p, n);
inout [0:4] p; inout [0:2] n; electrical [0:4] p; electrical [0:2] n;
parameter real r = 10;
genvar i;
analog for (i = 0; i <= 2; i = i + 1) I(p[i], n[i]) <+ V(p[i], n[i])/r;
endmodule
""",
    "amod3p": """module amod3p(p, n, q);
inout [0:4] p, n, q; electrical [0:4] p, n, q;
parameter real r = 10;
genvar i;
analog for (i = 0; i <= 4; i = i + 1) begin I(p[i], n[i]) <+ V(p[i], n[i])/r; I(q[i], n[i]) <+ V(q[i], n[i])/r; end
endmodule
""",
}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


for name, src in MODELS.items():
    with open(os.path.join(WORK, name + ".va"), "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, os.path.join(WORK, name + ".va"), "-o", os.path.join(WORK, name + ".osdi")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)

PRE = "\n".join(f"pre_osdi {m}.osdi" for m in MODELS)
CARDS = "\n".join(f".model {m}m {m}" + (" r=10" if m.startswith("amod") else "") for m in MODELS)


def run(adapter, netlist, ctl, tag, options=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* adaptmsg {tag}\n.option autobus autoadapt adapter={adapter} {options}\n.control\n{PRE}\n.endc\n{CARDS}\n{netlist}\n.control\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


BUS = "v0 s1 0 1\nN1 x s1 busdevm\nN2 x s2 busdevm\nr2 s2 0 1k\n"


def value(out, name):
    m = re.search(r"(?mi)^" + re.escape(name) + r" = (\S+)", out)
    return float(m.group(1)) if m else None


print("Enhancement-592: autoadapt messages, and .ic/.nodeset on a split bit\n")

# ------------------------------------------------------------- [1] ---
out = run("amodm", BUS, "op\nprint v(s2)", "t1")
check("[1] a scalar adapter is refused with the width-1 message and the bus-only rule",
      "has a port of width 1 (widths 1/1); autoadapt splits bus nodes only" in out and "exactly two bus ports of equal width" not in out,
      out[-300:])
# ------------------------------------------------------------- [2] ---
out = run("amod0m", BUS, "op\nprint v(s2)", "t2")
check("[2] a [0:0] adapter: the same message", "has a port of width 1 (widths 1/1)" in out, out[-300:])
# ------------------------------------------------------------- [3] ---
out = run("amod3pm", BUS, "op\nprint v(s2)", "t3")
check("[3] a three-port adapter: exactly two bus ports (found 3)", "must have exactly two bus ports (found 3)" in out, out[-300:])
# ------------------------------------------------------------- [4] ---
out = run("amod53m", BUS, "op\nprint v(s2)", "t4")
check("[4] ports of widths 5 and 3: different widths (5 and 3)", "ports of different widths (5 and 3)" in out, out[-300:])
# ------------------------------------------------------------- [5] ---
out = run("amod5m", BUS, "op\nprint v(x_f[2])\nprint v(x_r[2])\nprint v(s2)", "t5")
xf, xr, s2 = value(out, "v(x_f[2])"), value(out, "v(x_r[2])"), value(out, "v(s2)")
check("[5] a 5-bit adapter still splits the bus: x_f[2] 0.94111, x_r[2] 0.93935, s2 0.88046",
      xf is not None and abs(xf - 0.9411123) < 1e-5 and abs(xr - 0.9393456) < 1e-5 and abs(s2 - 0.8804579) < 1e-5,
      f"{xf} {xr} {s2}")
# ------------------------------------------------------------- [6] ---
out = run("amod5m", BUS + ".ic v(x[2])=0.5\n", "op\nprint v(s2)", "t6")
check("[6] .ic v(x[2])=0.5 on the split bus: the split explained, with x_f[2] and x_r[2] offered",
      "autoadapt split node 'x' into 'x_f' and 'x_r', so its bit 'x[2]' no longer exists" in out
      and "the .ic on it is ignored -- refer to x_f[2] or x_r[2] instead" in out
      and "IC on non-existent node" not in out, out[-400:])
# ------------------------------------------------------------- [7] ---
out = run("amod5m", BUS + ".nodeset v(x[2])=0.5\n", "op\nprint v(s2)", "t7")
check("[7] .nodeset v(x[2])=0.5: the same for .nodeset",
      "so its bit 'x[2]' no longer exists" in out and "the .nodeset on it is ignored -- refer to x_f[2] or x_r[2] instead" in out
      and "Nodeset on non-existent node" not in out, out[-400:])
# ------------------------------------------------------------- [8] ---
out = run("amod5m", BUS + "c9 x_f[2] 0 1u\n.ic v(x_f[2])=0.5\n", "tran 1n 3n uic\nprint v(x_f[2])[0]", "t8")
v0 = value(out, "v(x_f[2])[0]")
check("[8] .ic v(x_f[2])=0.5 is accepted and holds at t=0 under uic",
      v0 is not None and abs(v0 - 0.5) < 1e-3 and "no longer exists" not in out and "non-existent" not in out, f"{v0}")
# ------------------------------------------------------------- [9] ---
out = run("amod5m", BUS + ".ic v(nosuch)=1\n", "op\nprint v(s2)", "t9")
check("[9] .ic v(nosuch)=1 keeps the generic message", "IC on non-existent node - nosuch, ignored" in out, out[-300:])
# ------------------------------------------------------------ [10] ---
out = run("amod5m", "v0 a[0] 0 1\nr1 b 0 1k\nc1 a[2] 0 1u\nr2 a[1] 0 1k\nr3 a[3] 0 1k\nr4 a[4] 0 1k\nN1 a b busdevm\n.ic v(a[2])=0.7\n", "tran 1n 3n uic\nprint v(a[2])[0]", "t10")
v0 = value(out, "v(a[2])[0]")
check("[10] .ic on an autobus bit that was not split is unchanged (0.7 at t=0)", v0 is not None and abs(v0 - 0.7) < 1e-3, f"{v0}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
