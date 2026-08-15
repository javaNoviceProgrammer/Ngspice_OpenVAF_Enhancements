# Enhancement-459 — a part select as a filter coefficient vector

LRM Syntax 4-3 gives an analog filter's coefficient argument three forms:

```
analog_filter_function_arg ::=
      parameter_identifier
    | parameter_identifier [ msb_constant_expression : lsb_constant_expression ]
    | constant_assignment_pattern_or_null
```

Enhancement-458 implemented the first and the third. The middle one was rejected:

```
error: wrong number of array indices
  |
  |  I(p,n) <+ laplace_nd(V(p,n), nu[0:0], de[0:1]);
  |                                        ^^^^^^^ expected 1 index/indices, found 2
```

It is the form a model reaches for when it keeps one coefficient table and hands
each filter the slice it needs — the alternative is a separate array parameter
per filter, with the duplication that implies.

## Why it looked like it needed new syntax

`de[0:1]` and Enhancement-15's multi-dimensional `m[i][j]` both arrive at
inference as `Expr::BitSelect` carrying **two index expressions**. Read there, a
part select of a 1-D array is indistinguishable from two indices into a 2-D one,
which is exactly what the diagnostic said.

They are distinguishable one layer up, and the machinery was already in place:

- the parser keeps the `:` token in the tree (Enhancement-85), and
- body lowering records every part select it sees in `stray_part_selects`.

So no syntax work was needed. Inference resolves such an argument into its
element slice and records it in the same whole-array maps a bare array identifier
uses (`array_var_refs` / `array_param_refs`), and lowering carries it from there
unchanged — parameter elements lower to parameter reads, variable elements to
variable reads, exactly as the full-array form already did.

## Consuming the expression is what makes it legal

Enhancement-85 reports every part select left in a body: they are otherwise valid
only in instance port connections, which elaboration consumes textually and never
body-lowers. That check is what rejected this form even once inference understood
it.

Body validation now skips exactly those part selects that inference resolved into
a whole-array argument, and reports the rest as before. The restriction therefore
stands everywhere else, which the suite pins: `y = de[0:1];`, `de[0:1] * 2.0` and
`I(p,n) <+ de[0:1];` are all still refused, and an ordinary single-element
`de[1]` is untouched.

## Order is not cosmetic

The slice is built in the order written — `de[0:1]` is `{de[0], de[1]}` and
`de[1:0]` is `{de[1], de[0]}`. A Laplace coefficient *k* multiplies *sᵏ*, so a
reversed slice is a **different filter**, and pinning that is the difference
between testing the feature and testing that it compiles.

With `de = '{1.0, 1e-6, 9.0, 9.0}`, the slice `de[0:1]` is the denominator of
*H(s) = 1/(1 + 1e-6·s)*:

| written as | response at t = 5 µs |
|---|---|
| `'{1.0}, '{1.0, 1e-6}` (literal) | 4.00674 |
| `nu[0:0], de[0:1]` (parameter slice) | 4.00674 |
| `nv[0:0], dv[0:1]` (variable slice) | 4.00674 |
| `nu[0:0], de[1:0]` (reversed) | 1.25e-05 |

The forward slice matches the literal to the digit; the reversed one does not.
`de[0:3]` gives exactly what the bare identifier `de` gives.

## The trap: `zi_*` needed one more fix than `laplace_*`

With inference resolving the slice, the Laplace filters worked immediately and
the Z-transform filters still reported `wrong number of array indices`.

The Laplace filters resolve their array arguments in their own inference arm and
never look at them again. `zi_*` has no such arm: Enhancement-458 pre-resolves
its arrays and then falls through to the generic signature match — which called
`infere_expr` on the slice, reached `infere_bit_select`, and counted the two
range bounds as two indices into a 1-D array. The error being fixed, reappearing
one layer up.

`infere_expr`'s `BitSelect` arm now returns the recorded array type for an
expression already resolved as a whole-array argument, the same early return its
`Path` arm needed in Enhancement-458 for a resolved array parameter. That is the
second time this asymmetry has cost a fix, and it is written down in both places.

## Not to be confused with Enhancement-85's suite

`examples/partselect_examples/` already existed: it covers part selects in
instance **port connections**, which is where they have always been legal, and
its last check pins that a part select in behavioural code is refused with the
dedicated diagnostic. That check still passes here — the restriction is narrowed
to one position, not lifted — and this change's suite lives beside it under
`filterslice_examples` rather than inside it.

## Verification

`examples/filterslice_examples/verify_filterslice.py` — **20/20**, both solvers:
the value equivalences and the reversed-slice check above; all eight filters
(`laplace_nd/zd/np/zp`, `zi_nd/zd/np/zp`) accepting a slice; three out-of-range
spellings (`de[0:9]`, `de[-1:1]`, `de[4:4]`) refused with `bus bit-select index
out of range` and never a crash; and Enhancement-85's restriction still holding
in four places.

Enhancement-458's `lrmfuncs` suite recorded this form as a known gap pinned as
*rejected*; that pin is now *accepted* — **228/228**, both solvers — with the
detail left to the suite above.

**Corpus: 107 compiled by both, 17 rejected by both, 0 rc differences, 0 byte
differences**, measured against the Enhancement-458 binary. `cargo test` passes
across 44 test binaries. Full regression **373/373**, both solvers.
