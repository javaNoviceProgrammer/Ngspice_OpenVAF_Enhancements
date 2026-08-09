# Enhancement-429 — a `.tf` card answered 0.0 for a node that does not exist

```
.tf v(nosuch) v1     ->  transfer_function = 0.000000e+00     no diagnostic
.tf v(b) v1          ->  transfer_function = 7.500000e-01     correct
```

Every unknown output node — a plain typo, or a device-internal node that no card
can name — was answered with a confident zero. The `.control` command form of the
same thing refuses it properly; only the **card** form invents the node and
reports on it.

## Why the existing guard could not see it

Enhancement-426 already added a bounds test here, and it is not wrong — it simply
cannot fire on this path:

```c
job->TFoutPos->number > SMPmatSize(ckt->CKTmatrix)
```

A node named by a `.control` command is created **after** `CKTsetup()` has sized
the matrix, so its equation number lands past the end and the test catches it —
that is the out-of-bounds heap read E-426 documented. A node named by a **card**
is created *before* setup, so it is counted when the matrix is sized: the phantom
sits comfortably inside, the bounds test sees nothing wrong, and the analysis
reads a row that is simply all zero.

## Why the node cannot just be refused at parse time

Because creating it is sometimes right. Enhancement-349 deliberately allows an
analysis card to name a node the deck has not reached yet:

```
.tf v(b) v1          <- card first
V1 a 0 dc 1
R1 a b 1k
R2 b 0 3k            <- b is only defined here
```

That still has to answer 0.75, and it is pinned in `examples/`. So the question
at analysis time is not *"does this node exist"* — it does, the card made it —
but *"did anything other than the card itself ever refer to it"*.

## What records that

One bit on `CKTnode`, `devRef`. Every path that creates a **real** node sets it:

* `INPtermInsert` — a device card naming a terminal, whether it finds the node or
  creates it. Finding matters as much as creating: it is what makes a
  forward-referenced node real once the deck reaches its devices.
* `INPmkTerm` — the simulator's own internal nodes, via `IFnewUid`.
* `INPgndInsert` — ground.

Exactly one path clears it: `inp_analysis_node`, the only place that invents a
node on an analysis card's behalf. Whatever is still clear once the deck is
parsed was named by an analysis card and by nothing else.

`CKTnodePhantom()` is that test, and ground (node 0) is never phantom.

The default is *real* rather than *phantom*, deliberately: a creation path added
later and not taught about the flag produces a node that behaves exactly as it
does today, rather than one that a `.tf` starts silently rejecting.

It is also solver-agnostic. The obvious alternative — asking the matrix whether
the node has any entries — is not: `SMPfindElt` asserts Sparse and would have to
be special-cased for KLU, which the regression exercises on every suite.

## Both analyses, not one

`noisean.c` has the same shape and the same E-426 bounds test, so it gets the
same guard. `sens` needs nothing: its card path already fails earlier.

## Verification

* **`examples/inputguard_examples` — 93/93** (was 88). The new checks pin the
  refusals *and* both directions of the boundary: a real node still answers 0.75,
  and E-349's card-before-its-devices case still answers 0.75.
* **Full regression 345/345**, both solvers.

## Found by

A follow-up question — *"so all the commands such as `.save` or `.probe` now work
correctly with internal nodes?"* — after Enhancement-428. Answering it honestly
meant enumerating every command that names a node, which split them into two
groups: those that consume an output *vector* (all fixed by E-428, including
`.probe`, which is textually rewritten to `.save`) and those that name a node as
an *analysis output*, which resolve against the circuit's node table at parse
time and refuse internal nodes for the same reason `.ic` does.

The `.tf` card fell in neither group: it refused nothing and answered zero.

Two notes worth keeping.

**The bug was wider than the question.** It was raised as an internal-node issue;
it turned out to affect any nonexistent node name, including an ordinary typo,
and the phantom is visible afterwards in `display` as a perfectly ordinary vector.

**A guard that exists is not a guard that fires.** E-426's bounds test reads as
though it covers this case, and the E-426 write-up even says a card-created
phantom "lands inside the array and the read is merely wrong" — the limitation
was recorded at the time and then not acted on. Checking which of the two paths a
guard actually protects took one deck.
