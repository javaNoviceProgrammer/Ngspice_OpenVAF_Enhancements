# Enhancement-512 — `transition` reached its final value only for slow edges

User-reported, and it came from a good question rather than a failure: reading the
compliance document's "documented deviation" for `transition`/`slew` and asking
whether they are actually *correct*.

They were not.

## What was wrong

Both filters are one rate-limited tracking loop:

```
dy/dt = clamp( K·(x − y),  −1/tfall,  +1/trise )
```

While the clamp is saturated this is an exact linear ramp at the LRM's rate. It
releases once the remaining gap falls below `rate/K`, and the rest of the swing is
a first-order tail with τ = 1/K. **`K` was a fixed 1e9 s⁻¹**, so the released gap
was `1/(K·trise)` — it depended entirely on how fast the transition was:

| `trise` | linear part of the swing | value at delay + trise (LRM: 1.0) |
|---:|---:|---:|
| 3 ns | 66.7% | **0.8774** |
| 30 ns | 96.7% | 0.9873 |
| 300 ns | 99.7% | 0.99948 |
| 3 µs | ~100% | 1.000039 |

The shortfall is `e⁻¹/(K·trise)` — measured **0.877382** against **0.877374**
predicted at 3 ns, which is what identified the mechanism rather than just the
symptom. So the operator was effectively exact above a microsecond and 12% short
at three nanoseconds, which is exactly where `transition` is most used.

**Not a timestep artifact.** Refining the step 100× converged to 0.8776 — to the
*wrong* value. It converges to 1.0 now.

## The fix

`K = TRACK_C · rate`, so the released gap is `1/TRACK_C` at every speed and the
linear fraction is scale-invariant.

**`TRACK_C` is 1e3 by measurement, and bigger is not better.** The released gap
also bounds the truncation error the integrator shows at the corner where the ramp
meets the tail, so raising the constant makes
[Enhancement-47](Enhancement-47.md)'s plateau check *worse*:

| `TRACK_C` | plateau (want 0.875) |
|---:|---:|
| 1e3 | **0.875** (passes at 1e-6) |
| 1e4 | 0.874940 |
| 1e5 | 0.874766 |

At 1e3 the endpoint error is 2e-5…4e-4 across five decades of rise time, the
settled value is exactly 1.0, and timepoint counts and runtime are unchanged.

## Two things that had to be preserved

**An instantaneous edge.** [Enhancement-504](Enhancement-504.md) clamps a negative
rise/fall to zero, whose reciprocal is `+inf` — that is how an instantaneous
transition disables the rate limit. `TRACK_C · inf` is `inf`, and `inf · 0.0` is
NaN, so the gain falls back to the old fixed 1e9 s⁻¹ exactly there, which is the
behaviour E-504's suite measured. A merely *fast* finite rate is far below the
guard (`trise = 1 ps` gives 1e15) and is untouched.

**One gain, from the faster rate.** A gain chosen per *direction* was tried and
rejected: it makes the loop dynamics jump at the crossing point, and
`transition(x, td, 0.5n, -0.5n)` then overshot to 1.01 and recovered on the far
slower fallback gain — a regression against E-504's suite. Taking the faster rate
makes the slower direction stiffer than it needs to be, which costs nothing
measurable and *reduces* overshoot, since the ringing amplitude is bounded by the
same released gap.

## Why it survived this long

`defaulttransition` pins the **1 µs** case, deep inside the region where the old
code was already right. It is the same shape of blind spot as
[Enhancement-510](Enhancement-510.md), where the suite tested `$ln1p(0.5)` and a
literal folds before code generation: in both cases the test exercises the regime
where the implementation happens to be correct. The new suite spans five decades
of rise time for that reason.

## Two suites adjusted, with their assertions intact

- `rtdomain` check [5] required `len(n) == len(p)` *before* it could report that
  two waveforms differ. A properly rate-limited 2 ns ramp needs more timepoints
  than an instantaneous edge (119 against 102), so the check reported "the same"
  for waveforms that had just become *more* different. Differing lengths are
  themselves proof of difference; the assertion — a negative rise must not behave
  like a positive one — is unchanged.
- `hiername` asks for a 1 ns timestep on a 1 ns edge: it is testing hierarchical
  names, not waveform shape, so the edge is deliberately unresolved. At that
  resolution the shorter tail leaves a ~1e-5 residue on the settled level, and
  none at all once the deck resolves its own edge (1.00000 exactly at 0.1 ns and
  finer). Its 1e-6 tolerance on a level that is physically 1.0 was pinning
  integration noise, and is now 1e-4.

## Files

| file | change |
|---|---|
| `openvaf/hir_lower/src/expr.rs` | `lower_rate_limited_track`: gain scaled to the rate, single gain from the faster direction, finite fallback for an instantaneous edge |
| `examples/rtdomain_examples/verify_rtdomain.py` | check [5] made length-robust |
| `examples/hiername_examples/verify_hiername.py` | tolerance on an unresolved edge |
| `examples/transedge_examples/` | new suite |

## Verification

`transedge_examples` — **14 checks, both linear solvers**, spanning five decades of
rise time, the quarter points of the ramp, timestep convergence, the settled value,
`slew`, and E-504's instantaneous edge. Full regression **425/425**.
