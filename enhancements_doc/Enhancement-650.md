# Enhancement-650: eleven diagnostic slips from the 2026-09-16 hunt (F6)

**Scope:** F6 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md),
eleven small findings about what the compiler says, plus one spelling met
while fixing E-649. Compiler, by item: `openvaf/hir_ty/src/inference.rs` and
`openvaf/hir_ty/src/validation/body.rs` (a contribution destination whose
access names no nature of the branch's disciplines is reported by body
validation, not as "invalid destination"; `NonIntegerSetMember`);
`openvaf/preprocessor/src/{diagnostics,parser,processor,grammar}.rs` and
`openvaf/basedb/src/diagnostics/preprocessor_error.rs` (six new preprocessor
diagnostics: `UnmatchedConditional`, `BackslashBeforeWhitespace`, `NulByte`,
`LineDirectiveNotApplied`, `IncludeCycle`, `EmptyMacroArgList`; an include
stack); `openvaf/lexer/src/lib.rs` and `openvaf/syntax/src/validation.rs`
(`.5` lexes as one real; string escapes are checked); `openvaf/syntax/src/error.rs`
and `openvaf/basedb/src/diagnostics/syntax_error.rs` (`OctalEscapeTooLarge`,
`UnknownStringEscape`); `openvaf/basedb/src/lints.rs` (lints
`unknown_string_escape` L032, `line_directive_not_applied` L033,
`dead_range_member` L034; `LintRegistry::names`);
`openvaf/hir/src/diagnostics.rs` (the lint attribute tree's and the body
source map's own reports are emitted at last);
`openvaf/basedb/src/lint_attrs/diagnostics.rs` (a "did you mean");
`openvaf/basedb/src/diagnostics.rs` (a note naming the `-D` argument behind a
diagnostic in the virtual defines file); `openvaf-driver/src/cli_process.rs`
(the shape of a `-D` argument); `openvaf/hir/src/elaborate.rs` (`%m` in an
inlined child, `Scope::hier_path`, `qualify_hier_name_format`);
`openvaf/hir_ty/src/types.rs` (the spelling). New suite
[`diagslips_examples`](../examples/diagslips_examples/) (32 checks per
solver). `robustness` and `intrange`: one expectation each. **Compiler side.**

**Suites:** `diagslips` 32 of 32 per solver, both solvers (10 of 32 on the
E-644 compiler); `robustness` 26 of 26 and `intrange` 12 of 12 after their
updates; `stresc`, `vafdefine`, `lrmlex`, `display`, the three `hunt*diag`
suites and every other suite pinning a message green; workspace `cargo test`
green (the preprocessor's `misc_directives` now tolerates the `` `line ``
warning); full sweep 523 of 523.

## What was wrong, and what it says now

Every item is a message that blamed the wrong thing, said nothing, or said
"encountered unexpected token!" for an input that deserved a sentence of its
own.

| input | before | now |
|---|---|---|
| `Pwr(p,n) <+ 1.0` with `electrical p; thermal2 n;` | "invalid destination for branch contribution … expected nature access such as V(foo) or I(foo)" | "nodes 'p' and 'n' of branch '(p,n)' have incompatible disciplines!", with both declarations and the LRM 3.11.1 rule, as a read already got |
| `` `endif `` / `` `else `` with no `` `ifdef `` | "encountered unexpected token!" | "'`endif' without a matching '`ifdef' or '`ifndef'" |
| `` `define K \ `` with two spaces before the newline | the same | "a '\' line continuation must be the last character on its line, but 2 white-space character(s) follow it" |
| a NUL byte in the source | the same | "the source contains a NUL byte", with the binary/UTF-16/truncated-file hint |
| `` `line 100 "other.va" 0 `` | accepted in silence | a warning (L033): it moves `` `__FILE__ ``/`` `__LINE__ `` only, diagnostics keep the physical position |
| `(* openvaf_allow="no_such_lint" *)` | accepted in silence | "unknown lint 'no_such_lint'" (L008, deny), and "did you mean 'discarded_contribution'?" for a near miss |
| `parameter integer k = 1 from {1, 2.5};` | compiled without a word | a warning (L034): no integer equals 2.5, so the member can never be chosen |
| `.5` | "unexpected token '.'; expected '(', …" | LRM 2.6.2's sentence, the one `5.` already had |
| `"\777"` | printed U+01FF | refused: an octal escape names one 8-bit character, `\377` is the largest |
| `"\q"`, `"\x41"` | kept verbatim, in silence | kept verbatim, with a warning (L032) |
| `%m` in an inlined child instance | the top instance's name, `na1` | the hierarchical name, `na1.l1.l2`, `na1.l1.arr[0]` |
| `-D G==2.0`, `` -D `G=2.0 ``, `-D 1G=2` | a syntax error at `/std/__openvaf_defines__.va:5:11` | refused on the command line by shape, each with the corrected spelling; a value that fails to parse (`-D 'G=)'`) keeps its location and gains a note naming the argument |
| a file that `` `include ``s itself after its module | "'`include "disciplines.vams"' nests too deeply", 64 levels down | "'`include "self.va"' includes a file that is already being included", at the first occurrence |
| `` `define G() 6.0 `` | "unexpected token, expected 'an identifier'" at the `)` | "a macro with parentheses needs at least one formal argument" (IEEE 1364-2005 19.3.1) |
| a string where a real is expected | "string nature attriubte reference" | "string nature attribute reference" |

Three of these were not the message's fault but a missing wire: the unknown
lint name *was* checked (`UnknownLint`, a deny-level lint since the
beginning) and its report collected into the lint attribute tree for
declarations and into the body source map for statements; neither was ever
handed to a diagnostics sink. The contribution case was the reverse: inference
marked the access invalid and then reported the destination's shape itself,
and body validation, which knows the disciplines and would have named them,
never saw a destination without a recorded assignment target. The self-include
case was a bound where a stack was needed: the depth limit fired at level 64
on whichever include sat there.

## Decisions

The `from` set member is a warning and a lint, not an error: `intrange` pins
`from {1.5, 2, 3}` on an integer as legal-and-unreachable, and a range spec
shared with a real parameter may carry one on purpose. An `exclude` member is a
negative claim, vacuously true for an integer, and is left alone. An unknown
escape stays a warning because Enhancement-48 decided the backslash is kept
verbatim and `stresc` pins it; the octal case is an error because IEEE
1364-2005 2.6.3 says an implementation may refuse it and there is no character
to emit. The `` `line `` warning is a lint so generated code that carries the
directive on purpose can silence it from the command line. `.5` is lexed as one
real token only when a digit follows the dot directly, which no legal construct
does (a hierarchical name continues with an identifier).

