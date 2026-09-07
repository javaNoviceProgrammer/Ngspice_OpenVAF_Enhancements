# fmtdiag_examples — `%x`/`%t` conversions, the task named in a missing-argument error, lint L026 on literal formats, and `1.0 % 0.0`

Three findings of the 2026-09-07 compiler hunt
([write-up](../../docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md), F5, F6
and F7), fixed by Enhancement-578. Run `python3 verify_fmtdiag.py`; 40 checks, 16 of
which pass against the shipped compiler.

| check | what it pins |
|---|---|
| [1] `%x`, `%X`, `%t`, `%T` | the two hex synonyms IEEE 1364-2005 17.1.1.2 gives `%h`/`%H`, and the time conversion, compile with flags, width and precision and print through ngspice as C's `%x`/`%X` and, for `%t`, `%g` of the real argument (`ff FF`, `   ff|FF    |000000ff`, `2.5e-06`); `$sformat` and `$write` take them too; `%v` (a digital net strength) is still refused and the candidate list names the four new characters |
| [2] the missing-argument error | `$strobe("no %d")`, `$write`, `$fatal(0, ...)`, `$sformat(s, ...)` and a `%*d` short of its width each name their own task; `$display` still says `$display` |
| [3] lint L026 | ten literal-format shapes that used to warn or must stay quiet are quiet: a `%s` fed a string parameter with a `%g` after it, two `%s` operands, a string variable as a `%s` operand, an extra argument printed by type, `%*d`/`%-*.*f` widths, a lone run-time string, `$sformat`'s destination; a genuine run-time format with an operand warns exactly once, and so does a run-time string that sits after a literal's operands with an operand following it |
| [4] `x % 0.0` | a literal zero, `-0.0`, a localparam zero and a localparam that folds to zero are compile errors naming LRM 4.2.4 ("the result would be NaN"), in a body and in a parameter default; an overridable `parameter` zero still compiles and is the run-time `$fatal`; the integer form keeps Enhancement-333's own message; non-zero divisors are untouched |

The compile-time rule for [4] matches every other domain check in the body validator:
only a constant the compiler can see is judged (`const_num` folds literals and
`localparam`s, never a `parameter`), so a deck-supplied zero remains the model's own
business and reaches the run-time guard with the same LRM reference.
