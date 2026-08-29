# Enhancement-508 — a compile-time table built from a value that cannot be folded

This one came from a **static audit**, not a hunt. Four consecutive enhancements
(504, 505, 506, 507) had each closed instances of the same vein — *a check that
does not cover the route the value actually takes* — so rather than sample it a
fifth time, every site in `hir_lower` that reads a compile-time constant was
enumerated and classified.

## The audit

Six constant-reading accessors, **26 call sites in `hir_lower`** — the ones that
matter, because they change generated code silently. Every one falls into exactly
three classes:

| class | what happens to a non-constant | verdict |
|---|---|---|
| **signature-protected** — `as_literal(..).unwrap()` where inference already demands a string literal | refused before lowering runs, *"expected string literal"* | safe |
| **lowered as a runtime value** — `lower_array_elems_impl` | works; this is why a deck-set `laplace_*`/`zi_*` coefficient is honoured | safe |
| **fold-to-default** | silently becomes `0.0`, or takes a default branch | **3 sites, all defective** |

### The rule this establishes

> A site that folds a constant to build a **compile-time artifact** must **refuse**
> a non-foldable operand, not substitute a default. A site that lowers to a
> **runtime value** may accept a `parameter` — that is Enhancement-504 and
> Enhancement-506's territory, where the answer is a run-time clamp.

The discriminator is mechanical, which is the point: any future site can be
checked against it without another hunt.

## What was wrong

`const_real_in_body`'s own doc comment states the danger and does not prevent it:

> the callers build compile-time tables and turn `None` into `0.0`, so anything
> this cannot fold becomes a silent zero entry

A `localparam` folds — it is fixed when the model is compiled and can never be
overridden, so its default *is* its value, which Enhancement-479 taught the guards
to see. An overridable **`parameter` deliberately does not fold** ("the model card
may replace it"). So a parameter used inside a compile-time table became a **zero
entry**: its default ignored, and the deck's value ignored with it.

| call | before | correct |
|---|---|---|
| `noise_table('{1, q, 1e3, 1e-18})`, `q` a parameter | **4.870871387826e-05** for *both* `q=1e-18` and `q=4e-18` | the entry's value |
| `$table_model(x, '{0,0, 1,q})` with `q=100` | **0** at x=0.5 | 50 |
| `$table_model(x, '{0,0, q,100})` with `q=1` | **0** at x=0.5 | 50 |
| `$discontinuity(d)` with `localparam d = -1` | announced — 168 output rows | nothing — 132 rows |
| `$discontinuity(d)` with a **deck-set** `d = -1` | announced — 168 rows | nothing — 132 rows |

4.870871387826e-05 is exactly the figure measured in round 64 for a table with a
literal **zero** power, which is what pins the mechanism.

None of the three produced any diagnostic at all.

### `$discontinuity` is the sharpest of them

`-1` is Enhancement-24's sentinel for *no discontinuity*. Lowering read the degree
with `as_literalsignedint` — a **literal only**, which does not even fold a
`localparam` the way `const_num` has since Enhancement-479. So a named constant
meaning *do nothing* was misread as an ordinary announcement and bounded the
timestep on every crossing.

It is also where the audit's rule earned its second half. The first fix here
*refused* a degree that could not be folded — and that broke
[Enhancement-504](Enhancement-504.md)'s own model, which writes

```verilog
parameter integer disc = -1;   // -1 = none
...
if (disc >= 0) $discontinuity(disc);
```

That is the deck-supplied route working exactly as designed, and refusing it would
have withdrawn a shipped feature to fix a bug. The degree is **not** a compile-time
artifact — it only selects a branch — so by the rule it belongs in the second
class: a non-constant degree now emits the announcement under a run-time
`degree != -1` test instead of unconditionally. A deck-set `-1` means *no
discontinuity* just as a literal one does, and a deck-set `0` still announces.

`SetRetFlag` under a condition is the shape [Enhancement-505](Enhancement-505.md)
made op-dependent and [Enhancement-506](Enhancement-506.md)'s `runtime_fatal`
already relies on, so the conditional costs nothing new.

## Why the fix is small

The **whole-array** form of this mistake was already refused, and says exactly
why — *"the table is an array parameter or variable, whose values are only known
at run time; this table is built when the model is compiled"*. The guard simply
checked the **array** and not its **elements**. `require_const_elems` extends that
existing, correct guard one level down and names the offending entry by index.

And the check is *exact* rather than approximate: `const_num` (hir_ty) and
`const_real_in_body` (hir_lower) fold the same set — literals, unary `+`/`-`, the
four arithmetic operators with a non-zero divisor, and a `localparam` chain, never
a `parameter`. A value the check accepts is a value lowering can fold. **Keep them
in step.**

## What is deliberately unchanged

The **runtime** table — a bare array-variable reference (Enhancement-389) — is an
`Expr::Path`, not an `Expr::Array`, so the guard never fires on it. That is the
supported way to build a table from a `parameter`, and it still works: the table is
assembled and sorted at run time rather than materialised at compile time.

`$table_model`'s check is applied to every array **literal** argument rather than a
fixed position, so the N-dimensional forms are covered without assuming which
argument holds the data.

## Files

| file | change |
|---|---|
| `openvaf/hir_ty/src/validation/body.rs` | `require_const_elems`; applied to the `noise_table` and `$table_model` inline arms |
| `openvaf/hir_lower/src/expr.rs` | `$discontinuity` folds a `localparam` chain, and honours a run-time degree under a `!= -1` test |
| `examples/constfold_examples/` | new suite |

## Verification

`constfold_examples` — **19 checks, both linear solvers**, of which **11 fail on
the shipped binaries** (measured: 8/19 pass before the fix, 19/19 after). Full
regression **422/422**.

Enhancement-504's `rtdomain` suite is what caught the over-broad first attempt,
and it is green — 16/16 — with the run-time form.

All 21 table and noise suites were run first as the ones most exposed —
`cubic_table`, `dlutfix`, `mdtable`, `ndtable`, `tabledata`, `tablefix`,
`table_model`, `vaftabledup`, `noisetable`, `modelnoise` and the rest — every one
unchanged. A localparam ordinate still interpolates to 50, a localparam **chain**
to 25, and a localparam noise power still gives 4.997292826696e-05.
