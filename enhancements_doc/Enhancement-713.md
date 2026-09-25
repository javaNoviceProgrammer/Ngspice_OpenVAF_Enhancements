# Enhancement-713: compile time is linear in the size of an array literal, a noise table, a parameter list, a variable list and an event list — five quadratic walks, three of them in the front end and the descriptor, and an eval function whose one giant block is emitted through LLVM's fast instruction selector above 12 288 SelectionDAG nodes; 500 `@(cross)` events took 119 s and 2 000 did not finish, a 5 000-pair `noise_table` took a minute, a 20 000-element `localparam` array 15 s and 50 000 variables 47 s

**Scope:** F7 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only.** `basedb/src/ast_id_map.rs` (`AstIdMap::index`, `alloc`),
`hir_def/src/db.rs` and `hir_def/src/item_tree.rs` (`array_literal_leaves`,
`array_literal_leaf`), `hir_def/src/body.rs`, `hir_def/src/item_tree/lower.rs`
(`check_paramset_range`), `hir_lower/src/stmt.rs` (`lower_cross`), `osdi/src/access.rs`
(`given_flag_instance`, `given_flag_model`, `given_bit`), `osdi/src/load.rs`
(`build_noise_table_interp`), `osdi/src/lib.rs` (`EVAL_FAST_CODEGEN_BLOCK`, the one
LLVM option call, the descriptor module in `--dump-ir`), `mir_llvm/src/lib.rs`
(`ModuleLlvm::largest_block`, `replace_target_machine`, `LLVMBackend::set_codegen_level`,
`parse_llvm_args`), `sim_back/src/lib.rs` (`CompiledModule::largest_block`).
[`examples/arrayscale_examples/`](../examples/arrayscale_examples/) (9 checks, 38 in
all). The hunt page.

**Suites:** `arrayscale` 38 of 38 (32 of 38 on the E-712 binaries), `evtedge`,
`noise`, `tablearray`, `modelparamset` 7 of 7, `paramarrayarg`, `cubic_table`,
`filterforms` 95 of 95, `paramsetlrm` and `langguard` 132 of 132 unchanged; every
changed shape gives the same numbers through the E-712 compiler and this one (a
20 000-element array, 2 000 variables, 300 table calls, 300 `@(cross)` events, a
2 000-element loop read, a 300-pair noise table, a paramset array override); the
compiler workspace tests green apart from the three pre-existing sourcegen drift
failures (221 passed), no build warnings; full sweep 532 of 532, run alone.

## What was wrong

The campaign's F7 table, re-measured row by row on the E-712 compiler and on this one
(the two rows E-705 and E-712 had already fixed are kept for the record):

| shape | size | before | now |
|---|---|---|---|
| `localparam real t[0:n-1] = '{…}` | 20 000 | 15.5 s | 1.0 s |
| | 100 000 | not finished in 300 s | 13.9 s, 1.6 GB |
| `parameter real t[…] = '{…}` / `real t[…] = '{…}` | 20 000 | 15.5 s / 9.1 s | 1.5 s / 0.5 s |
| `for (…) a[k] = k*1.0;` over `real a[0:n-1]` | 20 000 | 107 s | 41 s |
| | 40 000 | not finished in 400 s | 163 s, 1.2 GB |
| `for (…) s = s + a[k];` | 10 000 | 26.8 s | 7.2 s |
| | 40 000 | not finished in 400 s | 59 s, 2.0 GB |
| `noise_table('{f1, p1, …})` of n pairs | 5 000 | 58.5 s | 0.5 s |
| | 20 000 / 100 000 | not finished in 400 s / 300 s | 0.5 s / 2.0 s |
| `laplace_nd(V, '{1}, '{n coefficients})` | 1 000 / 3 000 | 17.1 s / 91.8 s, 4.3 GB | 1.0 s / 2.6 s (E-712) |
| `$table_model(V, '{2n values}, "1L")` inline | 5 000 / 20 000 | 68.8 s / — | 0.5 s / 1.0 s (E-705) |
| `@(cross(V(p,n) − c))` event blocks | 500 | 118.7 s | 0.5 s |
| | 2 000 | not finished in 400 s | 2.6 s |
| `$table_model` calls on one 10-point table | 1 000 | 65.4 s (29 s after E-705) | 5.1 s |
| `real v0 … vn;` each assigned and summed | 20 000 / 50 000 | 7.8 s / 47.4 s | 1.0 s / 3.1 s |
| a chain of n modules, each instantiating the previous one | 200 | 208 s, 2 GB | 6.7 s, 1.0 GB |
| | 1 000 | not finished in 300 s, 6 GB | not finished in 300 s, 4.5 GB |

