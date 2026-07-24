# Builtin argument type-coercion gaps — format tasks + `ddx` (Enhancement-313)

Two independent defects found by grammar-based middle/back-end fuzzing (the campaign family
behind [E-307](../../enhancements_doc/Enhancement-307.md)–[E-310](../../enhancements_doc/Enhancement-310.md)),
both in `hir_ty` inference, both emitted silently by the shipped release compiler.

**(a) File/string format tasks were never type-checked.** `infere_display`
([hir_ty/src/inference.rs](../../OpenVAF-master-20260610/openvaf/hir_ty/src/inference.rs))
parses the format string and inserts the `int → real` cast a `%g`/`%e`/`%f`/`%r` conversion
needs — but only the **console** tasks reached it. The **file** (`$fdisplay`/`$fwrite`/
`$fstrobe`/`$fmonitor`/`$fdebug`) and **string** (`$swrite`/`$sformat`) tasks were missing, so a
`%g` fed an integer kept its integer value while the callback typed its parameter as `double`:
a raw `i32` passed to a `double` parameter — invalid LLVM IR. The verifier that catches this is
a `debug_assert!` (off in release), so release shipped a malformed `.osdi` whose callback reads
the integer's bits as a `double`. `fmt_roundtrip.va` makes it observable: format `5` with
`"%g"`, read it back, use it as a conductance — pre-fix the recovered value is the denormal
`2.47e-323`.

**(b) `ddx` with an integer argument crashed the compiler.** `infere_ddx` recorded the "must be
real" cast on the `ddx` **call** expression (already `Real`) instead of on the differentiated
**argument**; `needs_cast` then found `src == dst == Real` and tripped its debug_assert — release
aborted downstream with no `.osdi`. `ddx_integer.va` reproduces it.

Both fixes are output-preserving: the **419-model corpus produces byte-identical MIR** before and
after.

## Verify

```sh
python3 verify_vafargcoerce.py
```

Four checks under both solvers, all of which fail on the pre-fix binary: `ddx(integer, probe)`
compiles and simulates to `I = 1e-3·V`; `$sformat("%g", integer)` compiles and the round-tripped
value is exactly `5`. The OSDI models load from the prebuilt bundle via `SPICE_LIB_DIR` (set by
`_setup`); if unavailable the ngspice checks self-skip while the compile checks still run.

## Deferred

The same campaign found that a provably-infinite analog loop (`while (1) …`) crashes the
compiler via a degenerate (no-reachable-exit) CFG. That needs a design decision (reject with a
diagnostic vs. tolerate the CFG) and is left for a dedicated change — see the write-up.
