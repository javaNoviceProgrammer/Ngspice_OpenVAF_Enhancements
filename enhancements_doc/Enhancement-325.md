# Enhancement-325 — bound the *materialized size* of `{...}` / `{n{...}}`

Enhancement-314 capped the replication **count** at 2²⁰ after a
`{'d999999999{"x"}}` DoS. The count is only one factor of the final size, so two
abusive shapes still reached the **shipped** compiler. Both were found by the
seven-strategy fuzz campaign (~75 000 generated models).

## The two shapes

**A — string replication becomes LLVM function arity (compile-time hang).**

```verilog
parameter string s = {200000{"x"}};
```

`lower_string_concat` builds an `elems.len() * rep_cnt` operand list and a format
string with that many `%s`, and `print_callback` turns that into a generated LLVM
callback with **one parameter per operand**. LLVM degrades super-linearly in
function arity — measured on this compiler:

| operands | compile time |
|---:|---:|
| 2 000 | 0.4 s |
| 8 000 | 2.9 s |
| 16 000 | 8.6 s |
| 32 000 | did not finish |

So one line of source hung the compiler. (The original hypothesis — quadratic
string interning in the const-folder — was wrong; the const-fold is linear and
negligible. The cost is entirely in LLVM.)

**B — the product overflows the `u32` array length.**

```verilog
real c[0:1];
c = {1048576{{1048576{1.0}}}};       // 2^20 * 2^20 = 2^40
```

Each count is individually legal (exactly `MAX_REP`), but the size was computed as
an unchecked `u32` multiply, `len: total * rep_cnt`. Under overflow-checks that
panicked; in the **shipped release** it silently **wrapped to 0**, producing the
nonsense diagnostic `expected real[0:2] value but found real[0:0] value`. The
running total `total += len` was equally unchecked.

## The fix

The size is now computed in `u64` with saturating arithmetic and bounded *before*
it is narrowed to the `u32` length, with a dedicated `ConcatTooLarge` diagnostic
that reports the true expanded size. Two limits, because the two paths have
genuinely different cost profiles (both measured):

| path | limit | why |
|---|---|---|
| numeric array | `MAX_CONCAT_ELEMS = 2²⁰` | linear and cheap — 65 536 elements compile in 0.41 s; this only rules out the absurd and guards the `u32` length |
| string | `MAX_CONCAT_STR_OPERANDS = 4096` | becomes LLVM function arity, which is super-linear; 4096 keeps the worst case near a second |

Reusing the existing `InvalidReplicationCount` diagnostic would have been
misleading — in case B the count *is* a valid positive literal; it is the product
that is too large — so this is a new, precise diagnostic:

```
error: concatenation/replication expands to too many elements
4 |   analog c = {1048576{{1048576{1.0}}}};
  |              ^^^^^^^^^^^^^^^^^^^^^^^^^ expands to 1099511627776 elements
  = help: a `{...}` concatenation is materialized at compile time; this one would
          expand to 1099511627776 elements, above the limit of 1048576
```

Note `1099511627776` = 2⁴⁰: the u64 arithmetic reports the true size where the
u32 computation wrapped to zero.

## LRM position

`{n{...}}` over strings and 1-D arrays is this project's Enhancement-34 extension —
Verilog-A (LRM Annex C) has no vector concatenation at all, and Verilog-AMS defines
`{}`/`{n{}}` over bit vectors. So there is no LRM-mandated semantics being
violated: a compiler is entitled to a documented limit on how large a compile-time
expansion it will materialize, exactly the precedent E-314 set. For case B the
position is stronger still — any expansion larger than the destination is a *type
error* today; the only defect was that the compiler computed the size wrongly
before it could say so. No legal program changes meaning.

## Output preservation

`u64` saturating add/mul agree exactly with the old `u32` wrapping arithmetic for
every value below 2³², and both caps are checked *before* the narrowing — so any
model whose concatenation fits (every real one) takes a bit-identical path.
Confirmed against the corpus with the deterministic `--dump-mir` oracle.

## Files

- `OpenVAF-master-20260610/openvaf/hir_ty/src/inference.rs` — the two limits, the
  `u64` size arithmetic, the two bound checks, the `ConcatTooLarge` variant.
- `OpenVAF-master-20260610/openvaf/hir_ty/src/diagnostics.rs` — its rendering.
- `examples/vafconcatsize_examples/` — the three abusive shapes are rejected
  cleanly (they hang or misreport on the pre-fix binary) plus a forward guard that
  legitimate concatenation compiles *and simulates*
  (`verify_vafconcatsize.py`, 6 checks).
