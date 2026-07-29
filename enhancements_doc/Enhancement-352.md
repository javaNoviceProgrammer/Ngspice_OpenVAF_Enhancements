# Enhancement-352 — `.disto` for Verilog-A devices, with no variable-count ceiling

> **Superseded by [Enhancement-359](Enhancement-359.md).** The capability this
> added — distortion analysis for Verilog-A devices, with no variable-count
> ceiling — is unchanged and still verified by the same oracles. The
> *implementation* described below is not: the compiler no longer emits Taylor
> tensors at all. E-359 obtains them in ngspice by differencing the model's
> analytic Jacobian, which removed a 20-49x compile-time regression, 30MB
> objects, a 3.9x runtime penalty on every other analysis, and the OSDI 0.8/0.9
> ABI bump. Everything below is retained as the record of the original design and
> of the Volterra formulation, which E-359 reuses unchanged.

Before this, `.disto` on a circuit containing an OSDI device printed a warning
and left the device's nonlinearity out of the result. Now:

| | OSDI | reference | rel diff |
|---|---|---|---|
| HD2 | `6.2500000000e-03` | closed form `6.2500000000e-03` | `0.0` |
| HD3 | `4.6875000000e-04` | closed form `4.6875000000e-04` | `1.2e-16` |
| f1+f2, f1−f2, 2f1−f2 | — | built-in diode | `1.9e-06` |
| **cross term (2 variables)** | `1.2500000000e-03` | closed form | `0.0` |

---

## Why it did not work before

`.disto` is a Volterra-series analysis. It needs each device's Taylor expansion
of I(v) to **third order**, not the operating-point linearisation the Jacobian
provides. Built-in devices hand-code those coefficients — `diodset.c` computes
`id_x2`, `id_x3` and so on — which is why only **four of ~58** built-in devices
implement `DEVdisto` at all (diode, BJT, BSIM1, MES).

The OSDI ABI stopped at first derivatives: `load_residual_*`, `load_jacobian_*`
and nothing beyond. So `cktdisto` had nothing to ask an OSDI device for, and
E-62 added a warning rather than let it report a quietly-zero result.

## The three parts

**OpenVAF already had arbitrary-order autodiff.** `mir_autodiff`'s
`DerivativeIntern` chains derivatives through `previous_order`, with a comment
anticipating up to 8th order. Nested `ddx(ddx(ddx(...)))` was verified to match
closed form to every printed digit *before* any of this was built. So the
compiler work was not implementing higher-order AD — it was **asking** for it:
`build_taylor_tensors` re-runs `auto_diff` over its own first-order results to
get the second, and again for the third.

**A new ABI, OSDI 0.8.** `taylor2_entries` / `taylor3_entries` plus
`load_taylor2` / `load_taylor3`. Two decisions keep it honest:

- Tensors are indexed by **model input** (a branch voltage), not by node
  unknown. The ABI already publishes `inputs` as node pairs, so the consumer
  never has to unpick the hi/lo sign convention.
- The emitted values are **raw partial derivatives**. The `1/n!` and the
  multinomial multiplicity are applied by the simulator, so the interface
  carries no convention a reader has to infer.

Only `col1 <= col2 (<= col3)` is emitted, and identically-zero entries are
dropped, so a linear model carries none of this and pays nothing.

**A generic consumer, `osdidisto.c`.** Written once, it gives every Verilog-A
model distortion analysis.

## Removing the 3-variable ceiling

ngspice's framework caps at three controlling variables: `Dderivs` holds
derivatives *"w.r.t 3 variables"*, and the `DFx` helpers take up to **27 scalar
arguments** with no fourth-variable form (`DFn2F12` takes a struct because the
list outgrew the calling convention).

That cap is a property of those hard-coded helpers, not of the mathematics. The
Volterra contribution is a symmetric tensor contraction, so `osdidisto.c`
performs it directly over however many inputs the device has and **never calls
`D1x`/`DFx`**. `DISTO_VOLTERRA_FORMULATION.md` records each mode's N-variable
form together with its N=1 reduction back to the helper it must match.

