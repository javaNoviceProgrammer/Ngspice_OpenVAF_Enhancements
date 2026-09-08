# Enhancement-587: a crossing needs a previous sample on the other side, and `transition`/`slew` are unity in small-signal analyses

**Scope:** `openvaf/hir_lower/src/stmt.rs` (`lower_cross`, `lower_above`),
`openvaf/hir_lower/src/expr.rs` (`lower_rate_limited_track`),
`examples/evtedge_examples/` (new, 14 checks per solver); two existing suites whose
sources start exactly on the threshold updated (`hiername` shifts its comparator's
sine by −90°, `varinit` counts 3 crossings where the fourth was the seeded start).
**Compiler only.** Hunt findings F3 and F2 of 2026-09-07.

**Suites:** [`evtedge_examples`](../examples/evtedge_examples/) 14 of 14 per solver,
both solvers; the transition, slew, default-transition and other event suites pass
unchanged; full sweep 483 of 483.

**Behaviour change, stated plainly:** a source that starts *exactly* on a `cross`
threshold — `SIN(0 1 1meg)` against a zero threshold is the common case — no longer
fires at its first step. The first event is the first genuine crossing (for a rising
`cross` on such a sine, one full period in). A comparator that must be right from t = 0
sets its level in `@(initial_step)` or uses `above`, whose initialization event the LRM
defines for exactly this.

## F3 — the edge rule

`@(cross(e, +1))` and `@(above(e))` counted a rising edge as `prev <= 0 && cur > 0`.
An expression that **starts exactly at zero** — a sine whose offset equals the threshold,
the ordinary way to write a symmetric test — then fired on the first step after t = 0,
because `prev` was the seeded 0 of the initial step: three rising crossings over
2.5 periods where there are two. `above` fired once more on the t = 0 Newton walk of a
transient, whose iterates from the zero guess pass through the threshold.

The rule is now **strict on the previous side and inclusive on the current side**:
rising is `prev < 0 && cur >= 0`, falling `prev > 0 && cur <= 0`. An expression that
lands exactly on zero coming from the other side fires once, at that sample, and not
again when the next one is positive; one that starts on zero and rises is not a
crossing. `above` additionally gates its evaluation-to-evaluation edge at t = 0 of a
transient the way `cross` has since the events audit — except that an edge landing on a
*strictly positive* value still counts, since that is the LRM's initialization event
("positive at the conclusion of the initial condition analysis"), which no single
evaluation can otherwise see; the first-evaluation form of that event is kept, and dc
sweeps keep every edge.

## F2 — the small-signal transfer

`V(o) <+ transition(V(in))` showed −0.036° at 100 kHz, −0.36° at 1 MHz and −3.6° at
10 MHz in `ac` — a delay of exactly 1 ns on top of `td`, in every argument form, and the
same for `slew`. The loop that realises both, `dy/dt = clamp(K·(x − y))` with
K = 1000·rate (E-512), linearises to a first-order lag with τ = 1/K: t_rise/1000, one
nanosecond for the default 1 µs transition and one nanosecond again for an instantaneous
one through the finite fallback gain. The LRM's small-signal transfer of `transition()`
and of a `slew()` that is not slewing is unity.

The loop's **reactive residual is now zeroed for the `ac` and `noise` evaluations**
(`analysis("ac")`/`analysis("noise")`, the same runtime callback `cross` uses), which
turns the equation into `gain·(y − x) = 0`, exactly `y = x`. DC and transient are
untouched — there the residual is defined unconditionally for the reasons E-47 and
E-512 record — and `absdelay`, which is a true delay, keeps its phase.

## Verification

| check | result |
|---|---|
| a sine starting exactly on the threshold, 2.5 periods | 2 rising, 2 falling, 4 either, 2 above (was 3/2/5/3) |
| just above / just below | 2/2/4/3 (above adds its initialization event) and 3/3/6/3 |
| a triangle landing exactly on the threshold | one event per pass |
| positive at t = 0 | above's initialization event once, cross nothing |
| dc sweep | above counts the one pass, cross nothing |
| `transition()`, `transition(x,0,0,0)`, `slew(x,1e6,-1e6)` in ac | phase 0 and magnitude 1 at 100 kHz, 1 MHz, 10 MHz |
| `transition(x, 5u, 1u)` | exactly −180° at 100 kHz |
| noise | the spectrum through `transition` equals the spectrum at its input |
| transient | the 1 µs ramp is 0.5 half-way and 1 at its end; the 1 V/µs slew likewise |
