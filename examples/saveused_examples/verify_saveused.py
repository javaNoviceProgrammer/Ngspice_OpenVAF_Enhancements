#!/usr/bin/env python3
"""Enhancement-469: `.option saveused` -- keep only what the control block reads.

A sweep or a long transient stores every node at every point. On a circuit with
a few thousand unknowns that dominates the run: the deck this was written for
costs 521 ms per sweep point with everything stored and 30 ms with a
hand-written `save` of the four vectors it actually writes -- a factor of 17,
from one line the author has to remember and to keep in step with the `wrdata`
beside it.

With the option on, the control block is read before it runs and every vector
it mentions is saved; nothing else is.

WHAT IS COLLECTED is deliberately wider than the letter of the request.
Scanning only the arguments of `wrdata`/`plot`/`pyplot` would miss

    let r = v(out) - v(mid)
    wrdata f r

-- `r` is not a node, and the two vectors that build it would go unsaved, so a
deck that worked before would fail. Under-saving turns a performance option
into a correctness bug. So every `v(...)`, `i(...)` and `@dev[param]` reference
anywhere in the block is taken, whatever command it belongs to, plus the plain
node names given to output commands.

WHEN IT STANDS ASIDE, leaving the run exactly as it would have been: an
explicit `save`/`.save` (the author has already said what they want), `all` as
an argument (which asks for everything), and a control block with no output
command at all.

The observable used throughout is the set of node/branch vectors in the
resulting plot, read with `display`: unrestricted it is
{in, mid, out, v1#branch}, and a restricted run holds only what was asked for.
Names are compared rather than counted, so a check cannot pass on the right
number of the wrong vectors.
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
        if junk.startswith("_su_"):
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


CIRCUIT = ("V1 in 0 dc 1\nR1 in mid 1k\nR2 mid out 1k\nRl out 0 1k\n")


def run(opts, body, tag, pre=""):
    deck = (f"saveused {tag}\n{CIRCUIT}{opts}\n.control\noption noacct\n"
            f"set numdgt=8\n{pre}dc V1 0 1 0.5\n{body}\ndisplay\n.endc\n.end\n")
    p = os.path.join(HERE, f"_su_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=120, errors="replace")
    return r.stdout + r.stderr


ALL = ["in", "mid", "out", "v1#branch"]


def kept(out):
    """the node/branch vectors present in the resulting plot"""
    rows = re.findall(r"^\s+([A-Za-z0-9()#_\[\]]+)\s+:\s+(?:voltage|current)",
                      out, re.M)
    return len(rows), sorted(set(rows))


WR = "wrdata _su_out.txt v(out)"

print("Enhancement-469: .option saveused\n")

# ---------------------------------------------------------------- baseline ---
print("the baseline: everything is stored")
n, names = kept(run("", WR, "base"))
check("[1] with no option, the whole circuit is stored", names == ALL, f"{names}")

# ------------------------------------------------------------------- basic ---
print("\nwith the option on, only what the block reads")
n, names = kept(run(".option saveused", WR, "one"))
check("[2] `wrdata ... v(out)` keeps v(out) alone", names == ["out"], f"{names}")
n, names = kept(run(".option saveused", "wrdata _su_out.txt v(out) v(mid)", "two"))
check("[2] two vectors keep both", names == ["mid", "out"], f"{names}")
n, names = kept(run(".option saveused", "print v(out) > _su_p.txt", "print"))
check("[2] `print` counts as an output command too", names == ["out"], f"{names}")
n, names = kept(run(".option saveused", "wrdata _su_out.txt out", "bare"))
check("[2] a bare node name is understood as well as v(...)",
      names == ["out"], f"{names}")
n, names = kept(run(".option saveused",
                    "wrdata _su_out.txt v(out)\n"
                    "meas dc m FIND v(mid) WHEN v(out)=0.3", "meas"))
check("[2] `meas` contributes the vectors it reads",
      names == ["mid", "out"], f"{names}")

# ------------------------------------------------------- the correctness bit ---
print("\nthe dependency that makes naive scanning wrong")
n, names = kept(run(".option saveused",
                    "let r = v(out) - v(mid)\nwrdata _su_out.txt r", "let"))
check("[3] a `let` right-hand side is kept, though only `r` is written",
      names == ["mid", "out"], f"{names}")
out = run(".option saveused", "let r = v(out) - v(mid)\nwrdata _su_out.txt r", "letok")
check("[3] ...so the deck still runs, with no missing-vector complaint",
      "not available" not in out and "Error" not in out, "")

# --------------------------------------------------------- standing aside ---
print("\nwhen it must stand aside")
n, names = kept(run(".option saveused", "wrdata _su_out.txt all", "all"))
check("[4] `all` asks for everything, so nothing is restricted", names == ALL,
      f"{names}")
n, names = kept(run(".option saveused", "*no output command here", "noout"))
check("[4] a block with no output command is left alone", names == ALL, f"{names}")
n_on, names_on = kept(run(".option saveused", WR, "savon", pre="save v(mid)\n"))
n_off, names_off = kept(run("", WR, "savoff", pre="save v(mid)\n"))
check("[4] an explicit `save` wins, and saveused changes nothing",
      n_on == n_off and names_on == names_off and names_on == ["mid"],
      f"on={n_on}:{names_on} off={n_off}:{names_off}")
n, names = kept(run(".save v(mid)\n.option saveused", WR, "savecard"))
check("[4] ...and so does a `.save` card", names == ["mid"], f"{names}")

# ------------------------------------------------- a knob is not an output ---
print("\na wildcard accessor is a KNOB, not a vector to save")
o = run(".option saveused",
        "alter @#*[resistance]=1.5k\n" + WR, "wild")
check("[4] a wildcard accessor draws no 'stays empty' warning",
      "wildcard device name" not in o, "")
n, names = kept(o)
check("[4] ...and the block's real vector is still the only one kept",
      names == ["out"], f"{names}")
o = run(".option saveused",
        "alter @r1[resistance]=1.5k\n" + WR, "named")
check("[4] a NAMED accessor is still collected -- it is saveable",
      "wildcard device name" not in o and "out" in names, "")

# ------------------------------------------------------------- spellings ---
print("\nevery spelling of the option, on and off")
for spell, want_on in ((".option saveused", True), (".option saveused=1", True),
                       (".option saveused=true", True), (".option saveused=yes", True),
                       (".option saveused=on", True), (".option saveused=0", False),
                       (".option saveused=false", False), (".option saveused=no", False),
                       (".option saveused=off", False), (".option nosaveused", False)):
    n, names = kept(run(spell, WR, "sp" + re.sub(r"\W", "", spell)))
    ok = (names == ["out"]) if want_on else (names == ALL)
    check(f"[5] `{spell}` means {'ON' if want_on else 'off'}", ok, f"{names}")

out = run(".option saveused", WR, "noopt")
check("[5] the option name is registered, so no 'unknown option' warning",
      "unknown option" not in out, "")

# ---------------------------------------------------------------- F1, F2 ----
# Two under-saves found by a bug hunt (docs/bug_hunts/). Both are the failure
# this feature's own source comment calls out: "under-saving turns a
# performance option into a correctness bug".
print("\nan implicit-all `write`, and bare node names in an expression")

# F1: `write file.raw` with no vector arguments means EVERYTHING. saveused stood
# aside on an explicit `all` but not on this spelling, so a stray `print`
# elsewhere in the block pruned the raw file to whatever that print named.
out = run(".option saveused", "print v(out)\nwrite _su_f1.raw", "f1")
n, names = kept(out)
check("[F1] a `print` beside an implicit-all `write` does not prune it",
      names == ALL, f"{names}")
out = run(".option saveused", "write _su_f1b.raw", "f1b")
check("[F1] ...and a bare `write` alone is still everything",
      kept(out)[1] == ALL, f"{kept(out)[1]}")
# the option must still restrict when the block really does name its vectors
out = run(".option saveused", WR, "f1c")
check("[F1] ...while a block that names its vectors is still restricted",
      kept(out)[1] == ["out"], f"{kept(out)[1]}")

# F2: ngspice stores a node voltage as a vector named after the node, so
# `let y = mid + out` reads two of them by their plain names. `gettok` glues
# `y = mid` into one token, so the operator test skipped the name inside it.
out = run(".option saveused", "let y = mid + out\nprint y", "f2")
check("[F2] bare node names inside a `let` are saved",
      "not available" not in out and "invalid" not in out,
      "".join(l for l in out.splitlines(True) if "not available" in l)[:60])
out = run(".option saveused", "let y = v(mid) + v(out)\nprint y", "f2v")
check("[F2] ...and the v() spelling still works",
      "not available" not in out and "invalid" not in out, "")

# ---------------------------------------------------------- E-726, E-727 ----
# Five-options dig of 2026-09-25, F4 and F5: the scanner's vocabulary, and an
# inferred set that matches nothing.
print("\nEnhancement-727: names inside expressions, in `meas`, behind `$&`")

# a bare vector inside an expression on an output command was skipped whole
# ("the reference scan covers v()/i()"), so `out` went unsaved beside v(in)
out = run(".option saveused", "print v(in) mag(out)", "e727a")
check("[E-727] `print v(in) mag(out)`: the bare `out` inside the expression is kept",
      kept(out)[1] == ["in", "out"] and "not available" not in out, f"{kept(out)[1]}")
out = run(".option saveused", "print out*2", "e727b")
check("[E-727] `print out*2` alone now restricts to `out` (it used to keep everything)",
      kept(out)[1] == ["out"] and "not available" not in out, f"{kept(out)[1]}")
out = run(".option saveused", "wrdata _su_e727.txt out*2\nprint v(mid)", "e727c")
check("[E-727] `wrdata f out*2` beside a print keeps `out` and `mid`",
      kept(out)[1] == ["mid", "out"], f"{kept(out)[1]}")
# `meas` was kept out of the bare-word scan (E-496), so a vector named bare in
# it was never seen: "no such vector as out"
out = run(".option saveused", "meas dc m find out at=0.5\nprint v(in)", "e727d")
check("[E-727] `meas dc m find out at=0.5`: the bare `out` is kept and the measure works",
      "out" in kept(out)[1] and re.search(r"^m\s*=\s*1\.66", out, re.M) is not None
      and "no such vector" not in out, f"{kept(out)[1]}")
out = run(".option saveused", "meas dc m2 when mid=0.5\nprint v(in)", "e727e")
check("[E-727] `meas dc m2 when mid=0.5`: the vector left of the `=` is kept, the measure reads 0.75",
      "mid" in kept(out)[1] and re.search(r"^m2\s*=\s*7\.5", out, re.M) is not None
      and "no such vector" not in out, f"{kept(out)[1]}")
# `$&name` in an echo, an if, a set
out = run(".option saveused", "op\nprint v(out)\necho mid is $&mid", "e727f")
check("[E-727] `echo $&mid` beside print v(out) keeps `mid` and prints its value",
      kept(out)[1] == ["mid", "out"] and re.search(r"^mid is 0\.66", out, re.M) is not None
      and "no such variable" not in out, f"{kept(out)[1]}")
out = run(".option saveused", "op\nprint v(out)\nif ($&mid > 0.4)\necho yes\nelse\necho no\nend", "e727g")
check("[E-727] `if ($&mid > 0.4)` reads the saved `mid`",
      re.search(r"^yes$", out, re.M) is not None and "no such variable" not in out
      and "syntax error" not in out, out[-120:].replace("\n", "|"))
out = run(".option saveused", "print v(out)\necho \"a=$&i(v1)\"", "e727h")
check("[E-727] `$&i(v1)` stays the reference scan's: `v1#branch` kept, nothing else added",
      kept(out)[1] == ["out", "v1#branch"], f"{kept(out)[1]}")
# a subcircuit node read bare in a `let` was split at its dot
SUB = ("v1 in 0 dc 1\nx1 in out div\n.subckt div a b\nr1 a mid 1k\nr2 mid b 1k\n.ends\nrl out 0 1k\n")
deck = (f"saveused e727i\n{SUB}.option saveused\n.control\noption noacct\nset numdgt=8\n"
        f"dc V1 0 1 0.5\nlet y = x1.mid*2\nprint y v(out)\ndisplay\n.endc\n.end\n")
with open(os.path.join(HERE, "_su_e727i.cir"), "w") as f:
    f.write(deck)
out = subprocess.run([NGSPICE, "-b", "_su_e727i.cir"], cwd=HERE, capture_output=True, text=True,
                     timeout=120, errors="replace").stdout
check("[E-727] `let y = x1.mid*2`: the subcircuit node is kept whole, not split at its dot",
      re.search(r"(?m)^\s+x1\.mid\s+:\s+voltage", out) is not None and kept(out)[1] == ["out"]
      and re.search(r"1\.3333", out) is not None and "invalid" not in out and "not available" not in out,
      out[-300:].replace("\n", "|"))

print("\nEnhancement-726: a plot-qualified name, and a set that matches nothing")
# `print tran1.out` went into the set whole; no analysis produces that name,
# so every analysis was refused ("no data saved ...; analysis not run")
out = run(".option saveused", "op\nprint dc1.out", "e726a")
check("[E-726] `print dc1.out` (the plot-qualified spelling) keeps `out` and both analyses run",
      kept(out)[1] == ["out"] and "analysis not run" not in out
      and re.search(r"dc1\.out", out) is not None, f"{kept(out)[1]} {out[-100:].replace(chr(10), '|')}")
# a set the scan inferred that matches nothing an analysis produces: the
# analysis keeps everything and says so, instead of being refused. pz makes
# `pole(1)`, which no block names by a form the scan reads
# (the source carries `ac 1`: pz treats a dc-only source as a short of its input)
deck = (f"saveused e726b\nv1 in 0 dc 1 ac 1\nr1 in mid 1k\nr2 mid out 1k\nc1 out 0 1n\n.option saveused\n"
        f".control\noption noacct\nop\nprint v(mid)\npz in 0 out 0 vol pz\nprint pole(1)\n.endc\n.end\n")
with open(os.path.join(HERE, "_su_e726b.cir"), "w") as f:
    f.write(deck)
out = subprocess.run([NGSPICE, "-b", "_su_e726b.cir"], cwd=HERE, capture_output=True, text=True,
                     timeout=120, errors="replace")
out = out.stdout + out.stderr
check("[E-726] a `pz` beside `print v(mid)`: the inferred set names nothing of it, so it keeps everything, said once",
      "analysis not run" not in out and re.search(r"^pole\(1\) = -", out, re.M) is not None
      and out.count("saveused: nothing the control block names is in the pole-zero analysis; everything of it is kept") == 1,
      out[-200:].replace("\n", "|"))
check("[E-726] ...and the operating point, which the set does name, is not said",
      "names is in the D.C." not in out and "names is in the Operating" not in out, "")
# a HAND-WRITTEN save that matches nothing is still refused, as before
out = run("", "op\nprint v(out)", "e726c", pre="save nosuch\n")
check("[E-726] a hand-written `save nosuch` still refuses the analysis (only an inferred set is forgiven)",
      "analysis not run" in out and "saveused:" not in out, out[-160:].replace("\n", "|"))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
