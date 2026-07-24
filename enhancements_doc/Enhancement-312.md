# Enhancement-312 — ngspice: XSPICE integrating code models integrate at true second order

Found while oracle-checking the XSPICE `s_xfer` (Laplace transfer-function) code model
against a closed-form transient. Its transient error fell only as **O(h)** — first order —
where every native ngspice storage element (capacitor, inductor) is second order. Halving
the timestep barely halved the error instead of quartering it. Two independent causes,
one shared across *all* integrating code models and one specific to `s_xfer`.

## Cause (a) — the shared integrator was backward Euler, not trapezoidal

Every XSPICE analog code model that integrates — `s_xfer`, `int`, `d_dt`, and the rest —
goes through `cm_static_integrate()` in `src/xspice/cm/cm.c`. Its trapezoidal, order-2 arm
carried a self-documented stand-in:

```c
case 2:
    /* WARNING - This code needs to be redone.  */
    /* The correct code should rely on one previous value */
    /* of cur as done in NIintegrate() */
    cur = -0.5 * ckt->CKTag[0] * intgr[1];
    break;
...
geq = ckt->CKTag[0];
/* WARNING: Take this out when the case 2: above is fixed */
if((ckt->CKTintegrateMethod == TRAPEZOIDAL) && (ckt->CKTorder == 2))
    geq *= 0.5;
```

Working the algebra through `*integral = (integrand - cur)/geq`, that pair evaluates to
`y(n) = y(n-1) + h·u(n)` — **backward Euler**, an O(h) method — not the trapezoidal rule the
`case 2` label promised. The `WARNING` comments had flagged it for decades: the correct
formula needs "one previous value" that the code never kept.

## Cause (b) — `s_xfer` fed its loop back one timestep late

`s_xfer` (`xspice/icm/analog/s_xfer/cfunc.mod`) realises H(s)=num(s)/den(s) in
controller-canonical form: a chain of integrators whose outputs are fed back, scaled by the
denominator coefficients, into the highest-order input. It read those fed-back states from
the **previous timestep**:

```c
old_integrator[i] = (double *) cm_analog_get_ptr(i,1);   /* 1 = previous TIMESTEP */
```

That makes the feedback **explicit** — lagged one step — which caps the whole transfer
function at first order no matter how accurately each integrator is stepped. On its own this
holds `s_xfer` to O(h) even after (a) is fixed.

## The fix

**(a) True trapezoidal.** `cm_analog_alloc()` already reserves `bytes/sizeof(double)+1`
doubles per integrator, so there is a spare double immediately after each integral's slot —
and SPICE rotates the whole `CKTstates[]` history for us. `cm_static_integrate` now uses that
spare to remember the previous timestep's integrand `u(n-1)` and implements the real rule

```
y(n) = y(n-1) + (h/2)(u(n) + u(n-1))
```

exactly the SPICE companion-model idiom (store both the state and its rate in adjacent state
slots). `geq` becomes `ag[0]`, matching the order-1 and Gear arms; the `*0.5` half-step
compensation is gone. A guarded legacy fallback preserves the old numerics in the impossible
case that no spare slot exists.

**(b) Implicit feedback.** `s_xfer` now reads the feedback states from the
**current iteration** (`cm_analog_get_ptr(i,0)`), so the loop is solved implicitly within
each Newton step. Within a Newton iteration those slots hold the previous iteration's values
and converge to the consistent implicit solution. (The DC/init pass already used offset 0 for
both, so transient now matches it.)

Both integration methods, trapezoidal and Gear, now converge at O(h²).

## Why it is safe

- The spare state double is genuinely free: **every** integrating code model in the tree
  allocates exactly `sizeof(double)` per integrator tag, so `cm_analog_alloc`'s `+1` leaves an
  unused double between consecutive integrators. Written on every Newton iteration; the
  converged value is what rotates into `CKTstate1` after the accepted step.
- The implicit feedback does **not** destabilise Newton. A battery of transfer functions —
  first-order, a ζ=0.05 near-oscillatory resonator, a 3rd-order Butterworth, a stiff pair with
  poles three decades apart, and one with a numerator zero — all converge cleanly and match
  SciPy's independent `signal.lsim` to < 2.2e-4 relative.
- The full 246-example regression (both linear solvers) stays green.

## Verification

`examples/sxferorder_examples/verify_sxferorder.py` — 6 checks under both solvers. The
distinguishing signature of the bug is the **convergence order**, which a single binary can
measure on its own: halving the timestep quarters an O(h²) error but only halves an O(h) one.
So the order test **fails on a pre-fix build (ratios ~2, fitted p≈1.0) and passes here
(ratios ~4, p≈2.1)** with no reference binary required. Oracle: a first-order low-pass
H(s)=1/(1+τs) driven by sin(ωt) from rest,

```
y(t) = A·[ ωτ·e^(−t/τ) + sin(ωt) − ωτ·cos(ωt) ],   A = 1/(1+(ωτ)²)
```

whose LHP pole damps the startup transient, leaving a clean O(h²) steady-state error. The
checks: (1) error ratios ~4 across h = 100/50/25 ns; (2) least-squares fitted order p ≥ 1.7;
(3) absolute error at h=25 ns below 1e-4 (pre-fix ~5e-3); (4) the settled waveform tracks the
closed form to < 1 % of amplitude; (5)/(6) a resonant 2nd-order `s_xfer` driven at resonance
converges and hits its analytic peak gain 1/(2ζ)=1.667 within 3 %.

Measured post-fix, first-order low-pass, fixed step, TRAP:

| h      | max error | ratio |
|--------|-----------|-------|
| 100 ns | 5.04e-04  | —     |
| 50 ns  | 1.32e-04  | 3.82  |
| 25 ns  | 2.65e-05  | 4.98  |

(pre-fix the same column halved each row — O(h)).

## Scope of change

`src/xspice/cm/cm.c` (`cm_static_integrate`, shared by all integrating code models) and
`src/xspice/icm/analog/s_xfer/cfunc.mod` (`s_xfer` feedback only). No public interface change;
existing decks simulate identically apart from the smaller, correctly-scaling transient error.
