# Enhancement-514 — the analog operators, audited against the LRM

A clause-by-clause audit of **Accellera VAMS-2023 §4.5.1–4.5.15** (`docs/VAMS-LRM-2023.pdf`)
against the implementation. Eight conformance defects, one over-strict refusal
that rejected a legal program, and one measurement of my own that had to be
withdrawn.

## The headline: three faces of one root cause

A transient's state arrays were seeded with **zero** instead of with the
**converged operating point**. Three operators wear it:

**`slew` and `transition`.** LRM 4.5.9: *"If the rate of change of expr is less
than the specified maximum slew rates, slew() **returns the value of expr**."* A
constant input has rate of change zero, so `slew` must return it. It ramped up
from 0 at exactly the slew rate instead, for `|V_bias| / rate` seconds:

```
slew(V, 1e5, -1e5), CONSTANT 1 V input, no edge at all
  op   1.000000   correct
  t=4.5us  0.4512      <-- 1e5 V/s x 4.512 us, to five digits
  t=5.3us  0.5312
```

In a realistic model — a slew-rate-limited buffer at 1 V/µs biased at a 2.5 V
mid-rail — the operating point read 2.500 V and the transient then read 0.954 V
at 1 µs, taking 2.5 µs to climb back to its own DC bias. Silent: rc=0, no
warning, no convergence complaint. Any transient shorter than 2.5 µs lay
entirely inside the artifact.

The cause is one line in `lower_rate_limited_track`. The **reactive** residual was
gated on `enable_integration` and forced to `0.0` at DC:

```rust
let react = lower_select_with(enable_integration, |_| y, |cx| cx.ctx.fconst(0.0));
```

ngspice stores the react residual as that equation's charge state and, at
`MODEINITTRAN`, seeds the previous state from it (`CKTstate1[state] =
residual_react`). Zeroing it at DC left the stored charge at 0 while the
operating point had solved `y = x`, so the first transient step saw
`dy/dt = (y − 0)/h`, the clamp bounded it, and the output ramped. The DC
*solution* is unaffected either way — `CALC_REACT_JACOBIAN` is clear at the
operating point, so the reactive term contributes nothing to the residual or the
Jacobian there; it is only *stored*. [Enhancement-47](Enhancement-47.md)'s reason
for switching the **resistive** residual at DC (a saturated clamp has zero
derivative w.r.t. `y`, so the DC Jacobian diagonal vanished) does not apply to
the reactive one, whose derivative is 1. Every sibling that gets this right —
`laplace_*`'s state-space realization, a hand-written `ddt(V(o,c))` — defines its
react residual unconditionally, and so does this now.

**`absdelay`.** LRM 4.5.7 states the operator as `Output(t) = Input(max(t − td, 0))`.
For `t < td` that reads `Input(0)`: the input at time zero, i.e. the operating
point. `osdiload.c` stored a literal `0.0` there, with a comment claiming it was
"V_y at t=0 before the transient begins". So an `absdelay` around any non-zero
bias reported **0 for the whole first `td`** and then *stepped* to the bias — a
full-swing glitch in a model merely sitting at its operating point. `is_init_tran`
runs after the operating point has converged, so `CKTrhsOld` holds it; the
history is seeded from there now.

**`last_crossing`.** LRM 4.5.10: *"Before the expression crosses zero (0) for the
first time, the last_crossing() function returns a **negative** value."* It
returned `0.0`, so a model testing `last_crossing(...) < 0` for "not yet" read a
crossing that never happened. Two changes were needed, because fixing only the
sentinel left half the cases wrong: the sentinel itself (`OSDI_LAST_CROSSING_NONE`),
and the **crossing history**, which had the same zero-seeding problem — for an
expression already *above* zero at the operating point, the first accepted point
looked like a rising edge from 0, so a spurious crossing at t=0 overwrote the
sentinel before any model could read it.

### Why it survived this long

The state is seeded with **0**, and every stimulus in the four relevant suites
starts at zero:

```
absdelay_examples        PULSE(0 1 0 0.2n 0.2n 4.8n 10n)
transedge_examples       PWL(0 0 1p 0 2p 1 {tstop} 1)
slew_examples            dc 0
```

which is exactly where a zero-seeded state is indistinguishable from a correct
one. This is [Enhancement-512](Enhancement-512.md)'s lesson again — a suite
pinning ONE operating point — with the operating point itself as the hidden
variable. `examples/lrmops_examples/` biases every input away from zero on
purpose.

## Five more, each against the clause it implements

| LRM | was | now |
|---|---|---|
| 4.5.8 *"If a time_tol value of zero (0.0) is specified, the simulator shall apply a suitable value"* | `transition(…, 0.0)` refused | accepted; only a negative one is refused |
| Table 4-19 lists `idtmod(expr,ic,modulus,offset,nature)` | refused — the signature declared its last argument as a **real**, making it byte-identical to the `…,abstol)` form, so the NATURE spelling could never match | compiles |
| 4.5.12 *"[the transition time] shall be nonnegative"* | a negative z-filter transition time compiled in silence, while the identical rule for `transition`'s rise/fall was enforced | refused |
| 4.5.12 *"A Z-filter with zero (0) transition time shall not be directly assigned to a branch"* | silent | warns, on the LRM's own **literal** reading |
| 4.5.7 *"If td becomes greater than maxdelay, maxdelay will be used as a substitute for td"* | a hard **error** — which rejected a conformant program, since the LRM defines a substitution rather than an error | warns, and the substitution happens |

