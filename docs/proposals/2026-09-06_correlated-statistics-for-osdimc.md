# Proposal — statistically correlated parameters for `.option osdimc` (`automc`)

*Written 2026-09-06, after Enhancements 530, 554, 555 and 565. Status: proposal, not
implemented. Everything below describes the tree as it stands at commit 757d27db.*

## The question

A Verilog-A module declares its variability where the parameter lives —
`(* std= / std_rel= / dist= / trunc= *)` — and `.option osdimc` (alias `automc`) draws a
fresh value for every such parameter on each run. How do we let a model declare that two
of its statistical parameters are **correlated** (vth0 and u0 through tox; a card's
process shift and its instances' mismatch), so that Monte Carlo, `highsigma` and `wcd`
all honour the correlation?

## What exists, and what it lacks

Today (E-530, E-554) every `(* std *)` parameter gets its own standard-normal deviate `z`
from a pure hash of (seed, sample, owner name, parameter id) — `osdimc_kbase`,
`osdimc_n01`, `osdimc_z` in `ngspice-46/src/osdi/osdisetup.c` — and the value is
`nominal + sigma·z` (or the lognormal `nominal·exp(sigma·z)`, the uniform, and the
truncated variants). A model parameter is drawn once per model card (process), an
instance parameter once per instance (mismatch). Two things are built on that
independence:

* `highsigma -scale` inflates each parameter's `z` and multiplies **one importance weight
  per parameter** (`osdimc_log_lr`, `OSDImcSampleLogLR`);
* `wcd` walks a coordinate vector with **one Gaussian coordinate per parameter**
  (`osdimc_walk_value`, the fixed enumeration order: device type, model card, parameter,
  instance).

Correlation exists only on the netlist side (E-151): `mccorr k <matrix>` registers a
Cholesky-factored correlation matrix and `mvnorm(i)` returns its components for `.param`
expressions. Model-declared statistics cannot be correlated at all — neither between two
parameters of one card nor between a card's process shift and its instances' mismatch.

## The design

**Principle.** Model correlation as **independent standard-normal latent factors plus a
linear map**. Declared with attributes next to the existing `std`/`dist` ones, exported as
one more optional OSDI side table, sampled by the same pure-hash keys osdimc already uses.
Everything downstream (`highsigma` weights, `wcd` walk coordinates, seeding, determinism)
then falls out of the existing design instead of fighting it.

### Declaration — two spellings, one mechanism

Pairwise coefficients, the form PDK statistics blocks use:

```verilog
(* std=0.02, corr="u0:-0.6, tox:0.3" *) parameter real vth0 = 0.45;
(* std_rel=0.05 *)                       parameter real u0   = 0.04;
(* std_rel=0.03 *)                       parameter real tox  = 1.2e-9;
```

and explicit named factors with loadings, for the process-plus-mismatch decomposition:

```verilog
(* std=0.02, factors="model.pvth:0.8" *)                  parameter real vth0 = 0.45;
(* type="instance", std=5e-3, factors="model.pvth:0.5" *) parameter real dvth = 0.0;
```

A parameter's `z` becomes `Σ loading·F + r·ε`, with `F` the named factors, `ε` the
parameter's private residual, and `r = sqrt(1 − Σ loading²)`.

Rules:

* The compiler turns a `corr` matrix (unit diagonal; each pair declared once, on either
  side; a contradiction refused) into loadings by **Cholesky per module and scope**, so a
  matrix that is not positive definite is a compile-time error naming the offending pair,
  and a factor list whose loadings exceed unit norm is refused the same way.
* A factor is **model-scoped** when a model parameter names it, **instance-scoped** when
  only instance parameters name it, and explicitly `model.` or `global.` otherwise. A
  `global.` factor is shared across cards and across different `.osdi` modules by name —
  how a fab-wide shift reaches an nmos and a pmos model at once.
* `corr` on a uniform parameter is refused (a Gaussian copula through Φ is the clean later
  extension). `trunc` on a correlated parameter clamps the composed `z`, as the walk
  already does. `gated` (E-555) parameters that are not given are not drawn, so their
  loadings contribute nothing; the factor still exists for the others.
* A possible later bridge: a factor named `mvnorm.<i>` shared with the netlist's `mccorr`
  draw, so `.param` and model statistics can correlate. Not in the first step.

### Export

One optional side table beside `OSDI_STAT_PARAM_INFOS`: the factor names with their scope
(`OSDI_STAT_FACTORS`), and per statistical parameter the (factor, loading) list and the
residual weight (`OSDI_STAT_LOADINGS` with per-descriptor counts). Older simulators ignore
it and draw independently; older objects have none and behave as today. No descriptor ABI
change — the same pattern as the truncation (E-554), given-flag (E-555), range (E-558) and
paramset-family (E-565) tables.

### Sampling

A factor's deviate is keyed exactly like a parameter's, by (seed, sample, owner, factor
name): the owner is the model card for a model-scoped factor, the instance for an
instance-scoped one, and a constant for `global.`. The residual keeps the parameter's
current key, so a parameter with no correlation draws **bit-for-bit what it draws now**.
Determinism, `mcseed`, the loop commands' `-seed` (E-537, hunt F13's sample numbering),
`alter` recentring the nominal (draws are always nominal + delta), and the "first run is
the nominal baseline" rule are untouched.

