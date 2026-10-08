# Enhancement-806: a Verilog-A child's internal node answers to `n1#c1.mid`, and a vector holding a subcircuit instance to its short form `onoise_x1.n1_thermal`

**Scope:** D12 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/vectors.c`: `vec_fromplot` tries two more spellings when a name is not in the plot
  (`e806_alias`, `e806_short_form`).
- `frontend/outitf.c`: `name_eq` matches the hierarchical spelling (`.save`, and a `.meas`
  card's vector); the file includes `dstring.h`.
- `spicelib/analysis/cktsetnp.c`: `CKTapplyPendingNodPm` places a `.ic` or `.nodeset` on it
  (`e806_flat_internal`).

`examples/osdislips_examples/` (section [12], seven checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 93 of 93 per solver (5 of the 7
in [12] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

A Verilog-A module that instantiates a child is flattened: child `c1`'s internal node `mid`
becomes the device node `n1#c1__mid`, and a grandchild's `n1#g1__k1__mid`. Only that mangled
spelling worked. The hierarchical one, the way the source writes the path, was refused
everywhere:

```
print v(n1#c1.mid)            Warning from checkvalid: vector n1#c1.mid is not available
.ic v(n1#c1.mid)=0.5          Warning : IC on non-existent node - n1#c1.mid, ignored
.save v(n1#c1.mid)            Warning: save 'n1#c1.mid': nothing of that name is in this analysis
```

Separately, a vector whose name holds a device inside a subcircuit spells that device the way
ngspice flattens it: `n.x1.n1`, the type letter prefixed. A noise contribution is
`onoise_n.x1.n1_thermal`. `print`, `alter` and `show` accept `x1.n1` for the device itself
(E-410), but `onoise_x1.n1_thermal` was "not available".

## The change

When a name is not found as written, three lookup paths try the other spelling. A name that is
found as written is never re-read.

- **Vectors** (`vec_fromplot`, used by `print`, `let`, `plot` and `.meas`): two fallbacks.
  - A name with a `.` after its `#` is tried with each such `.` as `__`. So `v(n1#c1.mid)` finds
    `n1#c1__mid`, and `v(x1.n1#c1.mid)` goes on to E-428's subcircuit spelling.
  - The plot's vectors are tried by their E-410 short form: a `<c>.` before an `x…` path whose
    last segment begins with the same letter `c` is dropped. That is `onoise_n.x1.n1_thermal`
    read as `onoise_x1.n1_thermal`. The scan runs only for a name with a `.` and an `x`-led
    segment, so the many failed lookups of constants do not pay for it.
- **Saves** (`name_eq` in `beginPlot`): `.save v(n1#c1.mid)` and a `.meas` card's vector match
  the flattened name. E-428's subcircuit form is applied after the translation.
- **`.ic` and `.nodeset`** (the pending-node placement of E-608): the translated name is placed.
  A name that is no internal node is still refused with E-608's message.

The canonical spelling stays `n1#c1__mid`: it is what `display` lists and the raw file holds.

## The checks

osdislips [12]:

- `print v(n1#c1.mid)` and `v(n1#g1.k1.mid)` read the flattened nodes;
- `.save` and a `.meas` card take the hierarchical spelling;
- `.ic v(n1#c1.mid)=0.5` is applied;
- `.nodeset` takes it, and `n1#nosuch.mid` is still refused;
- `onoise_x1.n1_thermal` is `onoise_n.x1.n1_thermal`;
- a short form that names nothing is still "not available".

## Limits

- `.ic`, `.nodeset` and `.save @…` still refuse the `x1.n1` spelling of a subcircuit device's
  node or parameter. That is the hunt's F3, a separate finding.
