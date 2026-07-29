#!/usr/bin/env python3
"""Complexity sweeper: find compile-time blowups by scaling ONE knob at a time.

E-147 (nested ?: was O(2^N)) and E-264 (instance-array flatten was O(N^2)) were
both found by accident. This sweeps every size knob in the language
systematically and fits an exponent, so a superlinear path shows up as a number
rather than as a mysteriously slow build.

For each feature, compile at N, 2N, 4N... and report log2(t(2N)/t(N)) -- the
empirical exponent. ~1.0 is linear and fine. >=1.8 is quadratic-or-worse and is
a denial-of-service on a plausible input. A HANG at modest N is a finding.

Reports a table; exits 1 if any feature is superlinear.
"""
import os
import subprocess
import sys
import time

NG = os.environ["OPENVAF_BIN"]
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work_sweep")
os.makedirs(WORK, exist_ok=True)

HDR = '`include "disciplines.vams"\nmodule m(a, b);\n  inout a, b;\n  electrical a, b;\n'
FTR = "endmodule\n"


def wrap(decls, body):
    return HDR + decls + "  analog begin\n" + body + "  end\n" + FTR


# ---- each builder returns a complete source file exercising ONE knob at size n

def f_paren(n):
    return wrap("", "    I(a,b) <+ %s V(a,b) %s;\n" % ("(" * n, ")" * n))


def f_ternary(n):
    e = "V(a,b)"
    for i in range(n):
        e = "(V(a,b) > %d.0 ? %s : 1.0)" % (i, e)   # linear in text, deep in nesting
    return wrap("", "    I(a,b) <+ %s;\n" % e)


def f_addchain(n):
    return wrap("", "    I(a,b) <+ %s;\n" % " + ".join("V(a,b)" for _ in range(n)))


def f_mulchain(n):
    return wrap("", "    I(a,b) <+ %s;\n" % " * ".join("V(a,b)" for _ in range(n)))


def f_ifnest(n):
    s = ""
    for i in range(n):
        s += "  " * (i + 2) + "if (V(a,b) > %d.0) begin\n" % i
    s += "  " * (n + 2) + "I(a,b) <+ V(a,b);\n"
    for i in range(n - 1, -1, -1):
        s += "  " * (i + 2) + "end\n"
    return wrap("", s)


def f_vars(n):
    d = "".join("  real v%d;\n" % i for i in range(n))
    b = "".join("    v%d = V(a,b) * %d.0;\n" % (i, i) for i in range(n))
    b += "    I(a,b) <+ %s;\n" % " + ".join("v%d" % i for i in range(n))
    return wrap(d, b)


def f_params(n):
    d = "".join("  parameter real p%d = %d.0;\n" % (i, i) for i in range(n))
    return wrap(d, "    I(a,b) <+ %s;\n" % " + ".join("p%d" % i for i in range(n)))


def f_contribs(n):
    d = "".join("  electrical x%d;\n" % i for i in range(n))
    b = "".join("    I(x%d, b) <+ V(x%d, b);\n" % (i, i) for i in range(n))
    b += "    I(a,b) <+ V(a,b);\n"
    return wrap(d, b)


def f_case(n):
    b = "    case ($rtoi(V(a,b)))\n"
    for i in range(n):
        b += "      %d: I(a,b) <+ %d.0 * V(a,b);\n" % (i, i)
    b += "      default: I(a,b) <+ V(a,b);\n    endcase\n"
    return wrap("  integer k;\n", b)


def f_array(n):
    d = "  real arr[0:%d];\n" % (n - 1)
    b = "".join("    arr[%d] = V(a,b) * %d.0;\n" % (i, i) for i in range(n))
    b += "    I(a,b) <+ %s;\n" % " + ".join("arr[%d]" % i for i in range(n))
    return wrap(d, b)


def f_laplace(n):
    num = ", ".join("1.0" for _ in range(n))
    den = ", ".join("%f" % (1.0 + i * 1e-12) for i in range(n + 1))
    return wrap("", "    I(a,b) <+ laplace_nd(V(a,b), {%s}, {%s});\n" % (num, den))


def f_ddtnest(n):
    e = "V(a,b)"
    for _ in range(n):
        e = "ddt(%s)" % e
    return wrap("", "    I(a,b) <+ %s;\n" % e)


