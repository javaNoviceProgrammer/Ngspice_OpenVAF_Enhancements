# Enhancement-504 — a domain the compiler cannot see is still a domain

```
python3 verify_rtdomain.py
```

16 checks, both linear solvers. 11 of them fail without the fix.

## What was wrong

[Enhancement-479](../../enhancements_doc/Enhancement-479.md) taught openvaf-r's
const-domain guards to see a `localparam` as well as a literal. But a `parameter`
can be overridden from the deck, so the compiler correctly does **not** refuse one
— a default is the model author's business, the rule
[Enhancement-426](../../enhancements_doc/Enhancement-426.md) settled.

That leaves the ordinary case completely unguarded: **a model ships a sensible
default, a deck overrides it with something outside the operator's domain, and
nothing checks it afterwards.**

| construct | literal | `localparam` | from the deck (before) |
|---|---|---|---|
| `transition` rise/fall < 0 | refused | refused | **−24 V, unbounded** |
| `$bound_step` < 0 | refused | refused | **hangs forever** |
| `$bound_step` = 1e-18 (legal!) | — | — | **hangs forever** |
| `$discontinuity(0)` every eval | — | — | **hangs forever** |
| `white_noise(p)` p < 0 | refused | refused | silently `\|p\|` |
| `idtmod` modulus 0 | refused | refused | NaN, analysis aborted |

### `transition` was an unstable integrator

`pos_max` is `1/trise` and bounds `dy/dt` from **above** in the tracking loop, so
a negative `trise` inverts the clamp and the loop integrates *away* from its
input. A 0→1 signal reached **−24 V** — and unbounded with it: −120 V over a
longer run, and larger still as `|trise|` shrinks, because the runaway rate is
`1/|trise|`. A negative *fall* time overshoots +24 instead.

Clamped to zero, which is the projection onto the domain the LRM states, is
already what `transition` means with the argument omitted, and makes `1/0 = +inf`
disable the rate limit exactly as an instantaneous transition should. Check [5]
holds that a negative rise means *zero*, not its magnitude — guessing that the
author "meant" `|trise|` would be inventing intent.

### Two ways to hang the simulator

`$bound_step` writes the field that carries
[Enhancement-24](../../enhancements_doc/Enhancement-24.md)'s **sentinel**, where a
negative value does not mean "bound the step" but *"a `$discontinuity` happened
here"*. A model passing a negative therefore announced a discontinuity on every
evaluation, and the transient never returned. That one is fixed in the compiler:
a non-positive bound is dropped and the incumbent stands.

`$bound_step(1e-18)` is a perfectly **legal** positive request, and it was taken
literally — over 150 s with no output, no error, and no *"timestep too small"*,
because that test compares against `CKTdelmin` (~5e-20 here), far below what was
asked for. The step was not too small for the solver; it was too small to finish.
No clamp value makes 1.2e10 steps work, so the rule is stated in the only terms
that bound the run: **a model may not force more than 10⁶ steps across the
analysis window.** Beyond that the bound is clamped and the model is named once.

`$discontinuity(0)` outside any conditional pinned the timestep to the last
accepted delta, which could then never grow. `$discontinuity(-1)` means "no
discontinuity", is fine, and stays untouched and silent — check [10].

### The noise sign, and where *not* to fix it

`white_noise(-1e-20)` produced noise **bit-identical** to `+1e-20`: ngspice takes
`sqrt(fabs(pwr))`, so the sign was simply gone.

The clamp is at the `white_noise` **argument**, deliberately not in ngspice. By
the time the power reaches `osdinoise.c` the contribution factor has been folded
into it as `fac*|fac|`, and
[Enhancement-42](../../enhancements_doc/Enhancement-42.md) uses that sign to sum
same-named sources **coherently**. Rejecting a negative there would break
correlated noise; rejecting it at the user's argument cannot, because that runs
before the fold. Check [12] holds the coherent path.

## Withdrawn from the hunt

An out-of-range **array index** returning element 0 was reported and withdrawn.
The site says why: Enhancement-489 chose a select chain precisely so that no index
can read out of bounds at any value, and records that returning NaN was considered
and **rejected**, because a run-time index may be transiently out of range
mid-solve and a NaN would poison the iteration. That is a decision, not a defect.
