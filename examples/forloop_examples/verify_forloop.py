#!/usr/bin/env python3
"""Enhancement-474: `.for` / `.endfor`, a netlist-level repetition construct.

A deck often needs a run of near-identical instance lines differing only by an
index -- a ladder, a stack of periodic sections, a bank of taps. Written out by
hand they are long, and wrong in ways that are hard to see: one node name out of
step in the middle of forty lines still parses and still simulates.

    .for i in range(1,4)
    XP{{i}} P{{i}} P{{i+1}} hl_periodic n1={nL}
    .endfor

expands to exactly

    XP1 P1 P2 hl_periodic n1={nL}
    XP2 P2 P3 hl_periodic n1={nL}
    XP3 P3 P4 hl_periodic n1={nL}
    XP4 P4 P5 hl_periodic n1={nL}

THE ORACLE THROUGHOUT IS THE HAND-WRITTEN DECK. Every check below runs the
`.for` deck and the lines it is meant to stand for, and requires the two to
agree -- not to a tolerance, but character for character on the printed result.
A construct that expands to *something plausible* is the failure mode worth
guarding against, and comparing against an analytic value would not catch a
ladder wired one node out of step.

`range(a,b)` INCLUDES BOTH BOUNDS, which is not Python's rule. That is
deliberate -- an index range in a netlist reads as "1 through 4" -- and check
[2] is there to pin it, because it is the one thing about this construct a
Python-literate user will assume wrongly.

`{{ }}` rather than `{ }` because numparam owns single braces: the body above
carries both, and this pass removes every `{{ }}` before numparam runs.
"""
import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_fl_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(deck, tag):
    p = os.path.join(HERE, f"_fl_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return r.stdout + r.stderr


def listing(body, tag):
    """the deck as ngspice sees it after expansion, element lines only.

    The title is a constant, not the tag: two decks that must compare equal
    have to differ in nothing but the construct under test."""
    out = run(f"forloop deck\n{body}.control\nlisting\n.endc\n.end\n", tag)
    return [re.sub(r"^\s*\d+ : ", "", l)
            for l in out.splitlines() if re.match(r"^\s*\d+ : ", l)
            and not re.match(r"^\s*\d+ : [.*]", l)]


def values(body, ctl, tag):
    out = run(f"forloop deck\n{body}.control\noption noacct\nset numdgt=12\n"
              f"{ctl}\n.endc\n.end\n", tag)
    # only the printed vectors -- `Doing analysis at TEMP = 27.000000` also has
    # an `=` and would otherwise be read as the first result
    return re.findall(r"^\s*\S*[vi]\([^)]*\)\s*=\s*(-?[\d.]+e?[-+]?\d*)",
                      out, re.M | re.I)


def errors(body, tag):
    out = run(f"forloop {tag}\nV1 0 0 dc 0\n{body}.end\n", tag)
    return [l for l in out.splitlines() if l.startswith("Error:")
            and "incomplete or empty netlist" not in l]


print("Enhancement-474: .for / .endfor\n")

# ---------------------------------------------------------- the example ------
print("the construct expands to exactly the lines it stands for")

SUB = (".subckt hl_periodic a b n1=1\nRs a b {1k*n1}\n.ends\n")
FOR = (".param nL=1.5\nV1 P1 0 dc 1\n"
       ".for i in range(1,4)\n"
       "XP{{i}} P{{i}} P{{i+1}} hl_periodic n1={nL}\n"
       ".endfor\nR5 P5 0 1k\n" + SUB)
HAND = (".param nL=1.5\nV1 P1 0 dc 1\n"
        "XP1 P1 P2 hl_periodic n1={nL}\n"
        "XP2 P2 P3 hl_periodic n1={nL}\n"
        "XP3 P3 P4 hl_periodic n1={nL}\n"
        "XP4 P4 P5 hl_periodic n1={nL}\n"
        "R5 P5 0 1k\n" + SUB)

lf, lh = listing(FOR, "ex1"), listing(HAND, "ex1h")
check("[0] the expansion is line-for-line the hand-written deck",
      lf == lh and len(lf) > 4, f"{len(lf)} vs {len(lh)} lines")
xs = [l for l in lf if l.startswith("xp")]
check("[1] ...which is the four instances from the example",
      xs == ["xp1 p1 p2 hl_periodic {nl}", "xp2 p2 p3 hl_periodic {nl}",
             "xp3 p3 p4 hl_periodic {nl}", "xp4 p4 p5 hl_periodic {nl}"],
      f"{xs}")

# range(1,4) must give FOUR values, not Python's three
check("[2] range(a,b) includes BOTH bounds -- four sections, not three",
      len(xs) == 4, f"{len(xs)}")

LIST = FOR.replace("range(1,4)", "[1,2,3,4]")
check("[3] the list form `[1,2,3,4]` gives the identical deck",
      listing(LIST, "ex1l") == lh, "")

# and the circuit it builds is the one that was meant: four 1.5k sections in
# series with a 1k load, so v(P5) = 1/7 -- a node out of step would not give it
vf = values(FOR, "op\nprint v(P5)", "v1")
vh = values(HAND, "op\nprint v(P5)", "v1h")
check("[4] the circuit solves identically to the hand-written one",
      vf == vh and vf and abs(float(vf[0]) - 1.0 / 7.0) < 1e-9, f"{vf} vs {vh}")

# ------------------------------------------------------------- the forms -----
print("\nthe forms of the value list")

for tag, spec, want in (("step", "range(0,10,5)", ["0", "5", "10"]),
                        ("down", "range(3,1)", ["3", "2", "1"]),
                        ("list", "[7,2,9]", ["7", "2", "9"]),
                        ("one", "range(4,4)", ["4"])):
    got = [re.match(r"r(\S+)", l).group(1)
           for l in listing(f"V1 0 0 dc 0\n.for k in {spec}\n"
                            f"R{{{{k}}}} x{{{{k}}}} 0 1k\n.endfor\n", "f" + tag)
           if l.startswith("r")]
    check(f"[5-{tag}] `{spec}` yields {want}", got == want, f"{got}")

# an index expression, not just the index
got = listing("V1 0 0 dc 0\n.for i in range(1,3)\n"
              "R{{i}} n{{i-1}} n{{2*i}} {{i*100}}\n.endfor\n", "expr")
check("[6] {{i-1}}, {{2*i}} and {{i*100}} are evaluated",
      [l for l in got if l.startswith("r")] ==
      ["r1 n0 n2 100", "r2 n1 n4 200", "r3 n2 n6 300"],
      f"{[l for l in got if l.startswith('r')]}")

# ---------------------------------------------------------------- nesting ----
print("\nnesting")
got = [l for l in listing("V1 0 0 dc 0\n.for i in range(1,2)\n"
                          ".for j in range(1,3)\n"
                          "R{{i}}_{{j}} n{{i}} n{{j}} {{i*10+j}}k\n"
                          ".endfor\n.endfor\n", "nest") if l.startswith("r")]
check("[7] a nested loop expands to the full product, with {{i*10+j}} resolved",
      got == ["r1_1 n1 n1 11k", "r1_2 n1 n2 12k", "r1_3 n1 n3 13k",
              "r2_1 n2 n1 21k", "r2_2 n2 n2 22k", "r2_3 n2 n3 23k"], f"{got}")

# an inner bound written in terms of the outer index
got = [l for l in listing("V1 0 0 dc 0\n.for i in range(1,3)\n"
                          ".for j in range(1,{{i}})\n"
                          "R{{i}}_{{j}} a 0 1k\n.endfor\n.endfor\n", "nestb")
       if l.startswith("r")]
check("[8] an inner range bound may be an expression over the outer index",
      got == ["r1_1 a 0 1k", "r2_1 a 0 1k", "r2_2 a 0 1k",
              "r3_1 a 0 1k", "r3_2 a 0 1k", "r3_3 a 0 1k"], f"{got}")

# ------------------------------------------------------------ where it runs --
print("\nwhere it runs, and what it leaves alone")

SUBFOR = ("V1 in 0 dc 1\nX1 in out ladder\nR9 out 0 1k\n"
          ".subckt ladder a b\nRin a n0 1\n"
          ".for i in range(1,3)\nR{{i}} n{{i-1}} n{{i}} 1k\n.endfor\n"
          "Rout n3 b 1\n.ends\n")
SUBHAND = SUBFOR.replace(".for i in range(1,3)\nR{{i}} n{{i-1}} n{{i}} 1k\n"
                         ".endfor\n",
                         "R1 n0 n1 1k\nR2 n1 n2 1k\nR3 n2 n3 1k\n")
_sf = values(SUBFOR, "op\nprint v(out)", "sf")
_sh = values(SUBHAND, "op\nprint v(out)", "sh")
check("[9] a .for inside a .subckt body expands there",
      _sf == _sh != [], f"{_sf} vs {_sh}")

# a `.control` block has its own `foreach`; this construct must not touch it
out = run("forloop ctl\nV1 a 0 dc 1\nR1 a 0 1k\n.control\noption noacct\n"
          "foreach v 1 2\n  echo saw $v\nend\n.endc\n.end\n", "ctl")
check("[10] a .control `foreach` is left alone",
      out.count("saw 1") == 1 and out.count("saw 2") == 1, "")

# numparam's single braces must survive alongside {{ }}
check("[11] `{nL}` passes through untouched beside `{{i}}`",
      all("{nl}" in l for l in xs), f"{xs[:1]}")

# `.include`/`.lib` are resolved before this pass runs, so a loop works in an
# included file -- which is where a repeated structure often lives
inc = os.path.join(HERE, "_fl_inc.sp")
with open(inc, "w") as f:
    f.write(".for i in range(1,3)\nRi{{i}} m{{i-1}} m{{i}} 1k\n.endfor\n")
vi = values("V1 m0 0 dc 1\n.include _fl_inc.sp\nRl m3 0 1k\n",
            "op\nprint v(m3)", "inc")
check("[11b] a .for inside an .include'd file expands too",
      vi and abs(float(vi[0]) - 0.25) < 1e-12, f"{vi}")

# ------------------------------------------------------------------ scale ----
print("\nscale")
N = 2000
big_for = (f"V1 n0 0 dc 1\n.for i in range(1,{N})\n"
           "R{{i}} n{{i-1}} n{{i}} 1k\n.endfor\n" + f"Rl n{N} 0 1k\n")
big_hand = ("V1 n0 0 dc 1\n"
            + "".join(f"R{i} n{i-1} n{i} 1k\n" for i in range(1, N + 1))
            + f"Rl n{N} 0 1k\n")
bf = values(big_for, f"op\nprint v(n{N})", "bigf")
bh = values(big_hand, f"op\nprint v(n{N})", "bigh")
check(f"[12] a {N}-section ladder matches the hand-written deck exactly",
      bf == bh and bf and abs(float(bf[0]) - 1000.0 / ((N + 1) * 1000.0)) < 1e-12,
      f"{bf} vs {bh}")

# ----------------------------------------------------------------- refusal ---
# Every one of these is a deck that must not simulate, and each must produce
# exactly ONE message: a second complaint about a line that is itself correct
# points the user away from the mistake.
print("\nevery malformed loop is refused, with one message")

CASES = [
    ("no .endfor",        ".for i in range(1,3)\nR{{i}} a 0 1k\n",
     "no matching .endfor"),
    ("orphan .endfor",    ".endfor\n", "without a matching .for"),
    ("step the wrong way", ".for i in range(1,5,-1)\nR{{i}} a 0 1k\n.endfor\n",
     "covers no values"),
    ("zero step",         ".for i in range(1,5,0)\nR{{i}} a 0 1k\n.endfor\n",
     "step is zero"),
    ("non-literal bound", ".param n=4\n.for i in range(1,{n})\nR{{i}} a 0 1k\n"
                          ".endfor\n", "not a whole number"),
    ("empty list",        ".for i in []\nR{{i}} a 0 1k\n.endfor\n",
     "list is empty"),
    ("unclosed {{",       ".for i in range(1,2)\nR{{i a 0 1k\n.endfor\n",
     "without a closing"),
    ("{{ }} with no .for", "R{{i}} a 0 1k\n", "outside any .for"),
    ("no `in`",           ".for i range(1,3)\nR{{i}} a 0 1k\n.endfor\n",
     "expected `in`"),
    ("no variable",       ".for in range(1,3)\nR{{i}} a 0 1k\n.endfor\n",
     "loop variable name before `in`"),
    ("trailing junk",     ".for i in range(1,3) junk\nR{{i}} a 0 1k\n.endfor\n",
     "trailing text"),
    ("unclosed range(",   ".for i in range(1,3\nR{{i}} a 0 1k\n.endfor\n",
     "never closed"),
    ("unclosed list",     ".for i in [1,2\nR{{i}} a 0 1k\n.endfor\n",
     "never closed"),
    ("too many iterations", ".for i in range(1,3000000)\nR{{i}} a 0 1k\n"
                            ".endfor\n", "more than"),
]
for n, (label, body, want) in enumerate(CASES):
    errs = errors(body, f"e{n}")
    check(f"[{13+n}] {label} is refused, once",
          len(errs) == 1 and want in errs[0],
          f"{len(errs)}: {errs[0][:70] if errs else 'none'}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