def f_funcchain(n):
    d = ""
    for i in range(n):
        inner = "x" if i == 0 else "g%d(x)" % (i - 1)
        d += ("  analog function real g%d;\n    input x; real x;\n"
              "    g%d = %s + 1.0;\n  endfunction\n" % (i, i, inner))
    return wrap(d, "    I(a,b) <+ g%d(V(a,b));\n" % (n - 1))


def f_modules(n):
    s = '`include "disciplines.vams"\n'
    for i in range(n):
        s += ("module m%d(a, b);\n  inout a, b;\n  electrical a, b;\n"
              "  analog I(a,b) <+ V(a,b);\nendmodule\n" % i)
    return s


def f_noise(n):
    b = "".join('    I(a,b) <+ white_noise(%d.0, "n%d");\n' % (i + 1, i) for i in range(n))
    b += "    I(a,b) <+ V(a,b);\n"
    return wrap("", b)


def f_ddx(n):
    e = " + ".join("ddx(V(a,b) * %d.0, V(a))" % i for i in range(n))
    return wrap("", "    I(a,b) <+ %s;\n" % e)


def f_macro(n):
    s = '`include "disciplines.vams"\n'
    s += "`define M0 V(a,b)\n"
    for i in range(1, n):
        s += "`define M%d (`M%d + `M%d)\n" % (i, i - 1, i - 1)
    s += ("module m(a, b);\n  inout a, b;\n  electrical a, b;\n"
          "  analog I(a,b) <+ `M%d;\nendmodule\n" % (n - 1))
    return s


FEATURES = [
    ("paren-nesting", f_paren, 64),
    ("ternary-nesting", f_ternary, 32),
    ("add-chain", f_addchain, 128),
    ("mul-chain", f_mulchain, 128),
    ("if-nesting", f_ifnest, 16),
    ("variables", f_vars, 64),
    ("parameters", f_params, 64),
    ("contribs+nodes", f_contribs, 32),
    ("case-items", f_case, 64),
    ("array-elems", f_array, 32),
    ("laplace-order", f_laplace, 4),
    ("ddt-nesting", f_ddtnest, 2),
    ("function-chain", f_funcchain, 8),
    ("modules-per-file", f_modules, 16),
    ("noise-sources", f_noise, 32),
    ("ddx-count", f_ddx, 16),
    ("macro-expansion", f_macro, 4),
]

LIMIT = 40.0          # per-compile wall


def timed(src):
    p = os.path.join(WORK, "s.va")
    open(p, "w").write(src)
    t0 = time.time()
    try:
        r = subprocess.run([NG, p, "-o", p + ".osdi"], capture_output=True,
                           text=True, timeout=LIMIT, errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    dt = time.time() - t0
    if r.returncode == 101:
        return dt, "PANIC"
    if r.returncode != 0:
        return dt, "diag"
    return dt, "ok"


def main():
    print("%-18s %-34s %s" % ("feature", "N: time(s)", "verdict"))
    bad = []
    for name, fn, n0 in FEATURES:
        pts, n, note = [], n0, ""
        for _ in range(5):
            dt, st = timed(fn(n))
            if st == "HANG":
                note = "HANG at N=%d" % n
                break
            if st == "PANIC":
                note = "PANIC at N=%d" % n
                break
            pts.append((n, dt))
            if dt > LIMIT / 3:
                break
            n *= 2
        desc = " ".join("%d:%.2f" % p for p in pts)
        exps = [ (pts[i + 1][1] / pts[i][1]) for i in range(len(pts) - 1)
                 if pts[i][1] > 0.02 ]
        e = max(exps) if exps else 0.0
        # doubling N: ratio ~2 is linear, ~4 quadratic
        verdict = note or ("superlinear x%.1f/double" % e if e >= 3.0 else "ok")
        if note or e >= 3.0:
            bad.append((name, verdict))
        print("%-18s %-34s %s" % (name, desc[:34], verdict))
    print()
    if bad:
        print("SUPERLINEAR / FAILING:")
        for n, v in bad:
            print("   %-18s %s" % (n, v))
    sys.exit(1 if bad else 0)


main()
