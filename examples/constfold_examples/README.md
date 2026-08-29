# Enhancement-508 — a compile-time table built from a value that cannot be folded

```
python3 verify_constfold.py
```

19 checks, both linear solvers. 11 of them fail without the fix.

## Where this came from

Not a hunt — a **static audit**. Every site in `hir_lower` that reads a
compile-time constant was enumerated (26 of them) and each falls into one of three
classes:

| class | what happens to a non-constant | verdict |
|---|---|---|
| signature-protected (`as_literal(..).unwrap()`) | refused before lowering runs | safe |
| lowered as a **runtime value** (`lower_array_elems_impl`) | works — `laplace_*`/`zi_*` coefficients live here | safe |
| **fold-to-default** | silently becomes `0.0` / a default branch | **3 sites, all defective** |

### The rule

> A site that folds a constant to build a **compile-time artifact** must **refuse**
> a non-foldable operand. A site that lowers to a **runtime value** may accept a
> parameter — that is
> [Enhancement-504](../../enhancements_doc/Enhancement-504.md) /
> [Enhancement-506](../../enhancements_doc/Enhancement-506.md) territory, where the
> answer is a run-time test rather than a refusal.

## What was wrong

`const_real_in_body`'s own comment states the danger without preventing it:

> the callers build compile-time tables and turn `None` into `0.0`, so anything
> this cannot fold becomes a silent zero entry

A `localparam` folds and is fine. An overridable **`parameter` deliberately does
not** — the model card may replace it — so it became a **zero entry**, its default
ignored and the deck's value ignored with it.

| call | before | correct |
|---|---|---|
| `noise_table('{1, q, 1e3, 1e-18})`, `q` a parameter | 4.8709e-05 for **both** q=1e-18 and q=4e-18 — the literal-zero-power figure | the entry's value |
| `$table_model(x, '{0,0, 1,q})`, q=100 | **0** at x=0.5 | 50 |
| `$table_model(x, '{0,0, q,100})`, q=1 | **0** at x=0.5 | 50 |
| `$discontinuity(d)`, `d` a localparam `-1` | announced — 168 rows | nothing — 132 rows |
| `$discontinuity(d)`, `d` **deck-set** to `-1` | announced — 168 rows | nothing — 132 rows |

None of them said anything at all.

The `$discontinuity` case is the sharpest: `-1` is
[Enhancement-24](../../enhancements_doc/Enhancement-24.md)'s sentinel for *no
discontinuity*, and lowering read the degree with `as_literalsignedint` — a
**literal only**, which does not even fold a `localparam` the way `const_num` has
since [Enhancement-479](../../enhancements_doc/Enhancement-479.md). So a named
constant meaning *do nothing* bounded the timestep on every crossing.

It is also the case that separates the rule's two halves. Refusing a degree that
cannot be folded — the first thing tried here — broke
[Enhancement-504](../../enhancements_doc/Enhancement-504.md)'s own model, which
writes `parameter integer disc = -1; ... if (disc >= 0) $discontinuity(disc);`.
The degree is not a compile-time artifact, it only selects a branch, so it belongs
in the *runtime* class: a non-constant degree now announces under a run-time
`degree != -1` test. `rtdomain` is green, and a deck-set `-1` means what it says.

## Why the fix is small

The **whole-array** form of the same mistake was already refused, and says exactly
why ("materialised at COMPILE time"). The guard simply checked the **array** and
not its **elements**. And `const_num` (hir_ty) and `const_real_in_body`
(hir_lower) fold the same set — literals, unary `+`/`-`, the four arithmetic
operators with a non-zero divisor, and a `localparam` chain, never a `parameter` —
so the check is *exact* rather than approximate. Keep them in step.

## Files

| file | what it holds |
|---|---|
| `goodtab.va` | what must keep working: a literal, a localparam, and a localparam **chain**, in both table kinds |
| `disc.va` | `$discontinuity(-1)` and `(0)` written as literals and as localparams, selected by a deck parameter |
| `bad_nt_param.va`, `bad_ntlog_param.va` | a parameter as a noise-table entry |
| `bad_tm_ord.va`, `bad_tm_absc.va` | a parameter as a `$table_model` ordinate / abscissa |
| `disc_param.va` | a **deck-set** `$discontinuity` degree — must keep working, and honour `-1` |

## What is deliberately unchanged

The **runtime** table — a bare array-variable reference
([Enhancement-389](../../enhancements_doc/Enhancement-389.md)) — is an
`Expr::Path`, not an `Expr::Array`, so the guard never fires on it. A table whose
entries really are computed at run time still works, and that is the supported way
to build one from a `parameter`.
