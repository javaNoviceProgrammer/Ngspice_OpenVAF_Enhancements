# Enhancement-902: the harmonic-balance Newton uses its residual's derivative — an overdriven BJT stage stalled after 13,518 iterations and 450 s

**Scope:** F8 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).
The other half of F8 is [E-903](Enhancement-903.md).

ngspice:
- `spicelib/analysis/dcpss.c`: `HBanalyze` (`hb`), `QPSShb` (`qpss … hb`) and `HBOSCanalyze`
  (`hbosc`) build their Newton matrix in the row-frequency form. `QPSShb` takes 8K+2 phase
  points per tone by default, where it took 4K+2.

**ngspice only.**

**Suites:**
- [`hbnewton_examples`](../examples/hbnewton_examples/), new: checks [1] to [3], [6] and [7].
  7 of 7 per solver; on the E-901 binaries all 7 fail.
- `hb`, `hbconv`, `hbosc`, `hbtrust`, the `qpss` suites, `phasenoise`, `rfpa`, `rfconv`,
  `cyclofold` and `pnoisefold` pass.
- The full sweep: 595 of 595.

## What was wrong

Harmonic balance solves for the harmonics V of every node voltage. The residual's reactive
current is the exact dq/dt = C(v(t))·v̇(t). Its n-th harmonic is Σ_m C_{n−m}·jω_m·V_m: the
capacitance's harmonics times the voltage's, with the column frequency ω_m. The Newton loops used
this same matrix as their Jacobian, a "frozen-C" quasi-Newton.

The derivative of C(v)·v̇ is C·δv̇ + Ċ·δv = d/dt[C·δv]. Its n-th harmonic is jω_n·C_{n−m}·δV_m,
with the row frequency ω_n. This is the matrix the small-signal analyses (PAC, PSP, pnoise) already
use; it is exact because C_ij = ∂q_i/∂v_j. The frozen-C matrix leaves out Ċ·δv.

That term is small while a capacitance stays put. A BJT driven into saturation swings its
diffusion capacitance (`tr`·gm) through orders of magnitude each period:
- Newton fell to linear convergence: |F| ×0.84 an iteration.
- Every continuation level ran out of its 50 iterations, so the source stepping halved its step
  and retried, about 270 times.
- On seed 111 of the campaign's Family B, `hb` at K = 48 stopped after 13,518 iterations at
  λ = 0.87: "source stepping stalled … the circuit may be singular or have no periodic steady
  state". That took 452 s under Sparse and 453 s under KLU, the same 13,518 iterations on either
  (E-894's build).
- The campaign page put KLU at 3 s. It is not faster: the time is the dense HB solve, which is
  the same under both.

The two-tone `qpss … hb` sampled each tone at 4K+2 phase points. That is the least that holds
the difference spectra up to 2K, and it is enough only for a quadratic nonlinearity. A junction's
C(θ) aliased at that density, and the row-frequency matrix stopped being the derivative too. A
two-tone drive of the same stage (0.08 V a tone) converged ×0.85 an iteration for over ten
minutes with the Jacobian corrected. At 8K+2 points it takes 65 iterations.

## The change

- After the reactive current is formed with the column-frequency matrix, the Newton matrix is
  rebuilt in the row-frequency form, in all three loops.
- `QPSShb` takes 8K+2 phase points per tone, as one-tone `hb` takes 8K per period.
- For linear capacitances the two forms are the same matrix, and nothing changes.
- The denser two-tone grid also removes aliasing from the answer itself. On the stage at
  0.04 V a tone, the harmonics moved by up to 7e-4 of the fundamental (the (1,1) product).
  A nonlinearity up to cubic, as in the `qpss` suites, is exact on either grid.

## The checks

`hbnewton_examples`:
- **[1]** Seed 111 at K = 16 converges. E-901: stalled.
- **[2]** Seed 111 at K = 48 converges; harmonics 0 to 6 within 1e-4 of the settled transient
  (1.6e-5). E-901: stalled after 13,518 iterations.
- **[3]** The last level ends quadratically: 9.8e-7, 2.5e-8, 1.7e-11. E-901: no level at full
  strength converged.
- **[6]** Sparse and KLU take the same 201 iterations and 16 steps.
- **[7]** Two tones of 0.08 V on the stage: `qpss … hb 4 4` converges in 65 iterations.

The campaign's Family B, 120 stages (rectifiers, clippers, common-emitter and common-source,
built-in and Verilog-A), at K = 16 and 48, under both solvers, with E-903:

| | K = 16 | K = 48 | time |
|---|---|---|---|
| E-901 | 116 of 120 | 116 of 120 | 2,043 s, 1,869 s of it failing |
| now | 120 of 120 | 120 of 120 | 132 s |

- Every E-901 failure was an overdriven common-emitter stage. Seed 147 at K = 48 ran out of a
  900 s limit.
- Where both converge, the harmonics agree with the transient as before (9.9e-5 at K = 48).
- With this change alone, seeds 105 and 111 still stalled once each at |F| ≈ 2e-10; that floor
  is E-903's.

Two tones on the stage:

| tone amplitude | E-901 | now |
|---|---|---|
| 0.04 V | stalled at λ = 0.59 after 1,291 s | 63 iterations, 6 s |
| 0.08 V | stalled at λ = 0.43 after 1,145 s | 65 iterations, 7 s |
| 0.12 V | stalled at λ = 0.35 after 1,136 s | 100 iterations, 9 s |

## Limits

- Away from the solution Newton still walks down an exponential about one thermal voltage an
  iteration (|F| ×0.37). HB has no junction limiting, and a first full-strength step often
  diverges before the source stepping takes over.
- `hbosc` gets the same matrix; its suite's oscillator has linear capacitors, and no oscillator
  with a nonlinear charge was measured.