The z-filter branch rule is deliberately the literal reading: the contributed
expression **is** the filter call. A looser rule would fire on
`I(a,c) <+ zi_nd(...)*gain`, where the author has done nothing the LRM forbids,
and a lint that cries wolf on ordinary code is worse than no lint.

## Not fixed, deliberately

LRM 4.5.7 also says that with no `maxdelay`, *"the value of td when the
absdelay() is first evaluated shall be used and any future changes to td shall be
ignored"*. The only first-evaluation flag a model can see is `IsInitialStep`, and
**at that flag the circuit solution is still the zero initial guess** — a probe
read inside `@(initial_step)` returns 0, measurably (`V(ctl,c)` reads 1.0 outside
it and 0 inside). Latching there stores 0, which is worse than tracking. And for
the case that actually occurs — `td` a parameter — freezing is indistinguishable
from not freezing, because a parameter cannot change during an analysis anyway.
Doing it correctly means latching on the **simulator** side at `MODEINITTRAN`,
where the operating point has converged, which needs a per-slot "this delay is
fixed" flag in `OsdiAbsDelayInfo` — a descriptor/ABI addition not worth pairing
with these fixes. An implementation was written, measured, and reverted; the
reasoning is recorded at the site.

## Withdrawn

I reported `laplace_zp` with a root at the origin as having a nonzero DC gain
(45.0276 per volt where LRM 4.5.11.1's *"the term associated with it is
implemented as s"* requires 0). **That was my measurement, not a defect.** The
probe module also contained `laplace_np(V, '{1.0}, '{0.0,0.0})` — a pole at the
origin, i.e. an integrator, whose DC solution is genuinely indeterminate — and it
polluted the shared DC solve. Measured alone, `laplace_zp` returns exactly 0.0,
as do all three of its siblings for the same transfer function.

## Verified conformant, no change

All ten §4.5.15 restrictions are enforced: analog operators refused inside a
runtime `if` / `?:` / `case`, permitted under a parameter-controlled one, refused
inside events, refused in `while` / `repeat` / non-genvar `for`, refused in
user-defined functions, and null arguments refused outside the laplace/zi zeros
exemption.

Table 4-20's constant/dynamic split is honoured for the arguments audited
here — and it **validates** [Enhancement-509](Enhancement-509.md)'s rule: the
arguments openvaf declines to refuse at compile time (slew rates, transition
times, `absdelay`'s `td`) are exactly the ones the LRM classes as *dynamic
expressions*. (One counterexample surfaced in the later filter-operators
audit: dynamic `laplace_*` coefficient vectors — constant-class per the
table — are accepted and TRACK; they draw a warning now, and the compliance
doc's §4.3 records the deviation.)

Also checked and correct: `ddt` (DC returns 0, both optional forms), all five
`idt` signatures, `idtmod` wrapping into `[0, modulus)` and
`[offset, offset+modulus)` — verified on *discriminating* points, since the
obvious probe values are ones where the two windows legitimately agree — `ddx`,
`absdelay`'s AC phase, `slew`'s sign convention and its "opposite of max_pos"
default, small-signal gain 1.0 when not slewing, null zeros arguments (`,,`),
vector **parameter** references, the `zi` six-argument form with `t0`, and
`limexp`'s value.

## Three existing suites changed, and why

A fix that corrects behaviour has to update whatever was pinned to the old
behaviour. All three are recorded here rather than quietly adjusted.

**`reusestate` [16]** asserted the "no crossing yet" value was literally `0.0`.
It is now the LRM's negative sentinel. What the check is *about* — that each
reused sweep point starts fresh instead of inheriting the previous point's
crossing time, which is [Enhancement-498](Enhancement-498.md)'s defect — is
unchanged and still asserted.

**`limguard`** asserted that `absdelay` with a constant `td` greater than
`maxdelay` is **rejected**. It is not, any more: LRM 4.5.7 defines a
substitution, so refusing it rejected a conformant program. The row now expects
acceptance, and the warning plus the substituted delay are asserted in
`lrmops_examples`.

**`defaulttransition` [1] and [3]** are the interesting one. `dt_bare` and
`dt_forms` flipped their input with `@(timer(0, 4u))` and measured the resulting
ramp. But `@(timer(0, ...))` **fires during the DC solve** — measured: `s` is
already 1 and `transition(s)` is already 1 at the operating point — so a
transient starting from that operating point has nothing left to ramp. The old
ramp appeared only because the state was seeded with 0 *while the operating point
it had just computed said 1*. The models now flip at 0.5 µs so the ramp happens
inside the transient, which is what these checks are for, and is exactly what
`dt_delay` in the same file already did deliberately — its comment reads *"the
timer starts at 1u -- a flip at t=0 exercises the absdelay history's startup
value instead of the ramp, which is not what this check is about"*. The author
had already met this hazard in one module and not the other two.

**This is a visible behaviour change** and `lrmops_examples` check [26] pins it:
a model that flips a signal with `@(timer(0, ...))` and transitions it no longer
shows an initial ramp, because its operating point already holds the flipped
value. That is self-consistent where the old behaviour was not, but a model
relying on the old startup ramp will look different.

## Verification

`examples/lrmops_examples/` — **26 checks, both solvers**; **4/25 pass on the
shipped binaries** before the fix (check 26 pins a behaviour change rather than a
defect, so it is not part of that ratio). Every state check is paired with a regression
check that the operator still *does its job*: `slew` still rate-limits a real
edge to 0.55 V, `absdelay` still transports a 1→0 edge to arrive one delay later,
`last_crossing` still times a real crossing at 5 µs, and `maxdelay` is still
substituted for an over-long `td`.
