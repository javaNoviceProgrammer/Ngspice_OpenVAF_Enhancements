# Enhancement-349 — a mistyped node name no longer kills ngspice

```
ngspice 1 -> op
ngspice 2 -> tf v(ouy) v1
Internal Error: incomplete CKTunsetup(), this will cause serious problems, please report this issue !
$
```

One transposed letter, and the process is gone — along with every circuit
loaded, every plot computed, and every vector let-defined in that session.

Seven commands did this: `tf`, `pz`, `noise`, `sens`, `pss`, `pxf`, `psp`.

---

## How it was found

A **stateful cross-command fuzz** — random sequences of state-mutating commands
followed by a canary circuit whose answer is known exactly (a 1 V source across
a 1k/3k divider, so `v(b)` must be 0.75). The design target was silent state
corruption, but what it surfaced first was a sequence that never reached the
canary at all, because ngspice had exited underneath it.

The harness was checked against the pre-Enhancement-342 binary first, where it
found 38 aborts in 200 sequences, so a clean run means the detector works rather
than that it is asleep.

## What the message is really reporting

`CKTunsetup()` ends with a consistency check that ngspice added for exactly this
class of problem:

```c
if (ckt->prev_CKTlastNode != ckt->CKTlastNode) {
    fprintf(stderr, "Internal Error: incomplete CKTunsetup(), ...");
    controlled_exit(EXIT_FAILURE);
}
```

`prev_CKTlastNode` is the tail of the node list snapshotted by `CKTsetup()`
just before devices add their internal nodes. If the list is not back to that
tail when the circuit is torn down, something added a node that nothing will
remove — and the matrix, already sized, no longer matches the circuit. The check
is right. It was firing on a real inconsistency.

## The root cause

`INPtermInsert()` is **create-or-find**:

```c
/* insert 'token' into the terminal symbol table */
/* create a NEW NODE and return a pointer to it in *node */
```

That is correct for a device card, where the device *defines* its nodes — `R1 in
out 1k` is what brings `out` into existence. It is wrong for an analysis card,
where the node must already exist. `.tf v(out) v1` does not define `out`; it
*refers* to it.

So a mistyped name was quietly created as a new, unconnected node. Two
consequences, and the milder one is arguably the worse bug:

**Silently wrong.** Before the circuit is set up, nothing crashes — the invented
node simply reads as a perfectly plausible 0 V:

```
ngspice -> tf v(bogus) v1
ngspice -> print v(bogus)
v(bogus) = 0.000000e+00        <- no error, no warning
```

**Fatal.** From the `.control` section the circuit is already set up and the
matrix already sized, so the new node breaks the tail check above and takes the
process down.

The reason this never bit in a plain netlist is ordering: a `.tf` card in the
deck is parsed *before* `CKTsetup()` runs, so the invented node is included in
the snapshot and the tail still matches. It is only reachable interactively —
which is precisely where a typo is most likely and losing the session hurts
most.

## The fix

Analysis cards resolve their nodes through a lookup that will not invent one,
while keeping the one case that legitimately needs creation:

```c
static int
inp_analysis_node(void *ckt, char **token, INPtables *tab, CKTnode **node)
{
    CKTcircuit *c = (CKTcircuit *) ckt;

    if (INPtermSearch(c, token, tab, node) == E_EXISTS)
        return OK;                        /* the ordinary case: a real node */
    if (c && c->CKTisSetup)
        return E_NOTFOUND;                /* deck parsing is over -- a typo */
    INPtermInsert(c, token, tab, node);   /* card ahead of its own devices */
    return OK;
}
```

`INPtermSearch()` already existed alongside `INPtermInsert()` — the lookup-only
half of the pair was simply never used here.

**Deck order still works.** A `.tf` card may legally appear ahead of the devices
that define its nodes, so creation stays permitted while the circuit is not yet
set up. Only once `CKTisSetup` is true — deck parsing finished — is an unknown
name treated as the typo it is. This is tested explicitly, not assumed.

Applied at 14 call sites across `dot_noise`, `dot_tf`, `dot_sens`, `dot_pss`,
`dot_pac`, `dot_psp`, `dot_pnoise`, `dot_pxf` and `dot_hb`, via a macro that
reports the offending name and abandons the card:

```
Error on line 3 :
  tf v(ouy) v1
    no such node: ouy
```

`dot_pz` reached the same `INPtermInsert()` indirectly, through
`INPgetValue(…, IF_NODE, …)`. Its four node arguments are now read explicitly
so they go through the same path as every other analysis card.

## Verification

- **0 of 14 commands** kill the process on an unknown node name, from 7.
- The same reference **as a deck card still parses**, so nothing that worked
  before now fails.
- A `.tf` card placed **before** the devices it names still resolves and returns
  the same numbers (`transfer_function = 0.75`, `output_impedance = 750`,
  `input_impedance = 4000`) — the deck-order tolerance is intact.
- **No valid answer moved**: 22 correct invocations across every affected
  analysis compared digit-for-digit against the shipped binary, all identical.
- The full example suite passes.

Reproducers live in `examples/nodetypo_examples/`.
