# Enhancement-220 — openvaf-r crash hardening (round 2): ten panics → clean errors

A second robustness pass over `openvaf-r`, continuing [E-213](Enhancement-213.md)
and [E-219](Enhancement-219.md). Re-running the mutation fuzzer against the
shipped compiler — this time with **diverse compact-model seeds** (BSIM, HICUM,
PSP, HiSIM, VBIC, MEXTRAM, EKV, …) and **new mutation strategies** (keyword,
attribute `(* … *)`, and bracket injection alongside the byte/truncate/delimiter
ones) — found that **~5 % of mutated inputs still crashed the compiler** (exit
101, "OpenVAF encountered a problem and has crashed!") rather than reporting an
error. Triage grouped them into **ten distinct root causes**, all fixed here.

Every one is the E-213 pattern: a `panic!`/`assert!`/`unwrap()`/index that a
valid model never reaches, but malformed input does — turning a mere bad input
into a compiler crash. (All were caught by the E-213 panic hook, so the compiler
was never *memory-unsafe*; the bug is the crash UX and the missing diagnostic.)

## The ten root causes

| # | Site | Trigger → symptom (before) | Fix |
|---|---|---|---|
| 1 | `parser/src/parser.rs` | parser spins in error recovery → `assert!(steps ≤ 10M, "seems stuck")` panics | signal EOF at the step limit so parsing winds down and reports its errors |
| 2 | `basedb/src/diagnostics.rs` | a diagnostic with an empty span list → `to_unified_span_list([])` = `unimplemented!()` | render it label-less, anchored to the new `SourceMap::root_file()` |
| 3 | `preprocessor/src/grammar.rs` | `TextRange::new(start, end)` with `start > end` (macro-arg / `` `define `` / `` `include `` span at EOF), 5 sites | clamp `end` to `start` |
| 4 | `hir_ty/src/diagnostics.rs`, `validation.rs` | `expr_map_back[e].unwrap()` / `stmt_map_back[s].unwrap()` for a **synthesized** expr/stmt (no source location), 28 sites | resolve the span through a fallback (empty range) via one `expr_range` helper |
| 5 | `hir_ty/src/validation/body.rs` | `expr_types[arg].unwrap_node()` / `unwrap_branch()` / `unwrap_port_flow()` for a wrong-typed builtin/nature-access argument, 11 sites → `unreachable!()` | bail cleanly (`match … { Ty::X(id) => id, _ => return }`) |
| 6 | `syntax/src/lib.rs` | `to_ctx_span` mapping a span across source contexts → `TextRange::new(start, end)` with `start > end` | clamp |
| 7 | `preprocessor/src/sourcemap.rs` | `FileSpan::with_subrange` subrange past its parent → `assert!` | clamp the subrange into the parent |
| 8 | `preprocessor/src/grammar.rs` | stripping include quotes with `path[1..len-1]` on a malformed string literal (a lone `"`) → slice panic | total slice via `saturating_sub` + `get` |
| 9 | `hir_ty/src/inference.rs` | a call whose args match **no overload** → candidate list empty → `candidates[0]` out of bounds | fall back to the pre-filter candidate set |
| 10 | `hir_ty/src/validation/body.rs` | a builtin called with **too few arguments** (`$simparam()`, `$port_connected()`) → `args[0..]` out of bounds | one entry guard: skip builtin validation when `args.len() < BuiltinInfo::from(call).min_args` (inference already reports the `ArgCntMismatch`) |

None of the fixes changes the behaviour of a valid program: every one is on a
path that previously aborted the compiler.

## Method

The fuzzer classifies each outcome `OK` / clean-error / **CRASH** (panic/signal/
exit 101) / **HANG** (timeout). Each crash was triaged from its crash log to the
innermost `openvaf` frame (`Panic occurred in file … at line …`), grouped, and
the panic read at the source. Fixes were applied one cause at a time, each
verified against the recorded crash corpus, then a fresh fuzz run re-checked
convergence (each pass exposed the next-rarest site — a classic fuzzing tail —
until the rate hit zero).

## Result

- **Recorded crash corpus** (≈390 distinct fuzz-found inputs across two 4 000-run
  campaigns): every one now yields a clean error, **0 crashes**.
- **Fresh fuzz, 12 000 iterations** on the fixed compiler: **0 crashes, 0 hangs**
  — down from ~5 % (≈600 crashes over the same volume before the fixes).
- The compiler is unchanged on valid input: the **92 / 92** standalone production
  models compile to the identical verdict, and the parser/hir_ty/basedb/
  preprocessor/syntax/sim_back unit suites pass.

## Verification (`examples/vafcrash2_examples`)

`verify_vafcrash2.py` (19 checks) pins the fix with hand-crafted inputs targeting
each cause — an unterminated `` `include `` string, `$port_connected` of a
non-node and of nothing, `$simparam()`/`$noise_table()` with no arguments, a
mixed/degenerate module head, a bitwise-or of reals, keyword/attribute/bracket
salad, and a type error on a synthesized contribution — asserting each now yields
a clean **ERROR** (no crash/hang) and that valid code still compiles. The suite
was **mutation-tested**: reverting the fixes makes the guarded inputs crash again,
so it is not vacuous. Full regression: 179/179.

## Scope

openvaf-r only, eight files: `parser/src/parser.rs`, `syntax/src/lib.rs`,
`preprocessor/src/{grammar,sourcemap}.rs`, `basedb/src/diagnostics.rs`,
`hir_ty/src/{diagnostics,inference}.rs`, `hir_ty/src/validation.rs` +
`validation/body.rs`. No OSDI/ABI change; generated `.osdi` for every existing
model is identical.