Five separate walks were quadratic, none of them "the cost model of every value a
register" the hunt page guessed at:

- **Every element of an array literal re-flattened the whole literal.** Each element of
  an array variable or parameter is its own item with its own body, and each body
  called `flatten_pattern` on the whole `'{…}` to pick its one leaf: n syntax-node
  walks of n, for the default, the paramset override and the paramset range check.
- **Every item lookup was a linear scan.** `AstIdMap::erased_ast_id_of_ptr` searched the
  arena for the node, once per item; and `alloc` re-walked a declaration's attributes
  once per variable it declares, so `real v0, …, v49999;` was 50 000 walks of a
  50 000-child node. 30 s of the 50 000-variable module's 32 s were these two.
- **The given-flag functions were a `switch` with a case per parameter.** The OSDI
  descriptor's `given_flag_model` and `given_flag_instance` — 79 358 IR lines for a
  10 000-element array parameter — although the given bits are a flat bitfield indexed
  by parameter position, which E-555 had already made `param_given` read
  arithmetically. LLVM's switch lowering took 5.9 s of the 20 000-element module.
- **A noise table was a chain of selects in the descriptor.** `build_noise_table_interp`
  emitted one `fmul`, `fadd`, `fcmp` and `select` per segment straight into
  `load_noise`; LLVM's instruction combiner is quadratic in such a chain — 9.4 s of the
  2 000-pair module's 9.8 s, a minute at 5 000 pairs.
- **An eval function whose straight-line code is one giant basic block pays three
  quadratic LLVM backend passes.** Found with `OPENVAF_LLVM_ARGS=-time-passes` and
  `sample`: the SelectionDAG list scheduler's priority-queue pop, which scans every ready
  node (500 `@(cross)` events, each seven branch diamonds that LLVM folds into one
  block: 111 s); the machine scheduler's candidate pick (a 5 000-element array read in
  a loop: 9 s); and the greedy register allocator's local splitting (500 calls of a
  ten-point table: 9 s). Each of LLVM's alternative pre-RA schedulers helped one shape
  and hurt another, and every such switch is process-wide.

The hierarchy chain is not a compiler defect: each level's module holds the whole
chain below it, so the flattened design of a 1 000-deep chain is 500 000 resistors
and 5 million Jacobian entries. The 200-deep chain is 20 100 resistors, and its
descriptor now takes 2 s instead of 200.

## What changed

**The front end.** The leaves of an array literal are a memoised query,
`array_literal_leaves`, keyed by the literal's position in the file and shared by
every element's body (`hir_def`); the paramset lowering flattens an override once per
override. `AstIdMap` carries an index from node to id, and a declaration's attributes
are read once per declaration (`basedb`).

**The descriptor.** `given_flag_instance` and `given_flag_model` are a bounds check, a
shift and a load of the bitfield word, whatever the parameter count (31 and 18 IR
lines for any module); the model side adds the model-parameter count to an instance
parameter's id, as `is_nth_inst_param_given` lays the copies out. A noise table is
three constant arrays — the upper bound, slope and intercept of each segment — and its
search a loop over them: the first segment whose upper bound exceeds the key, the last
point when none does, which is exactly the chain's answer for any data, sorted or
not, NaN included, in 44 IR lines for any table. The descriptor module is part of
`--dump-ir` and `--dump-unopt-ir` now, as `osdi_descriptors`.

