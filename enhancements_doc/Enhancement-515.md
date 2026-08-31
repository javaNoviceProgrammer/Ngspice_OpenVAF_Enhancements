# Enhancement-515: the lexical layer and compiler directives, audited against the LRM

**Scope:** Accellera VAMS-2023 clauses 2 (lexical conventions) and 10 (compiler
directives), plus Annex B (reserved keywords). A clause-by-clause conformance
audit of the lexer, the preprocessor, and the keyword tables — five bugs, four
missing features, one refuted finding, and a set of silently-accepted illegal
forms, all fixed or (in one case) documented as already-correct.

**Suite:** [`examples/lrmlex_examples/`](../examples/lrmlex_examples/) — 26
checks, both solvers.

## The headline: two thirds of a based literal were unwritable

LRM 2.6.1 defines a based integer constant as "up to three tokens — an optional
size constant, an apostrophe character followed by a base format character, and
the digits", says the digits may be "optionally preceded by white space", and
adds: "It shall be legal to macro substitute these three tokens." Its own
Example 2 writes `5 'D 3`.

openvaf-r accepted only the fully contiguous spelling. `5 'D 3` died at the
apostrophe with "encountered unexpected token!", `12'b 0011_0101_0001` split
into an integer and an error, and the macro-substituted size

```verilog
`define SZ 8
a = `SZ'hFF;      // "unexpected token integer; expected ;"
```

could not be written at all — which matters because real model headers size
their field constants with macros.

The fix runs through the whole stack. The lexer now produces two new token
kinds: a complete unsized based literal (`'hFF`) and a bare base prefix (`'D`)
whose digits follow after white space. The parser's literal grammar joins
`[size] [base] [digits]` sequences into one literal node — the digits blob may
lex as an integer, an identifier (`FF`, `z3`), or an integer directly followed
by an identifier (`837FF` → `837` + `FF`), and exactly one of each is taken.
Evaluation joins the node's token texts (dropping white space and `_`) and
reuses the existing based-literal parser, so the semantics — signedness,
truncation, sign extension — are shared with the contiguous form byte for byte.
A joined literal whose digits are illegal for its base (`4'b 29`) is a located
error rather than a silent zero, because the multi-token form would otherwise
degrade quietly where the single-token form physically cannot.

The suite evaluates all five spaced/macro forms *at run time, next to the
contiguous forms*, so a regression in either direction shows as a number.

## Predefined macros: one missing, none protected

LRM 10.5: `__VAMS_ENABLE__` "shall always be defined during the parsing of
Verilog-AMS source text" — its whole purpose is the LRM's own
works-in-both-languages `not_gate` idiom. It was not defined; the idiom could
never take its VAMS branch. It is now in the predefined set (whose canonical
list moved into the preprocessor, re-exported to `basedb::STANDARD_FLAGS`).