## Verification

| check | result |
|---|---|
| each row of the table above | the "now" message, and the "before" message absent |
| `` `line `` | warned, `` `__LINE__ `` after it reads 100, an error after it is reported at the physical line |
| a known lint name on a parameter | still silences its lint |
| `exclude {2.5}`, `from {1, 2}` on an integer, `from {1, 2.5}` on a real | clean |
| `0.5`, `1.5e-3`, `2.5u`, `p.potential.abstol` | untouched by the new lexer rule |
| `\101`, `\n`, `\t`, `\\`, `\"` | raise nothing |
| `%m` in `mid l1` → `leaf l2` and `leaf arr[0:1]` | `na1.l1.l2`, `na1.l1.arr[0]`, `na1.l1.arr[1]`; `%%m` stays; the top prints `na1` |
| `-D G=2.0`, `` `define G(a) `` | unchanged |
| two files including each other | the cycle named once, at the second file's include |
| `robustness` (E-148's self-include check) and `intrange` (E-590's real set member) | updated to the new message and the warning; green |
| workspace `cargo test` | green |
| `diagslips_examples` | 32 / 32 per solver, both solvers; 10 / 32 on the E-644 compiler |
| full sweep | 523 of 523 |

## What this does not do

`` `line `` still does not relocate diagnostics; doing so would need a source
map that can override the file and line of a token range, and the warning says
exactly that. `\xhh` is not adopted (it is SystemVerilog's), only warned about.
A `\ddd` between `\200` and `\377` is still emitted as the UTF-8 encoding of
that code point, as Enhancement-48 left it. A `-D` value that fails to parse is
still reported inside the virtual defines file, now with the note. The
remaining hunt findings (F7, F8) are separate enhancements.
