# Enhancement-651: a deck-fixed argument that is projected onto its domain is named (2026-09-16 hunt F7)

**Scope:** F7 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md).
Compiler: `openvaf/hir_lower/src/ctx.rs` (`runtime_warn`, the deferred
`$warning`-style twin of `runtime_fatal`), `openvaf/hir_lower/src/expr.rs`
(`project_or_warn`, `card_fixed`; `lower_noise_power`, `guard_flicker_args`,
`sdev_or_warn` and `upper_bound_or_warn` route the four projections of
E-504/505/506 through it). New suite
[`domainwarn_examples`](../examples/domainwarn_examples/) (20 checks per
solver). Ten snapshots under `openvaf/test_data/contributions/` (the MIR and
topology of five `sim_back` topology tests) re-recorded for the models whose
noise power is a parameter. **Compiler side.**

**Suites:** `domainwarn` 20 of 20 per solver, both solvers (9 of 20 on the
E-644 compiler); `deckdomain`, `constguard`, `lrmnoise`, `rng` green;
workspace `cargo test` green; full sweep 524 of 524.

## What was wrong

Enhancement-504/505/506 project an unusable argument onto its domain at run
time: a negative or NaN noise power becomes 0 (the source contributes
nothing), a negative standard deviation becomes the mean with certainty, a
reversed uniform range becomes its start, a NaN flicker exponent makes the
source inert. Each projection was chosen on purpose and the LRM mandates no
error for any of them, so they stay. But every one of them was silent:

```verilog
parameter real pw = -1e-18;   // or: white_noise(z/z) with z = 0
analog I(p,n) <+ V(p,n)/1k + white_noise(pw, "w");
```

compiled (the compile-time check sees only a literal), and the noise analysis
returned exactly the series resistor's thermal floor with nothing said.
`$rdist_normal(s, 0, sg)` with a deck `sg = -1` returned the mean and
`$rdist_uniform(s, lo, hi)` with `lo = 1, hi = 0` returned 1, both without a
word. A Monte-Carlo run whose sigma parameter went negative through a formula
drew nothing and reported nothing. Meanwhile the same value written out as a
literal is refused at compile time with a clear sentence, and the exponential
family with a bad deck mean is a `$fatal` (E-527, where LRM 9.13.2 does say
"an error shall be reported").

## What changed

`runtime_warn` is `runtime_fatal`'s twin for a domain that has a natural
projection: a `$warning`-style print with `%g` placeholders, deferred to the
accepted iteration exactly as E-636's out-of-range index warning is, with no
abort flag, so the simulator's repeat suppression keeps a transient from
repeating it per point. `project_or_warn` applies a projection and, when the
argument is fixed by the model card (`param_derived_in_body`, Enhancement-509's
test: literals, `parameter`s and `+ - * /` over them, with at least one
overridable parameter), names it:

```
OSDI(warn) na1: white_noise: the argument is outside the domain of white_noise (noise power not negative, LRM 4.6.4); it is -1e-18 -- the source contributes nothing
OSDI(warn) na1: $rdist_normal: the argument is outside the domain of $rdist_normal (standard deviation not negative, LRM 9.13.2); it is -1 -- the mean is returned with certainty
OSDI(warn) na1: $rdist_uniform: the arguments are outside the domain of $rdist_uniform (start below end, LRM 9.13.2); the start is 1 and the end is 0 -- the start is returned with certainty
OSDI(warn) na1: flicker_noise: the argument is outside the domain of flicker_noise (exponent a number); it is nan -- the source contributes nothing
```

The four sites are `white_noise`/`flicker_noise`'s power, `flicker_noise`'s
exponent, `$rdist_normal`/`$dist_normal`'s standard deviation and
`$rdist_uniform`/`$dist_uniform`'s bounds (a pair counts as fixed when both
are, with a literal beside a parameter included). A run-time quantity -- a
variable, a node voltage -- takes the E-504/505/506 clamp byte for byte as
before, since it may pass through any value on its way to the solution. A
zero noise power (`flicker_noise(kf*..., af)` with a default `kf = 0` is how a
model switches a source off) and a zero standard deviation are legal and pass
without a word. The exponential family keeps its mandated fatal.

## Verification

| check | result |
|---|---|
| `white_noise(pw)`, deck `pw = -1e-18`; `white_noise(z/z)`, `z = 0` | the floor, and the warning naming white_noise, the number (or `nan`) and "the source contributes nothing" |
| `pw = 0`; `pw = 1e-18` | the floor / above it, no word |
| `flicker_noise(pw, 1.0)`, `pw = -1e-18`; `flicker_noise(1e-18, ea/eb)`, `0/0` | named as flicker_noise (power / exponent) |
| `$rdist_normal(s, 0, sg)`, `sg = -1`; `$dist_normal` | the mean, named; the integer sibling names `$dist_normal` |
| `sg = 0`; `sg = 1` | no word; a draw |
| `$rdist_uniform(s, lo, hi)`, `1, 0`; `1, 1`; `1` beside `hi = 0`; `$dist_uniform` | the start, both numbers named |
| `lo = 0, hi = 1` | a draw inside, no word |
| a run-time standard deviation `V(p,n) - 2` | projected in silence, as before |
| `$rdist_exponential` with a deck mean of 0 | E-527's `$fatal`, unchanged |
| a literal `-1` standard deviation | still refused at compile time |
| a 5-point transient with a bad deck sigma | the warning a handful of times, not per iteration |
| `sim_back` topology snapshots (`correlated_noise`, `manual_correlated_noise`, `conditional_noise`, `linear_analog_operators`, `psp103`; `*_mir.snap` and `*_topology.snap` under `openvaf/test_data/contributions/`) | re-recorded: their noise powers are parameters, so the eval function now carries the deferred print |
| workspace `cargo test` | green |
| `domainwarn_examples` | 20 / 20 per solver, both solvers; 9 / 20 on the E-644 compiler |
| full sweep | 524 of 524 |

## What this does not do

A projection is not turned into an abort: the LRM mandates an error only for
the exponential family, and E-504's reasoning -- an unusable spec makes the
source inert rather than the answer wrong -- stands; the warning is the
missing half. A value reached through a `?:`, a function call or a
comparison is not attributed to the deck (Enhancement-509's folder accepts
`+ - * /` over parameters and literals) and is projected in silence. A NaN
power from a run-time formula is still silent for the same reason a negative
`sqrt` argument mid-Newton is. F8 is a separate enhancement.
