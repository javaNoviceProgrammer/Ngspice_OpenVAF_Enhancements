# Enhancement-569: a node a device only reads is held and named — the floating-node test looks at the row as well as the column

**Scope:** the floating-node rule Enhancement-566 added to `CKTsetup`
(`src/spicelib/analysis/cktsetup.c`) and its helper `SMPmarkOccupied()`
(`src/maths/KLU/klusmp.c`, `src/include/ngspice/smpdefs.h`), both solvers. Found while
answering "what if an input node is floating — does the operating point fail under KLU
and Sparse?" with ten decks. **ngspice only.**

**Suites:** new [`floatnode_examples`](../examples/floatnode_examples/) (16 checks per
solver, both solvers; compiles its own `va_vcvs.va` and uses the benchmark BSIM4); `solvercore` (E-566), `ctrlnode` (E-492), `oprobust` (E-568),
`netinit`, `pzhb` pass; full sweep 468 of 468 on both solvers.

## What was wrong

Ten floating-input decks fall into three kinds. A node that a device drives or loads
but nothing conducts to — an open MOSFET gate, a gate reached only through a capacitor,
a capacitor to ground with nothing else, a CMOS inverter chain with its input open —
costs the whole ladder (plain Newton, dynamic gmin, true gmin and source stepping each
fail with "singular matrix: check node g") and is solved by optran after about 277
iterations, identically under both solvers. A node with only a current source is what
Enhancement-566 fixed: both solvers name it and hold it at I/gmin. A node that a device
only *reads* failed outright.

`b1 c 0 v=2*v(x)` with nothing else on `x`, or an XSPICE `a1 %v(x) %v(y) gainm` whose
input port touches nothing, ended in "The operating point could not be simulated
successfully" after 374 iterations on both solvers — every rung, Enhancement-568's
damped Newton included — and the two solvers blamed different things: Sparse "check
node x", KLU "check node b1#branch". Enhancement-492 refuses exactly this shape for an
`E`, `G` or switch control node, but a B-source and an XSPICE input create their nodes
through the ordinary terminal path and are not covered. A compiled Verilog-A module has
exactly the same shape: `V(out) <+ gain*V(in)` only *probes* its `in` port, OpenVAF emits
no Jacobian entry in that port's row, and with `in` on a node nothing else touches the
operating point failed after the same 374 iterations, KLU blaming the module's internal
branch `nx1#flow(out)`.

The cause is one word in E-566's rule. It gives every node that "owns no matrix entry"
a zero diagonal, so that gmin can hold it, and decided ownership by the node's matrix
**column**. That is right for the nodes it was written for — a current source's only
load, a controlled-current-source output — whose equation contains no unknown: an empty
column. A read-only node is the mirror image: the reader stamps its derivative into its
own row, column `x`, so `x` has a column entry and an **empty row** — no equation at all.
An empty row is as singular as an empty column, and nothing downstream can mend it:
gmin stepping adds to a diagonal element that does not exist, so the matrix stays
structurally singular in every rung, and each solver's factorization simply reports the
first pivot it cannot find.

Spectre's topology check treats both alike: "No DC path from node to ground, Gmin
installed to provide path", naming the node. `.option rshunt` gives ngspice the same
outcome on every deck above (three iterations, both solvers), because the shunt's setup
creates a diagonal for every node — but it is a global change to the circuit and it
silences the diagnosis.

## What changed

`SMPmarkOccupied()` now reports rows and columns separately — for KLU from the COO list
it already walked, for Sparse by visiting every element of the indices translated so
far — and `CKTsetup` gives a node its zero diagonal, and the E-566 warning, when its row
**or** its column is empty. Nothing else moves: the "no matrix to solve" note for a deck
with no matrix at all, the nodeset/ic diagonals and the size hint are as E-566 left
them.

The read-only node now reads 0 V on both solvers, named — "node 'x' is connected to
nothing that conducts; it is held only by gmin" — with the point reached through optran
after 277 iterations like the other floating shapes. E-566's empty-column cases are
still caught (the suite pins the current-source load at 1e9 V and the CCCS output at
−5e8 V, both named), and three ordinary shapes are pinned not to warn: a node both read
and reached through a resistor, a node held by a voltage-source branch (row and column
each hold the branch entry), a node between two inductors.

OSDI devices need nothing of their own: the Verilog-A module above now converges, named,
on both solvers, and the same module with its port driven is unchanged (v(c) = 2 in three
iterations, no warning). The other floating shapes behave as the built-ins do: a BSIM4
or PSP transistor with its gate open, or a gate reached only through a Verilog-A
capacitor, goes through the ladder to optran in about 290 iterations, both solvers agree
on the value (the BSIM4 gate settles at 0.43 V, what the source ramp couples into it
through the gate capacitances; PSP's at 25 µV), a HiCUM stage with an open base is not
floating at all (its junction is a DC path, 30 iterations) and a dangling Verilog-A
resistor simply reads its far end. One diagnosis wart was noticed and left: for the
capacitor-coupled BSIM4 gate the six "singular matrix" reports name `g` under Sparse
and `d` under KLU — the same singular block, a different pivot — and only Sparse's is
the useful one.

What this does not do: make a floating node cheap. Every floating shape still travels
the ladder to optran, some 277 iterations, because the diagonal is zero in the plain
solve and gmin stepping ramps its hold away before the final solve. Keeping `gmin`
permanently on the created diagonals — Spectre's "Gmin installed to provide path" — would
turn those into three-iteration points; it is a change to E-566's "held only by gmin"
semantics and is left for its own enhancement.

## Verification

| check | result |
|---|---|
| `b1 c 0 v=2*v(x)`, nothing else on `x`; an XSPICE `gain` whose input port touches nothing | v(c) = 0, v(x) = 0 on both solvers, `x` named as held only by gmin (both were "could not be simulated" after 374 iterations, Sparse blaming `x`, KLU `b1#branch`) |
| a current source's only load; a CCCS output | v(x) = 1e9, v(nx) = −5e8, both named — E-566's cases unchanged |
| a node read by a B-source and reached through a resistor; a node held by a voltage source; a node between two inductors | 1 V / 2 V, 2 V, 1 V, no warning, 3 iterations |
| an open MOSFET gate; an `E` control node that touches nothing | v(g) = 0 through optran in 276 iterations, unchanged; still refused by E-492 |
| a Verilog-A `V(out) <+ gain*V(in)` whose `in` port touches nothing; the same with `in` driven; BSIM4 (OSDI) with an open gate | v(c) = 0, `x` named, both solvers (was "could not be simulated" after 374 iterations, KLU blaming `nx1#flow(out)`); v(c) = 2 in 3 iterations, no warning; v(g) = 0.4317, v(d) = 1.0083 through optran in 290 iterations, both solvers |
| the read-only deck with `.option rshunt=1e12` | 3 iterations, v(c) = 0, no warning |
| `floatnode_examples`; `solvercore`, `ctrlnode`, `oprobust`, `netinit`, `pzhb`; full sweep | 16 / 16 both solvers; all pass; 468 of 468 |
