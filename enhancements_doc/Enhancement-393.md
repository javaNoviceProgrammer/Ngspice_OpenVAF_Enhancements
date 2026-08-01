# Enhancement-393 — a `localparam` may index a bus, not merely size one

A `localparam` is fixed at elaboration — the LRM forbids overriding one
externally — and this compiler already accepted it as a constant nearly
everywhere: array bounds, bus widths, parameter defaults, `repeat` counts, and,
since [E-392](Enhancement-392.md), `generate` bounds. A **bit-select index** was
the exception:

```verilog
localparam integer K = 3;
electrical [0:5] n;
...  V(b, n[K]) ...        // error: bus bit-select index must be a constant
```

E-392 left this open and named it: *"a localparam sizes a bus but still cannot
index one."* This closes it.

The same gap also rejected a plain constant expression of literals — `n[2+1]` —
because the index folder recognised only a bare literal, optionally negated.

## Three places resolve a bit-select

All three had to change, and two of them could not be fixed the same way as the
first, because they run **before name resolution** and so cannot ask for a
parameter's value at all:

| | where | folded by |
| --- | --- | --- |
| 1 | an index in the analog body | `hir_ty`'s inference |
| 2 | a **branch endpoint**, `branch (n[K], n[0])` | `item_tree::lower`, while the item tree is built |
| 3 | a **port connection**, `kid c(.p(bus[K]))` | the instantiation elaborator, by synthesizing the textual name `bus[K]` |

(1) is fixed semantically: the index folder resolves the localparam and continues
the fold **inside that parameter's own body**, which has its own expression arena
and its own scopes.

(2) and (3) are fixed in the textual declaration pre-pass that already folds
parameter-dependent *widths* ([E-91](Enhancement-91.md)/[E-92](Enhancement-92.md))
— the only point early enough to serve them. It gains a fourth pass that folds a
**single-index** bracket; ranges and part-selects, which contain a `:`, remain
the business of the width pass that already owns them.

## Which names may be folded is the whole question

Both halves answer it identically, and that agreement is the design. Only what is
fixed before the OSDI descriptor exists:

- a `localparam`, and a localparam built from other localparams;
- a `parameter` that E-92 froze **into** a localparam because it shaped a
  declaration width. Indexing the very bus that parameter sized is then
  consistent by construction — the width and the index move together or not at
  all.

A plain `parameter` is refused, and so is a localparam whose value is built from
one. A parameter binds at simulation time, and baking its default into a node
selection would silently ignore an override from the model card — the failure
would be invisible, since the model would compile and simulate, just against the
wrong node.

The semantic folder gets this right **structurally** rather than by a special
case: folding such a localparam requires folding the parameter it is built from,
which it will not do, so the whole chain returns "not constant". The textual pass
mirrors it by seeding its fixpoint only from names that are already
elaboration-constant, so a chain can never grow out of a parameter.

## The distinction that had to be preserved

`hir_ty` already had a `const_int_expr`, and merging the new folder into it would
have been the obvious move. It would also have been wrong, because the two ask
**different questions**:

- `const_int_expr` asks *"is this a constant the code generator can see?"* Its
  job is to spot operations LLVM defines as poison ([E-333](Enhancement-333.md)/
  [E-334](Enhancement-334.md)). A localparam is lowered as a runtime value, so it
  is deliberately excluded there — which is why a localparam zero divisor still
  compiles, as `vafcodegen_examples/constfold.va` asserts.
- the new folder asks *"is this fixed before the OSDI descriptor is built?"*,
  which a localparam is by definition.

They are kept separate, each with the comment saying why. Folding a localparam in
the first would have turned a working model into a compile error.

## Verification

`examples/vafconstidx_examples` — **25/25 fixed, 11/25 against the E-392
binary**.

Compiling is not the claim; selecting the *right* element is. Every accept case
is simulated over a three-resistor ladder and compared against the literal
spelling of the same index, where tapping the wrong node gives a different
current. That covers all three resolution paths, both bus directions, expressions
(`K+1`, `K*3`, `K/2`, `2+1`, `7/2`), a localparam built from another, the E-92
composition, variable arrays (read *and* write), parameter arrays and a 2-D
array.

The reject half is equally load-bearing: a plain parameter as an index and as a
branch endpoint, a localparam derived from a parameter, a runtime index into a
vectored net, and an oversized literal all still fail — and an out-of-range
localparam index now reports *out of range* rather than *not a constant*.

Beyond the suite:

- **corpus byte-differential against the E-392 build, same `-o` path**: 92/92
  industry compact models and 402 of the repo's own example models
  **byte-identical**, with **zero** bytes differing and **zero** newly-rejected
  files. The only change is two newly-*accepted* files (below), which is exactly
  the shape an additive fix should have.
- workspace tests 209 passed / 0 failed
- full regression **317/317**

### The LRM's own RC-line example now compiles

`lrm_p169_1.va` and `lrm_p169_2.va` (LRM 2023 page 169) graduate from
`limitations/` to `va/`. Between them they needed three enhancements to
elaborate, and the chain is worth reading as one story:

1. [E-96](Enhancement-96.md) — the bare module-level `generate for`, written
   without the `generate`/`endgenerate` keywords, parses;
2. E-92 + E-392 — the loop bound `N` also sizes `electrical [0:N] n`, so E-92
   freezes `N` into a localparam and E-392 accepts a localparam as a bound;
3. E-393 — the analog block's `n[N]` resolves.

The suite's documented-limitations count drops from 17 to 15.
