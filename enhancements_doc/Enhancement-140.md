# Enhancement-140 — Oscillator phase noise (autonomous HB + `phasenoise`)

The periodic-noise machinery (E-124/126) folds device noise through the conversion-matrix
adjoint for **driven** circuits — noise figure, spot noise. The one thing the "Pnoise"
gap still promised and lacked was a dedicated **oscillator phase-noise spectrum** `L(Δf)`.
This enhancement adds it, with the autonomous-oscillator engine it needs:

```
hbosc <oscnode> <K> [fguess] [tstab]   -- autonomous HB: oscillator steady state + f0
phasenoise <fstart> <fstop> [points]   -- phase-noise spectrum L(df)
```

## Autonomous harmonic balance (`hbosc`)

An oscillator has **no driving source**, so the HB residual is `F(V) = I_R(V) +
[dq/dt](V) = 0`, to be solved for the harmonics `V` **and** the unknown oscillation
frequency `ω₀`. Two facts shape the solve:

- the trivial `V = 0` also satisfies `F = 0`, so a **transient seed** is used to land on
  the limit cycle — `hbosc` runs a short transient from the deck's `.ic`, reads the
  amplitude and the frequency (from the zero-crossing spacing), and seeds the fundamental;
- the oscillator's **phase is free** (shifting it is a symmetry), so the Jacobian `dF/dV`
  — the conversion matrix `H` — is **singular**, its right null space the phase mode
  `u_k = jk V_k`.

Newton is therefore run on the **bordered** system, nonsingular by construction:

```
[ H     ∂F/∂ω₀ ] [ ΔV  ]   [ −F ]
[ u*ᵀ   0      ] [ Δω₀ ] = [  0 ]
```

with `∂F/∂ω₀ = I_C/ω₀` (the reactive current) and the gauge row `u*` removing the phase
freedom. It converges **quadratically** — on the test LC oscillator, 4 iterations to
`|F| = 3e−12`, returning `f0` (the true nonlinear oscillation frequency, slightly pulled
from the LC resonance) and the harmonic spectrum. Inductors are handled naturally
(ngspice's branch-current MNA makes `V_L = jωL·I_L` linear in ω, so they fit the `G+jωC`
conversion matrix). The operating point is retained for `phasenoise`.

## Phase noise (`phasenoise`)

At each offset `Δf`, `phasenoise` builds the **adjoint** of the conversion matrix at
input frequency `Δf` with the unit at the **carrier sideband** (`m = 1`) of the oscillator
node, and folds every device's noise through it (the same `DEVnoise` machinery as
pnoise). As `Δf → 0` the matrix approaches the singular limit-cycle `H`, so the adjoint
transimpedance blows up through the phase mode as `1/Δf`, and the folded output noise as
`1/Δf²` — the phase-noise skirt. Normalizing to the carrier power `P = 2|V₁|²` gives

```
L(Δf) = 10·log10( S_v(Δf) / P )   [dBc/Hz]
```

which is `−20 dB/dec` near the carrier and flattens into the device noise floor far out —
the classic Leeson shape — at a physical absolute level (no PPV normalization constant to
mis-scale: it is real folded device noise over carrier power).

## Verification

`verify_phasenoise.py` (8/8) on an LC oscillator (`f0 ≈ 5.03 MHz`, cubic negative
resistance `i = −g₀V + g₃V³`, describing-function amplitude `A = √(4g₀/3g₃)`):

- **autonomous HB converges** to `f0 ≈ 5.03 MHz`;
- the fundamental amplitude matches the **describing function**;
- `L(Δf)` has the **−20 dB/dec** skirt near the carrier (`L(1k) − L(10k) ≈ 20 dB`);
- it **flattens** into the noise floor far from the carrier;
- the absolute level is **physical** (≈ −147 dBc/Hz at 1 kHz for this high-Q tank, not the
  −300 dBc/Hz a mis-scaled PPV gives);
- **thermal scaling** — doubling the absolute temperature raises `L` by exactly 3 dB
  (`10·log10(2)`), pinning the absolute noise coupling;
- a clean error with no `hbosc` operating point, and **KLU == Sparse**.

The existing periodic-noise suites are unaffected: pnoise stays 9/9, cyclostationary
pnoise unchanged, and QPnoise 10/10.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `HBOSCanalyze` (autonomous HB: transient-seeded bordered Newton for `V` and `ω₀`, retains the oscillator operating point) and `PhaseNoiseAnalyze` (carrier-sideband adjoint at each offset, device-noise fold, carrier-power normalization → `L(Δf)`) |
| `ngspice-46/src/frontend/com_hbosc.c` / `.h`, `commands.c`, `com_commands.h`, `Makefile.am` (+ `Makefile.in`) | the `hbosc` and `phasenoise` commands (transient seed + node resolution) |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `HBOSCanalyze` / `PhaseNoiseAnalyze` prototypes |
| `examples/phasenoise_examples/verify_phasenoise.py` | the 8-check phase-noise suite |

## Scope

Autonomous single-tone HB for oscillators (harmonics + frequency, transient-seeded) and
the phase-noise spectrum `L(Δf)` via the carrier-sideband adjoint. This closes the
"Periodic / phase noise" gap. Follow-ups: flicker (1/f³) close-in corner from
cyclostationary device noise, a jitter (time-domain) figure, and multi-node oscillator
seeding beyond the transient-fundamental start.
