#!/usr/bin/env python3
"""Enhancement-442: `listing tree` -- the subcircuit hierarchy, drawn.

`listing e` answers "what is actually simulated": a flat wall of `r.x1.x3.r[0]`
lines, one per device, with the structure only implicit in the dotted names. On
a design with more than a couple of levels the structure is what you want first,
and reconstructing it by eye from flattened names does not scale.

    two-stage amp
    +- vdd
    +- vin
    +- x1 : amp
    |  +- xd : diffpair
    |  |  +- m1
    |  |  ...
    |  +- xg : gainstage
    |  |  +- m3
    |  |  `- rd
    |  `- cc
    `- rl

    3 subcircuit instances, 11 devices, 3 levels deep

The walk is over `ci_origdeck` -- the deck as read, with `.subckt` blocks still
intact -- because the expanded deck no longer knows which subcircuit each
instance came from. Array instances (Enhancement-441) are already expanded
there, so `X[0:2]` shows as three instances, which is what the design contains.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lt_"):
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


def run(body, tag, cmd="listing tree", analysis="op", timeout=120):
    """`analysis` is appended so the deck actually simulates -- without one
    ngspice exits 1 with "no simulations run", which says nothing about the
    listing itself. Pass "" for a deck that has no devices to analyse."""
    tail = f"{analysis}\n" if analysis else ""
    deck = f"{tag}\n{body}\n.control\noption noacct\n{cmd}\n{tail}.endc\n.end\n"
    p = os.path.join(HERE, f"_lt_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    out = r.stdout + r.stderr
    # the tree starts at the echoed title line and runs to the summary
    lines = out.splitlines()
    try:
        i = next(k for k, ln in enumerate(lines)
                 if ln.strip() == tag and k > 0)
    except StopIteration:
        return r.returncode, out, []
    tree = []
    for ln in lines[i + 1:]:
        if re.match(r"^[+`| ]", ln) and ln.strip():
            tree.append(ln.rstrip())
        elif tree:
            break
    return r.returncode, out, tree


def summary(out):
    m = re.search(r"(\d+) subcircuit instances?, (\d+) devices?, "
                  r"(\d+) levels? deep", out)
    return tuple(int(g) for g in m.groups()) if m else None


print("Enhancement-442: listing tree\n")

# ------------------------------------------------------------------- shape ---
print("the tree of a two-level hierarchy")
TWO = ("V1 in 0 dc 1\nRs in a 1k\nX1 a 0 stage\nX2 a 0 stage\n"
       ".subckt stage p n\nRin p m 2k\nX3 m n leaf\n.ends\n"
       ".subckt leaf p n\nR1 p n 4k\nC1 p n 1n\n.ends")
rc, out, tree = run(TWO, "hier")
check("[E-442] the command runs", rc == 0, f"rc={rc}")
check("[E-442] each X instance is labelled with its subcircuit",
      any(ln.endswith("x1 : stage") for ln in tree)
      and any(ln.endswith("x3 : leaf") for ln in tree), f"{tree[:4]}")
check("[E-442] children are indented under their parent",
      any(re.match(r"^\|  [+`]- rin$", ln) for ln in tree), f"{tree}")
check("[E-442] a grandchild is indented twice",
      any(re.match(r"^\|  \|  [+`]- (r1|c1)$", ln) for ln in tree)
      or any(re.match(r"^\|     [+`]- (r1|c1)$", ln) for ln in tree), f"{tree}")
# the LAST child of a level uses the corner and its subtree drops the bar --
# getting this wrong is the classic tree-drawing bug and is invisible in a
# one-level deck
check("[E-442] the last child uses a corner, not a tee",
      any(ln.startswith("`- x2 : stage") for ln in tree), f"{tree}")
check("[E-442] ...and its subtree is indented with blanks, not a bar",
      any(re.match(r"^   [+`]- rin$", ln) for ln in tree), f"{tree}")

print("\nthe summary counts what the design contains")
s = summary(out)
# instances: x1, x2 and the x3 inside each stage = 4
# devices:   v1, rs at the top, then per stage rin + (r1, c1) in its leaf,
#            so 2 + 2*3 = 8
check("[E-442] instances, devices and depth are all counted",
      s == (4, 8, 3), f"{s} want (4, 8, 3)")

# ------------------------------------------------------------------- flat ----
print("\na flat deck is a flat tree")
rc, out, tree = run("V1 in 0 dc 1\nR1 in a 1k\nR2 a 0 1k", "flat")
check("[E-442] every device hangs off the title",
      len(tree) == 3 and tree[-1].startswith("`- r2"), f"{tree}")
check("[E-442] and the summary says one level, no instances",
      summary(out) == (0, 3, 1), f"{summary(out)}")

# --------------------------------------------------------------- E-441 tie ---
print("\narray instances (Enhancement-441) appear as the instances they are")
rc, out, tree = run("V1 in 0 dc 1\nRs in a 250\nX[0:2] a 0 sub\n"
                    ".subckt sub p n\nR1 p n 1k\n.ends", "arrayed")
check("[E-442] X[0:2] shows as three separate instances",
      sum(1 for ln in tree if re.search(r"x\[\d\] : sub$", ln)) == 3, f"{tree}")
check("[E-442] each with its own child",
      sum(1 for ln in tree if ln.strip().endswith("- r1")) == 3, f"{tree}")
check("[E-442] counted as three instances, five devices",
      summary(out) == (3, 5, 2), f"{summary(out)}")

# ------------------------------------------------------------------ params ---
print("\nthe subcircuit name is found even after numparam rewrites the card")
# `X1 in 0 sub PARAMS: rv=2k` reaches this pass as `x1 in 0 sub 2k` -- the
# marker is gone and the tail looks like an ordinary node, so "the last token
# before the parameters" picks `2k`. Resolving against the collected
# definitions is what makes this right.
rc, out, tree = run("V1 in 0 dc 1\nX1 in 0 sub PARAMS: rv=2k\n"
                    ".subckt sub p n params: rv=1k\nR1 p n {rv}\n.ends", "params")
check("[E-442] a parameterised instance still names its subcircuit",
      any(ln.endswith("x1 : sub") for ln in tree), f"{tree}")

# ------------------------------------------------------------------- depth ---
print("\ndepth")
deep = ["V1 in 0 dc 1", "X1 in 0 s1"]
for i in range(1, 8):
    deep += [f".subckt s{i} p n", f"Rl{i} p m{i} 100",
             f"X{i+1} m{i} n s{i+1}", ".ends"]
deep += [".subckt s8 p n", "Rend p n 1k", ".ends"]
rc, out, tree = run("\n".join(deep), "deep")
check("[E-442] eight levels nest without losing alignment",
      summary(out) == (8, 9, 9), f"{summary(out)}")
check("[E-442] the deepest device is indented once per level",
      any(ln.endswith("- rend") and len(ln) - len(ln.lstrip(" |")) >= 20
          for ln in tree), f"{[ln for ln in tree if 'rend' in ln]}")

# ------------------------------------------------------------------ hygiene --
print("\nwhat must NOT appear in the tree")
# a .control block's commands begin with a letter and were counted as devices
rc, out, tree = run("V1 in 0 dc 1\nR1 in 0 1k", "ctrl",
                    cmd="option noacct\nlisting tree\nop")
check("[E-442] .control commands are not mistaken for devices",
      not any(re.search(r"- (option|listing|op)$", ln) for ln in tree),
      f"{tree}")
check("[E-442] ...and are not counted", summary(out) == (0, 2, 1),
      f"{summary(out)}")
rc, out, tree = run("V1 in 0 dc 1\nR1 in 0 1k\n.model nm nmos(level=1)\n"
                    ".param q=1", "dots")
check("[E-442] dot cards are not devices", summary(out) == (0, 2, 1),
      f"{summary(out)}")

# ---------------------------------------------------------------- controls ---
print("\nCONTROLS -- the other listing forms are untouched")
rc, out, _ = run(TWO, "lp", cmd="listing p")
check("[E-442] listing p still shows the source with .subckt intact",
      rc == 0 and ".subckt stage" in out and "x1 a 0 stage" in out, f"rc={rc}")
rc, out, _ = run(TWO, "le", cmd="listing e")
check("[E-442] listing e still shows the flattened deck",
      rc == 0 and "r.x1.x3.r1" in out.replace(" ", " "), f"rc={rc}")
rc, out, _ = run(TWO, "lbad", cmd="listing zzz")
check("[E-442] an unknown listing type is still rejected",
      "bad listing type" in out, "")
# `listing t` is accepted like l/p/d/e/r
rc, out, tree = run(TWO, "lt", cmd="listing t")
check("[E-442] the single-letter form `listing t` works too",
      any(ln.endswith("x1 : stage") for ln in tree), f"{tree[:3]}")

# A deck with nothing in it has nothing to analyse, so ngspice exits 1 with
# "no simulations run" -- that is the DECK's verdict, not the listing's. What
# matters here is that the tree walk survives an empty deck and still reports.
rc, out, tree = run("", "bare", analysis="")
check("[E-442] a deck with no elements is handled, not crashed",
      rc is not None and rc >= 0 and rc < 128 and summary(out) == (0, 0, 1),
      f"rc={rc} {summary(out)}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
