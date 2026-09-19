# Enhancement-672: an undeclared macro at file scope is one error — the hole the preprocessor leaves is marked and a syntax error located at it is dropped

**Scope:** F5 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
openvaf: `preprocessor/src/sourcemap.rs` (`SourceContextData::is_hole`,
`add_hole_ctx`, `SourceMap::is_hole`), `preprocessor/src/processor.rs`
(`synth_token_in`; the undeclared-macro hole takes a hole context),
`syntax/src/error.rs` (`SyntaxError::primary_range`), `syntax/src/lib.rs`
(`Parse::without_hole_errors`, applied in `SourceFile::parse`).
`examples/hunt17diag_examples/` (three checks added, 23 per solver). Handbook
[§2.12](../docs/handbook/02-verilog-a-language.md) row. **openvaf only.**

**Suites:** [`hunt17diag_examples`](../examples/hunt17diag_examples/) 23 of 23
per solver, both solvers (2 of the 3 new checks fail on the E-670 binaries;
the third is the `` `__LINE__ `` control, unchanged behaviour); the compiler
workspace tests green apart from the three pre-existing sourcegen drift
failures; full sweep 531 of 531.

## What was wrong

[E-665](Enhancement-665.md) made an undeclared macro reference one error: the
preprocessor leaves a synthesized `0` where the reference was, so the parser
does not complain about the hole (`= ;`) as well. That holds in expression
position. Alone on its line at file scope — a misspelled directive,
`` `timescal ``, `` `defin ``, `` `unknown_directive `` — the `0` is not a
module item, and in statement position it is not a statement, so the parser
reported it in its own right, at a position inside a file that does not
exist:

```
error: macro '`unknown_directive' has not been declared
  --> file.va:1:1
error: unexpected token integer; expected 'discipline', 'nature' or 'module'
  --> /file.va__macro_synth.va:1:1
  |
1 | 0
  | ^ expected 'discipline', 'nature' or 'module'
error: could not compile `file.va` due to 2 previous errors
```

`__macro_synth.va` is the virtual file the preprocessor keeps its
synthesized tokens in (the phantom-file shape of the 2026-09-08 hunt's F2).
In statement position the second error listed the parser's whole
statement-start vocabulary.

## What changed

**The hole is marked and the parser drops what it says about it.** The
source context the hole token is created in carries `is_hole`; after
parsing, any syntax error whose primary range maps to a hole context is
removed. The reference itself is reported by the preprocessor as before, so
the compile still fails, with one error, at the reference. A synthesized
token that is not a hole — `` `__LINE__ `` or `` `__FILE__ `` expanded in
place — keeps the ordinary context, so `` `__LINE__ `` alone at file scope is
still refused as an unexpected integer: the author wrote a number where an
item goes.

The filter lives in the parser rather than the preprocessor because the
preprocessor does not know where the reference sits: the `0` is what lets an
expression-position reference parse on (E-665's reason for it), and the
context mark is what lets the other positions stay quiet.

## Verification

| check | result |
|---|---|
| `` `unknown_directive `` alone on its line at file scope | one error, ``macro '`unknown_directive' has not been declared``; nothing about `__macro_synth.va` (was two errors) |
| `` `nosuch `` in statement position inside `analog begin … end` | one error (was two; the second listed the statement-start vocabulary) |
| `` `X `` after `` `undef X `` in expression position | one error (E-665's case, unchanged) |
| `` `__LINE__ `` alone at file scope | still `unexpected token integer; expected 'discipline', 'nature' or 'module'` — a synthesized token, not a hole |
| the hunt's probe (the file-scope case above) | one error on the current compiler, two on the E-670 one |
| the E-670 binaries on the suite | 2 of the 3 new checks fail; the `` `__LINE__ `` control passes on both |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- Only an error located *at* the hole is dropped. Should the parser recover
  from a hole by blaming a later token, that error would stay; none of the
  three positions exercised produces one.
- The compile still fails: the reference is an error, and nothing stands in
  for the macro's meaning. E-665's `0` is a parse aid, not a default.
