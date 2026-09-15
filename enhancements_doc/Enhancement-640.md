# Enhancement-640: the diagnostic slips of the 2026-09-14 hunt (F6)

**Scope:** F6 of the
[2026-09-14 hunt](../docs/bug_hunts/2026-09-14_openvaf-r-parameters-arrays-and-hierarchy.md)
— seven things the compiler said wrongly, or did not say. Compiler:
`openvaf/hir/src/elaborate.rs` and `openvaf/hir_ty/src/diagnostics.rs` (two
messages), `openvaf/openvaf/src/lib.rs`, `openvaf-driver/src/{cli_def,
cli_process,main}.rs` (`--dump-json`, `-C`), `openvaf/hir_lower/src/fmt.rs`
(message-less severity tasks), `openvaf/sim_back/src/module_info.rs` (the
statistics wordings), `openvaf/hir_ty/src/validation/body.rs` +
`validation.rs` (a default that folds to infinity),
`openvaf/parser/src/grammar/items/module.rs`, `parser/src/error.rs`,
`syntax/src/error.rs`, `syntax/src/parsing/tree_builder.rs`,
`basedb/src/diagnostics/syntax_error.rs` (a statement at module scope). New
suite [`hunt13slips_examples`](../examples/hunt13slips_examples/) (7 checks
per solver). **Compiler side.**

**Suites:** `hunt13slips_examples` 7 of 7 per solver, both solvers;
`osdimc_examples` (two pinned wordings updated) green; the `parser`,
`syntax`, `hir_ty` and `sim_back` crate tests green; full sweep 513 of 513.

## The seven, and what is done about each

| # | was | now |
|---|---|---|
| 1 | two messages carried runs of thirty spaces — the aliasparam-in-body help and the unknown `.zz` override error — from a line continuation flattened by a script | one line each; a scan of every message literal in the compiler and the OSDI/front-end sources finds no other |
| 2 | `--dump-json` was in `--help` ("Abort after lowering and serialize MIR as json") and answered `error: currently unimplemented`; the upstream implementation had been commented out when the MIR builder changed, while `Function::to_json` stayed alive | implemented: each module's optimized evaluation MIR is written beside the output as `<stem>_<module>.json` — the control-flow graph, the instructions, the values, the inputs by kind (`parameters`, `voltages`, `currents`, `sim_state`, `hidden_state`, `implicit_unknowns`, `cached` setup values, …) and the outputs; the library is still built, and with `--dry-run` the JSON is all that is produced (the abort the flag always promised); `--help` says so |
| 3 | `$fatal;` (and `$fatal(0);`, `$info;`, `$warning;`, `$error;`) printed an empty body, which the simulator's sink dropped — so ngspice's "see the OSDI(fatal) message above" pointed at nothing, and LRM 9.7.3's "these tasks shall also report the simulation run time" had no line to ride on | the task's own name is the message: `OSDI(fatal) n1: $fatal (at the operating point)`, `OSDI(info) n1: $info (at the operating point)` |
| 4 | `'std' and 'std_rel' attributes are mutually exclusive; the absolute 'std' is used` — an *error*, after which nothing is used; `'std' attribute is ignored: only a scalar real parameter can carry statistics` on an integer or string, while `(* std *) parameter real a[0:1]` draws every element | `'std' and 'std_rel' are both given on this parameter; give one of them -- an absolute sigma (std) or a relative one (std_rel)`; `statistics need a real parameter; this one is an integer` / `a string` |
| 5 | `-C foo=bar` — "passed directly to LLVM" per `--help` — was accepted without a word; nothing consumes the list (it only distinguishes batch-mode cache entries) | each `-C` is warned as consumed by nothing and ignored; `--help` says what the list is for |
| 6 | `parameter real y = 1e400` is refused ("real literal is too large to represent … this is infinity as a double") while `y = 1e308*10`, the same value by arithmetic, compiled and simulated as infinity (`inf` is not a legal default; only bounds may spell it) | a real default that folds to ±infinity or NaN is refused: `the default of parameter 'y' overflows to infinity … folds to inf`, with the literal's rule quoted; `1e307*10` and `-1.7e308` compile |
| 7 | `I(p,n) <+ V(p,n)/1k;` at module scope was read as a net declaration with discipline `I` and reported as three token errors (`unexpected token '('; expected identifier`, twice `expected discipline but found nature access function 'I'`); `x = 1;` and `$strobe(…)` and a bare `begin … end` were "expected function decl., port decl., net decl. or analog block" | a dedicated syntax error, once: `statement outside an analog block … this statement is at module scope … help: contributions, assignments and system tasks belong inside an analog block -- analog begin ... end`; the parser recognises an identifier followed by `(`, `=` or `<+`, a `begin`, or a system task at module scope, and skips the statement (a `begin` block to its `end`). `electrical [0:2] nd;`, branches and instances are untouched — an identifier followed by `[` stays a declaration |

## Verification

| check | result |
|---|---|
| the two messages | one line each, no run of spaces |
| `--dump-json` | `c2_m.json` with cfg/instructions/vals/inputs/outputs, `r` under parameters, `(p, n)` under voltages, `c` an output; with `--dry-run` no `.osdi` and no object files; EKV's 3316-instruction eval serialises |
| `$info; $warning; $error; $fatal;` | each prints its name with the context; ngspice's fatal note has a line to point at |
| std beside std_rel; std on an integer, a string; std on an array | the new wordings; the array's elements draw under `osdimc` |
| `-C foo=bar` | warned, ignored, the build goes on; `--help` truthful |
| `1e308*10`, `-1e308*10`, `1e308+1e308` / `1e307*10`, `-1.7e308` / `1e400` | refused as overflowing / compile / refused as the literal |
| `I(p,n) <+`, `x = 1`, `$strobe`, `begin..end` at module scope | one error each, named; widths, branches and instances still parse |
| `hunt13slips_examples` | 7 / 7, both solvers |
| full sweep | 513 of 513 |
