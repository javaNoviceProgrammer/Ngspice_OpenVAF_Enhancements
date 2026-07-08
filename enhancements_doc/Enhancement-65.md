# Enhancement-65 — preprocessor audit: macro-recursion guard

This document describes the changes made to **OpenVAF-r** in the
`version11/` directory following a systematic audit of the Verilog-A
compiler directives — the preprocessor predates every enhancement in this
series and had never been probed. Front-end only — no OSDI/ngspice change.

## The audit (22 probe forms)

Everything probed works, and the 18 compiling probes were verified
**numerically exact** at runtime (each engineered to produce exactly
1 mA — compiling proves nothing about correct expansion):

| feature | status |
|---|---|
| `define` (simple, 1-arg, multi-arg with nested parens in actuals) | exact |
| macro using another macro; macro call as another macro's **argument** | exact |
| `ifdef`/`else`, `ifndef`, `elsif` chains, nested conditionals | exact (right branch, dead branch dead) |
| conditionals **inside** a module body | exact |
| `undef` + redefinition; `resetall` | exact |
| backslash-continued (multi-line) definitions; trailing `//` comments | exact |
| macro **calls** spanning lines | exact |
| nested `include` chains (file → file → file) | exact |
| undefined macro use; unbalanced `ifdef` | clean, located errors |
| macro redefinition | warning (`macro was overwritten`) |

**One defect: recursive macro expansion crashed the compiler** — a stack
overflow for both the direct form (`` `define LOOP (`LOOP + 1) ``) and
the mutual form (`` `A `` uses `` `B `` uses `` `A ``).

## The fix — the fifth "scaffolded-but-unwired" find

The preprocessor's diagnostic enum **already had** a `MacroRecursion`
variant with a rendered message ("macro '`X' was called recursively") —
but nothing ever emitted it: `call_macro` carried a literal
`// TODO track recursion`, and the report builder in
`basedb/diagnostics/preprocessor_error.rs` was a literal `todo!()` that
would have panicked had the diagnostic ever been created. (This is the
same defect pattern as E-39 derived natures, E-45 nature attributes, and
E-46's based-literal sketch: complete machinery on one side of a
boundary, never wired on the other.)

Two changes:

1. **`preprocessor/src/processor.rs`**: an `expansion_stack: Vec<&str>` on
   the `Processor`; `call_macro` reports `MacroRecursion` when the called
   name is already on the stack. Crucially, the name is pushed **around
   the body expansion only, after arguments are built**: a nested call of
   the same macro inside an *argument* — `` `define QUAD(x)
   (`TWICE(`TWICE(x))) `` — is finite and legal (argument tokens belong to
   the caller's expansion), and the first draft of the guard wrongly
   rejected exactly that. The final scoping catches direct bodies, mutual
   cycles through any depth, and recursion smuggled through arguments'
   *expansions*, while leaving argument-level self-nesting alone.
2. **`basedb/src/diagnostics/preprocessor_error.rs`**: the `todo!()`
   replaced with a real report — primary label at the recursive call site
   plus a help note.

Both forms now produce clean, source-located errors; the legitimate
`QUAD` nesting compiles and evaluates exactly.

## Examples (`preproc_examples/`, 5 checks, ALL PASS)

`verify_preproc.py`: [1] an 8-way self-checking macro tour (one branch per
feature, total exactly 8 mS, with a not-taken `ifdef` that would add
100 S if it leaked); [2] a two-deep `include` chain; [3] direct recursion
= clean error naming the macro; [4] mutual recursion likewise; [5] the
`QUAD(x) = TWICE(TWICE(x))` false-positive regression pin, exact at
runtime.

## Regression

All version11 example verify suites pass; crate tests (preprocessor,
basedb, parser, syntax, hir, hir_lower, sim_back, osdi) pass; the VA_TEST
corpus compiles 92/92.
