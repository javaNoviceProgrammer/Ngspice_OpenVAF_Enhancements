# Enhancement-7 — `@(initial_step)` event gating and variable persistence (version8)

While scoping `cross()`/`above()`/`timer()` (all three are only valid
inside `@(...)` event-control statements, per the LRM), this enhancement
found and fixed a foundational, pre-existing gap those operators — and a
large fraction of real-world Verilog-A models — depend on: **event-control
statements didn't gate anything, and ordinary analog-block variables didn't
persist their value across evaluations at all.** `cross()`/`above()`/
`timer()` and `generate`/`genvar` blocks are deferred to **Enhancement-8**
(see §5) now that this foundation is in place.

## 1. `@(initial_step)` / `@(final_step)` didn't gate execution at all

**Root cause**: `openvaf/hir_lower/src/stmt.rs`'s `Stmt::EventControl`
lowering discarded the `event` field entirely and unconditionally lowered
the body — `@(initial_step) foo();` behaved identically to bare `foo();`,
every evaluation, forever. Verified with a real simulation before the fix
(a reset statement that should only fire once kept firing on every
timepoint).

**Fix**:
- New `ParamKind::IsInitialStep` — a simulator-provided boolean, true only
  on an instance's first-ever `eval()` call (`openvaf/hir_lower/src/lib.rs`).
- `Stmt::EventControl` now genuinely branches on it for `@(initial_step)`
  (`openvaf/hir_lower/src/stmt.rs`, using the same `make_cond` machinery
  `Stmt::If` already uses). `@(final_step)` fails safe (never fires) rather
  than firing every evaluation — true "about to finish" detection needs a
  dedicated simulator-lifecycle hook not built yet (see §5).
- ngspice-46 side: new `EVAL_FLAG_IS_INITIAL_STEP` bit (`osdidefs.h`), a
  per-instance `has_evaluated` flag (`OsdiExtraInstData`), set once in
  `osdiload.c`'s sequential (non-OMP) eval loop, reset at instance
  setup/temperature-update (`osdisetup.c`). No new OSDI ABI struct needed —
  just an additional input flag bit, same convention as the existing
  `CALC_*`/`ANALYSIS_*` flags.
- Verified via `--dump-mir` (real `br v18, block2, block3` conditional, not
  dead code) and a real ngspice run showing the flag set exactly once per
  instance.

## 2. Ordinary `real`/`integer` variables didn't persist across evaluations at all

Testing item 1 above surfaced a much deeper, pre-existing issue: **an
ordinary analog-block variable's value was reset to its declared default on
*every* evaluation**, not just the first — with zero event-control involved:
```verilog
real accum;
analog begin
    accum = accum + 1.0;   // stayed flat forever; never accumulated
    V(out) <+ accum;
end
```
**Root cause, in two parts**:
- `openvaf/osdi/src/inst_data.rs`/`eval.rs` had two `todo!("hidden state")`
  panics and one `unreachable!()` on the read side — genuinely unimplemented
  scaffolding predating this enhancement (the `HiddenState(Variable)`
  parameter kind existed but nothing backed it with real storage).
- `openvaf/hir_lower/src/state.rs`'s `insert_var_init` **unconditionally**
  replaced every use of a variable's `HiddenState` parameter with its
  declared initializer expression — meaning even if the storage problem
  above were fixed, every read would still resolve to the init value, every
  single call.

