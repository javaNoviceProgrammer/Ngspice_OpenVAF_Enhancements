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

## RF periodic small-signal suite (Enhancements 119–121)

Built on the retained PSS operating point, `rc_pss.cir` also exercises the periodic
small-signal chain that leads to periodic AC (PAC):

- **E-119** retains the converged periodic operating point (node voltages + device
  states per sample) on the analysis job instead of freeing it.
- **E-120** turns it into the harmonics `G_k`, `C_k` of the periodically
  time-varying device Jacobian `G(t) = ∂I/∂V`, `C(t) = ∂Q/∂V`.
- **E-121** assembles those harmonics into the **harmonic conversion matrix**
  `H_{nm} = G_{n−m} + j·ω_m·C_{n−m}` (size `(2M+1)N`) and solves it — injecting a
  unit current at the osc node in the 0-th sideband and reporting the response at
  each sideband `f_in + k·f0`. This is the numerical engine of PAC / periodic
  noise / PXF.

For the linear RC the conversion matrix is block-diagonal, so the sideband-0
response equals the ordinary AC driving-point impedance at `f_in = f0/2`
(`|Z| = 1/|1/R + j·2π·f_in·C| = 303.3 Ω`) and the ±1 sidebands carry no converted
energy — exactly what a non-mixing circuit should show. `verify_rcpss.py` checks
all of this. A pumped nonlinear circuit fills the off-diagonal blocks and produces
real conversion gain through the same path.

## `.pac` command (Enhancement-122)

`rc_pac.cir` drives the same RC through the user-facing **periodic-AC** command:

```
.pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     <DEC|OCT|LIN> Npts Fstart Fstop
```

The first seven fields are the `.pss` parameters (PAC runs a PSS to find the
operating point it linearizes around); the tail is an `.ac`-style sweep. `.pac`
runs PSS, then sweeps the small-signal input frequency and, at each point, solves
the E-121 conversion matrix — emitting the **0-th-sideband node responses** as a
complex `PAC Analysis` plot you read back with `print`/`plot`/`wrdata`:

```
.pac 1meg 1u b 1024 10 50 5u dec 10 10k 1meg
```

For the linear RC the swept sideband-0 response at node `b` equals the AC
driving-point impedance `|Z(f)| = 1/|1/R + j·2π·f·C|` across the whole band —
998 Ω at 10 kHz down to 157 Ω at 1 MHz. `verify_rcpac.py` asserts every swept
point against `|Z(f)|` (worst-case `1.6e−7`). A pumped nonlinear circuit's
sideband-0 response is the genuine periodic-AC response (differs from a plain
`.ac`) through the same path.

**Note:** `.pac` runs a PSS shooting method (~2 minutes) and `verify_rcpac.py`
runs it under the Sparse solver only.
