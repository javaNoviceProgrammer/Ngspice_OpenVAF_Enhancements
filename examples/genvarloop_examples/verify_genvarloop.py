#!/usr/bin/env python3
"""verify_genvarloop.py -- Enhancement-407: a `genvar` for-loop inside an
`analog` block is unrolled at elaboration.

The loop exists because a vectored net's bit-select must be a CONSTANT: each bit
is its own simulator unknown, so `V(out[i]) <+ ..` over a run-time `integer` is
rejected outright ("bus bit-select index must be a constant"). Unrolling turns
the index into a literal, which is what makes the LRM's own pages 91, 117 and 134
compile.

The oracle is the LRM's own: page 117 ships the rolled `dac` and a hand-written
`dac8` side by side, so the unrolled form IS the specification. This file does the
same -- `rolled` and `unrolled` are one weighted sum written both ways and must
agree exactly.

Passes iff the rolled and hand-written forms agree, the shapes that need
unrolling work, and the cases that cannot be unrolled are still rejected with a
clear message. Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
OSDI = os.path.join(tempfile.gettempdir(), "genvarloop.osdi")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_file(path, extra=()):
    r = subprocess.run([OPENVAF, path, *extra, "-o", OSDI], capture_output=True,
                       text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


def compile_src(name, src):
    path = os.path.join(tempfile.gettempdir(), f"gv_{name}.va")
    with open(path, "w") as fh:
        fh.write(src)
    out = os.path.join(tempfile.gettempdir(), f"gv_{name}.osdi")
    r = subprocess.run([OPENVAF, path, "-o", out], capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


def v_out(model, nodes, probe="v(o)"):
    path = os.path.join(tempfile.gettempdir(), f"gl_{model}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* genvarloop {model}
vi 1 0 dc 0.8
v2 2 0 dc 0.4
v3 3 0 dc 0.2
v4 4 0 dc 0.1
nd1 {nodes} m{model}
.model m{model} {model}()
ro o 0 1meg
r0 q0 0 1meg
r1 q1 0 1meg
r2 q2 0 1meg
r3 q3 0 1meg
.control
pre_osdi {OSDI}
op
print {probe}
.endc
.end
""")
    out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                         timeout=120).stdout
    m = re.findall(re.escape(probe).replace(r"\(", r"\(").replace(r"\)", r"\)")
                   + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


HDR = '`include "disciplines.vams"\n'


def mod(decls, body, ports="out", extra_ports=""):
    return HDR + f"""
module m(out{extra_ports});
    output [0:3] out;
    electrical [0:3] out;
{decls}
    analog begin
{body}
    end
endmodule
"""


def main():
    print("Enhancement-407: analog-block genvar loops, unrolled at elaboration\n")
    code, log = compile_file(os.path.join(HERE, "genvar_loop.va"))
    if not check("genvar_loop.va compiles", code == 0, log.strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    # the LRM's own oracle: rolled vs hand-written must agree
    a = v_out("rolled", "o 1 2 3 4")
    b = v_out("unrolled", "o 1 2 3 4")
    check("rolled form works", a is not None and abs(a - 0.53125) < 1e-9, f"v(o)={a}")
    check("hand-written form works", b is not None and abs(b - 0.53125) < 1e-9, f"v(o)={b}")
    check("rolled == hand-written (the LRM's own oracle)",
          a is not None and b is not None and a == b, f"{a} vs {b}")

    # per-bit contribution: the shape an `integer` loop cannot express at all
    f0 = v_out("fanout", "q0 q1 q2 q3 1", "v(q0)")
    f3 = v_out("fanout", "q0 q1 q2 q3 1", "v(q3)")
    check("descending per-bit contribution: out[0] = 1*V(in)",
          f0 is not None and abs(f0 - 0.8) < 1e-9, f"v(q0)={f0}")
    check("descending per-bit contribution: out[3] = 4*V(in)",
          f3 is not None and abs(f3 - 3.2) < 1e-9, f"v(q3)={f3}")

    # a frozen width parameter is a usable bound (E-92 + E-407)
    s0 = v_out("sized", "q0 q1 q2 q3 1", "v(q0)")
    check("bound from a width-shaping parameter", s0 is not None and abs(s0 - 0.8) < 1e-9,
          f"v(q0)={s0}")

    print("\n  shapes that must still be rejected, clearly")
    code, out = compile_src("value", mod("    genvar i;\n    real a;",
                                         "        a = i*1.0;\n        V(out[0]) <+ a;"))
    check("a genvar read as a value", code != 0 and "genvar" in out,
          [l for l in out.splitlines() if "error" in l][:1])
    code, out = compile_src("settable", mod("    parameter integer n = 4;\n    genvar i;",
                                            "        for (i=0;i<n;i=i+1) V(out[i]) <+ 1.0;"))
    check("bound is a settable parameter", code != 0 and "compile-time constant" in out,
          [l for l in out.splitlines() if "error" in l][:1])
    code, out = compile_src("runaway", mod("    genvar i;",
                                           "        for (i=0;i<100000;i=i+1) V(out[0]) <+ 1.0;"))
    check("runaway loop is capped", code != 0 and "statement copies" in out,
          [l for l in out.splitlines() if "error" in l][:1])

    print("\n  shapes that must keep working unchanged")
    code, _ = compile_src("intloop", mod("    integer k;\n    real a;",
                                         "        a=0; for (k=0;k<4;k=k+1) a=a+1.0;\n"
                                         "        V(out[0]) <+ a;"))
    check("an ordinary integer for-loop is untouched", code == 0)
    code, _ = compile_src("gen", HDR + """
module m(out);
    output [0:3] out;
    electrical [0:3] out;
    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin
        analog V(out[g]) <+ 0.5;
    end
    endgenerate
endmodule
""")
    check("a module-level `generate for` still elaborates", code == 0)

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
