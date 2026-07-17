# Enhancement-213 — openvaf-r crash hardening: four compiler panics

Fuzzing **openvaf-r** with malformed Verilog-A found **four distinct panics**. Instead
of printing a diagnostic, the compiler aborted with

```
OpenVAF encountered a problem and has crashed!
A log file has been generated at "…/openvaf-crash-….log".
To help us fix the problem, please open an issue at …
```

and exited 101 — telling the user to file a bug report for what is simply a typo in
their model. Every one is reachable from ordinary source mistakes; the headline case
is **a module that is merely missing its `endmodule`**, one of the most common
Verilog-A editing errors. All four are fixed here, so each input now produces a normal
error message.

This is the OpenVAF-r counterpart to [Enhancement-212](Enhancement-212.md) (the same
campaign against ngspice), and a direct continuation of
[Enhancement-148](Enhancement-148.md), which hardened the compiler against pathological
*depth* (parser recursion, `` `include `` nesting, array expansion). E-148 covered
inputs that were too big; E-213 covers inputs that stop too early or are simply
malformed.

## 1. Parse errors at end of file (the `endmodule` crash)

[`syntax/src/parsing/tree_builder.rs`](../OpenVAF-master-20260610/openvaf/syntax/src/parsing/tree_builder.rs).
When a parse error lands at EOF, the error's span was built as

```rust
span: TextRange::at(
    self.text_pos,                                                   // already the end of the file
    self.tokens.last().map_or_else(|| TextSize::from(0), |t| t.span.range.len()),  // the LAST token's length
),
```

`text_pos` is *already* the end of the source, so adding the **previous** token's
length yields a span that runs **past the end of the file** — for the 6-byte input
`module`, the span is `6..12`. Mapping that back to its source file then failed the
`assert!(range.end() <= self.range.end())` in `FileSpan::with_subrange`
(`preprocessor/src/sourcemap.rs`), which crashed the compiler *while trying to print
the error*. The panic message told the story exactly:

```
subrange 6..12 -> 6..12 must fit into the total range 0..6
```

**Fix:** the error belongs *at* EOF, so use an empty range there
(`TextRange::at(self.text_pos, 0.into())`) — precisely what the neighbouring
`expected_at` field already does.

Additionally, [`syntax/src/lib.rs`](../OpenVAF-master-20260610/openvaf/syntax/src/lib.rs)
`find_ctx_range` maps a global position to its source context through half-open
`[start, end)` ranges, which by construction **never cover the EOF position itself**
(`pos == last_range.end()` compares `Less` against every range). It `.expect()`ed and
panicked; it now clamps to the nearest range.

Triggers fixed: a module missing `endmodule`; a bare `module` keyword; a module header
followed by EOF; an unclosed `analog begin`; an unterminated string literal.

## 2. Real literal with an exponent marker but no exponent

[`lexer/src/lib.rs`](../OpenVAF-master-20260610/openvaf/lexer/src/lib.rs). The lexer
consumed `e`/`E` as an exponent marker **without checking that an exponent follows**
(the result of `eat_float_exponent()`, which reports whether it saw a digit, was
discarded). So `1e` became a `Float` token whose text does not parse as an `f64`, and
`ast::StdRealNumber::value()`'s `src.parse().unwrap()` panicked.

**Fix:** an `e` only joins the number when a digit (optionally after a sign) actually
follows it. A bare `1e` now lexes as `1` and an identifier `e`, and surfaces as an
ordinary parse error — the same approach `based_literal_body` already takes for a
malformed `8'squark`. Valid exponents (`1.5e3`, `2e-3`, `1E6`) are untouched.

Triggers fixed: `1e`, `1e+`, `99e`, `1.5e`, and `parameter real p=2e`.

## 3. Preprocessor directives that end the file

[`preprocessor/src/parser.rs`](../OpenVAF-master-20260610/openvaf/preprocessor/src/parser.rs).
Two accessors indexed the token list **directly**, which is out of bounds when the
parser sits one past the last token — a bare `` `define `` that ends the file:

* `previous_range()` — `self.full_tokens[pos]`, reached while building the
  "expected an identifier" diagnostic;
* `followed_by_bracket_without_space()` — `self.relevant_tokens[self.pos + 1u32]`
  (`index out of bounds: the len is 2 but the index is 2`).

**Fix:** both use `.get()` with a sensible fallback — a zero length, and "nothing
follows, so it is not followed by a bracket" — mirroring the `.get().map_or()` idiom
`current_range()` already used.

Triggers fixed: `` `define ``, `` `define M(a ``, `` `ifdef ``, `` `include `` at EOF.

## 4. `path()` asserted a precondition its callers do not check

[`parser/src/grammar/paths.rs`](../OpenVAF-master-20260610/openvaf/parser/src/grammar/paths.rs).
`path()` began with `assert!(p.at_ts(PATH_SEGMENT_TS))`. Several callers do not check
that precondition and reach it on plausible input, crashing the compiler:

| input | caller |
|---|---|
| `aliasparam x = 5;` — a literal where a parameter name belongs | `alias_parameter_decl` |
| `aliasparam x = ;` | `alias_parameter_decl` |
| `I(<1>)`, `I(<>)` | `port_flow` |
| `discipline d 1 = 2;` | `discipline` |

**Fix:** drop the assert. The very next line, `p.expect_ts(PATH_SEGMENT_TS)`, already
emits "expected identifier" and returns false, so the error is reported and an empty
path node completed. (`nature`'s parser already guarded its own call site this way in
[Enhancement-39](Enhancement-39.md); this makes the helper itself safe for every
caller.)

## Verification

New suite [`examples/vafcrash_examples/verify_vafcrash.py`](../examples/vafcrash_examples/verify_vafcrash.py)
(25 checks) drives every repro and asserts it now yields a clean error instead of a
crash, plus regression checks that valid code is unchanged (a resistor; real exponents
`1.5e3`/`2e-3`/`1E6`; an `aliasparam` bound to a real parameter; a `` `define `` with
arguments).

One detail worth noting: openvaf-r installs a **custom panic hook** that prints its own
message and exits **101**, rather than dying on a signal or printing the usual Rust
`panicked at`. A crash check that only looks for those two — as E-148's suite does —
would score these panics as ordinary errors, so the new suite treats exit code 101 and
the hook's message as a crash.

Toolchain tests pass unchanged (`lexer` 8, `preprocessor` 6, `basedb` 9, `sim_back` 26,
`hir` 15, `hir_lower` 4). Full regression: 173/173.

## Scope

openvaf-r only, five files (`syntax/src/lib.rs`,
`syntax/src/parsing/tree_builder.rs`, `lexer/src/lib.rs`,
`parser/src/grammar/paths.rs`, `preprocessor/src/parser.rs`). No change to any
accepted program: every fix is on a path that previously aborted the compiler. The
generated OSDI for every existing model is unchanged — the full example suite compiles
and simulates identically.
