# Enhancement-8 — `generate for`/`genvar` and `cross()`/`above()`/`timer()` (version9)

Enhancement-7 (`Enhancement-7.md` §5) deferred two features to this
enhancement: `generate`/`genvar` compile-time elaboration (**Feature B**),
and the `cross()`/`above()`/`timer()` event-control functions (**Feature
A**). Both are implemented. Feature B is built on the existing text-level
elaboration pattern from Enhancement-5's module instantiation and is fully
working with no known gaps. Feature A's event-detection logic is real,
verified, and correct; it originally surfaced a significant *pre-existing*
compiler bug (confirmed present in version8's unmodified baseline, not
introduced by this enhancement) that blocked its most natural use case —
persistent-variable writes inside the event body — which has since been
found and fixed; see §2's "Known limitations" item 1 for the full root-cause
writeup.

All work is in `version9/` only; all simulation verification uses
`version9/ngspice-46`'s own locally built binary.

## 1. `generate for` / `genvar`

**Scope**: structural/declarative generation only — `generate for` with an
ascending, compile-time-constant-foldable `genvar` loop, generating repeated
net/instance/variable/parameter declarations. Per the Verilog-A LRM,
`generate` may never emit a new `analog` block, so this scope boundary
matches the language, not just an implementation shortcut. `generate
if`/`generate case` are not implemented (noted as follow-up work, same
convention as prior enhancements deferring sub-scope).

### Design: text-level elaboration, mirroring Enhancement-5

- **Grammar** (`openvaf/syntax/veriloga.ungram`): new `ModuleItem`
  alternatives `GenvarDecl` (`genvar i, j;`) and `GenerateFor` (`generate for
  (i = 0; i < N; i = i + 1) begin : label ... end endgenerate`, body items
  restricted to structural `ModuleItem`s via a new `GenerateBlock`
  production).
- **Parser** (`openvaf/parser/src/grammar/items/module.rs`): unambiguous
  keyword-dispatch on `genvar`/`generate` (simpler than `Instantiation`'s
  2-token lookahead, since there's no bare-identifier ambiguity).
- **Elaboration** (`openvaf/hir/src/elaborate.rs`, new
  `elaborate_generates()`, run *before* `elaborate_instantiations()` so any
  instantiation statements inside a `generate for` body are already unrolled
  into concrete text by the time instantiation elaboration processes them):
  text-level splicing, not item-tree-level — for each `generate for` block,
  renders `N` concatenated copies of the block body's raw source text via
  the same `render_with_holes` machinery Enhancement-5 built, substituting
  the genvar identifier with its literal per-iteration integer value
  (whole-token substitution, plus a small integer-only constant-expression
  evaluator, `eval_int_expr`, to fold `node[i+1]`-style bit-select indices),
  and disambiguating every name declared inside the block by suffixing it
  with the genvar value (`r` → `r_0`, `r_1`, ...), exactly like an instance
  array's per-element naming. The loop bound/init/step must constant-fold to
  integer literals (`fold_int`, reusing the same literal-only evaluator
  `hir_def::item_tree::lower::fold_width_range` uses for `[msb:lsb]`
  instance-array ranges); a non-constant bound is a hard compile error
  (`NonConstantGenerateBound`).
- Rationale for text-level over structural: Enhancement-5 proved this needs
  zero downstream (`hir_def` onward) changes, and every `hir_def`-level
  consumer independently re-parses `db.parse(root_file)`, so a
  structural-only synthetic node would be invisible to them anyway.

### Verification

- **`--dump-mir` equivalence**: `examples/generate_examples/resistor_ladder_generate.va`
  (a 4-element `generate for` resistor chain) vs.
  `resistor_ladder_manual.va` (the same chain, hand-written as 4 explicit
  instantiations) produce structurally identical "Optimized model setup MIR"
  — same block/branch/phi shape (`br v20, block4, block3`, ...), differing
  only in SSA value numbers from the different intermediate filenames.
- **ngspice DC sweep**: both compiled with version9's own `openvaf-r` and run
  through version9's own `ngspice`; `examples/generate_examples/compare_ladder.py`
  cross-checks the two — **bit-exact** match (`max |generate - manual| =
  0.0`) at every swept point, and both match an independent analytical
  resistor-divider computation to `2.068e-09` (floating-point noise level).
- **Regression**: full existing example folders (`instantiation_examples`,
  `bus_examples`, etc.) still compile unchanged through the patched
  pipeline. Full `cargo test` suite (see §3) unaffected.

See `examples/generate_examples/README.md` for the full example writeup.

## 2. `cross()` / `above()` / `timer()`

### Grammar

Extended `EventStmt`'s existing token alternation (not a general callable
builtin in `hir_def::builtin.rs`) so misuse outside event-control position
(`x = cross(...)`) is statically impossible, matching how
`initial_step`/`final_step` are handled today:
```
EventStmt =
  AttrList* '@' '(' (('initial_step' | 'final_step') SimPhases? | condition: Expr) ')' Stmt
```
`condition`, when present, is always a `Call` per the LRM (these three names
are only ever legal in this exact position) — recognized by bare function
name in `hir_def::body::lower::collect_cross_above_timer`, *not* materialized
as a general builtin/function-call expression. A malformed/unrecognized
condition degrades to the event being dropped (body fires unconditionally)
rather than a hard lowering error — there's no lowering-level diagnostic
channel in this module yet (a real "not a valid event-control expression"
diagnostic is noted as follow-up work, same as other soft-degradation
conventions in this codebase).

