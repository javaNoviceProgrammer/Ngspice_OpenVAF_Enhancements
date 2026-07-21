# Enhancement-258 — the `.dc` sweep's cold-start point is guarded too

The third extension of Enhancement-256. E-256/257 fixed the silent spurious
operating point for singular-derivative behavioral sources (`B I=sqrt(v(n))`,
`1/v`, `ln(v)`) for the DC operating point (`MODEDCOP`) and the transient
operating point (`MODETRANOP`). A `.dc` sweep still false-converged on its first
point.

## The bug

A `.dc V1 …` sweep of a `sqrt(v)` source gave a **spurious first point**:

```
V1 = 0.6    v(n) = 9.3e-17     <- spurious (true root 0.178045)
V1 = 0.8    v(n) = 0.2753      <- correct
V1 = 1.0    v(n) = 0.3820      <- correct
```

Only the **first** point is wrong: every later point warm-starts from the
previous solution (away from the `v = 0` singularity) and converges correctly.

## Why E-256/257's guard missed it

E-256's false-convergence guard fires only when `CKTdcFirstTry` is set, and that
flag is set only inside `CKTop` (around its first plain-Newton attempt). But in
the default (non-HSPICE) path, the `.dc` sweep in `dctrcurv.c` solves each point
with a **direct `NIiter` call, bypassing `CKTop`** — it only falls back to `CKTop`
if that direct solve *fails*. Since the false convergence "succeeds", `CKTop` (and
the guard) never ran.

## The fix

Two coordinated pieces:

1. **`maths/ni/niiter.c`** — the E-256/257 guard, which enumerated the operating-
   point modes (`MODEDCOP || MODETRANOP`), is generalized to fire on any
   `CKTdcFirstTry` operating-point solve (gated by `MODEINITFLOAT`, excluding the
   junction-guess iteration). Since `CKTdcFirstTry` is only ever set around a
   first-attempt op solve, this now covers `.op`, the transient op, **and** the
   `.dc` sweep — and any future op path — in one condition.

2. **`spicelib/analysis/dctrcurv.c`** — the `.dc` sweep sets `CKTdcFirstTry` for
   its first (cold-start) point (`firstTime`) around the direct `NIiter`. When
   that point false-converges, the guard declines it, `NIiter` returns
   non-converged, and the existing `CKTop` fallback (gmin/source stepping) finds
   the true root. Subsequent warm-started points are unaffected (`CKTdcFirstTry`
   is cleared).

## Verification

`examples/bsrcconv_examples/verify_bsrcconv.py` gains check **[5]**: the first
point of a `.dc` sweep of the `sqrt(v)` source is the true root `0.178045`
(pre-fix `~9e-17`) — both solvers. Checks [1]–[4] (the DC/transient op fixes) are
unchanged. The full regression, including the `.dc`/sweep-heavy suites (`sweep`,
`optimize`, `montecarlo`) and the convergence-aid suites (`convhelp`, `ptcont`,
`corenum`, `tempphys`), passes on both solvers.

## Scope

Generalization of the E-256 guard in `maths/ni/niiter.c` + a two-line
`CKTdcFirstTry` set/clear in `dctrcurv.c`; the ngspice binary is rebuilt.
Result-neutral for every circuit that already converged.
