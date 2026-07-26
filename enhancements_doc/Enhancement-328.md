# Enhancement-328 — `get_expr` was not total: a dynamic array index crashed the compiler

From the seven-strategy fuzz campaign. A dynamically-indexed array read used
directly as a contribution RHS crashed the **shipped** compiler:

```verilog
real g[0:3]; integer k;
analog I(a,b) <+ V(a,b) * g[k];     // panic: invalid HIR: path BitSelect { .. } was not resolved
```

## Root cause — a partial function used as if it were total

`BodyRef::get_expr` funnelled *every* `BitSelect` into `resolve_path`:

```rust
hir_def::Expr::Path { .. } | hir_def::Expr::BitSelect { .. } => Expr::Read(self.resolve_path(expr)),
```

and `resolve_path` can only resolve expressions that have a `Ref` — `Ty::Var`,
`Ty::Param`, a function var/return, a nature attribute — and `panic!`s otherwise.

A dynamically-indexed array read has **no backing variable**: inference types it
`Ty::Val(..)` and records the element variables, per-dimension bounds and index
expressions out-of-band in `dynamic_index_refs`. So `get_expr` was a *partial*
function, and any caller that merely probed an expression's **shape** — a
literal-zero test, a literal-condition fold, an aggregate check — crashed on a
perfectly legal dynamic array read.

The asymmetry this produced is the tell:

| spelling | before |
|---|---|
| `x = g[k]; I <+ V*x;` | compiles |
| `I <+ V*g[k];` | **panic** |

`lower_expr` never hit the bug because it short-circuits on `dynamic_index()`
*before* consulting `get_expr`; the contribution path has no such short-circuit.

## The fix

Restore the invariant that `get_expr` is **total**: give `Expr` a `DynIndexRead`
variant and answer the shape question directly, gated on the same
`dynamic_index_refs` map the value path already uses:

```rust
if self.infere.dynamic_index_refs.contains_key(&expr) {
    return Expr::DynIndexRead;
}
```

The *value* is still lowered by `lower_expr`'s existing `dynamic_index()`
short-circuit, exactly as before — nothing about code generation changes.

Pleasingly, making the enum non-exhaustive pointed the compiler at **exactly one**
match that needed updating (`lower_expr`'s, which already short-circuits and so
gets an `unreachable!` arm), confirming how tightly scoped the change is.

## Verified numerically

A dynamic index must select the *right* element, not merely stop crashing. Four
instances of the same model, each selecting a different element of
`g = {1,2,3,4} mS` at V = 1:

| `k` | expected | measured |
|---|---|---|
| 0 | −1 mA | `-1.00000e-03` |
| 1 | −2 mA | `-2.00000e-03` |
| 2 | −3 mA | `-3.00000e-03` |
| 3 | −4 mA | `-4.00000e-03` |

and the results agree bit-for-bit with the `x = g[k]` spelling that always worked.

## Output preservation

The new branch is gated on `dynamic_index_refs.contains_key(&expr)`. For any
expression *not* in that map — every expression in every model that compiles
today — `get_expr` executes exactly the previous code path. For an expression
that *is* in it, `get_expr` previously **panicked**, so there is no prior
behaviour to preserve. Confirmed against the corpus with the deterministic
`--dump-mir` oracle.

## Files

- `OpenVAF-master-20260610/openvaf/hir/src/body.rs` — the `DynIndexRead` variant
  and the `get_expr` guard.
- `OpenVAF-master-20260610/openvaf/hir_lower/src/expr.rs` — the corresponding
  `unreachable!` arm in `lower_expr`.
- `examples/vafdynidx_examples/` — the crashing shape compiles and each index
  selects its own element (`verify_vafdynidx.py`, 3 checks).
