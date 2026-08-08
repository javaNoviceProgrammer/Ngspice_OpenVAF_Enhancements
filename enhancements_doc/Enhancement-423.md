# Enhancement-423 — the comma that ate the rest of the expression

```verilog
r = (1.0, 2.0);        // compiled clean. r == 1.0
r = (3.0, 2.0, 1.0);   // compiled clean. r == 3.0
```

A parenthesised comma list was accepted **everywhere an expression is wanted**
and silently reduced to its first element: ordinary expressions,
`parameter`/`localparam` defaults, elements of an array literal, `from`-range
bounds, contributions, access-function arguments, array indices (`a[(0,1)]` →
`a[0]`), and function-call arguments (`max((1,2),3)` → 3).

That alone would be an ordinary silent-wrong-answer defect. The sharper half is
what it did to *other* errors.

## It was a place errors went to hide

Every one of these compiled clean:

| written | what was hiding in the dropped element |
|---|---|
| `(1.0, nosuchname)` | an undeclared name |
| `(1.0, nosuchfunc(3))` | an undeclared function |
| `(1.0, "a string")` | a type error |
| `(1.0, max(1))` | a builtin with the wrong argument count |
| `(1.0, last_crossing(V(p,n), 7))` | an argument Enhancement-420 rejects |

`nosuchname` written alone is rejected. `(nosuchname, 1.0)` is rejected too —
which is the proof that **only the first element was ever analysed**. Everything
after the first comma was discarded before name resolution, before type checking,
before every argument check this project has added.

## Root cause: a tuple loop that was never meant to be here

`parser/src/grammar/expressions.rs`, `paren_expr`, carried a tuple-parsing loop
over from rust-analyzer, with its original Rust test comment still sitting in it:

```rust
while !p.at(EOF) && !p.at(T![')']) {
    // test tuple_attrs
    // const A: (i64, i64) = (1, #[cfg(test)] 2);
    if expr(p).is_none() { break; }
    if !p.at(T![')']) { p.expect(T![,]); }
}
```

Verilog-A has no tuples. `hir_def/src/body/lower.rs` then does

```rust
ast::Expr::ParenExpr(e) => return self.collect_opt_expr(e.expr()),
```

— `e.expr()` is the **first** child, so the later children never reached the HIR
and nothing downstream could see them.

**Enhancement-387's comment sits directly above that loop.** It lists the
malformed expression forms it enumerated while fixing the `()` crash — `{}`,
`{1,}`, `a[]`, `? :`, `sqrt()`, `1+` — and notes that every one was already
rejected in the parser. This one was missed because it is *not malformed to that
loop*: it parses perfectly, it just means something the author did not write.

And once again the aggregate siblings were already handled: `{1.0, 2.0}` and
`'{1.0, 2.0}` used as a real are correctly **type**-rejected, and still are. The
recurring shape — handled for one form, silently not for its sibling.

## Why it matters, measured rather than asserted

Compact models are full of long parenthesised sums split across lines. A comma
where a `+` was meant:

```verilog
I(p,n) <+ (gm*V(p,n) ,        // meant +
           gds*V(p,n));
```

takes `i(v1)` from **−5 mA to −1 mA** — a 5× wrong answer, silently, from source
that looks right at a glance. A deleted builtin name does the same: `pow(gm,2)`
written `(gm,2)` gives 3 instead of 9.

Both are checked in the example suite as **numbers**, not as diagnostics: the
correct spelling is compiled and simulated to −5 mA, and the one-character
variant must now be rejected.

## The fix

`paren_expr` parses exactly one expression. If a comma follows, it reports
`CommaExpr` and then consumes the rest of the list so the caller resynchronises
on `)` instead of producing a cascade.

It is reported in its own right rather than as a generic `UnexpectedToken`, for
the same reason Enhancement-387 gave `ExprTooDeep` its own variant: the source is
not malformed, so a "expected `(`, `{`, identifier, …" message would describe a
problem the source does not have. What it says instead:

```
error: a parenthesised list is not an expression
  |
5 |   r = (1.0, 2.0);
  |            ^ expected ')' -- Verilog-A has no comma expression
  |
  = only the FIRST element was ever used; everything after the comma was
    discarded before it could be checked, so an undeclared name or a wrong
    argument count hiding in one was never reported
  = help: if a sum was intended, write '+' -- a comma where an operator was
    meant silently drops the rest of the expression
```

### Also: a trailing comma in a call argument list

`max(1.0, 2.0,)` was accepted — the loop in `arg_list` ended on the `)` and
counted two arguments — while the same trailing comma with one fewer argument,
`max(1.0, )`, was caught only later by the arity check, which described it as a
count problem rather than a stray comma. A comma must now be followed by an
argument, so both are a clean syntax error at the comma.

## Verification

* **`examples/commaexpr_examples` — 41/41.** Roughly half is the accept half,
  and it checks *values*, not just silence: every ordinary parenthesised form —
  a plain expression, a sum, nested parentheses, two parenthesised factors, a
  unary minus, a ternary condition, a multi-line sum, two- and three-argument
  builtins, a parenthesised call argument, and an array literal (which
  legitimately takes commas) — is compiled and its result read back from a real
  ngspice operating point.
* **The errors that used to hide are asserted to surface**, each of the five.
* **164 real models — the 124-model VA_TEST industry corpus and the 40-model
  `integration_tests` corpus — compiled with the previous shipped binary and this
  one: ZERO differences.** That is the answer to the question the hunt left open:
  no real model contains the shape, so none was silently wrong, and rejecting it
  breaks nothing. A textual grep could not have answered that; the differential
  could.
* `cargo test --features llvm18` **210/210**, no parser or MIR snapshot moved.
* **Full regression 340/340**, both solvers.

## Found by

A round-29 hunt over openvaf-r, which reached this by asking a narrow question —
"is `(1,2)` really an expression?" — after a macro probe (`` `F((1,2)) ``) came
back silent for a reason that did not fit.

The same hunt verified the preprocessor clean and it is worth recording, because
it has form (Enhancement-219's macro-argument hang): `` `include `` cycles, both
self and mutual, are caught with a proper "nests too deeply" error; 60-deep
chains, missing files, directories, empty paths, absolute paths and escaping
paths all behave; macro recursion (self, mutual, argument-recursive, doubly
recursive) is rejected by name; all four macro-arity mismatches are caught; and
400-deep chains and 400-wide expansions are fine.
