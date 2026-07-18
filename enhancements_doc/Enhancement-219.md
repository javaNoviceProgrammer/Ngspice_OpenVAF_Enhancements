# Enhancement-219 — preprocessor macro-argument hang + diagnostic-flood cap

Re-running the `openvaf-r` robustness campaign (the
[robustness report](../docs/internals/openvaf_internals/OpenVAF_robustness_report.md))
against the shipped compiler surfaced a **fifth hang path** that the original
campaign ([E-147](Enhancement-147.md), [E-148](Enhancement-148.md)) did not
cover. A mutation fuzzer hit it at a ~2% rate. This enhancement fixes it, plus a
second, related slowdown found in the same investigation. Both turn a
pathological input that *hangs* the compiler into a fast, clean rejection —
exactly the E-148 philosophy applied to two paths E-148 missed.

## Finding A — preprocessor argument-collection loops could spin forever

The preprocessor has token-by-token collection loops that scan until a closing
delimiter — the macro-**call** argument list (`parse_macro_call`) and the
`` `define `` **parameter** list (`parse_define`). Neither had a forward-progress
guarantee: on certain tokens, none of the `expect`/`eat`/branch calls in the
loop body consumes anything, so the loop re-examines the same token forever,
appending an error each pass — an unbounded diagnostics-vector growth that pins
the CPU. Two concrete triggers, both found by the fuzzer:

- **`` `name( `` + a stray directive.** A backtick followed by `(` is a macro
  call; its arguments are collected by `parse_macro_call` → `parse_macro_token`.
  When a **non-`Macro` compiler directive** (`` `include ``, `` `ifdef ``,
  `` `endif ``, `` `undef ``, …) appears in the list, `parse_macro_token` pushed
  an "unexpected token" error and `return`ed **without consuming it**. Trivially
  reached by injecting `(` near any `` `include ``/macro token, so the rest of the
  file is scanned as a macro argument. (`` `define `` did *not* trigger it —
  `compiler_directive()` has no `` `define `` arm, so it falls through to `Macro`
  and is consumed as a bogus macro name, which happens to advance.)
- **`` `define M( … ) `` with a stray delimiter in its parameter list.** A token
  that is neither an identifier, `)` nor `,` (e.g. a `/` or `"` in a corrupted
  define) is matched by none of the loop's `expect`/`eat` calls, so `parse_define`
  spins on it.

A `sample` of a hung compile showed each loop exactly (`parse_macro_call` /
`parse_define` → `Parser::eat`/`expect` → `RawVec::grow_one` → `realloc`, the
diagnostics vector growing forever).

**Fix** (`preprocessor/src/grammar.rs`): guarantee forward progress. The
stray-directive branch of `parse_macro_token` now consumes the offending token
after reporting it (`p.bump()`); and *both* collection loops gained a backstop
that records the source offset and bails with a clean `UnexpectedEof` if an
iteration consumes nothing — so no non-advancing token, present or future, can
spin them. No valid model puts a directive inside a macro call's parentheses or a
stray delimiter in a `` `define `` parameter list, so valid input is unaffected.

## Finding B — a flood of diagnostics rendered without bound

With Finding A fixed, deeply nested *non-macro* garbage (e.g. `sin(`×3000 in a
declaration) no longer looped, but still took ~40 s: it produces thousands of
parse errors, and `codespan_reporting` builds a full source-annotated report for
**every** one. Rendering ~3000 diagnostics, each extracting and laying out its
surrounding source, is the entire cost (it persists with stderr redirected to
`/dev/null` — it is the *building*, not the writing). A bounded-but-40-second
rejection is still a denial-of-service vector.

**Fix** (`basedb/src/diagnostics/sink.rs`): cap the number of diagnostics the
console sink *renders* at **128**; beyond that it only advances the counters and
prints a one-line "further diagnostics suppressed" note. `summary()` still
reports the true error total, and the exit code is unchanged. This is the
standard "too many errors" behaviour of rustc/clang, and it does not affect any
input with ≤128 diagnostics (i.e. every real model and every ordinary mistake).

## Result

| Pathological input | before | after |
|---|---|---|
| `` `name( `` + stray `` `include `` | **hang (∞)** | clean error, &lt;0.01 s |
| real model + injected `(` (macro-arg split) | **hang (&gt;90 s)** | clean error, &lt;0.05 s |
| `sin(`×3000 in a declaration | ~40 s | clean error, &lt;1 s |
| file with a few real errors | (unchanged) | (unchanged, all shown) |

## Verification

- **`examples/robustness_examples`** (the E-148 hardening suite) gains eight
  argument-collection cases — five macro-call (`` `m( `` followed by
  `` `include ``/`` `ifdef ``/`` `endif ``/`` `undef ``, and one with 4000
  leading `(`) and three `` `define `` parameter-list ones (`M(a,/,b)`,
  `M(a"b)`, `M(a;b)`) — plus a valid macro-call-with-nested-parens regression:
  **26/26**, every pathological input erroring in well under a second.
- **Production corpus** (`VA_TEST/compile_all.py`): all **92/92** standalone
  models still compile to the identical verdict — the fixes touch only
  malformed-input paths.
- **Mutation fuzzing**: re-running the campaign fuzzer for **3,000 iterations**,
  the ~2% hang rate drops to **0 hangs, 0 crashes** (it also runs 2× faster —
  no iteration stalls on a 15 s timeout).

## Scope

openvaf-r only, two files (`openvaf/preprocessor/src/grammar.rs`,
`openvaf/basedb/src/diagnostics/sink.rs`). No change to any valid program's
output beyond the &gt;128-diagnostic suppression note.