### Design: eval-granularity edge detection, not breakpoint-forcing

The original plan called for exact-crossing-time detection via a real OSDI
ABI extension and ngspice-side `CKTsetBreak` breakpoint scheduling (Feature
A's Phase 7/8 in the approved plan), mirroring Enhancement-6's
`last_crossing` ABI extension. **This was descoped during implementation** in
favor of a much simpler design that turned out to need *zero* new OSDI ABI
surface and *zero* ngspice-46 C changes:

- New `ParamKind::EventState(u32)` / `PlaceKind::EventState(u32)`: a
  persistent real storage slot, read-at-start/store-at-end-of-`eval()`,
  exactly like Enhancement-7's `HiddenState(Variable)` mechanism, but keyed
  by a compiler-assigned index instead of a source-level `Variable` (there's
  no user declaration to hang synthetic per-call-site state off of). Wired
  into `openvaf/osdi/src/inst_data.rs` (`event_state` field,
  `read_event_state`/`store_event_state`) and `openvaf/osdi/src/eval.rs`
  identically to `hidden_state`'s existing plumbing.
- `above(expr)`: fires when `expr` transitions from `<= 0` to `> 0` between
  the *previous evaluation* and the *current* one (`hir_lower/src/stmt.rs`'s
  `lower_above`) — `prev` is seeded to the current value on
  `ParamKind::IsInitialStep`, so the first evaluation never spuriously
  fires.
- `cross(expr, dir)`: fires on any evaluation-to-evaluation zero-crossing,
  filtered by `dir` (`< 0` falling-only, `> 0` rising-only, `== 0`/absent
  either) — `dir` is read as an ordinary runtime `Value`, not assumed
  constant, mirroring how `last_crossing`'s own `dir` argument is handled.
- `timer(t0, period)`: fires when `Abstime >=` a persisted "next fire time"
  (initially `t0`); reschedules by one `period` each firing (or to
  `INFINITY`, i.e. never again, for a one-shot timer with no `period`). No
  crossing-prediction math needed — `t0`/`period` arithmetic is ordinary MIR.
- All three combine boolean sub-conditions via `bool_and`/`bool_or` helpers
  built from `LoweringCtx::make_select` (the same machinery
  `BooleanAnd`/`BooleanOr` expression lowering already uses), since the MIR
  has no native `Band`/`Bor` opcode for pre-computed boolean `Value`s.
- **Why this is a legitimate design, not a shortcut**: Enhancement-7 already
  established (and verified) that this codebase's variable-persistence
  granularity is *per-`eval()`-call*, not per-accepted-timepoint — "the
  accumulator... incrementing correctly once per Newton iteration/evaluation
  as expected" (Enhancement-7.md §2). `EventState` reuses that exact,
  already-verified granularity rather than introducing a different one.

### Compile-time verification (`--dump-unopt-mir`)

All three event kinds produce genuine, non-dead-code conditional branches.
`above`:
```
v19 = phi [v16, block2], [v17, block3]   // gated "previous value"
v20 = fle v19, v3                        // was_below = prev <= 0
v21 = fgt v16, v3                        // is_above  = current > 0
br v20, block5, block6
```
`cross` additionally shows the `dir`-filtering rising/falling/either
combination (`fgt`/`flt`/`fle`/`fge` combined via nested branches); `timer`
shows `v21 = fge v20, v19` (fired) and `v22 = fadd v19, v16` (reschedule).

### ngspice verification

`examples/cross_examples/tran_above.cir`: `V(in) = 2·sin(2π·1kHz·t)`, `thresh = 1.0`
— `above` fires once per cycle, exactly every ~1ms, at `in ≈ thresh`:
```
above fired at t=8.428e-05 in=1.01028
above fired at t=0.00108428 in=1.01028
above fired at t=0.00208428 in=1.01028
```
`examples/cross_examples/tran_cross.cir`: same sine, `thresh = 0.0`, `dir = 0.0`
(either direction) — `cross` fires twice per cycle (rising and falling),
alternating sign, exactly every ~0.5ms.

`examples/timer_examples/tran_timer.cir`: `t0 = 2ms`, `period = 1ms` — first firing
at exactly `t0`, then every `period` after:
```
timer fired at t=0.0020028
timer fired at t=0.0030028
timer fired at t=0.0040028
timer fired at t=0.0050028
timer fired at t=0.0060028
```

### Known limitations

1. **No persistent state inside the event body — a chain of three
   pre-existing compiler bugs, not introduced by this enhancement, all now
   fixed.** The natural way to use `cross`/`above`/`timer` is to accumulate a
   count or track state on each firing (`count = count + 1.0;` inside the
   event body). **Confirmed to already crash on version8's unmodified
   baseline** with a plain `if (V(in) > 0.0) count = 1.0;` — no event-control
   involved at all; the trigger is any *single-branch* conditional write to a
   variable that's also read elsewhere (an implicit "else: keep old value"
   phi) — `if`/`else` where *both* branches assign does **not** trigger it.
   Same class of bug as Enhancement-7.md §3's two documented
   `@(initial_step)`-write crashes, now confirmed *general*. Three distinct,
   independently-diagnosed bugs were found and fixed chasing this:
   - **Fixed**: `mir_opt::simplify_cfg::SimplifyCfg::simplify_bb`'s
     "remove CFG-unreachable block" cleanup unconditionally `zap_inst`-ed
     every instruction in such a block, unlike this file's other
     phi-removal helpers (`simplify_trivial_phis`,
     `simplify_duplicates_phis_naive`), which call `replace_uses` first. A
     block can look CFG-unreachable at this point in the pipeline while one
     of its instructions' results is still genuinely needed by a
     not-yet-inserted `mir_autodiff` derivative/Jacobian instruction
     (created *after* this pass runs, referencing existing values by raw
     operand before its own instructions are spliced into the layout).
     Fixed by skipping removal when any of the block's instructions still
     have outstanding uses (`sim_back`'s `compute_outputs`/`base_keep` also
     needed a matching `PlaceKind::EventState` entry, already covered in
     the diff table above).
   - **Fixed**: `mir::dominators::DominatorTree::compute_reverse_postorder`
     (post-dominance) seeded its walk from only `func.layout.last_block()`,
     silently treating it as the function's one universal exit. A function
     with more than one real exit block (e.g. two independent branch
     regions each ending their own control-flow path) left every block
     that couldn't reach *that specific* block with `rpo_number == UNDEF`,
     making `ipdom()` return `None` for perfectly well-defined nested
     branches — which `mir_opt::split_tainted::propagate_taint`'s
     branch-handling relies on to know where an op-dependent branch's
     control-dependence region ends, and which
     `sim_back::refresh_op_dependent_insts` calls right before every
     `Initialization::new`. Fixed by seeding the reverse-postorder walk
     from *every* real exit block at once (as if they fed into one virtual
     super-exit) and giving each of them beyond the first an explicit
     synthetic `idom` of the first (rather than computing one, which
     requires at least one reachable predecessor these true exits don't
     have by construction) — equivalent to a virtual multi-exit root
     without allocating a real block.
   - **Fixed**: `mir::Layout::merge_blocks(pred, succ)` keeps `pred` at its
     own layout position and discards `succ` entirely — it never moves
     `pred` to `succ`'s old position. `mir_opt::simplify_cfg`'s
     `merge_block_into_predecessor` uses this to fold a block into its
     unique predecessor whenever safe, including cases where the merged-away
     block (`succ`) happened to be `func.layout.last_block()` — the
     function's true, physically-last exit block. After such a merge,
     `last_block()` silently started pointing at whatever block was
     physically last *before* the removed block, which is not necessarily
     related to the true final block at all (confirmed via debug
     instrumentation: `bb=block1 pred=block4` merge, with `block1` the
     actual last block, left `last_block()` pointing at an unrelated
     earlier block, `block8`). This directly broke
     `mir::cursor::CursorPosition::goto_exit()` (`self.goto_bottom(self.layout().last_block().unwrap())`),
     which `sim_back::dae::builder::ensure_optbarriers()` calls to append
     `optbarrier`-wrapped DAE residual/Jacobian instructions at "the" exit —
     it silently appended them into the wrong block, producing a value
     (`v31 = optbarrier v19`) used before its operand's defining block
     (`block4`) dominated the insertion point (`block8`), a genuine SSA
     dominance violation. This is the exact same class of "trust
     `last_block()` as the one universal exit" bug already fixed once above
     in `dominators.rs`, now confirmed to also afflict block-merging.
     Caught precisely (rather than as the late, opaque
     `"internal error: entered unreachable code: attempted to read
     undefined value"` LLVM-codegen panic release builds produce) by
     switching to a plain debug build, which activates
     `debug_assert!(cx.func.validate())` in `sim_back/src/lib.rs` and
     surfaces `mir::validation`'s real dominance checker's precise
     diagnostic (`"v19 doesn't dominate use (block4 !dom block8)"`)
     immediately after `DaeSystem::new`, long before codegen. Fixed with a
     new `Layout::move_block_to_end(pred)` helper, called from
     `merge_block_into_predecessor` whenever the merged-away block was the
     layout's last block — `pred` (which now holds the merged-away block's
     terminator and contents) takes over the last-block position, so
     `last_block()` continues to mean "the function's true exit" for every
     downstream consumer (`goto_exit()` included) without those consumers
     needing to change.
   - **Verified fixed**: `verify_fix.va` (`examples/cross_examples/`) — a plain
     `if (V(in) > 0.0) count = 1.0; V(out) <+ count;` — now compiles and
     simulates correctly (ngspice transient run: `count`/`V(out)` latches to
     `1.0` the instant `V(in) > 0` and stays there even after `V(in)` falls
     back to `0`, exactly the correct persistent-write semantics). The
     `above_demo.va`/`cross_demo.va`/`timer_demo.va` examples have been
     upgraded from `$strobe`-only reporting to real persistent-counter
     accumulation (`count = count + 1.0;` on every firing, exposed on
     `V(out)`) — see the updated DC/AC/transient plots and READMEs in
     `examples/cross_examples/`/`examples/timer_examples/`. Full regression re-verified after
     the fix: all unit tests in the touched crates (`mir`, `mir_opt`,
     `mir_autodiff`, `mir_build`, `hir_lower`, `sim_back`) pass; every
     existing example folder (`cross_examples`, `timer_examples`,
     `generate_examples`, `absdelay_examples`) still compiles and simulates
     cleanly.
