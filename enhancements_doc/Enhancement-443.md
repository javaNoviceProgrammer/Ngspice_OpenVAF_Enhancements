# Enhancement-443 — index lists

Enhancement-221 gave a node field `base[lo:hi]`, and Enhancement-441 gave an
instance name the same. Both now also read an explicit list, and the two written
together:

```
base[lo:hi]        a range            a[0:3]    ->  0 1 2 3
base[i,j,k]        a list             a[1,3,5]  ->  1 3 5
base[lo:hi,k,...]  both               a[0:1,7]  ->  0 1 7
```

Every reading those two enhancements established carries over unchanged, because
only the *source of the indices* is new:

```
X1       a[1,3,5,7] sub      one instance, four terminals        (E-221)
R[1,3,5] a 0 1k              three resistors r[1], r[3], r[5]    (E-441)
R[1,3,5] a[2,4,6] 0 1k       r[1] a[2] ... r[3] a[4] ... r[5] a[6]
R[0:2]   a[1,3,5] 0 1k       the two spellings mix across a line
```

Indices are used in **written order** — neither sorted nor deduplicated —
because the order is what binds nodes to terminals. A descending list is
therefore just a list; there is no direction to get wrong, which is why
Enhancement-411's reversed-binding warning still fires for `a[1:0]` and stays
quiet for `a[3,1]`.

## The one rule that keeps every existing netlist reading the same

**A lone `a[2]` is not a list.** It is a scalar bus *bit* and stays a node name.
Enhancement-221's contract is that `a[0:1]` and an explicit `a[0]` denote the
same node, so a single item with no comma and no colon is refused by the reader.
That single condition is what makes this change additive: every deck that parses
today parses identically, because the only spellings that now mean something new
are ones that previously meant nothing.

## One reader, four consumers

The parse is split in two: `inp_bus_indices()` reads the contents between the
brackets, and `inp_bus_index_parse()` validates the base name around it. Four
places consume it, and they cannot drift apart about what a list is:

| consumer | what a list means there |
|---|---|
| `inp_expand_bus_token` | a sequence of node tokens (E-221) |
| `inp_expand_array_instances` | a sequence of cards, node lists in step (E-441) |
| `inp_bus_rewrite_wrapped` | one copy of `v(a[i])` per index (E-408) |
| `inp_bus_looks_malformed` | the diagnostic below |

The wrapped path matters for `.save`, `.print`, `.ic` and `.nodeset` cards:
`.save v(a[1,3,5])` now saves exactly those three, and `.save v(a[0:1,5])`
exactly those three. Its previous range-specific parse is gone rather than left
beside the shared one, so there is no second definition to fall behind.

## A malformed list is reported, not quietly used

`R2 a[1,] 0 1k` is not merely an oddly named node. The stray comma re-tokenises
the line, and ngspice went on to build a resistor with **no value** — warning
only that the value was "too small, set to 1e-12" — from a deck whose author
believed they had named two nodes. That is a silent miswire in the syntax this
change introduces, so a bracket group that looks like an index list and is not
one now says so.

The test is deliberately tight, so it cannot fire on a deliberate but exotic
name: the base must be a plain node name and the bracket contents must consist
only of the characters an index list is written with. `mem[addr]` is silent,
`a[2]` is silent, and `a[1,]`, `a[,1]`, `a[1,,2]`, `a[1:2:3]` and `a[]` are all
reported.

A length mismatch on an array instance keeps E-441's treatment: named, and the
deck rejected — `R[1,3,5] a[2,4] 0 1k` cannot be half-expanded into something
that parses.

## Verification

* **`examples/idxlist_examples` — 26/26, both solvers.** Structural checks are
  paired with electrical ones: three 1 kΩ in parallel against 250 Ω read
  0.571428…, and the in-step ladder is checked against its analytic divider
  value, because a wrong expansion still simulates. The controls are the point
  of the suite — a lone `a[2]` still a scalar bit and silent, a non-numeric
  `mem[addr]` left alone and silent, E-221's plain range unchanged, E-441's
  plain range instance unchanged, and E-411 warning for `a[1:0]` but not
  `a[3,1]`.
* **Full regression 354/354**, both solvers.
