# Enhancement-34 — `{...}` concatenation & `{n{...}}` replication

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to implement the Verilog-AMS **concatenation** and **replication**
operators properly. Purely front-end (`parser` → `syntax` → `hir_def` → `hir` →
`hir_ty` → `hir_lower`); no OSDI/ngspice change.

## The two brace constructs

Verilog-AMS has two distinct brace constructs that OpenVAF previously conflated:

| syntax | construct | OpenVAF before E-34 |
|--------|-----------|---------------------|
| `'{...}` | array **aggregate** literal (assignment patterns, incl. nested `'{'{..},..}` for N-D arrays) | supported (E-4/14/15) |
| `{...}` | **concatenation** operator; `{n{...}}` replication | parsed as just another spelling of the aggregate literal |

Because `{...}` was treated as an aggregate literal: whole arrays could not appear
inside it (`{p, q}` → "requires a bit-select"), the replication form `{n{...}}`
did not parse at all (`unexpected token '{'`), and string operands produced a
useless *string array* instead of the LRM's concatenated string.

## What Enhancement-34 implements

`{...}` is now the real concatenation operator:

- **numeric concatenation** flattens its operands in order — scalars, whole-array
  variables, aggregate literals, nested concatenations — into one flat 1-D array
  value: `w = {half1, {3{k2}}, 3.0*k2};`
- **replication** `{n{...}}` repeats the flattened operand list `n` times, where
  `n` is a positive compile-time integer literal (diagnosed otherwise);
- **string concatenation**: if any operand is a string, all must be, and the
  result is a runtime-concatenated **string** — `{"volt","age"} == "voltage"`,
  including replication (`{2{"ab"}} == "abab"`). Lowered through the proven
  `$swrite`/`$sformat` machinery (a `PrintDst::String` print callback with a
  `"%s%s..."` format, so operand data is never interpreted as a format string);
- usable **everywhere an array value is consumed**: array assignment, whole-array
  function arguments, `laplace_*`/`zi_*` coefficient vectors, `case`
  discriminants/items;
- element typing: the result is `real` if any operand is real (integer *scalars*
  are cast, exactly like aggregate-literal elements; an integer *array* mixed
  into a real concatenation is a type error, since array elements have no
  per-element cast machinery).

`'{...}` aggregates are completely untouched.

## Implementation sketch

- **parser/syntax**: `'{...}` and `{...}` now produce different nodes
  (`ARRAY_EXPR` vs new `CONCAT_EXPR`/`REPLICATION_EXPR`; the replication node's
  children are `[count, elem0, elem1, ...]`).
- **hir_def/hir**: new `Expr::Concat { rep: Option<ExprId>, elems }`.
- **hir_ty**: `infere_concat` types the expression (string mode vs flattened
  array, constant replication count, casts, diagnostics — new
  `InvalidReplicationCount`/`EmptyConcat` diagnostics); array assignment gains a
  concat case that expands into per-destination-element sources
  (`ArrayAssign::Concat`, each element either a scalar expression or a source
  array-element variable), which the existing mixed `Val`/`Copy`
  `ArrayAssignElem` machinery consumes unchanged.
- **hir_lower**: `lower_array_elems` (the shared array-expression flattener from
  E-33) flattens concat operands recursively and repeats the list for
  replication, which makes concat work in every array-consuming context for
  free; a string-typed concat lowers via a new `lower_string_concat` helper on
  the E-11 formatting machinery.

### Behaviour change

`{...}` no longer denotes an aggregate literal. For the common flat scalar list
(`x = {1.0, 2.0}`) concatenation produces the identical result, so nothing
breaks; but a *nested* bare-brace literal (`{{1,2},{3,4}}`), previously a 2-D
aggregate spelling, now **flattens** (concatenation semantics — and 2-D
destinations require `'{'{..},'{..}}`, the LRM aggregate form, as all shipped
examples already use).

## Verification — `concat_examples/`

`concat_demo.va` assembles a 6-tap coefficient vector by concatenation +
replication (`w = {half1, {3{k2}}, 3.0*k2}`), feeds a concat-built vector with
integer scalars to an averaging function (`avg4({1, 3, 2.0, 2.0})` — casts), and
gates the output branch on a runtime string concatenation
(`{"con","cat"} == "concat"`). `verify_concat.py` (ALL PASS):

1. it compiles (array operands / replication / string concat all used to fail);
2. the DC conductance equals `2·(3·k1 + 6·k2)` **exactly** for two parameter
   sets — proving the concatenated coefficient vector, the replication, the
   integer casts and the string gate all evaluate correctly;
3. `{0{...}}` and a non-literal replication count are clean diagnostics.

Additionally exercised during development: concat as `laplace_nd` coefficient
vectors, as a `case` discriminant, string replication, and replication of a
mixed scalar/array list (`{2{p, 10.0}}`). Regressions: 15 example verify suites
(all array-family + string/file I/O + analysis/portflow/intstate) ALL PASS, and
`laplace_variants`/`zi_lpf`/`bessel5` compile unchanged.
