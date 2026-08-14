# Enhancement-457 — replication inside an assignment pattern

`'{ 4{0} }` did not compile:

```
error: unexpected token '{'; expected ','
```

The LRM uses this form in its own initializer examples, with the comment *"all
elements are initialized to 0.0 using an assignment pattern and replication
operator"*:

```verilog
real distort[0:2][0:2]      = '{ 3{ '{3{0.0}}}};
string above_0p5[0:2][0:2]  = '{ 3{ '{3{" "}}}};
```

Both were rejected, as was every simpler spelling — `'{4{0.0}}`,
`'{1.0, 2{3.0}, 4.0}`, and the same construct in a Laplace coefficient vector
(`laplace_nd(x, '{1}, '{2{1.0}})`). The only way to write an initialised array
was to spell every element out, which for the LRM's own 3×3 means nine copies of
the same number.

## Two constructs one apostrophe apart

The replication that *always* worked — `{4{0}}` — is the **concatenation**
operator (Enhancement-34). `'{4{0}}` is an **assignment pattern** (LRM 4.2.14), a
different construct that merely looks like it. The LRM flags the trap itself in
4.2.13, noting that `{ }` means concatenation in Verilog while C uses braces for
array initialisers.

`array_expr` parsed a plain comma-separated list of expressions: it read the
count `4` as an element, expected `,` or `}` next, met `{`, and stopped.

## The fix

The parser now recognises `count{ ... }` as a pattern element and builds the same
node shape `concat_expr` already produces for `{n{...}}` — children
`[count, elem0, ...]` — so `ReplicationExpr::count()`/`elems()` read it unchanged.

Expansion happens where the count can be folded, and it had to happen in **one**
place rather than three. A `'{...}` literal is walked by three separate pieces of
code: the leaf **count** checked against the declared array size, and the two
per-element extractors (array variables, array parameters). Each counted a
replication as a single leaf. They now share one walker, `flatten_pattern`, so
the count and the elements cannot disagree — a pattern that expands to the right
*length* but the wrong *contents* would satisfy the size check and still be
wrong.

A count that will not fold, is negative, or exceeds a cap of 2²⁰ leaves the
element unexpanded. It then reads as one leaf and the ordinary length-mismatch
diagnostic reports it, rather than a silently mis-sized array. The cap mirrors
Enhancement-34's for the same reason: a replication count is a size read from
source, and a size has to be bounded before it is acted on.

## Verification

**`examples/patternrep_examples` — 25/25** under both solvers, and **10/20 on
the previous compiler**.

The suite checks **values, not just acceptance**. Every array carries distinct,
checkable numbers rather than a repeated `0.0`, because the interesting failure
mode is an expansion of the correct length holding the wrong contents:

| pattern | expands to | checked |
|---|---|---|
| `'{4{2.5}}` | 2.5 ×4 | `quad[0]+quad[3]` = 5.0 |
| `'{1.0, 2{3.0}, 4.0}` | 1.0, 3.0, 3.0, 4.0 | `mixed[1]+mixed[2]` = 6.0 |
| `'{2{1.0,2.0}}` | 1.0, 2.0, 1.0, 2.0 | all four = 6.0 |
| `'{ 3{ '{3{0.5}}}}` | a 3×3 of 0.5 | `grid[0][0]+grid[2][2]` = 1.0 |
| `'{4{1.5}}` (a *variable*) | 1.5 ×4 | `vals[0]+vals[3]` = 3.0 |

That check earned its place: it caught a real bug during development — a mixed
pattern whose length was right and whose middle elements were not.

Refused as before, and pinned: a count of 3 or 5 into `[0:3]`, a zero count, a
negative count, a count of 99999999, and a non-constant count. Untouched and
pinned: spelled-out patterns, nested 2-D patterns, single-element patterns, and
the `{n{...}}` concatenation operator.

**Corpus: 107 compiled by both, 17 rejected by both, 0 rc differences, 0 byte
differences** — measured against the pre-Enhancement-455 binary, so it covers
E-455, E-456 and this change together. `cargo test` passes across all test
binaries. Full regression **371/371**, both solvers.

`lrm_examples` is unaffected: the LRM example containing these initializers,
`limitations/lrm_p045_4.va`, is pinned on a *different* diagnostic (`refers to
module 'gen'`, from the undefined `gen`/`sink` modules), which still fires. The
replication gap had been masked behind that earlier error and was never recorded
separately.

## A trap worth recording

The value check first reported `mixed[1]+mixed[2]` as **1.0** instead of 6.0, and
the compiler was innocent — the model named its operating-point variable `m`, and
**every ngspice instance already has an `m` multiplier parameter**, so `@n1[m]`
read the multiplier (1.0) rather than the model's variable. The opvar is now
`mx`, with the reason recorded in the suite so it is not reintroduced.
