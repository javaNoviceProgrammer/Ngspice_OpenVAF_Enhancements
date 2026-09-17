# Enhancement-647: a real converts into an integer function input, and a real `case` item matches an integer selector (2026-09-16 hunt F3)

**Scope:** F3 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md).
Compiler: `openvaf/hir_ty/src/types.rs` (`TyRequirement::Assignable`, the
requirement LRM 4.2.1's implicit conversion satisfies), `openvaf/hir_ty/src/inference.rs`
(a user function's scalar integer input formal takes it; a `case` with an
integer or boolean selector and a real item is compared as real),
`openvaf/hir_lower/src/stmt.rs` (`lower_case` takes its comparison from the
selector's cast). `examples/vafopenitems_examples/` (E-389's two checks that
pinned the refusal now pin the rounding). New suite
[`intformal_examples`](../examples/intformal_examples/) (19 checks per
solver). **Compiler side.**

**Suites:** `intformal_examples` 19 of 19 per solver, both solvers (9 of 19 on
the E-644 compiler); `vafopenitems` 28 of 28; `funcarray`, `lrmudf`,
`arraycase`, `funcarity`, `funclocal`, `paramarrayarg` green; workspace `cargo
test` green; full sweep 520 of 520.

## What was wrong

LRM 4.2.1.1 converts a real assigned to an integer by rounding; 4.7.3 assigns a
call's actual arguments to the formals; 5.8.3 compares the case expression with
each item, and between an integer and a real that comparison is a real one.
openvaf-r applied the conversion in some of those places and refused it in
others, so the hunt's table read:

| context | result |
|---|---|
| `integer k; k = 2.7;`, an integer array element, `repeat (2.7)`, a real into an integer function's *return* | accepted, rounded |
| `analog function integer f; input y; integer y;` called as `f(2.7)` or `f(r)` | **refused**: "expected integer value but found real literal" |
| `case (sel)` with `parameter integer sel` and a label `2.0` (or a real parameter) | **refused**: "expected integer value but found real literal" |
| `case (sel)` with `parameter real sel` and an integer label `2` | accepted |

The user function's inputs were matched against `TyRequirement::Val(Integer)`,
which admits only what converts losslessly (an integer, a boolean); the `case`
items were matched against `Val(<selector type>)`, so an integer selector took
integer items only while a real selector took integers by conversion. A model
that computes an index or a bin number in real arithmetic and hands it to an
integer formal — the rounding the author wrote on purpose — could only get it
through an explicit temporary.

## What changed

- **`TyRequirement::Assignable(ty)`** is satisfied, by conversion, by any value
  `is_assignable_to` the type — LRM 4.2.1's rule, a real into an integer
  included — and records the same cast `Val` does, so the value is rounded where
  it is used; for the semantic and exact rankings it behaves as `Val`, so an
  overload taking the actual's own type still wins. A user function's scalar
  `integer` input formal is matched with it. A `$random`/`$dist_*` seed and a
  shift distance keep `Val(Integer)`: neither is an assignment (Verilog forbids
  a real shift operand), and E-642's refusal of a real seed stands.
- **`case`:** the items are inferred first; when the selector is an integer or a
  boolean and any item is real, the selector is cast to real and every item is
  expected as real (an integer item then converts as before). `lower_case`
  takes its comparison opcode from the selector's cast target when there is
  one, so the `feq` sees two reals. A real selector, `casez`/`casex` masks
  (integer items only, as before) and the array `case` are untouched.

The rounding is the cast every assignment uses (2.5 → 3, −2.5 → −3, 0.5 → 1,
1.5 → 2, LRM 4.2.1.1). A `case` item that is not integral, `2.5:` under an
integer selector, matches nothing — the comparison is exact in real arithmetic,
not a rounded match.

## Verification

| check | result |
|---|---|
| `f(2.7)`, `f(-2.5)`, `f(0.5)`, `f(1.5)` into `input y; integer y;` | 3, −3, 1, 2 |
| a real variable and `V(p,n)*3` into the integer formal | 3 and 3, I = −3 A |
| an integer into a real formal; mixed formals `f(1.6, 1)` with `integer y; real z;` | unchanged (−6 A); 3 |
| `case (sel) 2.0:` with `parameter integer sel = 2`; a real parameter item | −20 A, matches |
| `case (sel) 2.5: … 3:` with `sel = 3`; `2.5:` alone with `sel = 2` | the integer item matches (−30 A); default (−99 A) |
| a real selector with an integer item; a boolean selector `V(p,n) > 0.5` with `1.0:`; `casez` with `4'b01?1`; an array `case` | −20, −5, −7, −1 A, unchanged |
| a real seed for `$rdist_normal`; `1 << 2.0`; an integer `output` formal bound to a real variable; a string into an integer formal; a string selector with a real item | still refused, same messages |
| E-389's `vafopenitems` [2] (an `integer` argument declared in the combined and the ANSI form) | now pins `f(2.7) = f(3) = 6`, where a real argument gives 5.4 — the declared type still applies |
| workspace `cargo test` (verilogae and `sourcegen` excluded as before) | green, no generated file rewritten |
| `intformal_examples` | 19 / 19 per solver, both solvers; 9 / 19 on the E-644 compiler |
| full sweep | 520 of 520 |

## What this does not do

`$strobe("%d", 2.7)` stays a type error: the specifier names the type it
prints, and a `%g` prints the real. An integer `output`/`inout` formal still
needs an integer variable to write back into. The hunt's F4 and the rest of the
list are separate enhancements.
