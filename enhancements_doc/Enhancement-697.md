# Enhancement-697: a `slew` rate at or above 1e12 V/s is instantaneous — it aborted the transient at the first edge from 1e13 up to 1e297

**Scope:** F7 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_openvaf-r-cli-integers-transition-and-json.md).
openvaf: `hir_lower/src/expr.rs` (`lower_rate_limited_track`: `RATE_INST`, the
per-side switch to the infinite-rate path). `examples/transedge_examples/`
(three checks added, 17). Handbook [§2.4](../docs/handbook/02-verilog-a-language.md)
rows; the compliance document. **openvaf only.**

**Suites:** [`transedge_examples`](../examples/transedge_examples/) 17 of 17
per solver, both solvers (the three new checks fail on the E-694 binaries: the
transient aborts there); `lrmfilters`, `rtdomain`, `hiername`, `domainwarn`
both solvers, unchanged; the compiler workspace tests green apart from the
three pre-existing sourcegen drift failures; full sweep 531 of 531.

## What was wrong

`slew(cmp, pos, neg)` on a 0/1 comparator stepping at 1 ms, rates set on the
card, `tran <step> 4m`:

| card | step 0.5 µs | step 10 µs |
|---|---|---|
| `pos=1e12 neg=-1e12` | runs | runs |
| `pos=1e13 neg=-1e13` | runs | **aborts at 3 ms** (timestep 1.2e-17) |
| `pos=1e14 neg=-1e14` | **aborts at 3 ms** (4.0e-18) | **aborts at 1 ms** (1.25e-17) |
| `pos=5e14 … 1e30` | **aborts at 1 ms** (6.25e-19) | **aborts at 1 ms** (1.25e-17) |
| `pos=1e15 neg=-1e5` | **60 s timeout** | **60 s timeout** |
| `pos=1e299`, `1e300` | runs | runs |

"doAnalyses: TRAN: Timestep too small; time = 0.001, timestep = 6.25e-19: trouble
with node "n1#implicit_equation_0"; tran simulation(s) aborted" — the slew's own
implicit equation. The rate written as a literal in the model aborted the same
way, and `method=gear` changed nothing. Nothing in the model is wrong: LRM 4.5.9
puts no upper bound on a slew rate, and 1e15 V/s on a 1 V signal is a
femtosecond edge, which every other operator takes in stride.

[E-512](Enhancement-512.md)'s tracking loop sets its gain relative to the rate,
`K = TRACK_C · rate` with `TRACK_C = 1e3`, so the tail after the linear ramp has
τ = 1/K. At 1e13 V/s that is 1e16/s, a 0.1 fs time constant; at the corner
where the clamp releases, ngspice's timestep control has to resolve it, cannot,
and shrinks the step until it underflows. The loop's `HUGE` guard (1e300 on the
gain) was written for an *infinite* rate — a zero transition time — and only
took over above 1e297 V/s, three hundred decades past where the loop already
failed.

## What changed

**A side at or above `RATE_INST` (1e12 V/s) is instantaneous.** In
`lower_rate_limited_track`, each of `pos_max` and `neg_max` at or above the
threshold is replaced by `+inf` before the gain and the clamp are formed, so
that side takes the infinite-rate path the loop already had: no clamp in that
direction and the fixed `TRACK_GAIN_INF` gain (1e9/s, τ ≈ 1 ns), the same
behaviour as `transition(x, 0, 0)` and E-504's suite. A ramp faster than a
picosecond per unit swing is instantaneous to any transient ngspice runs; the
threshold sits ten-fold below the first failure. Per side, so an asymmetric
`transition(x, 0, 0, 100u)` keeps its 100 µs fall (and `transition(x, 0, 100u, 1e-30)`
its 100 µs rise) while the other edge is instantaneous. Rates at or below 1e12
V/s are the exact ramp as before, and E-512's five decades of rise time are
unchanged.

## Verification

| check | result |
|---|---|
| `slew` at 1e13, 1e15, 1e30, 1e300 V/s, `pos=1e15 neg=-1e5`, steps 10 µs and 0.5 µs | every transient runs to the end, the output at 1.0 after the rise and 0 after the fall (was an abort or a minute of grinding) |
| `slew` at 1e11 and 1e12 V/s | unchanged |
| `transition` with a 1e-14 and a 1e-30 s rise | 1.0, unchanged |
| `transition(x, 0, 0, 100u)`, `(x, 0, 1e-13, 100u)`, `(x, 0, 100u, 1e-30)` | the finite side ramps in 100 µs, the other is instantaneous |
| E-512's endpoint table (3 ns … 30 µs), the 25× refinement, the settled value | unchanged (the suite's 14 checks) |
| the E-694 binaries on the suite | the three new checks fail (no points: the transient aborted) |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- A rate between 1e12 and 1e297 V/s no longer produces a finite ramp of its
  own length; it is the 1 ns tail of the instantaneous path. A transient that
  could resolve a sub-picosecond ramp does not exist in practice, and the
  alternative was the abort.
- The loop's constants (`TRACK_C`, `TRACK_GAIN_INF`) are unchanged; E-512's
  note on not raising `TRACK_C` without re-running `defaulttransition` stands.
- F2 of the same hunt — the settled value off by 2e-4 under the trapezoidal
  rule when the ramp is shorter than the step — is not touched here.
