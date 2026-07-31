# Enhancement-388 — closing the two items Enhancement-387 deferred

[Enhancement-387](Enhancement-387.md) shipped three compiler fixes and recorded
two things it deliberately did not do. This does them.

## [1] `-D` values are now substituted

E-387 fixed the **name** — `-DK=5.5` had defined a macro literally called
`K=5.5`, unreachable by any spelling — but left the **value** unimplemented, for
a concrete reason: `-D` flags were synthesised straight into

```rust
Macro { head: 0.into(), span: CtxSpan::dummy(), body: vec![], arg_cnt: 0 }
```

and a macro body is a `Vec<ParsedToken>` whose text resolves **by span against a
real source file**. A value that arrived through `argv` has no backing text, so
no body could be built for it. The body was therefore always empty, which meant
`-DK=5.5` could not substitute 5.5 *and* a bare `-DK` expanded to nothing rather
than the documented `1`.

The fix removes that synthesis entirely. The flags are written into a virtual
source file as ordinary directives —

```verilog
`define K 5.5
```

— which the preprocessor parses exactly as if the user had typed them, spans and
all. Nothing about macro expansion had to change; the definitions simply became
real.

```
-DK=5.5        ->  5.5
-DK=42         ->  42
-DK=1e-3       ->  0.001
-DK=-2.25      ->  -2.25
-DK=(2.0+3.0)  ->  5          (an expression, since it is now really parsed)
-DK            ->  1          (what `-D <MACRO[=VALUE]>` always promised)
```

**What the accept half is really guarding.** This moves *every* `-D` flag onto a
new path, and `STANDARD_FLAGS` — `__OPENVAF__`, `__VAMS__`,
`__VAMS_COMPACT_MODELING__` — travel it too. Compact models branch on those, so a
fix that defined the user's flags but dropped the standard ones would break real
models while every `-D` test still passed. They are asserted individually.

The preamble is skipped when it is empty, so a compilation with no `-D` flags
takes exactly the path it always did.

## [2] The expression-depth guard says what it means

[E-148](Enhancement-148.md) bounds expression depth so a pathologically deep
expression is rejected rather than overflowing the recursive-descent parser. It
reported that through the ordinary "unexpected token" path — `expr_too_deep()`
said so in its own comment — so a 999-term operator chain came back as

```
error: unexpected token identifier; expected '(', ''{', '{', system function...
```

a complaint about a token that is perfectly valid, with no hint that a limit
exists. It now reports itself:

```
error: expression nests too deeply
      --> deep.va:1003:6
      |
 1003 |    + k
      |      ^ expression nests too deeply
      |
      = help: openvaf limits expression nesting (and operator-chain length) to
        1000 to avoid overflowing the parser; split the expression across
        intermediate variables
```

This is the same thing the preprocessor's include guard has always done
(*"nests too deeply (a file that includes itself?)"*).

Carrying it took a new variant through both `SyntaxError` enums, the tree
builder's conversion — which was an **irrefutable `let`**, valid only while the
parser's enum had exactly one variant — and the renderer. The limit itself is
unchanged (998 terms still compile), and so is the error cascade after recovery:
**129 diagnostics before and after** on the same input.

## A test that had encoded the old behaviour

E-387's own example checked `-D` handling with

```verilog
analog I(p,n) <+ V(p,n)*1e-3 `EXT ;
```

which parsed *only because* a `-D` macro expanded to nothing. Once values
substitute, it became `... 1e-3 5.5 ;` and failed. The test was asserting the
defect, not the intent, and now uses `` 1e-3*(`EXT) `` — valid for a real
expansion. Worth recording: a test written against a broken behaviour will fail
when the behaviour is fixed, and that failure is the fix working.

## Verification

`examples/vafdefine_examples` — 16 checks.

```
   fixed:     16/16
   pre-fix:    7/16
```

The baseline is the **pre-E-387** binary, so one of the nine failures
(`` `ifdef `` seeing `-DFOO=9`) was already E-387's; the other eight are this
change. The eight accept checks pass on both: all three `STANDARD_FLAGS`,
`` `ifdef `` under both flag spellings, a compile with no `-D` flags at all, an
undefined macro still being reported, and 998 terms still compiling.

`examples/vafice_examples` remains 11/11 (4/11 pre-fix).

The compact-model corpus is unaffected: **92/92 compile** and **92/92
correctness**. Regression 311/311 → 312/312.
