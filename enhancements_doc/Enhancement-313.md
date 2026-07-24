# Enhancement-313 — openvaf-r: builtin argument type-coercion gaps (format tasks + `ddx`)

Found by grammar-based middle/back-end fuzzing (the same campaign family that produced
E-307…E-310): generate well-typed Verilog-A that reaches HIR → MIR → autodiff → codegen and
run it through an assertions-enabled build. Two independent defects surfaced, both in
`hir_ty`'s inference, both producing code the **shipped (release) compiler emitted silently** —
one an observable miscompile, one a hard crash.

## (a) File/string format tasks were never type-checked → invalid IR / miscompile

`infere_display` parses a format string and, for each conversion, records the argument type it
requires — inserting the `int → real` cast a `%g`/`%e`/`%f`/`%r` conversion needs. It was
reached only by the **console** tasks:

```rust
BuiltIn::write | display | strobe | monitor | debug | warning | error | info | fatal
    => self.infere_display(stmt, args),
```

The **file** tasks (`$fdisplay`/`$fwrite`/`$fstrobe`/`$fmonitor`/`$fdebug`) and **string** tasks
(`$swrite`/`$sformat`) were missing from that dispatch, so their format arguments were never
checked. A `%g` fed an integer kept its integer value, while the formatting callback types its
parameter as `double` (`print_callback` in `osdi/compilation_unit.rs` builds the signature from
the conversion). Lowering therefore passed a raw `i32` to a `double` parameter:

```
Call parameter type does not match function signature!
  i32 3
   double  %35 = call fastcc ptr @cb.2(ptr %0, ptr @str.3, i32 3)
```

That is **invalid LLVM IR**. The module verifier catches it — but the verifier is a
`debug_assert!`, compiled out of the shipped release build, so release emitted a malformed
`.osdi`. At runtime the callback reads the integer's bit pattern as a `double`: garbage. The
example makes it observable — format `5` with `"%g"`, read it back with `$sscanf`, use it as a
conductance: the recovered value is the denormal `2.47e-323` (the bits of the integer `5`)
instead of `5`.

**Fix:** add the file and string format builtins to the `infere_display` dispatch.
`infere_display` scans for string-**literal** format strings, so the leading file descriptor
(an integer) or destination (a string variable) argument is naturally skipped and the real
format string is found — the console path's exact logic now applies to every format task.

## (b) `ddx` with an integer argument crashed the compiler

`infere_ddx` requires its first argument (the value being differentiated) to be real:

```rust
if let Some(ty) = self.infere_expr(stmt, val) {
    self.expect::<false>(expr, None, ty, &[TyRequirement::Val(Type::Real)]);   // wrong target
}
```

`expect` records any needed cast on its **first** argument. It was handed `expr` — the whole
`ddx` call — but `ty` is the type of `val`, the first *argument*. When `val` is an integer,
`expect` records an `int → real` cast **on the `ddx` call expression**, which already has type
`Real`. `needs_cast` then computes `src = Real` (the call's type) and `dst = Real` (the recorded
cast), trips `debug_assert_ne!(src, dst, "cast types must be different")`, and — with the assert
compiled out — the release build aborts downstream with no `.osdi` (`ddx(n, V(b))` for integer
`n`).

**Fix:** record the requirement on `val`, the argument being differentiated, not on `expr`. An
integer argument is then correctly coerced to real (the derivative of a probe-independent value
is `0`), and a real argument is unchanged (no cast needed either way).

## Why it is safe

Both fixes only add the coercion/type-check that was missing on a **previously-crashing or
previously-invalid** path; no valid model relied on the broken behavior. The whole **419-model
corpus produces byte-identical MIR before and after** (deterministic `--dump-mir` oracle,
`0/419` changed), the corpus replays cleanly through the assertions build, and a 15,000-module
re-fuzz on the fixed compiler is clean.

## Verification

`examples/vafargcoerce_examples/verify_vafargcoerce.py` — 4 checks under both solvers, all of
which **fail on the pre-fix binary**: (1) `ddx(integer, probe)` compiles (crashed before);
(2) its model simulates to `I = 1e-3·V` (the `ddx` term is `0`); (3) `$sformat("%g", integer)`
compiles (invalid IR before); (4) the round-tripped `%g` value is exactly `5` — the pre-fix
release reads the garbage denormal `2.47e-323`.

## Scope of change

`openvaf/hir_ty/src/inference.rs` only: the `infere_display` dispatch arm and one argument in
`infere_ddx`. No interface change.

## Not fixed here (separate, deferred)

The same fuzz campaign also found that a **provably-infinite analog loop** (`while (1) …`)
crashes the compiler: the constant-true condition leaves the loop-exit block unreachable, and
the resulting degenerate CFG (no reachable exit) aborts the aggressive-DCE / control-flow passes
(shipped: release aborts with no `.osdi`). A minimal `mark_inst_live` guard stops the DCE
`unwrap`, but the crash then resurfaces in the CFG-validity machinery — a complete fix needs a
design decision (reject non-terminating analog loops with a diagnostic, or make the passes
tolerate an unreachable exit) and is left for a dedicated change.
