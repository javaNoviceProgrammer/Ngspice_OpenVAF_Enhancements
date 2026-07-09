# PSS (periodic steady state) — Enhancement-117

Periodic steady state analysis (`.pss`) computes the periodic operating point of a
driven or autonomous (oscillator) circuit directly, via a shooting method, instead
of integrating transients until they settle. It is the foundation of the RF
periodic small-signal suite (PAC / pnoise / PXF, future work).

Before Enhancement-117 PSS was experimental: it was gated behind the
`--enable-pss` configure flag — so `.pss` was an *"unimplemented dot command"* in
every shipped ngspice — and, when enabled, it printed ~230 lines of shooting-loop
trace to stderr per run. E-117 makes PSS **build by default** and routes the
per-iteration trace through `set ngdebug`, so normal runs show a clean converged
summary and the harmonic table.

## `.pss` syntax

```
.pss Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff [uic]
```

| field | meaning |
|---|---|
| `Fguess` | initial guess for the fundamental frequency |
| `StabTime` | stabilization time run before shooting starts |
| `OscNode` | the probe/oscillation node |
| `Points` | time samples per period (for the DFT) |
| `Harmonics` | number of harmonics reported |
| `SC_iter` | maximum shooting-cycle iterations |
| `Steady_coeff` | steady-state detection coefficient |
| `uic` | optional — use initial conditions |

## `rc_pss.cir`

A 1 MHz-driven RC low-pass (`R=1k`, `C=1n`). PSS converges to the drive frequency
and its fundamental harmonic equals the analytic AC response
`|H(1MHz)| = 1/sqrt(1 + (2*pi*f*R*C)^2) = 0.15714`. `verify_rcpss.py` checks the
converged frequency, the fundamental magnitude, and that the default output is
free of shooting-loop trace.

**Note:** PSS is a shooting method — it simulates many drive periods — so this
deck takes ~1–2 minutes and is intentionally run under a single linear solver.

To see the full shooting-loop diagnostics, add `set ngdebug` in the `.control`
block before `run`.
