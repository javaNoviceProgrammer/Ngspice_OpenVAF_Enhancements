# Enhancement-337 — `x * 0 -> 0` is retained for floats, deliberately

Enhancement-335 removed the IEEE-unsound algebraic rewrites from the float
simplifier. `x * 0 -> 0` belongs to that family — `inf * 0` and `NaN * 0` are NaN,
not 0 — and was removed with them. That was wrong, and the 92-model corpus campaign
caught it.

## What the campaign found

Running the corpus campaign after E-335/336 and diffing against the pre-E-335
toolchain, **one** of 92 device-modules had moved:

```
hisim2_va    Id  1.0e-05 -> 4.2e-07        (campaign bias)
             Id -1.30e-04 -> -1.33e-05     (Vg=0.7, Vd=1.0)
```

A 10x shift in a production MOSFET model. Both Id–Vg curves were smooth and
monotonic, so nothing looked obviously broken — which is exactly why this needed a
differential rather than an eyeball.

## Isolating it

Reverting the E-335 gates one at a time identified `x * 0 -> 0` as the sole cause:
restoring only that gate restored the value exactly, and restoring any of the others
did not.

**That is itself the diagnosis.** `x * 0` is exact for every finite `x`, so removing
the fold could only change a result if the operand were **inf or NaN**. HiSIM2
produces a non-finite intermediate at that bias, and this fold had been silently
absorbing it.

## What actually triggers the fold

Worth recording, because my first two attempts to write a reproducer missed it:

- one operand must be the interned **constant** zero, and the other a **runtime**
  value;
- if **both** are constant, `const_eval` folds `0 * inf` to NaN first — correctly —
  and the rewrite never applies;
- a zero-valued **parameter** is a runtime value, so `flag * term` with a
  zero-valued parameter flag does **not** trigger it either.

So the case being guarded is a constant-zero coefficient multiplying a runtime term
that happens to be non-finite.

## The decision

The fold stays, gated separately from `EXACT_ALGEBRA` and documented at the site.

There is no evidence the un-folded answer is the physically correct one — only that
it differs. Changing a production model's DC current by 10x in exchange for IEEE
purity, on a fold whose unsoundness requires a non-finite operand the model was
never expected to produce, is not a trade worth making. The rewrites that actually
produced the reported wrong answers — `x/x -> 1`, `sqrt(x)*sqrt(x) -> x`,
`exp(ln x) -> x`, and the domain/overflow inverse cancellations — remain removed.

If the non-finite intermediate in HiSIM2 is itself a model defect, that is a finding
about the model, not a reason for the compiler to change its answer.

## Verified

- **92/92 corpus device-modules OK**, worst KCL residual 2.3e-13 A.
- Against the pre-E-335 toolchain: **no device-module has a different drain
  current**. Three rows differ only in their KCL residual, at 1e-16/1e-17 — orders
  of magnitude below the worst-case residual and pure floating-point noise from the
  folds that were legitimately removed.
- The E-335 fixes all survive: `x != x` detects NaN, `1 << 32` is 0, and `x/x`,
  `sqrt(x)*sqrt(x)` and `exp(ln x)` are still NaN outside their domains.

## Files

- `OpenVAF-master-20260610/openvaf/mir_opt/src/simplify.rs` — `x * 0` retained, with
  the rationale recorded at the site.
- `examples/vafmulzero_examples/` — a constant-zero coefficient kills a runtime
  +inf term, and the E-335 removals survive (`verify_vafmulzero.py`, 2 checks).
