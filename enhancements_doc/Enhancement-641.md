# Enhancement-641: macro text survives the paramset fold's re-rendering (IHP hunt A1)

**Scope:** A1 of the
[2026-09-15 IHP SG13G2 hunt](../docs/bug_hunts/2026-09-15_ihp-sg13g2-paramset-library.md)
— a paramset with an out-of-module reference over a module built from macros
(r3_cmc, PSP103) could not compile. Compiler, preprocessor:
`openvaf/preprocessor/src/parser.rs` (a `//` comment is not macro text; two
bumps that keep the trivia after a token), `grammar.rs` (the argument
reference, the macro call and the `` `include `` directive keep their
separators), `processor.rs` (the separators appended after the expansion /
the included file), `tests.rs` + `test_data/` (a new golden test, five
goldens moved by white space only). Also `openvaf/openvaf/tests/integration.rs`
and `melange/core/src/veriloga.rs` (the `dump_json` field E-640 added to
`Opts` was missing from their initializers, so the workspace test suite did
not build), and `examples/constguard_examples/verify_constguard.py` (check
[24]'s expectation, see below). New suite
[`macrofold_examples`](../examples/macrofold_examples/) (4 checks per
solver). **Compiler side.**

**Suites:** `macrofold_examples` 4 of 4 per solver, both solvers (0 of 4 on
the E-640 compiler); the workspace `cargo test` green (`sourcegen` and
`verilogae` excluded as before); full sweep 514 of 514.

## What was wrong

The E-563 fold serves LRM 6.4.1's "hierarchical out-of-module references to
local parameters of a different module" (`.rsh = corner_res.rsh_rsil;`) by
substituting each reference textually and re-parsing the result: it takes
the text of the parsed tree — the **preprocessed** token stream, macros
expanded and includes spliced — writes it as a virtual `<file>__paramset.va`
and makes that the root. Three things the preprocessor did to macro text did
not survive being laid out as text again:

1. **A `//` comment at the end of a `` `define `` body was kept as macro
   text.** IEEE 1364-2005 19.3.1 (the LRM's reference for `` `define ``):
   *"If a one-line comment is included in the text, then the comment shall
   not become part of the text substituted."* The parser never noticed — a
   comment is trivia — but rendered inline the comment ran to the end of the
   line: `tk = 273.15 // 0C in K+ 27.0;`. r3_cmc's `` `TABS_NIST2004 273.15
   // (NIST2004) 0C in K `` is exactly that.
2. **The white space after an argument reference in a body, and after a
   macro call, was dropped** — `bump` skips the trivia behind the token it
   consumes, and those two paths used it. `begin : blk \` on one line and
   `real t;` on the next expanded to the tokens `blkA` `real` with nothing
   between them: parsed fine, re-rendered as `blkAreal`. A call at the end
   of a line glued its last token to the next line's first: `endI(p,n)`.
3. **The line break after an `` `include `` directive was dropped** the same
   way, so an included file that ends without a newline — PSP103's
   `PSP103_scaling.include` ends in `end` — ran into the next line of the
   including file: `endEPSOX = 8.85e-12 * EPSROX_i;`.

The fold returns early when the file holds no reference, which is why the
constant-only paramset suites never met any of it, and why every IHP
paramset — all of which read a corner module — met all of it.

## What changed

The preprocessor now produces a token stream whose text means what the
tokens mean, so the fold's rendering is faithful by construction (and
`--print-expansion` reads right):

- `save_tokens_to_macro` drops a `LineComment` from a body (19.3.1); a block
  comment is macro text and stays.
- Two new bumps, `bump_keep_trivia_to_macro` and `bump_keep_trivia`, consume
  a token and keep the trivia after it — into the macro body, or handed
  back as output tokens — capped at the define's end like `bump_to_macro`,
  and guarded for a token that is the last one before that end (a file that
  ends in a macro use, or an `` `include `` at end of file with no newline,
  used to slice past the end).
- An argument reference keeps its trailing trivia in the body;
  `parse_macro_call` returns the trivia that followed the call (the name of
  a call without arguments, the `)` of one with), and its two callers append
  it after the expansion — the processor to the output stream, the body
  parser as resolved tokens after the nested `MacroCall`; `parse_include`
  does the same for the line break after the string literal, appended after
  the included file's tokens; `` `__FILE__ ``/`` `__LINE__ `` likewise.

One visible side effect: the trivia after an `` `include `` line is now
*converted*, not skipped, so a lexer error hiding in it is reported. An
unterminated `/*` opened right after an include used to swallow the module
in silence and surface only as "defines no module" (with a help line
guessing at the cause); it is now `unexpected EOF, expected */` at the
comment. `constguard_examples` [24] accepts the precise message.

Five preprocessor goldens moved — every difference is a `WHITESPACE` token
that is now kept (a newline after a macro call, after an include, after a
`` `define `` whose body ends in a nested call). A new golden,
`macro_text_separators`, pins the four cases: the trailing comment gone from
the body, `blkA \` then `real t;`, `end` then the next line, an include
without a trailing newline followed by `next;`, and a file ending in a macro
use.

## Verification

| check | result |
|---|---|
| the minimal reproducer (`macrofold.va`: trailing-comment macro, multi-line macro with an argument before a continuation, nested macro, an include ending in `else` with no newline, two paramsets reading `consts.rsh`/`consts.scale`) | compiles; 1/7 + 1/14 A through the fold |
| `--print-expansion` of it | `tk = 273.15 + 27.0 ;`, `begin : blkA \` / `real t ;`, `end` / `I ( p , n )`, `else` / `g = g * 1.0 ;` |
| IHP `resistor_paramset.va` bound to `res_typ` with `cornerRES.va`'s constant corners included (the real OOMR fold over r3_cmc) | compiles; rsil/rppd/rhigh at 1 mA = 0.024731 / 0.39397 / 3.4375 V, the gnucap reference values |
| IHP `sg13g2_moslv_paramset.va` bound to `moslv_tt` with `cornerMOSlv.va`'s corners (the fold over PSP103, 14 include files) | compiles in 2.5 s; nmos Id(1.2 V, 1.2 V) = 85.558 µA, the gnucap reference |
| the same two files on the E-640 compiler | `unexpected token 'end'; expected ';'` at `tiniK = 273.15 // (NIST2004) 0C in K+tnom;`; `'endEPSOX' was not found` |
| `cargo test -p preprocessor` | 8 of 8 (the new golden included) |
| workspace `cargo test --features llvm18` (verilogae excluded; `sourcegen`'s three generator tests rewrite generated files on an unpatched tree and are reverted) | every other binary green, the `openvaf` integration tests (25) and UI tests (16) included — they did not build before the `dump_json` fix |
| `macrofold_examples` | 4 / 4 per solver, both solvers; 0 / 4 on the E-640 compiler |
| `constguard_examples` [24] (an unterminated `/*` after the include line) | the lexer's own `unexpected EOF, expected */` now, where "defines no module" was the only symptom; `vafcrash2_examples` (an `` `include `` at end of file, an unterminated string after it) 19 / 19 |
| full sweep | 514 of 514 |

## What this does not do

The corner binding (`corner_res` is an instance the netlist creates, not a
module — the hunt's *Features* 1), the §6.4.1 statistical route (*Features*
2), the literal seed (A2) and the ngspice-side selection bugs (B1, B2, C1)
are separate enhancements; the IHP verification above binds the corner by
renaming `corner_res.` to `res_typ.` and leaves the statistical corners out
of the include.
