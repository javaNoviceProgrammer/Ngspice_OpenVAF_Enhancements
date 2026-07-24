# Const-eval / literal-materialization robustness (Enhancement-314)

Two openvaf-r defects from grammar-based fuzzing (the [E-307](../../enhancements_doc/Enhancement-307.md)–[E-313](../../enhancements_doc/Enhancement-313.md) family):

**(a) Integer const-fold overflow.** Two hand-rolled integer const evaluators used unchecked
i32 arithmetic — `elaborate.rs`'s Enhancement-91 bus-width folder (`+`/`-`/negate; its `*` was
already checked) and `const_eval.rs`'s MIR const-fold (`Ineg`, which Enhancement-286 missed when
it made the binary ops wrapping). `localparam integer k = 2147483647 + 1;` or `-(1<<31)` aborted
the overflow-checked build. Fixed with checked (elaborate) / wrapping (const_eval) arithmetic.

**(b) Unbounded replication → compile-time DoS.** `{N{...}}` materializes N copies at compile
time; `{'d999999999{"x"}}` (~1e9) allocated gigabytes and **hung** the shipped compiler on one
line of source. Fixed by capping the count at 2²⁰ in `concat_rep_count` and rejecting an abusive
count with a clean diagnostic.

Both output-preserving: checked/wrapping ≡ plain on non-overflow inputs, and the cap only rejects
counts above 2²⁰.

## Verify

```sh
python3 verify_vafconstlit.py
```

Four checks under both solvers. The replication check fails on the pre-fix binary (it hangs);
the overflow model is a forward correctness guard (that defect is assertions-only). The OSDI
model loads from the prebuilt bundle via `SPICE_LIB_DIR` (set by `_setup`); if unavailable the
ngspice check self-skips.