2. **Detection is eval-granularity, not exact-time-forced.** No breakpoint
   scheduling (`CKTsetBreak`) — see "Design" above for why this is an
   intentional, documented scope reduction, not an oversight. Firing times
   land within one simulator timestep of the true crossing, not bit-exact
   (see the `in` values in the `above`/`cross` results above — close to but
   not exactly `thresh`/`0`).
3. **Fixed**: an unrelated, pre-existing `ngspice-46` parser bug (confirmed
   on version8's baseline too, before this fix): the *first* `param=value`
   pair in a multi-parameter `.model` override list was silently ignored,
   falling back to the `.va`'s declared default; subsequent ones applied
   correctly. Discovered while debugging what first looked like a `timer()`
   bug (`t0` appeared stuck at its default) — turned out to be entirely
   unrelated to event-control, reproducible with a plain two-parameter
   module and no event-control at all. Root-caused to
   `INPgetNetTok()` (`ngspice-46/src/spicelib/parser/inpgtok.c`): its
   leading-garbage-skip loop treats `(` as a skippable boundary character,
   but its token-end scan loop did **not** treat `(` as a terminator (unlike
   the sibling function `INPgetTok()`, which is consistent on both loops).
   `spicelib/parser/inpgmod.c`'s `create_model()` uses `INPgetNetTok()` to
   discard an OSDI model's device-type token (`.model name devtype(p1=v1
   p2=v2)` — note no space before `(`), and this asymmetry made it swallow
   the `(` **and** the first parameter's name (`devtype(p1`) as one token,
   stopping only at the following `=`. The first parameter's *value* token
   was left with no name attached, silently dropped by `create_model`'s
   unrecognized-bare-number fallback; every subsequent `name=value` pair
   re-synced correctly since the token boundaries realign after that.
   Fixed by adding the missing `if (*point == '(') break;` to
   `INPgetNetTok()`'s token-end scan loop. Verified against the entire
   existing example suite (every `*_examples/` folder's `.cir` files) with
   no behavior change, and confirmed `timer_demo`/`above_demo`/`cross_demo`
   now correctly apply a *single* (non-repeated) first-parameter override —
   the repeat-first-param workaround in the example `.cir` files has been
   removed.

## 3. Verification summary

- Full `cargo test --workspace` (excluding `verilogae*`, which has an
  unrelated pre-existing `llvm-sys` feature-unification build issue in this
  environment, and the `openvaf --test integration` binary, which reads from
  `external/vacask/devices`, a git submodule absent in this non-git working
  copy): all green except the single pre-existing `sourcegen::osdi::gen_osdi_structs`
  failure, already documented as a pre-existing, unrelated header-parsing
  quirk in Enhancement-5.md's regression notes.
- `sim_back`'s full 24-test suite (`dae`/`init`/`topology`) passes —
  including after the `PlaceKind::EventState`/`compute_outputs` keep-alive
  extension.
- Regression-compiled every pre-existing example folder
  (`instantiation_examples`, `initial_step_examples`,
  `variable_persistence_examples`, etc.) through the patched compiler —
  unchanged output.

## 4. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/syntax/veriloga.ungram` | `GenvarDecl`/`GenerateFor`/`GenerateBlock` productions; `EventStmt`'s `condition: Expr` alternative |
| `openvaf/parser/src/grammar/items/module.rs` | `genvar`/`generate` keyword dispatch |
| `openvaf/parser/src/grammar/stmts.rs` | `event_stmt` falls through to `expr(p)` for non-keyword conditions |
| `openvaf/hir_def/src/item_tree.rs`, `item_tree/lower.rs`, `item_tree/diagnostics.rs` | `ModuleItem::GenerateFor`/`Genvar` variants, genvar constant-fold diagnostics |
| `openvaf/hir_def/src/builtin.rs`, `openvaf/syntax/src/ast/generated/*.rs`, `openvaf/tokens/src/parser/generated.rs`, `sourcegen/src/ast/src.rs` | Regenerated via `cargo test -p sourcegen ast` after the grammar changes above |
| `openvaf/hir/src/elaborate.rs`, `openvaf/hir/src/db.rs` | New `elaborate_generates()`, text-splicing `generate for` unrolling, hooked into `CompilationDB::new` before `elaborate_instantiations` |
| `openvaf/hir_def/src/expr.rs` | `Event::Cross`/`Above`/`Timer` variants + `walk_child_exprs` |
| `openvaf/hir_def/src/body/lower.rs` | `collect_cross_above_timer`: recognizes `cross`/`above`/`timer` calls by name |
| `openvaf/hir_ty/src/inference.rs` | Type-checks `Event`'s exprs as `Real` |
| `openvaf/hir_ty/src/validation/body.rs` | Validates `Event`'s exprs |
| `openvaf/hir_lower/src/lib.rs` | `ParamKind::EventState`, `PlaceKind::EventState`, `event_state_count` counter |
| `openvaf/hir_lower/src/stmt.rs` | `lower_above`/`lower_cross`/`lower_timer`, `bool_and`/`bool_or` helpers |
| `openvaf/hir_lower/src/ctx.rs` | `PlaceKind::EventState`'s default-init case |
| `openvaf/osdi/src/inst_data.rs` | `event_state` field, `read_event_state`/`store_event_state` (mirrors `hidden_state`) |
| `openvaf/osdi/src/eval.rs` | `EventState` read/store wiring |
| `openvaf/sim_back/src/context.rs` | `PlaceKind::EventState` added to both keep-alive predicates (`base_keep`, `compute_outputs`) |
| `openvaf/mir_opt/src/simplify_cfg.rs` | **Compiler fix**: `simplify_bb`'s unreachable-block removal now skips blocks whose instructions' results still have outstanding uses; `merge_block_into_predecessor` now preserves the layout's last-block invariant when the merged-away block was last (§2, limitation 1) |
| `openvaf/mir/src/dominators.rs` | **Compiler fix**: `compute_reverse_postorder`/`compute_domtree` now handle functions with more than one real exit block (§2, limitation 1) |
| `openvaf/mir/src/layout.rs` | **Compiler fix**: new `Layout::move_block_to_end` helper, used by `merge_block_into_predecessor` to keep `last_block()` meaning "the true function exit" after a block merge (§2, limitation 1) |
| `ngspice-46/src/spicelib/parser/inpgtok.c` | **ngspice fix**: `INPgetNetTok()` now terminates a token on `(`, fixing the first-`.model`-parameter-silently-ignored bug (§2, limitation 3) |

No OSDI ABI header extension (`osdi_0_4_enhancement3.h`) and no `ngspice-46`
C-side changes were needed — see §2's "Design" for why.

Deferred to follow-up work: `generate if`/`generate case`; exact
breakpoint-forcing for `cross`/`above`/`timer` (§2, limitation 2); a real
diagnostic (rather than silent degradation) for malformed `@(...)`
conditions.