### Importance sampling

`highsigma -scale` must inflate the **latents**, not the parameters, and the log-likelihood
ratio must be summed **once per latent** (a factor shared by five parameters contributes
one term). Because the map is linear, inflating every latent by the scale inflates each
parameter's `z` by the same factor, so the per-parameter scope filters of E-538 keep their
meaning. The truncation normalisers of E-554 apply per composed parameter as now.

### The walk

`wcd` needs its coordinate vector over the **independent latents** (factors first, then
residuals, in the applier's fixed enumeration), so the distance it reports is the
Mahalanobis distance of the correlated model rather than a Euclidean one in a skewed
space. This is the one place where getting correlation wrong silently gives a wrong β,
and it is why the latent representation is the right internal model. `osdimc_walk_count`
and the "held at the truncation" reporting extend naturally.

## Verification to pin (the suite)

* Sample correlation of two drawn parameters over a couple of thousand trials matching the
  declared coefficient; a card's instances sharing its model-scoped factor while their
  residuals differ; a `global.` factor shared by two different modules.
* A `highsigma` failure probability under correlation agreeing with plain Monte Carlo on
  the same deck (checks the per-latent weights).
* A `wcd` β for a correlated pair equal to the analytic Mahalanobis distance.
* Seed reproducibility; an uncorrelated deck drawing byte-identical values before and
  after the change (the E-530/E-554 suites must pass unchanged).
* The refusals: a non-positive-definite matrix, loadings over unit norm, an unknown
  partner name, a contradictory pair, `corr` on a uniform.

## Where the code goes

| side | files | work |
|---|---|---|
| compiler | `openvaf/sim_back/src/module_info.rs` (attribute parsing beside `std`/`dist`/`trunc`, the Cholesky, the validation diagnostics), `openvaf/osdi/src/{lib,metadata}.rs` (the side tables) | a few hundred lines |
| ngspice | `src/osdi/osdiregistry.c` (read the tables into `OsdiRegistryEntry`), `src/osdi/osdisetup.c` (factor keying in `osdimc_apply_type`, the latent enumeration for `osdimc_walk_count`/`osdimc_walk_value`, per-latent terms in `OSDImcSampleLogLR`), `src/include/ngspice/osdiitf.h` | somewhat more |
| docs | `docs/internals/ngspice_internals/ngspice_statistics.md` §5, handbook §2.1/§3, a new example suite | |

It fits one enhancement, split compiler/simulator like E-554. Suggested order: the
compiler half and plain sampling first (measurable correlation, determinism, refusals),
then the `highsigma` and `wcd` integration as the second step.
