# Enhancement-119 — retain the PSS periodic operating point

This is the **first step toward the RF periodic small-signal suite** (PAC → pnoise
→ PXF). Those analyses linearize the circuit around the *periodic* operating point
produced by [PSS](Enhancement-117.md) — the device Jacobians `G(t)=∂I/∂V` and
`C(t)=∂Q/∂V` sampled along the steady-state waveform — and solve a harmonic
conversion matrix. Before any of that can be built, the periodic operating point
has to **exist past the analysis**. Today it does not.

## The gap

PSS's shooting method already samples the node voltages at `P` equally-spaced time
points across one converged period — it needs them for the DFT that produces the
harmonic output. But it then **frees** those samples (`dcpss.c`), and it never
captured the **device states** (the charges/fluxes in `CKTstate0`) at all. The
reactive Jacobian `C(t)` a small-signal analysis needs is a function of those
states, so voltages alone are not enough.

## What E-119 does

Retain the converged periodic operating point on the PSS job (`PSSan`) instead of
discarding it:

- capture `CKTstate0` (all `CKTnumStates` device states) at each of the `P`
  samples, alongside the node voltages that were already being captured;
- transfer ownership of the sample arrays to the job (`PSSopVoltages`,
  `PSSopStates`, `PSSopTimes`) with the metadata a consumer needs
  (`PSSopPoints`, `PSSopMsize`, `PSSopNumStates`, `PSSopFreq`), rather than
  freeing them;
- keep the memory bookkeeping correct: the previous run's operating point is
  freed before a new one is retained, the abort paths free the new states array,
  and on the frequency-relaunch path the stale samples are still freed (the
  relaunched run retains the correct ones).

A **self-check** reports the osc-node's voltage swing straight from the retained
samples, so the retained data can be validated before any consumer exists.

## Verification

The 1 MHz-driven RC low-pass (`R=1k`, `C=1n`):

```
Convergence reached ... 999999.8976 Hz
PSS periodic operating point retained: 1024 samples x 3 unknowns x 2 states at f = 999999.8976 Hz
  retained op-point self-check: osc-node swing [-0.157176, 0.157175] over the period
```

- **1024 samples × 3 unknowns × 2 states** — the right shape (`P` points; nodes
  `a`, `b` plus the `V1` branch current; `C1`'s charge + current).
- **osc-node swing [−0.157176, 0.157175]** — the retained samples hold the *actual*
  periodic waveform: the peak equals the fundamental amplitude `|H(1MHz)| =
  0.157136`, computed **directly from the retained data**, independent of the DFT
  output.
- PSS still converges to the identical result under both solvers — no regression.

The per-sample state capture is a straight copy sized by `CKTnumStates`, so it
scales automatically with the circuit's reactive content (here `C1` → 2 states;
more reactive elements simply retain more).

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/pssdefs.h` | add the retained periodic-operating-point fields to `PSSan` (`PSSopVoltages`/`PSSopStates`/`PSSopTimes` + dims + frequency) |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | capture device states per sample; retain the operating point on the job instead of freeing it; self-check the retained data |
| `examples/rfpss_examples/verify_rcpss.py` | assert the operating point is retained with the right dimensions and that the retained samples reproduce the fundamental amplitude |

## Scope

E-119 only **captures and retains** the periodic operating point; nothing consumes
it yet. Next: **E-120** walks the retained samples, `CKTload`s each to build the
periodic Jacobians `G(t)`, `C(t)` and DFTs them to harmonics; then **E-121**
assembles and solves the harmonic conversion matrix and wires up the `.pac`
command.
