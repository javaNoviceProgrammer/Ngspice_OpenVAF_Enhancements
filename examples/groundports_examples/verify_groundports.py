#!/usr/bin/env python3
"""Enhancement-482: `.option silentports=ground` -- ground the terminals a netlist
leaves out, and give the option a value table.

Enhancement-481 gave `.option silentports` one job: turn off the absent-terminal
warning Enhancement-402 added, for the case where the netlist is written by a tool
rather than by a person. **That job is unchanged here**, and `silentports_examples`
still scores 24/24 against this binary. What E-481 could not do is make the deck
run.

An omitted OSDI terminal is not grounded. `inp2n.c` binds every terminal the line
did not reach to -1, and `osdi/osdisetup.c` then builds a private node
`<inst>#<term>` for each one. That is UPSTREAM behaviour -- E-402 only started
saying so. Ten of the twelve corpus models with an optional pin tie it off with a
POTENTIAL contribution (`Temp(t) <+ 0.0`), which contributes nothing to a node
ngspice allocated itself, so the private node has nothing driving it and the
operating point dies on `singular matrix: check node <inst>#t`. E-402 diagnosed
that, accepted it, and gave one answer: write `0` for the pin. A schematic front
end that hides the pin cannot write anything -- and neither could E-481, which
removed the five warning lines and left the six singular-matrix reports exactly
where they were.

`.option silentports=ground` writes the `0`. Every terminal the instance line left
out is bound to ground in the parser, exactly as if the netlist had spelled it.

THREE STATES, because silencing the report and repairing the circuit are different
requests, and the BARE CARD KEEPS E-481's MEANING:

  (unset)                        warn, terminal dangles     -- E-402's default
  silentports (bare)             silent, terminal DANGLES   -- E-481, unchanged
  silentports=dangle / =quiet    the same, spelled out
  silentports=ground             silent, terminal GROUNDED  -- what E-482 adds

`1`, `true`, `yes`, `on` mean the bare card. `0`, `false`, `no`, `off` turn the
feature off. `dangle` and `quiet` are synonyms.

Grounding is asked for BY NAME because it CHANGES THE CIRCUIT: the model reads
`$port_connected() == 1` for those terminals and builds branches it would
otherwise skip, with the node held at 0 -- a different circuit from the one the
netlist describes. A word the user typed is the right gate for that; the bare card
is not.

[7] is the strongest check: `=ground` must be INDISTINGUISHABLE from a netlist
that typed the `0` itself. [5] is its counterweight: the bare card must be
indistinguishable from the warned default except for the message -- which is what
keeps E-481's contract intact.

[11] walks the whole value table, and the ordering inside `silentports_mode()` is
what it pins. E-467 gave `cp_getvar` a CP_BOOL COERCION, so a CP_BOOL query
answers TRUE for anything that is not an off-word -- correct for a two-state
option, fatal for a three-state one, because it swallows every value word and
reports them all as plain "on". Measured with the BOOL query still first, `=quiet`
and `=bananna` BOTH GROUNDED the terminal. The string has to be read before
anything coerces it. An unrecognised word is REPORTED and falls back to the
DEFAULT: a typo must not be what silently drops a diagnostic or changes a circuit.

The three shapes, all compiled here:
  * gp_rth.va   -- thermal network contributed unconditionally, so it converges
                   in every state and the states can be compared directly;
  * gp_gated.va -- branch gated on `$port_connected`, the shape the real models
                   use: singular by default AND when merely silenced, repaired
                   only by `=ground`. Note it does not always ABORT -- on a small
                   circuit the gmin/source-stepping ladder can limp to an answer
                   after the singular matrices, which is exactly why this needed
                   a fix and not a louder message;
  * gp_two.va   -- two optional terminals, so a fix that grounded only the first
                   would be caught.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(stem):
    src = os.path.join(HERE, stem + ".va")
    osdi = os.path.join(HERE, "_" + stem + ".osdi")
    r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=HERE, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr), osdi


def run(deck, ctl, tag, osdi, timeout=120):
    path = os.path.join(HERE, f"_gp_{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* silentports {tag}\n{deck}\n.control\npre_osdi {osdi}\n"
                f"option noacct\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=timeout, cwd=HERE, stdin=subprocess.DEVNULL)
    try:
        os.remove(path)
    except OSError:
        pass
    return r.returncode, (r.stdout + r.stderr)


def warn_lines(out):
    """Lines of the Enhancement-402 absent-terminal warning."""
    return len(re.findall(r"are not connected|is absent|port_connected\(\) = 0"
                          r"|NOT grounded -- connect|Line: n1", out))


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def txt(out, name):
    """The printed value verbatim, for exact-equality comparisons."""
    m = re.findall(re.escape(name) + r"\s*=\s*(\S+)", out, re.I)
    return m[-1] if m else None


def singular(out):
    return len(re.findall(r"singular matrix", out, re.I))


def near(x, want, tol=1e-9):
    return x is not None and abs(x - want) <= tol * max(1.0, abs(want))


print("Enhancement-482: `.option silentports=ground`\n")

# ------------------------------------------------------------ compile all --
rc, out, OSDI_RTH = compile_va("gp_rth")
check("[1] the well-posed optional-thermal model compiles", rc == 0,
      out.splitlines()[0][:60] if rc else "")
rc, out, OSDI_GATED = compile_va("gp_gated")
check("[1] ...and the $port_connected-gated one", rc == 0,
      out.splitlines()[0][:60] if rc else "")
rc, out, OSDI_TWO = compile_va("gp_two")
check("[1] ...and the two-optional-terminal one", rc == 0,
      out.splitlines()[0][:60] if rc else "")

OMIT = "V1 a 0 dc 1\nN1 a 0 mm\n.model mm gp_rth()"
CONN = "V1 a 0 dc 1\nN1 a 0 0 mm\n.model mm gp_rth()"
PROBE = "op\nprint i(v1) @n1[pc] @n1[trise]"

# ------------------------------------------ the default is UNCHANGED (E-402) --
print("\nthe default still warns, and still leaves the terminal dangling")
rc, o_def = run(OMIT, PROBE, "default", OSDI_RTH)
check("[2] an omitted terminal warns by default", warn_lines(o_def) == 5,
      f"{warn_lines(o_def)} lines")
check("[2] ...the model is told the terminal is NOT connected",
      near(val(o_def, "@n1[pc]"), 0.0), f"$port_connected={val(o_def,'@n1[pc]')}")
check("[2] ...it heats a node of its own instead of ground",
      near(val(o_def, "@n1[trise]"), 10.0, 1e-6), f"Temp(t)={val(o_def,'@n1[trise]')}")
check("[2] ...and that node is real and solvable",
      near(val(o_def, "i(v1)"), -9.0909090909e-4, 1e-6), f"i(v1)={val(o_def,'i(v1)')}")
rc, o = run(OMIT, "op\nprint v(n1#t)", "node_default", OSDI_RTH)
check("[2] ...ngspice named it n1#t", near(val(o, "v(n1#t)"), 10.0, 1e-6),
      f"v(n1#t)={val(o,'v(n1#t)')}")
rc, o = run(CONN, PROBE, "conn", OSDI_RTH)
check("[3] a fully connected instance never warned and still does not",
      warn_lines(o) == 0, f"{warn_lines(o)} lines")

# ------------------------------------------- the bare card: silence, only ----
print("\nthe bare card silences the report and changes NOTHING else")
rc, o_bare = run(".option silentports\n" + OMIT, PROBE, "bare", OSDI_RTH)
check("[4] the warning is gone", warn_lines(o_bare) == 0, f"{warn_lines(o_bare)} lines")
check("[4] ...and it is not reported as an unknown option",
      "unknown option" not in o_bare.lower(), "registered in both places")
check("[5] the terminal is STILL not connected",
      near(val(o_bare, "@n1[pc]"), 0.0), f"$port_connected={val(o_bare,'@n1[pc]')}")
for name in ("i(v1)", "@n1[pc]", "@n1[trise]"):
    check(f"[5] ...answering exactly as the warned default does: {name}",
          txt(o_bare, name) is not None and txt(o_bare, name) == txt(o_def, name),
          f"{txt(o_bare,name)} vs {txt(o_def,name)}")
rc, o = run(".option silentports\n" + OMIT, "op\nprint v(n1#t)", "node_bare", OSDI_RTH)
check("[5] ...and the private n1#t node is still there",
      near(val(o, "v(n1#t)"), 10.0, 1e-6), f"v(n1#t)={val(o,'v(n1#t)')}")

# ------------------------------------------------- =ground: the extra step ---
print("\n=ground also binds the omitted terminal to node 0")
rc, o_gnd = run(".option silentports=ground\n" + OMIT, PROBE, "ground", OSDI_RTH)
check("[6] the warning is gone here too", warn_lines(o_gnd) == 0,
      f"{warn_lines(o_gnd)} lines")
check("[6] ...the model is now told the terminal IS connected",
      near(val(o_gnd, "@n1[pc]"), 1.0), f"$port_connected={val(o_gnd,'@n1[pc]')}")
check("[6] ...the thermal node is held at 0, so the device cannot self-heat",
      near(val(o_gnd, "@n1[trise]"), 0.0), f"Temp(t)={val(o_gnd,'@n1[trise]')}")
check("[6] ...and the terminal current changes to match",
      near(val(o_gnd, "i(v1)"), -1e-3, 1e-9), f"i(v1)={val(o_gnd,'i(v1)')}")
rc, o = run(".option silentports=ground\n" + OMIT, "op\nprint v(n1#t)", "node_ground",
            OSDI_RTH)
gone = re.search(r"n1#t is not available", o, re.I) is not None
check("[6] ...with no private n1#t node created at all", gone,
      "no such vector" if gone else f"v(n1#t)={val(o,'v(n1#t)')}")

print("\n...and is exactly what the netlist would have done by hand")
rc, o_hand = run(CONN, PROBE, "hand", OSDI_RTH)
for name in ("i(v1)", "@n1[pc]", "@n1[trise]"):
    check(f"[7] =ground == a netlist that typed the 0: {name}",
          txt(o_gnd, name) is not None and txt(o_gnd, name) == txt(o_hand, name),
          f"{txt(o_gnd,name)} vs {txt(o_hand,name)}")

# ------------------------------------------- EVERY omitted terminal, not one --
print("\nevery terminal the line left out, not just the first")
TOMIT = "V1 a 0 dc 1\nN1 a 0 mm\n.model mm gp_two()"
TCONN = "V1 a 0 dc 1\nN1 a 0 0 0 mm\n.model mm gp_two()"
TPROBE = "op\nprint i(v1) @n1[pct] @n1[pcb]"
rc, o = run(TOMIT, TPROBE, "two_default", OSDI_TWO)
check("[8] two omitted terminals warn together by default", warn_lines(o) == 6,
      f"{warn_lines(o)} lines")
check("[8] ...and neither reaches the model as connected",
      near(val(o, "@n1[pct]"), 0.0) and near(val(o, "@n1[pcb]"), 0.0),
      f"pct={val(o,'@n1[pct]')} pcb={val(o,'@n1[pcb]')}")
rc, o2 = run(".option silentports=ground\n" + TOMIT, TPROBE, "two_ground", OSDI_TWO)
check("[8] with =ground BOTH are connected",
      near(val(o2, "@n1[pct]"), 1.0) and near(val(o2, "@n1[pcb]"), 1.0),
      f"pct={val(o2,'@n1[pct]')} pcb={val(o2,'@n1[pcb]')}")
rc, o3 = run(TCONN, TPROBE, "two_hand", OSDI_TWO)
check("[8] ...and the current proves the LAST one was grounded too",
      txt(o2, "i(v1)") == txt(o3, "i(v1)") and near(val(o2, "i(v1)"), -1.1e-3, 1e-9),
      f"{txt(o2,'i(v1)')} vs {txt(o3,'i(v1)')}")

# ------------------------------------- the shape a warning could never repair --
print("\nthe gated shape -- only =ground repairs it, silence never does")
GOMIT = "V1 a 0 dc 1\nN1 a 0 mm\n.model mm gp_gated()"
GCONN = "V1 a 0 dc 1\nN1 a 0 0 mm\n.model mm gp_gated()"
GPROBE = "op\nprint i(v1) @n1[pc]"
rc, o = run(GOMIT, GPROBE, "gated", OSDI_GATED)
sing_default = singular(o)
check("[9] the gated model's floating node is singular by default",
      sing_default > 0, f"{sing_default} singular lines")
check("[9] ...the branch was never built, so the model never saw the pin",
      near(val(o, "@n1[pc]"), 0.0) and re.search(r"gmin stepping", o) is not None,
      f"pc={val(o,'@n1[pc]')}, reached the gmin ladder")
rc, o = run(".option silentports\n" + GOMIT, GPROBE, "gated_bare", OSDI_GATED)
check("[9] the bare card silences the warning and leaves it JUST AS SINGULAR",
      warn_lines(o) == 0 and singular(o) == sing_default,
      f"{warn_lines(o)} lines, {singular(o)} vs {sing_default} singular")
rc, o_g = run(".option silentports=ground\n" + GOMIT, GPROBE, "gated_ground", OSDI_GATED)
check("[9] =ground makes the singular matrix GONE", singular(o_g) == 0,
      f"{singular(o_g)} vs {sing_default}")
rc, o_gh = run(GCONN, GPROBE, "gated_hand", OSDI_GATED)
check("[9] ...and it reaches the same operating point as writing 0 by hand",
      txt(o_g, "i(v1)") is not None and txt(o_g, "i(v1)") == txt(o_gh, "i(v1)"),
      f"{txt(o_g,'i(v1)')} vs {txt(o_gh,'i(v1)')}")

# --------------------------------------------------- inside a subcircuit ----
# The KiCad case is hierarchical: the instance the exporter writes short is
# usually inside a subckt. Node 0 is global, so the binding has to reach the
# real ground and not a subcircuit-local name.
print("\nand the same inside a subcircuit, where the front end actually puts it")
SUB = ("V1 a 0 dc 1\nX1 a 0 wrap\n.subckt wrap p n\nN1 p n mm\n"
       ".model mm gp_rth()\n.ends")
SUBPROBE = "op\nprint i(v1) @x1.n1[pc] @x1.n1[trise]"
rc, o = run(SUB, SUBPROBE, "sub_default", OSDI_RTH)
# warn_lines()'s `Line: n1` clause cannot match the flattened name `n.x1.n1`,
# so count the four name-independent lines instead.
check("[10] a subcircuit instance warns by default too",
      warn_lines(o) == 4 and re.search(r"n\.x1\.n1.*not connected", o) is not None,
      f"{warn_lines(o)} lines, named n.x1.n1")
check("[10] ...and dangles there as well", near(val(o, "@x1.n1[pc]"), 0.0),
      f"pc={val(o,'@x1.n1[pc]')}")
rc, o = run(".option silentports=ground\n" + SUB, SUBPROBE, "sub_ground", OSDI_RTH)
check("[10] =ground reaches the GLOBAL ground from inside the subcircuit",
      near(val(o, "@x1.n1[pc]"), 1.0) and near(val(o, "@x1.n1[trise]"), 0.0)
      and near(val(o, "i(v1)"), -1e-3, 1e-9),
      f"pc={val(o,'@x1.n1[pc]')} Temp={val(o,'@x1.n1[trise]')} i={val(o,'i(v1)')}")

# ------------------------------------------------------- the value table ----
print("\nthe whole value table, each read back through $port_connected")
GROUND, DANGLE, OFF = "ground", "dangle", "off"
WANT = {GROUND: (0, 1.0), DANGLE: (0, 0.0), OFF: (5, 0.0)}
for spelling, want in [("silentports", DANGLE), ("silentports=dangle", DANGLE),
                       ("silentports=Dangle", DANGLE), ("silentports=quiet", DANGLE),
                       ("silentports=1", DANGLE), ("silentports=true", DANGLE),
                       ("silentports=yes", DANGLE), ("silentports=on", DANGLE),
                       ("silentports=ground", GROUND), ("silentports=GROUND", GROUND),
                       ("silentports=0", OFF), ("silentports=false", OFF),
                       ("silentports=no", OFF), ("silentports=off", OFF)]:
    rc, o = run(f".option {spelling}\n" + OMIT, PROBE, re.sub(r"\W", "", spelling),
                OSDI_RTH)
    want_n, want_pc = WANT[want]
    n, pc = warn_lines(o), val(o, "@n1[pc]")
    check(f"[11] .option {spelling} -> {want}",
          n == want_n and near(pc, want_pc) and "unknown option" not in o.lower()
          and "unsupported value" not in o,
          f"{n} lines, pc={pc}")

# ------------------------------------------------------- a global default ----
print("\na front end can set it globally, without editing netlists")
spiceinit = os.path.join(HERE, ".spiceinit")


def with_spiceinit(text, tag):
    with open(spiceinit, "w") as f:
        f.write(text)
    try:
        return run(OMIT, PROBE, tag, OSDI_RTH)
    finally:
        os.remove(spiceinit)


rc, o = with_spiceinit("set silentports\n", "spiceinit_bare")
check("[12] `set silentports` in .spiceinit silences it too",
      warn_lines(o) == 0 and near(val(o, "@n1[pc]"), 0.0),
      f"{warn_lines(o)} lines, pc={val(o,'@n1[pc]')}")
rc, o = with_spiceinit("set silentports=ground\n", "spiceinit_ground")
check("[12] ...and `set silentports=ground` reaches the same three-state reader",
      warn_lines(o) == 0 and near(val(o, "@n1[pc]"), 1.0),
      f"{warn_lines(o)} lines, pc={val(o,'@n1[pc]')}")
rc, o = run(OMIT, PROBE, "after", OSDI_RTH)
check("[12] ...and removing it brings the warning back",
      warn_lines(o) == 5 and near(val(o, "@n1[pc]"), 0.0),
      f"{warn_lines(o)} lines, pc={val(o,'@n1[pc]')}")

# ---------------------------------------------------- an unrecognised word --
print("\nan unrecognised word is reported, and falls back to the DEFAULT")
BAD = "V1 a 0 dc 1\nN1 a 0 mm\nN2 a 0 mm\n.model mm gp_rth()"
rc, o = run(".option silentports=bananna\n" + BAD, PROBE, "badword", OSDI_RTH)
check("[13] the bad word is named", "unsupported value 'bananna'" in o,
      "reported")
check("[13] ...exactly once, not once per device",
      len(re.findall(r"unsupported value", o)) == 1,
      f"{len(re.findall(r'unsupported value', o))} for 2 devices")
check("[13] ...and it falls back to the DEFAULT, not to either ON state",
      near(val(o, "@n1[pc]"), 0.0) and warn_lines(o) >= 5,
      f"pc={val(o,'@n1[pc]')}, still warns")

# ------------------------------------------------ the option does not overreach --
print("\nit does what it was asked and touches nothing else")
rc, o = run(".option silentports=ground\nV1 a 0 dc 1\nN1 a 0 0 0 mm\n"
            ".model mm gp_rth()", PROBE, "toomany", OSDI_RTH)
check("[14] too MANY nodes is still an error",
      re.search(r"too many nodes", o, re.I) is not None, "")
for spelling, tag in [("silentports", "conn_bare"),
                      ("silentports=ground", "conn_ground")]:
    rc, o = run(f".option {spelling}\n" + CONN, PROBE, tag, OSDI_RTH)
    check(f"[14] a fully connected instance is unchanged by {spelling}",
          all(txt(o, n) == txt(o_hand, n) for n in ("i(v1)", "@n1[pc]", "@n1[trise]")),
          f"i(v1)={txt(o,'i(v1)')}")

for stem in ("_gp_rth.osdi", "_gp_gated.osdi", "_gp_two.osdi"):
    p = os.path.join(HERE, stem)
    if os.path.exists(p):
        os.remove(p)

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
