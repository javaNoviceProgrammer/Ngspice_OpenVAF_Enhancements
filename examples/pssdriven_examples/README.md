# Driven-mode PSS shooting (Enhancement-176)

Follow-up to the E-175 RF audit, which flagged "PSS shooting robustness" —
the pumped-varactor PSS ran **17+ minutes without converging** while a plain
transient of the same circuit took milliseconds.

## Diagnosis

ngspice's PSS (the Lannutti shooting) was built for **autonomous oscillators**:
it *hunts* the fundamental frequency, and to resolve the hunt it forces a
breakpoint grid whose spacing is proportional to `steady_coeff`. Two
consequences on **driven** circuits (which is what the whole periodic
small-signal stack — `pac`/`pnoise`/`pxf`/`psp`, E-117…126 — runs on):

1. **The breakpoint flood**: at the standard decks' `steady_coeff = 5e-6` the
   forced grid spacing is ~0.2 **picoseconds** — measured **9,627,161 accepted
   timepoints by t = 2 µs** (~33 s of CPU per µs of circuit time). The
   convergence-tolerance knob doubles as the grid density, so tightening
   convergence quadratically explodes runtime.
2. **The residual floor**: the frequency estimate can never settle *exactly* on
   the source frequency, so the cycle-end residual floors (~1e-4) and shooting
   on some circuits **never converges** — the varactor deck's 17 minutes.

![pssdriven](pssdriven.png)

## The fix

A **driven mode**, auto-detected when the circuit contains a time-varying
independent source (SIN/PULSE/… V or I source):

- the period is pinned to the **exact source period** — no frequency
  estimation, no estimator breakpoint grid; each shooting cycle runs at
  plain-transient speed and the residual converges geometrically (8e-9 in 17
  cycles on the varactor);
- the shooting-phase max step is clamped to `T/psspoints`, so the orbit is
  integrated on the **same discretization as the retained samples** (without
  this, LTE lets steps grow to T/2 and shooting converges to the fixed point of
  a coarse discretization several percent off the true orbit — the retained
  swing read 0.1651 vs the analytic 0.15718);
- the post-FFT "relaunch at the strongest spectral line" is disabled when
  driven (a rectifier-like circuit with a dominant harmonic must not retain the
  wrong period);
- the **autonomous (oscillator) path is untouched** — verified byte-identical
  behavior on oscillator decks.

## Measured impact

| analysis | before | after |
|---|---|---|
| varactor `.pss` | 17+ min, **never converged** | 0.3 s, err 8e-9, f exactly 1 MHz |
| `rc_pss` (linear) | ~4 min, f = 999999.8976 Hz | 0.05 s, f = 1000000 Hz exactly |
| `psp` example | 406 s | 0.9 s |
| rfpss battery (5 verifies) | minutes each (regression-excluded) | < 0.5 s each |
| rfanalyses | "several minutes even Sparse-only" | 0.56 s |
| KLU PSS pass | "prohibitively slow" (skipped) | 0.14 s |

**`rfanalyses` and `rfpss` now run in every regression sweep, under both
solvers** — the entire RF periodic small-signal suite is guarded continuously
instead of "verified once when the feature landed".

## Files

- **`verify_pssdriven.py`** — 6 checks × both solvers: driven detection +
  exact retained frequency; retained swing == |H| (step-clamp guard); retained
  period self-consistency; **direct `.pac` on the pumped varactor vs transient
  ground truth** (closing the E-175 loop with the direct PAC path — previously
  unaffordable); autonomous deck does *not* trigger driven mode.
- **`make_pssdriven_fig.py`** → **`pssdriven.png`**, **`pssdriven_demo.cir`**,
  **`varcap.va`**.

## Running

```sh
python3 verify_pssdriven.py     # 6 checks x {sparse, klu}
python3 make_pssdriven_fig.py   # figure
ngspice -b pssdriven_demo.cir   # demo
```