LRM 10.4: "The `undef compiler directive shall have no effect on predefined
Verilog-AMS macros; the simulator may issue a warning." `` `undef
__VAMS_COMPACT_MODELING__ `` removed it — a model could sabotage its own
feature detection. `` `undef `` (and `` `undefineall ``) now leave the
predefined set alone, with the warning the clause suggests. The same clause
reserves the `__VAMS_` name prefix, so a user `` `define `` there warns too.

## Keywords: three words reserved that the LRM never reserved

Annex B's Table B.1 does not contain `assert`, `root`, or `do` — all three are
legal Verilog-AMS identifiers — yet `real assert;` was a hard "reserved
keyword" error, and `root`/`do` failed as "unexpected token". Each had a
different root: `assert` sat in the hand-written semantic reservation list
(removed); `root` was a full lexer keyword so that `$root` paths could parse
(the keyword table now has a *contextual* tier — the `ROOT_KW` token survives
for the `$root` spelling, the bare identifier lexes as a name); and `do` fed
the do-while extension, so it is reclassified by one token of lookahead in the
parser's token stream — `do` stays a keyword exactly where a do-while body can
start, and is an identifier in `real do;`, `do = 3.0;`, `y = do + 1`. The
do-while suite is untouched.

The audit's flip side — Table B.1 *does* reserve `break`/`continue`/`return`
(new in VAMS-2023) and `expm1`/`ln1p`, which this compiler deliberately leaves
usable — stays as-is: the `expm1`/`ln1p` decision is documented in
`syntax/src/name.rs` (reserving them broke eight shipping HiSIM models), and
the jump-statement words belong with the jump-statement feature.

## Attributes: the expression positions existed only in the LRM

LRM 2.9: an attribute instance "can appear as a suffix to an operator or a
Verilog-AMS function name in an expression". Every such position was a parse
error. The expression grammar now consumes attribute lists after binary and
unary operators, after `?` (A.8.3's exact position), and between a function
name and its argument list.

The same clause says that when an attribute name is written twice, "the last
attribute value shall be used". The audit reported first-wins here — and this
is the enhancement's **refuted finding**: the attribute iterators walk the
lists in reverse, so first-match-of-reversed *is* the last value. The suite
pins it through the OSDI descriptor text (`(*desc="dup attr", desc="last
wins"*)` publishes "last wins") so the question stays answered.

## Directives: `begin_keywords`, `resetall`, and a lost working directory

`` `begin_keywords ``/`` `end_keywords `` (LRM 10.6) were undeclared-macro
errors. They now parse and validate the five version specifiers the clause
names; the VAMS sets are satisfied as-is, a `1364-*` set warns that this
compiler keeps its single VAMS-2023 keyword table, an unknown specifier warns
and lists the valid five, and a stray `` `end_keywords `` warns instead of
dying.

`` `resetall `` warned "unsupported compiler directive" while the compliance
document listed it as supported. It now genuinely resets the directive state
the compiler tracks (`` `default_transition ``, `` `default_discipline ``) —
text macros are not directives and survive, per IEEE 1364 19.6 practice.

Using `` `__FILE__``/`` `__LINE__ `` anywhere used to break every *relative*
`` `include `` in the compilation: the source-location rewrite compiles a
synthetic copy of the root file that lives at the VFS root, so
`` `include "incsub/level1.va" `` resolved against the wrong directory and
failed with "entity not found". The original file's parent directory is now
prepended to the synthetic root's include path (before the `-I` directories,
preserving the LRM's search order). A use inside an *included* file remains
unsupported — but the "macro not found" error now says so explicitly instead
of leaving the user to guess.

## Illegal forms that compiled in silence

LRM 2.6.2 lists `9.` among its illegal real constants ("at least one digit on
each side of the decimal point"); `x = 1.;` compiled. LRM 2.7 requires a
string to be "contained on a single line"; a raw newline inside one compiled.
Both are located errors now, with the clause in the help text.

## Refuted / unchanged

* Duplicate attributes (above): already last-wins; the audit finding is
  withdrawn and the behavior is pinned.
* `` `__LINE__ `` inside a macro body expands at the definition site, not the
  use site — an architectural property of the textual pre-pass, documented at
  the pass.
* `` `default_transition `` is compilation-global last-wins rather than
  positional; its proper fix belongs with the `transition()` operator work.

## Files

Compiler: `preprocessor/src/{lib,parser,processor,diagnostics}.rs`,
`basedb/src/lib.rs`, `basedb/src/diagnostics/{preprocessor_error,syntax_error}.rs`,
`hir/src/elaborate.rs`, `lexer/src/lib.rs`, `tokens/src/{lexer,lib}.rs`,
`tokens/src/parser/generated.rs`, `parser/src/grammar/expressions.rs`,
`syntax/src/{lib,name,parsing,validation,error,ast}.rs`,
`syntax/src/ast/expr_ext.rs`, `sourcegen/src/ast.rs`, `sourcegen/src/ast/src.rs`.
New suite: `examples/lrmlex_examples/`.