**The eval.** `lower_cross`'s seven conjunctions per event are `select` instructions
(their operands are pure comparisons), not diamonds. After the middle-end passes of an
eval module have run at the requested level, `ModuleLlvm::largest_block` estimates the
SelectionDAG size of its largest basic block — an instruction that produces or
consumes an `i1` counts four, the rest one, which is what the comparisons and boolean
selects of an event or a table search expand to in legalisation — and above
`EVAL_FAST_CODEGEN_BLOCK` (12 288) the module's target machine is swapped for a -O0
one (`LLVMBackend::set_codegen_level`, per module, no process-wide state) so the
object code is emitted through the fast instruction selector, which is linear. The
block's arithmetic is as simplified as ever; only the scheduling and register
assignment of its machine code are the simpler ones. The same size, in MIR
instructions before code generation, also turns E-710's SLP switch on: the vectoriser's
store-chain search took 10 of the 19 s of a loop that fills a 10 000-element array.

The largest block of every compact model in the integration set is far below the
threshold — BSIM4's estimate is 5 246 (2 624 instructions), MVSG-CMC's 1 166, PSP102's
1 046, every other one under 900 — so their eval functions are compiled exactly as
before.

**One LLVM option call.** The osdi driver makes a single `LLVMParseCommandLineOptions`
call per process, before any pass pipeline: `-global-isel=false` (at -O0 the AArch64
backend selects through GlobalISel, whose legaliser is quadratic in a block — an
80 000-instruction block took 12.8 s; with it off the -O0 modules of E-579, E-712 and
this enhancement go through FastISel, 3.5 s), E-710's `-vectorize-slp=false` when a
table or a block calls for it, and E-712's `OPENVAF_LLVM_ARGS` appended last.
`disable_slp_vectorizer` is gone; `parse_llvm_args` no longer guards itself with a
`Once`.

## Verification

`arrayscale` section [5]: a 20 000-element `localparam` array literal compiles in
under 8 s (0.8 s; 15.5 s before); the given-flag functions are under 40 IR lines for
2 000 parameters (31 and 18) and the same size for a two-parameter module; a
2 000-pair `noise_table` loads through a loop of under 80 IR lines (44) and the same
size as a five-pair table; 300 `@(cross)` events leave at most three blocks per event
in the evaluation MIR (601, ten per event before) and compile in under 10 s (0.3 s;
17 s before); 50 000 real variables compile in under 20 s (2.7 s; 47 s before); a
10 000-element array filled in a loop compiles in under 40 s (10.5 s; 25 s before,
through the fast instruction selector). The 29 checks of E-579 unchanged.

By hand: the table above, every row one compile at a time under a 12 GB watchdog;
`PHASE_PROF=1`, which now prints each eval module's largest block, its SelectionDAG
estimate and whether the fast instruction selector was used; the seven changed shapes
compiled with the E-712 compiler and this one and simulated on the same decks, the
same printed numbers throughout; the integration-set survey of largest blocks; the
given-flag functions of a five-parameter module read line by line against E-555's
layout; the ten suites; the workspace tests; the sweep.

## What this does not do

- The loop that fills or reads a large array is still superlinear: at 40 000
  elements, 163 s and 59 s. What remains is LLVM's instruction combiner on the
  120 000-instruction loop body (5.5 s at 10 000 elements) and the MIR passes on a
  40 000-phi loop (37 s). The real fix is a memory-backed array for a run-time index —
  a load or a store instead of a select or a phi per element — which is a change to
  the language implementation, not a hunt fix.
- The fast-instruction-selector path does not form fused multiply-adds. The eval's
  derivative instructions carry the `contract` flag (`FastMathMode::Partial`), so for a
  giant-block eval the Jacobian's last bits can differ from the -O3 emission's; the
  residuals, which carry no flags, are the same. No compact model reaches the path.
- `EVAL_FAST_CODEGEN_BLOCK` is 12 288 by measurement, more than twice the largest
  compact model's estimate; it is a constant, not an option.
- The two-instance-per-level chain (`u1` and `u2` of the previous module) is 2ⁿ
  instances by construction and still does not finish; the campaign's chain row was
  the one-instance form, which it now measures.
- `given_flag_model` and `given_flag_instance` are OSDI descriptor entries ngspice
  never calls (`osdi.h` declares them); they were rewritten for the compile time and
  checked by reading, not by a simulation.
