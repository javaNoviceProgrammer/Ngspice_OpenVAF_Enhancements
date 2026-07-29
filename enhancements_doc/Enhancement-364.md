# Enhancement-364 — transient noise for OSDI devices

`.noise` linearises about an operating point and reports spectral densities. It
cannot show jitter, noise-induced switching, or an oscillator's phase noise,
because those need the noise present **in the time domain**.

ngspice has had time-domain noise for independent sources (`trnoise` on V/I
sources) for years. OSDI devices were silently noiseless in `.tran`, so a deck
that asked for transient noise got noise from its sources and **nothing from its
transistors** — the devices were the only silent components in an otherwise
noisy circuit.

This is a **simulator-side change only**: no ABI change, no compiler change.

---

## Everything needed was already being emitted, and never read

The compiler puts a complete parametric description of every Verilog-A noise
contribution into each `.osdi`:

| descriptor field | meaning | read before this? |
|---|---|---|
| `noise_source_type[i]` | WHITE / FLICKER / TABLE | **no** |
| `load_noise_params()` | per-source `power`, `exponent` → S(f)=power/f^exp at the **current bias** | **no** |
| `noise_sources[i].nodes` | the node pair the source injects between | only in `.noise` |
| `noise_sources[i].name` | correlation group (LRM 4.6.4) | only in `.noise` |

`load_noise_params` and `noise_source_type` were **dead ABI** — declared in
`osdi.h`, called nowhere. Part of the reason is that the `NOISE_TYPE_*` constant
names existed only in the compiler-side header and had never been mirrored into
ngspice's copy, so nothing could interpret the field. They are mirrored now.

## Automatic activation

There is no option to set. Transient noise switches itself on when the circuit
**already contains a `trnoise` source**, and adopts that source's own noise
timestep so every generator in the circuit shares one grid.

The rationale is that such a deck is demonstrably already running a noisy
transient. Activation is deliberately **not** keyed on "this device declares
noise sources": practically every real compact model (BSIM, MEXTRAM, HICUM)
declares thermal and flicker noise, so that test is equivalent to *always on* —
it would make every existing transient stochastic, change results nobody asked
to change, and cost convergence for a feature the deck never requested. A deck
with no `trnoise` source is unaffected.

## The amplitude law — derived, not fitted

The generator is a unit-parameter source filtered by ngspice's `f_alpha`, which
is Kasdin's fractional-noise method: white noise of deviation `Q` convolved with
`h_k = h_{k-1}(a/2 + k-1)/k`, i.e. `H(z) = (1 - z^-1)^(-a/2)`. Hence
`|H|² → (2·pi·f·ts)^-a` well below Nyquist, and discrete white noise of
deviation `Q` on a grid of period `ts` has one-sided density `2·Q²·ts`:

```
S(f) = 2 Q² ts (2 pi f ts)^-a      =>      Q = sqrt( |power| (2 pi ts)^a / (2 ts) )
```

`a = 0` collapses this to `sqrt(|power|/(2 ts))`, the white case, so both source
kinds share **one expression**.

This matters: the first implementation used the white law for flicker too. That
overstates the amplitude by `sqrt(1/(2·ts·pi))` — **399x** at `ts = 1 us` — and
measuring against `.noise` gave **397x and 396x**. Agreement with the predicted
398.9x to under 1% is what confirmed the derivation, rather than inviting a
fitted correction factor that would have silently moved with `ts` and run length.

## Why a separate, fixed noise grid

The sample must **not** be scaled by the adaptive simulation timestep. A white
source of density S sampled at `dt` has deviation `sqrt(S/(2 dt))`; if `dt` is
the LTE-controlled step, the injected *power* moves whenever the step controller
changes its mind and the spectrum becomes an artefact of the integrator.
ngspice's `trnoise_state` already samples on a fixed grid and interpolates
(`vsrcload.c`), and that is reused verbatim, one generator per (instance,
correlation group).

Device noise is not stationary — shot noise follows the current, flicker follows
I^AF — so `power` is re-read **every timepoint** and the unit sequence scaled by
the instantaneous amplitude. That is the standard quasi-stationary
approximation, and it is what makes `ts` meaningful.

## Correlation

Verilog-A expresses perfectly correlated sources by giving them the **same
name** (LRM 4.6.4, the rule `osdinoise.c` already implements for `.noise`), so
streams are keyed on the source *name*, not its index — correlated sources share
one stream instead of drawing independently. `power` may be negative (OpenVAF
folds the contribution factor as `fac*|fac|`, [E-42](Enhancement-42.md)), and
that sign is carried into the amplitude so correlated sources add coherently.

## Verification

Injection is an independent current source: right-hand side only, no Jacobian
entry, so it cannot alter the Newton matrix. It is stamped in the **serial**
post-eval loop next to the absdelay and last_crossing stamps.

| source | oracle | result |
|---|---|---|
| thermal (white) | exact analytic `S·R/(4C)` | **1.7 %** |
| shot (bias-dependent) | analytic at each operating point, 45x current range | **0.6 – 4.5 %** |
| flicker (1/f) | `.noise` spectrum, 60 Welch segments, 153 bins | **0.9939 ± 0.0091**, fitted slope **-0.993** |

The shot-noise sweep is the one that proves `load_noise_params` is re-read at
the current bias rather than latched once: the current spans 2.3 uA to 104 uA
and the predicted variance tracks it at every point.

`examples/trnoise_examples` is a proven trigger — **2/6 against the unmodified
binary, 6/6 with the change** — and runs in under 3 s. The heavy statistical
work that established the flicker normalisation lives in
`examples/trnoise_examples/validate/`, committed for repeatability but excluded
from the regression by name.

## Limits, deliberately

- **`noise_table` is not injected.** A tabulated spectrum needs arbitrary
  frequency *shaping*, not a scalar amplitude, which neither generator can
  express. It warns once, naming the source, and remains fully accounted for in
  `.noise`. Silently substituting a flat source would misstate the noise at
  every frequency except where the table happens to cross it.
- **Memory.** A 1/f generator pre-computes its whole sequence for the run
  (`f_alpha` is called once with `CKTfinalTime/ts` points), so a long transient
  with many flicker sources costs about 8 bytes per source per instance per
  noise timestep. White sources stream and cost nothing.
- The quasi-stationary approximation assumes the operating point moves slowly
  compared with `ts`.

Regression 288/288.
