# Enhancement-492 — a node named only in a control position

**Files:** `src/spicelib/parser/inp2dot.c`, `src/spicelib/parser/inp2e.c`,
`src/spicelib/parser/inp2g.c`, `src/spicelib/parser/inp2s.c`,
`src/spicelib/parser/inppas3.c`, `src/include/ngspice/inpdefs.h`,
`src/include/ngspice/cktdefs.h`, `src/spicelib/analysis/cktop.c`,
`src/osdi/osdiload.c`, `src/maths/KLU/klusmp.c`.

**Suite:** `examples/ctrlnode_examples/` — 37 checks.

## Why

`E`, `G` and `S` take a controlling node **pair**, and those two names were bound
exactly the way the output pair is — `INPtermInsert`, which **creates** the node.
So a typo simply invented a node and the run continued against it.

For `E` and `G` the invented node has no path to ground, the matrix goes singular,
and the user is told:

```
Warning: singular matrix:  check node nosuch
```

a node they never wrote, reported as a fault in their circuit.

**`S` is worse.** A switch only *reads* its control voltage to decide open or
closed and stamps nothing for it, so the matrix stays non-singular, the solve
succeeds, and the answer is silently wrong:

| | v(b) | state |
|---|---|---|
| `S1 a b ctl 0 sw` (correct) | 0.999001 | CLOSED |
| `S1 a b nosuch 0 sw` (typo) | **9.99999e-07** | **OPEN** |

A factor of a million from one mistyped character, `rc=0`, no diagnostic at all.
**A phantom reference is dangerous exactly where it is read but not stamped.**

## Every other route already answered this

* `.ic` and `.nodeset` → *"IC on non-existent node - nosuch, ignored"*
* `F`, `H`, `W`, and a B-source's `i()` → *"unknown controlling source vnope"*
* all thirteen output constructs (`print`, `let`, `wrdata`, `meas`, `fourier`,
  `fft`, `settype`, `save`, `.print` …) name a vector that does not exist

Only the controlling-node pair skipped it. `warn_physics` even validates the
switch's numeric parameters — `ron`, `roff`, `vh` — while its control node
reference was validated by nothing, under any option.

## The mechanism is Enhancement-429's, unchanged

E-429 added `CKTnode::devRef` — "was this node ever named by a device, or made by
the simulator?" — so that a `.tf` card may legitimately precede the devices
defining its nodes while a typo is still caught. A control reference is the same
kind of reference: it names a node without making it real. So it no longer sets
`devRef`, and `CKTnodePhantom()` answers the question unchanged.

Marking is left to `INPtermInsert` for every other position, so a control node
that **is** connected somewhere — including one that is the source's own output,
`E1 out 0 out 0 2` — stays marked and is never reported. The check runs in **pass
3** for the same reason `.ic`'s does: only once every device card has been read is
*"did anything connect to this?"* answerable.

It **refuses** rather than warns. `E` and `G` already fail on their own; a switch
does not, and would otherwise carry on and answer from a node that is not in the
circuit — the detect-announce-then-use-it-anyway shape Enhancement-485 had to undo
eight times in one round.

## Two diagnostics that named the wrong thing

**CKTop blamed Verilog-A for faults that were not Verilog-A's.** E-378 added the
abort message and E-399 narrowed its entry to `E_PANIC` checks, arguing the test
is exact because `E_PANIC` (1) and `E_ITERLIM` (103) are distinct values. That is
true — but the invariant the *message* relies on is **`E_PANIC` ⟺ a Verilog-A
`$fatal`**, and `E_PANIC` has around ten producers: `cktsetup` (missing model and
device lists), `osdiparam`, `osdiload`, `osdisetup`, `dcpss`, `cktpzstr`,
`ifeval`, CIDER's `twosolve`. Measured: `.option klu` with a netlist whose matrix
holds only current sources — **no Verilog-A device anywhere in the deck** —
printed *"a Verilog-A device raised `$fatal`"* and pointed at an `OSDI(fatal)`
message that does not exist, through `op`, `dc`, `ac` and `tran` alike, since each
calls CKTop for its operating point.

`CKTvaFatalRaised` is now set only where a `$fatal` is actually detected, and
cleared on entry to CKTop so a previous analysis's fatal cannot be inherited. Each
case says what it knows.

**KLU printed nine lines for one condition.** PreOrder's own comment says an empty
matrix is legitimate — *"XSPICE pure digital circuits produce empty KLU matrix"* —
and it returns success for one. But all three sites printed *"Error (…): KLU
Matrix is empty"* on every call, and Solve then added *"KLUnumeric object is
NULL"* and *"KLUsymbolic object is NULL"*, which are **consequences** of the same
empty matrix rather than separate faults. Re-entered per Newton iteration, one
circuit produced nine or more lines, none naming what had happened. It now says
once, in words, what the state is.

## What this deliberately does not change

* **A control node connected anywhere else** — including the source's own output,
  one defined later in the deck, ground, or one passed through a subcircuit port.
* **`F`, `H`, `W` and B-source `i()`**, which already named their missing
  controlling source.
* **A real Verilog-A `$fatal`**, which is still named as such and still points at
  the `OSDI(fatal)` line.
* **An ordinary circuit under either solver**, and a mixed-signal KLU run, which
  get no empty-matrix note.

## Verification

```
python3 examples/ctrlnode_examples/verify_ctrlnode.py    # 37/37
python3 examples/run_regression.py                       # 406/406
```

**19/37** against the pre-fix binary, so **18 of 37 checks discriminate**; the
other nineteen are controls that must not move, and do not — the ones that make
this fix easy to get wrong are among them: a control node that is the source's
own output, one defined later in the deck, ground, and one passed through a
subcircuit port.
