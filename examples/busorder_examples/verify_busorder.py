#!/usr/bin/env python3
"""Enhancement-637: a bus actual connects positionally, in its declared or
written order, whichever way either side is declared.

A whole bus `.a(p)` and a part-select `.a(p[3:0])` were laid onto the port by
INDEX VALUE, ascending onto ascending, while a concatenation `.a({p})` has
always connected positionally (leftmost = port msb). So `.a(p)` and `.a({p})`
differed when the two declarations ran opposite ways, and the reversed
part-select `p[3:0]` of a `[0:3]` bus silently meant `p[0:3]` while
`{p[3],p[2],p[1],p[0]}` reversed. Now every form is positional: the actual's
leftmost bit -- its msb as declared, or as written for a part-select -- lands
on the port's msb.

The child puts (k+1) mA per volt on its bit a[k]; each parent bit is driven by
its own 1 V source, so the current at a parent bit says which child bit it is
wired to.

Checks (child a[0:3] unless stated; the list is the child bit + 1 seen on p[0], p[1], ...):
  [1]  same direction, plain bus: p[0:3] -> 1 2 3 4 (unchanged)
  [2]  opposite direction, plain bus: p[3:0] onto a[0:3] -> 4 3 2 1, the same as {p}
  [3]  a[3:0] child: p[0:3] -> 4 3 2 1 (= {p}); p[3:0] -> 1 2 3 4
  [4]  reversed part-select p[3:0] of a [0:3] bus -> 4 3 2 1, the same as {p[3],p[2],p[1],p[0]}
  [5]  same-order part-select p[0:3] -> 1 2 3 4 (unchanged)
  [6]  sub-slices of a wider bus: p[1:4] of p[0:5] -> bits 1..4 get 1 2 3 4; p[4:1] -> 4 3 2 1
  [7]  a[3:0] child with p[3:0] declared: p[3:0] -> 1 2 3 4; p[0:3] -> 4 3 2 1
  [8]  E-85's partselect suite decks still route as pinned (run here on the same object shapes)
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
WORK = tempfile.mkdtemp(prefix="busorder_")
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


CHILD = {
    "asc": "module ch(a,b); inout [0:3] a; inout b; electrical [0:3] a; electrical b; genvar i;\n"
           "  analog for (i=0;i<4;i=i+1) I(a[i],b) <+ V(a[i],b)/1k*(i+1);\nendmodule\n",
    "desc": "module ch(a,b); inout [3:0] a; inout b; electrical [3:0] a; electrical b; genvar i;\n"
            "  analog for (i=0;i<4;i=i+1) I(a[i],b) <+ V(a[i],b)/1k*(i+1);\nendmodule\n",
}


def route(tag, child, decl, conn):
    """Compile a parent with bus p declared `decl`, connected to the child by `conn`;
    return the child bit + 1 seen at each parent bit p[0], p[1], ... (0 where nothing lands)."""
    src = CHILD[child] + f"module m(p,n); inout {decl} p; inout n; electrical {decl} p; electrical n; ch c(.a({conn}), .b(n)); endmodule\n"
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[-300:]
    lo, hi = (int(x) for x in decl[1:-1].split(":"))
    n = abs(hi - lo) + 1
    srcs = "\n".join(f"v{i} {i + 1} 0 1" for i in range(n))
    nodes = " ".join(str(i + 1) for i in range(n))
    deck = os.path.join(WORK, f"{tag}.cir")
    with open(deck, "w") as f:
        f.write(f"* busorder {tag}\n{srcs}\nn1 {nodes} 0 mm\n.model mm m\n.control\nset noinit\npre_osdi {tag}.osdi\nop\n"
                + "print " + " ".join(f"i(v{i})" for i in range(n)) + "\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(deck)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    out = p.stdout + p.stderr
    vals = []
    for i in range(n):
        m = re.search(rf"^i\(v{i}\)\s*=\s*(\S+)", out, re.M)
        if not m:
            return None, out[-300:]
        vals.append(int(round(-float(m.group(1)) * 1e3)))
    return vals, out[-200:]


print("Enhancement-637: bus actuals connect positionally, in declared or written order\n")

v, d = route("c1", "asc", "[0:3]", "p")
check("[1] same direction, plain bus p[0:3] onto a[0:3]: 1 2 3 4", v == [1, 2, 3, 4], f"{v} {d if v is None else ''}")

v1, _ = route("c2a", "asc", "[3:0]", "p")
v2, _ = route("c2b", "asc", "[3:0]", "{p}")
check("[2] opposite direction, plain bus p[3:0] onto a[0:3]: 4 3 2 1, the same as {p} (it used to be 1 2 3 4 by index)",
      v1 == [4, 3, 2, 1] and v2 == [4, 3, 2, 1], f"{v1} {v2}")

v1, _ = route("c3a", "desc", "[0:3]", "p")
v2, _ = route("c3b", "desc", "[0:3]", "{p}")
v3, _ = route("c3c", "desc", "[3:0]", "p")
check("[3] child a[3:0]: p[0:3] -> 4 3 2 1 (= {p}), p[3:0] -> 1 2 3 4",
      v1 == [4, 3, 2, 1] and v2 == [4, 3, 2, 1] and v3 == [1, 2, 3, 4], f"{v1} {v2} {v3}")

v1, _ = route("c4a", "asc", "[0:3]", "p[3:0]")
v2, _ = route("c4b", "asc", "[0:3]", "{p[3],p[2],p[1],p[0]}")
check("[4] the reversed part-select p[3:0] of a [0:3] bus: 4 3 2 1, the same as {p[3],p[2],p[1],p[0]} (it used to mean p[0:3])",
      v1 == [4, 3, 2, 1] and v2 == [4, 3, 2, 1], f"{v1} {v2}")

v, _ = route("c5", "asc", "[0:3]", "p[0:3]")
check("[5] the same-order part-select p[0:3]: 1 2 3 4", v == [1, 2, 3, 4], f"{v}")

v1, _ = route("c6a", "asc", "[0:5]", "p[1:4]")
v2, _ = route("c6b", "asc", "[0:5]", "p[4:1]")
check("[6] sub-slices of p[0:5]: p[1:4] puts 1 2 3 4 on bits 1..4, p[4:1] puts 4 3 2 1",
      v1 == [0, 1, 2, 3, 4, 0] and v2 == [0, 4, 3, 2, 1, 0], f"{v1} {v2}")

v1, _ = route("c7a", "desc", "[3:0]", "p[3:0]")
v2, _ = route("c7b", "desc", "[3:0]", "p[0:3]")
check("[7] child a[3:0] with p[3:0]: p[3:0] -> 1 2 3 4, p[0:3] -> 4 3 2 1",
      v1 == [1, 2, 3, 4] and v2 == [4, 3, 2, 1], f"{v1} {v2}")

# [8] E-85's own routing: pair(o, i[1:0]) outputs 2*V(i[1]) + V(i[0]); v[k] = k volts
src = """module pair(o, i); output o; input [1:0] i; electrical o; electrical [1:0] i;
  analog V(o) <+ 2*V(i[1]) + V(i[0]);