**Fix**:
- `openvaf/osdi/src/inst_data.rs`: new `hidden_state: Vec<(Variable,
  EvalOutputSlot)>` field, built from `HiddenState(var)` parameters with a
  live corresponding `Var(var)` output; `read_hidden_state`/
  `store_hidden_state` (read at the start of `eval()`, store the final value
  at the end — the same OSDI-instance-memory slot serves as both "previous"
  input and "new" output, since instance memory is never reallocated
  between an instance's evaluations).
- `openvaf/osdi/src/eval.rs`: `ParamKind::HiddenState(var)` now reads via
  `read_hidden_state`; `store_hidden_state` called at the end of `eval()`.
- `openvaf/hir_lower/src/state.rs`: `insert_var_init` now applies the
  initializer only when `ParamKind::IsInitialStep` is true (via
  `make_select`, snapshotting pre-existing uses of the parameter *before*
  constructing the select, to avoid a self-referencing cycle), falling back
  to the genuine `HiddenState` read otherwise.
- `openvaf/sim_back/src/context.rs`: **two-pass build**. A variable's final
  value must be kept alive as a real output for `hidden_state` to have
  anything to store — but naively marking *every* `PlaceKind::Var` as
  always-alive broke `aggressive_dead_code_elimination`'s assumptions for
  genuinely-dead variables (19 pre-existing test failures, including a real
  `unwrap()` panic in `mir_opt/src/dead_code_aggressive.rs`). Fixed with a
  throwaway first build (baseline predicate) to discover exactly which
  `HiddenState(var)` parameters are genuinely live (not eliminated as dead),
  then a real second build that keeps alive only that discovered set (plus
  `op_vars`, as before). Fully reverted the regression; full existing test
  suite passes again (`cargo test -p sim_back` and friends).

**Verified**: the accumulator model above now genuinely accumulates across
timepoints (`1074, 1076, 1078, ...`, incrementing correctly once per Newton
iteration/evaluation as expected); full existing workspace test suite
passes with zero regressions.

## 3. Known limitation: explicit `@(initial_step)` statements that write to a variable can crash the compiler

Two related crashes, both involving an *explicit* `@(initial_step)`
statement writing to a variable (as opposed to relying on the variable's
plain declared initializer, `real x = 5.0;`, which is unaffected — see
`initial_step_examples/`, built entirely around the safe form):

1. **Self-referential + explicit double-init**: a variable both explicitly
   written inside `@(initial_step)` *and* separately self-referentially read
   elsewhere crashes with `assertion failed: cx.func.validate()` (a
   dominance violation — `insert_var_init`'s `FunctionBuilder::edit`-based
   CFG insertion collides with the pre-existing branch structure from the
   explicit `@(initial_step)` statement):
   ```verilog
   real accum;
   analog begin
       @(initial_step) accum = 0.0;   // now redundant -- see below
       accum = accum + 1.0;
       V(out) <+ accum;
   end
   ```
2. **Any explicit `@(initial_step)` write, even without self-reference**:
   found while building this enhancement's examples — crashes with a
   *different* panic, `Option::unwrap()` on `None` in
   `mir_opt/src/dead_code_aggressive.rs:105`, reached via
   `sim_back::init::Builder::build_init_cache` — a separate init/operating-
   point-cache-building pass with its own similar keep-alive-predicate
   assumption that the `sim_back/src/context.rs` two-pass fix above didn't
   cover:
   ```verilog
   real marker;
   analog begin
       @(initial_step) marker = 100.0;   // crashes even with no self-reference
       V(out) <+ marker + V(in);
   end
   ```

Both patterns are **now redundant** given the fix above (variables already
get their declared initializer applied automatically and only on the true
first evaluation — no explicit `@(initial_step)` reset is needed for the
common case anymore), so this is a narrow edge case, not a blocker for
typical models using plain declared initializers. Root-causing and fixing
the `FunctionBuilder::edit` interaction (crash 1) and extending the
two-pass keep-alive fix to `sim_back::init` as well (crash 2) are noted here
as follow-up work rather than silently left for someone to rediscover via a
crash.

## 4. Examples

Two example folders (`.va`, `.osdi`, DC/AC/transient `.cir`, raw `wrdata`
results, and PNG plots — all run against `version8`'s own `openvaf-r` and
`ngspice-46` binaries, not system-wide ones) demonstrate the fixes above.
Both deliberately use the *safe* (plain declared-initializer) form, per the
known limitation in §3:

- **`initial_step_examples/`** (`initial_step_demo.va`): `real accum =
  seed;` (a parameter), then `accum = accum + 1.0;`. DC/AC confirm
  `V(out) = accum + V(in)` has slope 1 and unity/0dB/0deg AC gain (accum
  itself has zero small-signal sensitivity to the input); transient shows
  the sine input riding on a slowly-rising, *persistent* baseline that
  starts near `seed` rather than resetting to `seed` every evaluation.
- **`variable_persistence_examples/`** (`persist_demo.va`): the minimal
  case, `real accum; accum = accum + 1.0;`, no parameters, no event-control
  at all. Transient is the key plot — a clean, sustained linear ramp over
  100µs, proving `accum` is never silently reset. DC/AC are included for
  completeness and show the honest (and expected) non-behavior: `accum`
  counts evaluations, not a real function of `V(in)`, so DC produces a
  roughly-monotonic curve driven by Newton-iteration count rather than a
  real transfer function, and AC gain is ~zero — the same "documented
  negative result" spirit as `last_crossing_examples/`'s DC/AC plots in
  Enhancement-6.

## 5. Deferred to Enhancement-8

- **`cross()`/`above()`/`timer()`**: not started. These need new `@(...)`
  event-control grammar (currently only `@(initial_step)`/`@(final_step)`
  are parseable — see `openvaf/syntax/veriloga.ungram`'s `EventStmt`
  production) plus OSDI/ngspice breakpoint-scheduling support (predicting
  and forcing a timestep at the exact crossing time) analogous to but
  distinct from `last_crossing`'s history-based detection from
  Enhancement-6. The event-gating foundation built in this enhancement
  (`ParamKind::IsInitialStep`, the `make_cond`-based conditional lowering
  pattern, the `EVAL_FLAG_*` convention for simulator-to-model flags) is
  directly reusable for wiring up whatever new event kinds `cross`/`above`/
  `timer` need.
- **`generate`/`genvar` blocks**: not started. No grammar exists anywhere in
  `openvaf/parser/src/grammar/`. Comparable in scope to Enhancement-5's
  module-instantiation work (likely another compile-time elaboration pass).

## 6. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/hir_lower/src/lib.rs` | New `ParamKind::IsInitialStep` |
| `openvaf/hir_lower/src/stmt.rs` | Real `@(initial_step)`/`@(final_step)` gating |
| `openvaf/hir_lower/src/state.rs` | `insert_var_init` gated by `IsInitialStep`, not unconditional |
| `openvaf/hir/src/lib.rs` | `Event`/`GlobalEvent` re-exports (needed to name them from `hir_lower`) |
| `openvaf/osdi/src/inst_data.rs` | `hidden_state` field, `read_hidden_state`/`store_hidden_state` |
| `openvaf/osdi/src/eval.rs` | `IsInitialStep` flag read, `HiddenState` real read/write wiring |
| `openvaf/sim_back/src/context.rs` | Two-pass build to correctly keep self-referential `Var` outputs alive |
| `ngspice-46/src/osdi/osdidefs.h` | `EVAL_FLAG_IS_INITIAL_STEP`, `has_evaluated` field |
| `ngspice-46/src/osdi/osdiload.c` | Sets the flag once per instance in the sequential eval loop |
| `ngspice-46/src/osdi/osdisetup.c` | Resets `has_evaluated` at instance setup/temperature update |

No OSDI ABI struct/header extension was needed for this enhancement (unlike
Enhancement-6's `last_crossing`) — the `IsInitialStep` mechanism reuses the
existing eval-flags convention, and `hidden_state` reuses Enhancement-6's
`eval_outputs` infrastructure. `cross`/`above`/`timer` will very likely need
a real ABI extension, following the `osdi_0_4_enhancementN.h` convention.
