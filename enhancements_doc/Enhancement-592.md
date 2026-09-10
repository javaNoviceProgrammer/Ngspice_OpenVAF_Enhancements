# Enhancement-592: `autoadapt` says which adapter rule failed, and a `.ic` or `.nodeset` on a bit of a split node is explained

**Scope:** `src/spicelib/parser/inp2n.c` (the adapter-model check, and a lookup of
the split-node list), `src/spicelib/parser/inppas3.c` (the `.ic` and `.nodeset`
non-existent-node branches), `src/include/ngspice/inpdefs.h`,
`examples/adaptmsg_examples/` (new, 10 checks per solver);
`examples/autoadapt_examples/` accepts the new wording. **ngspice only.** Findings F4
and F5 of the 2026-09-09 dig.

**Suites:** [`adaptmsg_examples`](../examples/adaptmsg_examples/) 10 of 10 per solver,
both solvers; `autoadapt` 26 of 26; full sweep 487 of 487.

## F4 — one message for three faults

`INPadapt` checked the adapter model with one compound test,

```c
if (anp != 2 || acnt[0] < 2 || acnt[1] < 2 || acnt[0] != acnt[1])
```

and one message, "must have exactly two bus ports of equal width (found %d port(s),
widths %d/%d)". For an adapter with scalar ports, or ports declared `[0:0]`, that
read "found 2 port(s), widths 1/1" — two ports, equal widths, refused. The rule the
middle clause enforces is stated nowhere in the message: `autoadapt` splits bus nodes
only (a shared scalar node is never adapted, E-463's table), so a port of width one has
nothing it could sit in. The test is now three tests with three messages:

| adapter | message |
|---|---|
| three bus ports | `must have exactly two bus ports (found 3)` |
| scalar or `[0:0]` ports | `has a port of width 1 (widths 1/1); autoadapt splits bus nodes only -- a shared scalar node is never adapted -- so a scalar or one-bit port has nothing it could sit in. Declare both ports as buses of the shared node's width, inout [0:N-1] p, n;` |
| widths 5 and 3 | `has ports of different widths (5 and 3); both must be the shared bus's width` |

## F5 — `.ic` and `.nodeset` on a split bit

`.option autoadapt` renames a shared bus `x` into `x_f` and `x_r`. E-572 warns when
the control block or a surviving dot card still names a bit of `x`, with the two new
names offered — but `.ic` and `.nodeset` are consumed in pass 3, resolving their nodes
before that check ever runs, so `.ic v(x[2])=0.5` got ngspice's generic "IC on
non-existent node - x[2], ignored" while the `.save v(x[2])` beside it got the split
explained. The split list is intact in pass 3; `INPadaptSplitOf` reads it, and both
branches now say:

```
Warning: autoadapt split node 'x' into 'x_f' and 'x_r', so its bit 'x[2]' no longer exists;
         the .ic on it is ignored -- refer to x_f[2] or x_r[2] instead.
   Please check line .ic v(x[2])=0.5
```

A `.ic v(x_f[2])=0.5` is accepted and holds under `uic`; a `.ic` on a node that never
existed keeps the generic message; a `.ic` on an `autobus` bit that was not split is
untouched.

## Verification

| check | result |
|---|---|
| scalar adapter, `[0:0]` adapter | the width-1 message with the bus-only rule; the old "equal width" text gone |
| three-port adapter; widths 5 and 3 | "exactly two bus ports (found 3)"; "different widths (5 and 3)" |
| a 5-bit adapter | still splits: `x_f[2]` 0.94111, `x_r[2]` 0.93935, `s2` 0.88046 |
| `.ic v(x[2])=0.5`, `.nodeset v(x[2])=0.5` on the split bus | the split message, `x_f[2]`/`x_r[2]` offered, no generic text |
| `.ic v(x_f[2])=0.5` under `tran uic` | 0.5 at t = 0, no warning |
| `.ic v(nosuch)=1`; `.ic` on an unsplit `autobus` bit | the generic message; 0.7 at t = 0 |
