#!/usr/bin/env python3
"""Enhancement-791..795: the smaller slips D1..D5 of the openvaf-r hunt of
2026-10-04 (docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-
instances.md), each pinned end-to-end through the committed openvaf-r (and
ngspice for the run-time cases).

  [1] E-791 (D1): a diagnostic quoted the whole source line it pointed into --
      the depth error on a generated 100 000-term one-line sum was 664 KB. A
      line longer than 240 bytes is now quoted as 60-byte windows around each
      label's start and end, the cuts marked `...`; the location keeps the
      line's real column.
  [2] E-792 (D2): a real constant converted to an `integer` (`ic = 1e20;`, a
      `repeat (1e10)` count) saturated without a word; L030 now says so. And
      the run-time conversion (`ficast`, `$rtoi` too) saturates on every
      platform: it was `llvm.lround.i32.f64`, which x86-64 lowers to libc
      `lround` and keeps the low 32 bits of -- 3e9 ran as -1294967296 there,
      while the folded literal was 2147483647.
  [3] E-793 (D3): `%c` of 0 wrote a NUL into the formatted line and everything
      after it was lost, the line break too (the next line was glued on). And
      `%b` of 0 printed nothing (`__builtin_clz(0)`, undefined).
  [4] E-794 (D4): `from [0:inf]` -- a bracket at an infinite bound -- is lint
      L039 (`inclusive_infinite_bound`), as the CMC's VAMPyRE reports it; allowed
      by default, because standard models' range macros spell it that way and
      it admits the same values as `[0:inf)`.
  [5] E-795 (D5): `` `define include 7 `` redefined a directive name without a
      word (IEEE 1364-2005 19.3.1 makes it illegal); it is an error now.
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
WORK = tempfile.mkdtemp(prefix="vafslips_")
HDR = '`include "disciplines.vams"\n'
H = "module m(p, n); inout p, n; electrical p, n;\n"
T = "analog I(p,n) <+ V(p,n)*1e-3;\nendmodule\n"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag, *flags, hdr=True):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w", encoding="utf-8") as f:
        f.write((HDR if hdr else "") + src)
    r = subprocess.run([VAF, *flags, path, "-o", os.path.join(WORK, f"{tag}.osdi")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, r.stdout + r.stderr


def lines(msg, start):
    return [l for l in msg.splitlines() if l.startswith(start) and "could not compile" not in l
            and "generated" not in l]


def run(deck, ctl, osdi, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* vafslips {tag}\n{deck}\n.control\nset noinit\npre_osdi {osdi}.osdi\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK,
                       errors="replace")
    return p.stdout + p.stderr


def location(msg):
    m = re.search(r"--> .*?:(\d+):(\d+)", msg)
    return (int(m.group(1)), int(m.group(2))) if m else None


def quoted(msg, line_no):
    m = re.search(rf"^{line_no} \| (.*)$", msg, re.M)
    return m.group(1) if m else ""


# ------------------------------------------------------------- [1] ---
# An undefined name at the far end of a 3000-term one-line sum: the label is
# at column 8 + 5*3000 + 1.
terms = "+".join(["V(p,n)"] * 3000)
src = H + f"analog I(p,n) <+ {terms}+nosuch;\nendmodule\n"
ok, msg = compile_src(src, "longend")
col = len("analog I(p,n) <+ ") + len(terms) + 2
q = quoted(msg, 3)
check("[1] an undefined name at the end of a 21 000-byte line: one error, under 2 KB of output",
      not ok and len(lines(msg, "error")) == 1 and "'nosuch' was not found" in msg and len(msg) < 2000,
      f"{len(msg)} bytes")
check("[1] ...the location keeps the line's real column",
      location(msg) == (3, col), f"{location(msg)} expected (3, {col})")
check("[1] ...the quoted line is a window ending at the name, the cut marked `...`",
      q.startswith("...") and q.endswith("+nosuch;") and len(q) < 100, q)
rows = msg.splitlines()
at = next((i for i, l in enumerate(rows) if l.startswith("3 | ")), None)
check("[1] ...the caret sits under the name in the window",
      at is not None and at + 1 < len(rows) and "^^^^^^ not found" in rows[at + 1]
      and rows[at + 1].index("^") == rows[at].index("nosuch"), rows[at + 1] if at is not None else "")
# a name redeclared 3000 bytes after its first declaration, on one line
decls = " ".join(f"real y{i};" for i in range(300))
ok, msg = compile_src(H + f"real x; {decls} real x;\n" + T, "redecl")
q = quoted(msg, 3)
check("[1] two labels 3000 bytes apart on one line: one window each, `...` between, both labels shown",
      not ok and "already declared" in msg and "first declared here" in msg and q.startswith("real x;")
      and "..." in q and q.endswith("real x;") and len(q) < 300 and location(msg) == (3, len(f"real x; {decls} real ") + 1),
      q[:80] + " ... " + q[-40:])
# a line under the limit is quoted whole
short = "+".join(["V(p,n)"] * 30)
ok, msg = compile_src(H + f"analog I(p,n) <+ {short}+nosuch;\nendmodule\n", "short")
check("[1] a 230-byte line is quoted whole, with no `...`",
      not ok and quoted(msg, 3) == f"analog I(p,n) <+ {short}+nosuch;", quoted(msg, 3)[:60])
# multi-byte characters around the cut
ok, msg = compile_src(H + "analog I(p,n) <+ V(p,n) + nosuch; // " + "é" * 400 + "\nendmodule\n", "utf8")
q = quoted(msg, 3)
check("[1] a long comment of two-byte characters after the name: cut on a character boundary",
      not ok and "'nosuch' was not found" in msg and q.startswith("analog I(p,n) <+ V(p,n) + nosuch; // é")
      and q.endswith("...") and "�" not in q, q[:60])

# ------------------------------------------------------------- [2] ---
CASES2 = (
    ("integer i; analog begin i = 1e20; I(p,n) <+ V(p,n)*i*1e-12; end", "100000000000000000000", "2147483647"),
    ("integer i; analog begin i = -3e9; I(p,n) <+ V(p,n)*i*1e-12; end", "-3000000000", "-2147483648"),
    ("integer i; analog begin i = 1e10 * 2; I(p,n) <+ V(p,n)*i*1e-12; end", "20000000000", "2147483647"),
    ("localparam real big = 5e9; integer i; analog begin i = big; I(p,n) <+ V(p,n)*i*1e-12; end", "5000000000", "2147483647"),
    ("integer i; analog begin i = 2147483647.5; I(p,n) <+ V(p,n)*i*1e-12; end", "2147483647.5", "2147483647"),
    ("analog begin repeat (1e10) begin end I(p,n) <+ V(p,n)*1e-3; end", "10000000000", "2147483647"),
)
for k, (body, value, stored) in enumerate(CASES2):
    ok, msg = compile_src(H + body + "\nendmodule\n", f"sat{k}")
    w = lines(msg, "warning")
    check(f"[2] `{body.split('begin ')[1].split(';')[0].strip()}`: L030, the value and what the conversion stores",
          ok and len(w) == 1 and f"warning[L030]: the real {value} does not fit a 32-bit integer" in w[0]
          and f"saturates to {stored}" in msg, "; ".join(w) or msg[:120])
QUIET2 = (
    "integer i; analog begin i = 2147483647.4; I(p,n) <+ V(p,n)*i*1e-12; end",
    "integer i; analog begin i = -2147483648.4; I(p,n) <+ V(p,n)*i*1e-12; end",
    "integer i; analog begin i = 2.5; I(p,n) <+ V(p,n)*i*1e-12; end",
    "parameter real r = 1e20; integer i; analog begin i = r; I(p,n) <+ V(p,n)*i*1e-12; end",
    'integer i; analog begin (* openvaf_allow="lossy_integer_constant" *) i = 1e20; I(p,n) <+ V(p,n)*i*1e-12; end',
)
for k, body in enumerate(QUIET2):
    ok, msg = compile_src(H + body + "\nendmodule\n", f"quiet{k}")
    check(f"[2] no word: `{body.split('begin ')[-1].split(';')[0].strip()[:60]}`"
          + (" (a parameter: run-time)" if "parameter" in body else ""),
          ok and not lines(msg, "warning"), "; ".join(lines(msg, "warning")))
ok, msg = compile_src(H + "integer i; analog begin i = 3000000000; I(p,n) <+ V(p,n)*i*1e-12; end\nendmodule\n", "intlit")
w = lines(msg, "warning")
check("[2] an integer literal wider than 32 bits: E-590's one warning, not a second one for the conversion",
      ok and len(w) == 1 and "integer literal 3000000000 does not fit" in w[0], "; ".join(w))
ok, msg = compile_src(H + "parameter integer k = 3e9;\n" + T, "intparam")
w = lines(msg, "warning")
check("[2] an integer parameter's default: E-590's one warning", ok and len(w) == 1 and "integer parameter 'k'" in w[0],
      "; ".join(w))

# run time: the same values from a model card, through the conversion and $rtoi
ok, msg = compile_src(H + "parameter real v = 0;\ninteger r, t, z, f;\nanalog begin\n"
                      "  r = v; t = $rtoi(v); z = sqrt(-1 - abs(v)); f = 3e9;\n"
                      "  I(p,n) <+ V(p,n)*1e-3;\n"
                      '  if (analysis("static")) $strobe("CONV %m r=%d t=%d z=%d f=%d", r, t, z, f);\n'
                      "end\nendmodule\n", "conv")
check("[2] the run-time conversion model compiles", ok, "; ".join(lines(msg, "error")))
if ok:
    VALS = (("3e9", 2147483647, 2147483647), ("-3e9", -2147483648, -2147483648), ("1e20", 2147483647, 2147483647),
            ("-1e20", -2147483648, -2147483648), ("2147483647.5", 2147483647, 2147483647),
            ("-2147483648.4", -2147483648, -2147483648), ("2.5", 3, 2), ("-2.5", -3, -2))
    deck = "".join(f"n{k} a 0 mm{k}\n.model mm{k} m v={v}\n" for k, (v, _, _) in enumerate(VALS)) + "v1 a 0 1"
    out = run(deck, "op", "conv", "conv")
    got = {int(a): (int(b), int(c), int(d), int(e)) for a, b, c, d, e in
           re.findall(r"CONV n(\d+) r=(-?\d+) t=(-?\d+) z=(-?\d+) f=(-?\d+)", out)}
    for k, (v, r, t) in enumerate(VALS):
        check(f"[2] run time v={v}: the conversion gives {r}, $rtoi {t} (the same on every platform)",
              got.get(k, (None, None))[:2] == (r, t), f"got {got.get(k)}")
    check("[2] run time: a NaN converts to 0, and the folded `3e9` agrees with the run-time 3e9",
          got and all(g[2] == 0 for g in got.values()) and got.get(0, (0, 0, 0, 0))[3] == got.get(0, (0,))[0] == 2147483647,
          f"{sorted(got.items())[:2]}")

# ------------------------------------------------------------- [3] ---
F = (('[%c]', '0', '[]'), ('[%c|tail %d]', '0, 7', '[|tail 7]'), ('[%c%c%c]', '72, 0, 73', '[HI]'),
     ('[%c]', '65', '[A]'), ('[%3c]', '66', '[  B]'), ('[%-3c]', '67', '[C  ]'), ('[%c]', '321', '[A]'),
     ('[%c]', '256', '[]'), ('[%b]', '0', '[0]'), ('[%b]', '5', '[101]'),
     ('[%b]', '-1', '[' + '1' * 32 + ']'), ('[%0b]', '0', '[0]'))
body = "\n".join(f'  $strobe("P{i}{f}", {a});' for i, (f, a, _) in enumerate(F))
body += '\n  $sformat(s, "S[%c]after", 0); $strobe("P99%s", s);'
ok, msg = compile_src(H + "string s;\nanalog begin\nif (analysis(\"static\")) begin\n" + body +
                      "\nend\nI(p,n) <+ V(p,n)*1e-3;\nend\nendmodule\n", "fmt")
check("[3] the format model compiles", ok, "; ".join(lines(msg, "error")))
if ok:
    out = run("n1 a 0 mm\n.model mm m\nv1 a 0 1", "op", "fmt", "fmt")
    got = {}
    for l in out.splitlines():
        m = re.match(r"OSDI n1: P(\d+)(.*)$", l)
        if m:
            got[int(m.group(1))] = m.group(2)
    for i, (f, a, e) in enumerate(F):
        check(f"[3] `$strobe(\"{f}\", {a})` prints {e}" + (" on a line of its own" if a.startswith("0") else ""),
              got.get(i) == e, repr(got.get(i)))
    check("[3] `$sformat` with `%c` of 0 keeps the rest of the string", got.get(99) == "S[]after", repr(got.get(99)))
    check("[3] no line carries two outputs (a NUL used to eat the line break)",
          not re.search(r"OSDI n1: P\d+.*P\d+", out), "")

# ------------------------------------------------------------- [4] ---
# L039 is allowed by default: the spelling is all through standard models
# (PSP103's `MPRcc(..., inf, ...)` expands to `from [lower:inf]`) and admits the
# same values; `-W inclusive_infinite_bound` asks for it.
W39 = ("-W", "inclusive_infinite_bound")
ok, msg = compile_src(H + "parameter real r = 1 from [0:inf];\n" + T, "infdefault")
check("[4] `from [0:inf]` by default: compiles without a word (L039 is allowed by default)",
      ok and not lines(msg, "warning"), "; ".join(lines(msg, "warning")))
CASES4 = (
    ("parameter real r = 1 from [0:inf];", ["the `from` range of parameter 'r' closes the infinite bound inf with `]`"]),
    ("parameter real r = -1 from [-inf:0];", ["the `from` range of parameter 'r' closes the infinite bound -inf with `[`"]),
    ("parameter real r = 1 from [-inf:inf];", ["bound -inf with `[`", "bound inf with `]`"]),
    ("parameter integer r = 1 from [1:inf];", ["parameter 'r' closes the infinite bound inf with `]`"]),
    ("parameter real r = 1 from [0:inf) exclude [5:inf];", ["the `exclude` range of parameter 'r' closes the infinite bound inf"]),
    ("parameter real m = 1.0 from(0.0:inf];", ["parameter 'm' closes the infinite bound inf with `]`"]),
)
for k, (decl, want) in enumerate(CASES4):
    ok, msg = compile_src(H + decl + "\n" + T, f"inf{k}", *W39)
    w = [x for x in lines(msg, "warning") if "[L029]" not in x]  # `m` is ngspice's multiplier
    check(f"[4] -W: `{decl}`: L039 x{len(want)}, pointing at the bound",
          ok and len(w) == len(want) and all(x.startswith("warning[L039]") for x in w)
          and all(any(s in x for x in w) for s in want) and "write `" in msg, "; ".join(w))
for k, decl in enumerate(("parameter real r = 1 from [0:inf);", "parameter real r = 1 from (-inf:inf);",
                          "parameter real r = 1 from [0:1e300];",
                          '(* openvaf_allow="inclusive_infinite_bound" *) parameter real r = 1 from [0:inf];')):
    ok, msg = compile_src(H + decl + "\n" + T, f"infok{k}", *W39)
    check(f"[4] -W, no word: `{decl}`", ok and not lines(msg, "warning"), "; ".join(lines(msg, "warning")))
ok, msg = compile_src(H + "parameter real r = 1 from [0:inf];\n" + T, "infdeny", "-E", "inclusive_infinite_bound")
check("[4] `-E inclusive_infinite_bound` makes it an error (VAMPyRE's verdict)",
      not ok and any(l.startswith("error[L039]") for l in lines(msg, "error")), "; ".join(lines(msg, "error")))

# ------------------------------------------------------------- [5] ---
for name in ("include", "define", "ifdef", "timescale", "resetall", "begin_keywords", "default_discipline"):
    ok, msg = compile_src(f"`define {name} 7\n" + H + T, f"dir_{name}")
    e = lines(msg, "error")
    check(f"[5] `` `define {name} 7 ``: one error naming the directive and the IEEE 1364 rule",
          not ok and len(e) == 1 and f"'`{name}' is a compiler directive and cannot be defined as a macro" in e[0]
          and "19.3.1" in msg, "; ".join(e))
ok, msg = compile_src(H + T, "dir_cli", "-D", "include=1")
check("[5] `-D include=1` on the command line: the same error",
      not ok and "'`include' is a compiler directive" in msg, "; ".join(lines(msg, "error")))
ok, msg = compile_src("`define includes 1\n`define include_path 2\n" + H + "parameter real r = `includes + `include_path;\n" + T, "dir_ok")
check("[5] `includes` and `include_path` are ordinary macro names", ok and not lines(msg, "error"),
      "; ".join(lines(msg, "error")))
ok, msg = compile_src("`define __LINE__ 1\n" + H + T, "dir_line")
check("[5] `` `define __LINE__ `` keeps its warning (reserved predefined macro), not the new error",
      ok and "macro name '__LINE__' is reserved" in msg, "; ".join(lines(msg, "warning")))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