endmodule
module top(o1, o2, o3, v3, v2, v1, v0); inout o1, o2, o3, v3, v2, v1, v0;
  electrical o1, o2, o3, v3, v2, v1, v0; electrical [3:0] v;
  analog begin V(v[3]) <+ V(v3); V(v[2]) <+ V(v2); V(v[1]) <+ V(v1); V(v[0]) <+ V(v0); end
  pair p1 (o1, v[3:2]);
  pair p2 (.o(o2), .i(v[1:0]));
  pair p3 (.o(o3), .i({v[0], v[3]}));
endmodule
"""
path = os.path.join(WORK, "e85.va")
with open(path, "w") as f:
    f.write(HDR + src)
r = subprocess.run([VAF, path, "-o", os.path.join(WORK, "e85.osdi")], capture_output=True, text=True)
deck = os.path.join(WORK, "e85.cir")
with open(deck, "w") as f:
    f.write("* busorder e85\nv3 v3 0 3\nv2 v2 0 2\nv1 v1 0 1\nv0 v0 0 0\nn1 o1 o2 o3 v3 v2 v1 v0 mm\n.model mm top\n"
            ".control\nset noinit\npre_osdi e85.osdi\nop\nprint v(o1) v(o2) v(o3)\n.endc\n.end\n")
p = subprocess.run([NGSPICE, "-b", "e85.cir"], capture_output=True, text=True, timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
out = p.stdout + p.stderr
o = {k: float(m.group(1)) for k in ("o1", "o2", "o3") for m in [re.search(rf"^v\({k}\)\s*=\s*(\S+)", out, re.M)] if m}
check("[8] E-85's routing holds: v[3:2] -> 2*3+2 = 8 V, .i(v[1:0]) -> 2*1+0 = 2 V, {v[0],v[3]} -> 2*0+3 = 3 V",
      r.returncode == 0 and abs(o.get("o1", 0) - 8) < 1e-6 and abs(o.get("o2", 0) - 2) < 1e-6 and abs(o.get("o3", 0) - 3) < 1e-6,
      f"{o} {(r.stdout + r.stderr)[-200:] if r.returncode else ''}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
