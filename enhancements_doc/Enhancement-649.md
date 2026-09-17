# Enhancement-649: a nature or discipline attribute value is a constant expression (2026-09-16 hunt F5)

**Scope:** F5 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md).
Compiler: `openvaf/syntax/src/ast/expr_ext.rs` (`ast::Expr::fold_constexprval`,
the folder, with `int_pow` for IEEE 1364-2005 Table 5-6),
`openvaf/hir_def/src/item_tree/lower.rs` (a nature's `abstol` and its other
attributes, a discipline's attributes and overrides, and the `[msb:lsb]` bound
folder `fold_const_int` all go through it), `openvaf/hir_ty/src/validation.rs`
(a help line on "not a real constant" naming what folds). New suite
[`natureexpr_examples`](../examples/natureexpr_examples/) (20 checks per
solver). E-422's `natureref` suite: three expectations updated. **Compiler
side.**

**Suites:** `natureexpr` 20 of 20 per solver, both solvers (1 of 20 on the
E-644 compiler); `natureref` 52 of 52; `filterforms` (E-405's bounds) 85 of
85; workspace `cargo test` green; full sweep 522 of 522.

## What was wrong

LRM A.1.6: `nature_attribute ::= nature_attribute_identifier =
nature_attribute_expression ;` with `nature_attribute_expression ::=
constant_expression | nature_identifier | nature_access_identifier`. The
compiler folded an attribute value with `as_constexprval`, which sees one
literal and an optional sign, so

```verilog
nature N1; units = "x"; access = X1; abstol = 1e-3*1e-3; endnature
```

was refused as `nature 'N1' declares an abstol that is not a real constant`
and the nature was left with no abstol at all. E-422 had added that report
(before it, the discard was silent) but not the fold, and its suite pinned
`abstol = 1e-6+0.0` as refused while calling it "perfectly sane".

The same folder served every other attribute value, with three quieter faces.
A user-defined nature attribute or a discipline override spelled as an
expression (`potential.abstol = 1e-3*1e-3`) was stored with no value and
dropped from the `.osdi` tables, and nothing said so. Worse, the model's own
read of `p.potential.abstol` goes through the body lowering, which evaluates
any expression: the model read 1e-6 while ngspice's convergence test (E-539)
applied the nature's own 1e-12 underneath. One declaration, two values; the
suite's check 10 on the E-644 compiler shows exactly that
(`stamped 1e-12, read back 1e-06`). And E-405's integer folder for
`[msb:lsb]` bounds was a second copy of the same idea, without `**` or the
`<<<`/`>>>` shifts.

## What changed

`ast::Expr::fold_constexprval` folds a constant expression built from
literals: parentheses, unary `+`/`-`, binary `+ - * / % **` and, on integers,
the four shifts, with the LRM's operand rules (4.1). Two integers make an
integer, division and remainder truncating toward zero, `>>` zero-filling and
`>>>` sign-extending as the lowering does, and a negative-exponent integer
`**` following Table 5-6 exactly as `lower_int_pow` does at run time (`0 **
-1` is 0 on both paths rather than one answer each); any real operand makes
the result real, and a string folds only on its own. Every integer step is
checked, so an overflow or an integer division by zero is "not a constant"
rather than a wrap or a panic. A real division by zero folds to the infinity
or NaN it is and the consumer judges it: `abstol = 1.0/0.0` is now refused as
`abstol = inf, which is not a usable absolute tolerance`, by value.

The folder is syntactic on purpose. It runs in the item tree, before name
resolution, so a name, a function call or a system function still folds to
nothing and takes the path it always took; a `` `define `` has been expanded
by then, so `` `MY*`MY `` folds. A nature's `abstol`, its other attributes, a
discipline's attributes and overrides, and `fold_const_int` all call it, so
there is one folder rather than three. The "not a real constant" report keeps
its sentence and gains a help line: LRM A.1.6 allows a constant expression
here, and this is what folds and what does not.

## Verification

| check | result |
|---|---|
| `abstol = 1e-3*1e-3` | compiles; ngspice stamps 1e-6 on the node (E-585's `set ngdebug` line), the same value the model reads back from `p.potential.abstol` |
| `(1e-6)`, `1e-6/1000`, `2.0**-20`, `-(-1e-6)`, `` `MY*`MY ``, `1e-6+0.0`, `7.5 % 2` | each folds, stamps and reads back the same value |
| a discipline's `potential.abstol = 1e-3*1e-3` over a nature saying 1e-12 | 1e-6 stamped and read back (the E-644 compiler stamped 1e-12 and read back 1e-6) |
| `1/1000000`, `10**-6` | fold to the integer 0 and are refused as `abstol = 0` |
| `-7.5 % 2`, `1.0/0.0`, `0.0/0.0` | refused as `abstol = -1.5`, `inf`, `NaN`, by value |
| `"abc"`, a name `1e-3*x`, a call `pow(10,-6)` | still "not a real constant", with the help line |
| `real a[0:2**2-1]; integer b[0:(1<<<1)]` | compile through the shared bound folder; `a[3]` and `b[2]` usable |
| a literal `abstol = 1e-12` | unchanged |
| `natureref` (E-422) | 52 of 52 after moving `1.0/0.0` and `0.0/0.0` to the refused-by-value list and `1e-6+0.0` to accepted |
| workspace `cargo test` (verilogae and `sourcegen` excluded as before) | green, no generated file rewritten |
| `natureexpr_examples` | 20 / 20 per solver, both solvers; 1 / 20 on the E-644 compiler |
| full sweep | 522 of 522 |

## What this does not do

A name is still not folded: another nature's attribute (`Voltage.abstol/10`)
or a function call would need the value computed after name resolution and
inference, on the body path, and the item tree's `abstol` field is filled
before either exists. The help line says so. An integer expression that
overflows is "not a constant", as E-405 chose for bounds, rather than a
wrapped value. A user-defined attribute's folded value now reaches the `.osdi`
tables, but nothing in ngspice reads a user-defined attribute. The remaining
hunt findings (F6 to F8) are separate enhancements; the misspelt
`string nature attriubte reference` in a type-mismatch message, met while
writing the string check, belongs to F6's diagnostics list.
