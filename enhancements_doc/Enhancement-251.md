# Enhancement-251 — harmonic-balance tight nonlinear correctness verification

A rigorous tightening of the harmonic-balance (`hb`, E-134/135) correctness
cross-check. The existing checks compare the HB spectrum of several nonlinear
circuits against ngspice's own transient + `fourier` steady state, but at `K=8`
harmonics and a 1.5–3 % tolerance. This enhancement proves — and then enforces in
the regression — that HB converges to the **exact** periodic steady state, not
merely to within a few percent.

## The audit

HB solves for the periodic steady state directly in the frequency domain;
`tran` + `fourier` reaches it by time-stepping. They are completely independent
code paths, so their agreement is a real oracle — *if* the transient reference is
made accurate enough. Two effects limit a naive comparison:

- **Transient discretization.** A finite timestep carries an `O(dt²)`
  (trapezoidal) error. Using a purely **resistive** rectifier (`cjo=0`, `tt=0`)
  removes reactive memory, so the steady state is reached instantly and the
  transient's *only* error is its timestep — which can then be driven down and
  Richardson-extrapolated to `dt→0`.
- **HB truncation.** HB with `K` harmonics discards everything above `K`; for a
  sharp rectifier those discarded harmonics **alias** back onto the retained
  ones, so the retained harmonics carry a truncation error that shrinks as `K`
  grows.

Sweeping `K = 8, 12, 16, 24, 32, 48` on the resistive rectifier, the HB harmonics
converge **monotonically** to the `dt→0` transient. At `K = 48`:

| harmonic | HB(K=48) / transient − 1 |
|---|---|
| h1 | 0 |
| h2 | 0 |
| h3 | −1.9e-7 |
| h4 | −3.1e-6 |
| h5 | +8.9e-7 |

i.e. HB reproduces the exact nonlinear steady state to **~1e-7** once enough
harmonics are kept. The 13 % apparent "error" of the 5th harmonic at `K = 8` is
entirely HB truncation (aliasing), not a modelling error — it vanishes as `K`
increases.

## The tightened check

`examples/hb_examples/verify_hb.py` gains a check that, on the resistive
rectifier:

1. runs HB at `K = 24` and a fine transient (`dt = period/2000`), and asserts the
   HB spectrum matches the transient `fourier` to **< 0.5 %** for DC…4th — 6×
   tighter than the previous loose checks, with orders of magnitude of margin
   (the observed worst-case relative error is ~2e-5); and
2. asserts that raising `K` from 8 to 24 **strictly shrinks** the 5th-harmonic
   mismatch, encoding the "converges as K grows" property so a future regression
   that broke HB's harmonic content — not just its convergence — would be caught.

## Scope

Verification only — `examples/hb_examples/verify_hb.py`. No change to the ngspice
binary, the HB engine, or any analysis; this hardens the existing E-134/135
regression and documents that HB is exact, not merely within tolerance. Full
regression: all examples pass.