The test that proves it is an ideal mixer, `I(out) = k·V(a,ref)·V(b,ref)`, whose
*only* nonlinearity is the mixed partial — both diagonal second derivatives are
identically zero. A dropped cross term would give exactly zero. It gives the
closed form `0.5·k·A²·R` exactly.

## Two silent-zero bugs found on the way

Both produced "no distortion", which is indistinguishable from a linear model —
the exact failure this change exists to remove.

1. **The tensors were optimised away.** `ensure_optbarriers` protects residuals,
   noise sources and jacobian entries; the Taylor values feed nothing else in
   the MIR, so without a barrier the optimiser deleted them and every
   coefficient arrived as zero. They also take the `mfactor` scaling, for the
   same reason the jacobian does: *m* parallel devices inject *m* times the
   distortion current.
2. **Nothing stored them.** Eval's jacobian/residual stores are gated on `CALC_*`
   flags that `.disto` never sets, so the slots needed their own unconditional
   store.

And one wrong-by-a-constant bug that only a reference implementation could
catch: `D1nF12` returns `0.5 * S2vF12(...)`, and `S2vF12` **already** sums both
index orderings. Without that 0.5 the mixed-tone products came out exactly 2×,
and because IM3 consumes the f1−f2 kernel its error was a non-obvious 2.246×.

## Known limitation: `$limit` — resolved by [Enhancement-353](Enhancement-353.md)

A model whose contribution goes through `$limit` emitted **no tensors**. The
residual depends on the limited value, not the raw voltage read;
`build_jacobian` handled that through `intern.lim_state` and the tensor pass did
not. Limiting is standard in production diode/BJT/MOS models, so this was a real
restriction and not a corner case.

[Enhancement-353](Enhancement-353.md) folds the limited values into the
derivative chain and lifts it. What remains unreachable is a nonlinearity in a
**ground-referenced probe**: the tensors are indexed by model input, and a bare
`V(a)` is not recorded as one because it has no hi/lo pair.

Registering `DEVdisto` removed `cktdisto.c`'s blanket warning, so such a model
would have become a **silent zero** — worse than before. `OSDIdisto` therefore
warns for itself:

```
Warning: Verilog-A (OSDI) device 'odio' contributes no distortion
         tensors; .disto will NOT include its nonlinearities.
         (A nonlinearity in a ground-referenced probe, which is
         not a model input, falls in this case.)
```

## Verification

Four oracles, two of which involve no simulator at all:

| check | oracle | result |
|---|---|---|
| HD2, HD3 | closed-form polynomial | `0.0`, `1.2e-16` |
| A² / A³ scaling laws | theory | `4.0000`, `8.0000` |
| f1±f2, 2f1−f2 | built-in diode (`diodisto.c`) | `1.87e-06` |
| IM3 | transient + FFT, a different domain | → `0.21%`, converging as A² |
| multi-variable cross term | closed-form mixer | `0.0` |

The transient cross-check matters because it is the only oracle independent of
ngspice's own Volterra code: agreement improves 5.7% → 1.4% → 0.21% as the drive
halves, exactly the A² signature of the fifth-order content a third-order
truncation excludes.

Two harness traps worth recording, both of which would have produced a confident
wrong answer:

1. The first IM3 transient was measuring **spectral leakage from the
   fundamentals**, not IM3. The A³ law exposed it (ratio 2.93 instead of 8) —
   the value alone looked plausible.
2. A first parameter choice made HD3 **identically zero** (the two contributions
   cancel exactly when `c3 = 2c2²/Ytot`, and `2(1e-4)²/2e-3` is precisely the
   `1e-5` chosen). A zero result would have passed a naive check for the wrong
   reason — the same trap as the old campaign's "HD2 ~ 0 on a linear network".
   The suite now refuses to score a both-zero comparison.

Regression 284/284. `examples/osdidisto_examples/` is a proven trigger: on the
pre-fix binaries **5 of its 6 checks fail**, and the one that passes is the one
that should — a linear model yields no distortion either way.
