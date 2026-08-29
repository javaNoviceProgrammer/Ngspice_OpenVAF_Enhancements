# Enhancement-504 — a domain the compiler cannot see is still a domain

Enhancement-479 taught openvaf-r's const-domain guards to see a `localparam` as
well as a literal. But a `parameter` can be overridden from the deck, so the
compiler correctly does **not** refuse one — a default is the model author's
business, the rule Enhancement-426 settled and Enhancement-455 restated.

That leaves the ordinary case completely unguarded. **A model ships a sensible
default, a deck overrides it with something outside the operator's domain, and
nothing checks it afterwards.**

| construct | literal | `localparam` | from the deck (before) |
|---|---|---|---|
| `transition` rise/fall < 0 | refused | refused | **−24 V, unbounded** |
| `$bound_step` < 0 | refused | refused | **hangs indefinitely** |
| `$bound_step` = 1e-18 (legal) | — | — | **hangs indefinitely** |
| `$discontinuity(0)` every eval | — | — | **hangs indefinitely** |
| `white_noise(p)`, p < 0 | refused | refused | silently `|p|` |
| `idtmod` modulus 0 | refused | refused | NaN, analysis aborted |

## 1. `transition` was an unstable integrator

`pos_max` is `1/trise` and bounds `dy/dt` from **above** in the tracking loop, so
a negative `trise` inverts the clamp and the loop integrates *away* from its
input rather than towards it. A 0→1 signal reached **−24 V**, and it was
unbounded: −120 V over a longer run, and larger still as `|trise|` shrinks,
because the runaway rate is `1/|trise|`. A negative *fall* time overshoots +24.

Clamped to zero. That is the projection onto the domain the LRM states, it is
already what `transition` means with the argument omitted, and it makes
`1/0 = +inf` disable the rate limit exactly as an instantaneous transition
should. A negative rise now means *zero*, not its magnitude — guessing that the
author "meant" `|trise|` would be inventing intent. `slew` needed no such change:
it already applies `lower_fabs` to both rates, for its own sign-convention
reasons.

## 2. Two ways for a model to hang the simulator

**The sentinel collision.** `$bound_step` writes the field that carries
Enhancement-24's sentinel, where a negative value does not mean "bound the step"
but *"a `$discontinuity` happened here"*. A model passing a negative was therefore
not merely asking for something meaningless — it was announcing a discontinuity on
every evaluation, and the transient never returned. Fixed in the compiler: a
non-positive or non-finite bound is dropped and the incumbent stands, which is
what "no constraint from this call" has always meant (the place defaults to
`INFINITY`).

**No floor on a legal request.** `$bound_step(1e-18)` is a perfectly legal
positive request and was taken literally: over 150 s of wall clock with no
output, no error and no *"timestep too small"*. That check compares against
`CKTdelmin`, which for a 12 ns analysis is ~5e-20 — far *below* the 1e-18 being
asked for — so nothing ever fired. The step was not too small for the solver; it
was too small to finish.

No clamp value makes 1.2e10 steps work, so the rule is stated in the only terms
that bound the run: **a model may not force more than `E504_MAX_MODEL_STEPS`
(10⁶) steps across the analysis window.** Beyond that the bound is clamped and the
instance is named once. A model wanting genuinely fine resolution is unaffected —
a million steps is already far more than any transient here needs — and ngspice's
own adaptive stepping is untouched, because this bounds only what a *device* may
demand.

**The same floor on the sentinel branch.** `$discontinuity(0)` outside any
conditional pinned the timestep to the last accepted delta, which could then never
grow, so once the retry had cut it the transient crawled and never returned.
Enhancement-55 already made the *retry* edge-triggered for exactly this reason;
the cap needed the same protection. `$discontinuity(-1)` means "no discontinuity",
is fine, and stays untouched and silent.

## 3. The noise sign, and where deliberately not to fix it

`white_noise(-1e-20)` produced noise **bit-identical** to `white_noise(1e-20)`:
the simulator takes `sqrt(fabs(pwr))`, so the sign was simply gone. A power is a
variance and cannot be negative.

The clamp is at the `white_noise` / `flicker_noise` **argument** — the user's
value — and deliberately **not** in ngspice. By the time the power reaches
`osdinoise.c` the contribution factor has been folded into it as `fac*|fac|`, and
Enhancement-42 uses that sign to sum same-named sources **coherently**. Rejecting
a negative there would break correlated noise. Rejecting it at the user's argument
cannot, because that runs before the fold — and the suite holds the coherent path
(two same-named sources still sum to 2×, not √2×).

## 4. `idtmod` divided by a zero modulus

It returned NaN and took the analysis down with *"Timestep too small; cause
unrecorded"* — a message naming neither the model nor the call. A modulus that is
not strictly positive now falls back to the **unwrapped** integral, which is
exactly what `idtmod` means with no modulus supplied, so the model keeps running
and the value stays finite.

## Withdrawn

An out-of-range **array index** returning element 0 was reported in round 61 and
withdrawn on reading the site. Enhancement-489 chose a select chain precisely so
that no index can read out of bounds at any value, and records that returning NaN
was considered and **rejected** — a run-time index may be transiently out of range
mid-solve, and a NaN would poison the iteration and break models that converge
today. That is a decision, not a defect, and the comment says so.

## Files

| file | change |
|---|---|
| `openvaf/hir_lower/src/expr.rs` | clamp `transition`'s rise/fall; drop a non-positive `$bound_step`; `lower_noise_power()` for `white_noise`/`flicker_noise`; `idtmod`'s modulus falls back to unwrapped |
| `ngspice-46/src/osdi/osditrunc.c` | bound the step count a model may force, on both the literal-bound and the sentinel branch |
| `ngspice-46/src/osdi/osdidefs.h` | the per-instance latch so each warning is said once |

## Verification

`examples/rtdomain_examples/verify_rtdomain.py` — 16 checks under both linear
solvers. 11 fail on the shipped binaries.
