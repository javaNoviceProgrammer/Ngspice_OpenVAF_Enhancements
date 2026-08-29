# Enhancement-506 — a guard that only ever saw the literal

Every value guard in `hir_ty` judges a **constant**. It sees a literal or a
localparam and nothing else, and that is deliberate: a `parameter`'s *default* is
the author's business, which Enhancement-426 settled and Enhancement-479 kept when
it taught `const_num` to see a named constant.

But the ordinary way a model is used is that the **deck overrides that
parameter**, and on that route the value reached the runtime with nothing in
between. So a value the compiler calls an outright error was accepted in silence
whenever it arrived the way values actually arrive.

Enhancement-504's own comment states the shape:

> `hir_ty`'s `require_non_negative` already refuses a negative it can SEE, but it
> only sees a literal or a localparam. The ordinary case is a model whose
> `parameter real tr = 0.5n` is overridden from the deck, which the compiler
> cannot refuse (a default is the author's business) and which nothing checked
> afterwards.

Enhancement-504 closed it for `transition`, `$bound_step`, the noise power and
`idtmod`. Round 63 found it still open in five more places, and two further
faults in the same family.

## Clamp where the domain has a boundary, refuse where it has none

Enhancement-504 set the rule for the first case and this enhancement keeps it: a
negative rise time becomes zero, because zero is what `transition` already means
with the argument omitted; an unusable noise power becomes zero, because an
unusable spec should make the source inert rather than the answer wrong.

Three of the new sites have **no such projection**. A sampling period that must be
positive, a denominator that must have a leading term, and an event direction that
is one of exactly three values are not quantities with a nearest legal value —
substituting one would trade a visibly absurd answer for an invisibly wrong one.
There the run time says what the compiler would have said and aborts.

`LoweringCtx::runtime_fatal` emits that: a `Print` of severity `Fatal` naming the
builtin and the offending number, then `SetRetFlag(Abort)`. Its shape follows
`$fatal` (Enhancement-324) — **print, raise a flag, and continue**. The OSDI eval
function has a mandatory epilogue that the ABI requires to run and every ret-flag
is only a flag the simulator inspects *after* eval returns, so terminating the MIR
function early would strand the epilogue in a block with no incoming edges. Each
guard substitutes a finite value for the one evaluation that still has to
complete, purely so the matrix is stamped with numbers rather than NaN before the
flag is honoured.

When the argument is a constant the condition folds and the branch disappears
entirely, so a conforming model pays nothing.

## 1. `zi_*` sampling period — 1.2e+240, exit code 0

`T` decides the whole bilinear map. A negative period inverts
`w = (1 - sT/2)/(1 + sT/2)`, which reflects every pole across the imaginary axis:
the filter became unstable and ran to **1.2e+240** over 60 ns, with exit code 0
and not one diagnostic. The worst of the set, because the number is absurd and
nothing says so.

`hir_ty` refuses a literal (Enhancement-420, *"the sampling period must be greater
than zero"*), so only the deck route was exposed. All four `zi_*` forms share
`lower_zi` and all four diverged — `zi_nd`/`zi_zd` to 1.2e+240, `zi_zp`/`zi_np` to
-1.0e+12.

A tiny-magnitude negative period (-1e-18) and a huge one stay bounded; the
divergence needs a substantially negative value, which is why a smoke test would
not have found it.

## 2. `laplace_*` leading denominator coefficient — a convergence report for a structural fault

`a_n` divides every normalised coefficient of the state space. Written as a
literal the compiler names the fault exactly:

```
error: laplace_nd: the denominator has a highest-order coefficient of zero,
       so its effective order is 0 rather than 1
```

Written as `'{1, d1}` with `d1` a deck-set parameter, the same filter compiled
clean, divided by zero, and produced:

```
Warning: Dynamic gmin stepping failed
Warning: True gmin stepping failed
Warning: source stepping failed
Error: Transient op failed, timestep too small
doAnalyses: TRAN:  Timestep too small; initial timepoint: cause unrecorded.
```

Six lines of convergence failure, ending in *cause unrecorded*, for a
structurally invalid filter the compiler can already describe precisely.

The order `n` is fixed when the state space is built, so the effective order
cannot be reduced at run time; substituting a small epsilon would only hide the
mistake behind a stiff parasitic pole. The guard therefore refuses.

## 3. `@(cross)` and `last_crossing` direction — interpreted, not checked

The direction is dispatched by **sign**: `dir > 0` rising, `dir < 0` falling,
exactly zero either. So a deck direction of 7 fired on rising edges and -3 on
falling ones, each producing a plausible count from a spec the compiler calls an
outright error, and a NaN direction made every comparison false so the event went
silently **dead**.

Sign is not a projection of `{-1, 0, +1}` — it is a guess at what a seventh
direction might have meant. Both builtins take the same argument and had the same
hole, so both use one shared guard.

## 4. The integer `$dist_*` family — Enhancement-505 clamped only half of it

Enhancement-505 added run-time clamps to `rdist_uniform`, `rdist_normal`,
`rdist_exponential` and `rdist_poisson`. The integer siblings sit in the same
`match`, four arms away, and did not get them.

`hir_ty` validates the two spellings **together** — one arm serves
`rdist_normal | dist_normal` — which is what keeps them from drifting apart, and
it means a literal was refused for both. Only the deck route reached the gap:

| call, value from the deck | before | after |
|---|---|---|
| `$dist_exponential(seed, -1)` | deviates in **-10..0** | 0 |
| `$dist_normal(seed, 0, -1)` | the exact **negation** of the correct distribution | 0 |
| `$dist_uniform(seed, 10, 0)` | drew 0..10 from reversed bounds | 10 |
| `$rdist_exponential(seed, -1)` | 0 (E-505) | unchanged |

Every sample of `$dist_exponential` was negative, from a distribution whose
support is `[0, inf)`.

`chi_square`, `t` and `erlang` needed nothing: measured, 0 and -1 give
bit-identical results in *both* families, so there is no asymmetry to close.

## 5. `flicker_noise` — two arguments of one builtin disagreed

`flicker_noise(pwr, exp)` had its power guarded at compile time
(`require_non_negative`) and at run time (Enhancement-504's `lower_noise_power`),
and its **exponent** guarded nowhere. A NaN exponent made `pwr/f^exp` NaN at every
frequency.

This is invisible in a way its value-path twin is not: `sqrt(p)` in a `V(o) <+`
aborts the operating point loudly, because a NaN in the matrix cannot converge. A
noise contribution has no such feedback, so the same NaN printed
`onoise_total = nan` and exited 0.

**Zeroing the power alone does not fix it.** The runtime evaluates `pwr / f**exp`,
and `0 / f**NaN` is still NaN — the first version of this fix left the spectrum
exactly as poisoned as before. Both arguments are neutralised.

Only NaN is refused. Every finite exponent is meaningful (0 is white noise,
negative shapes the other way) and both infinities saturate per frequency rather
than poisoning the spectrum.

## 6. `noise_table_log` cannot represent a zero

Both table variants shared `require_non_negative`, and log-log interpolation takes
`log10` of **both** columns — so zero is exactly the one value that rule admits
and the log form cannot take. The whole output spectrum came back NaN, at every
frequency, with nothing reported.

`1e-300` works in both columns, which is what makes this a guard about zero rather
than about smallness. Plain `noise_table` interpolates linearly and a zero entry
is fine there, so only the log form is tightened.

## 7. The noise data **file** form was checked for shape and never for values

`table_file_is_usable` judges a noise file's structure — readable, one
`(frequency, power)` pair per line, every token finite. Its values were judged
nowhere. A file holding a frequency of **-1** produced output **bit-identical** to
the same file holding **+1**: the sign quietly discarded.

That is precisely the defect Enhancement-396 fixed for an *inline* table —
*"a negative power is not a noise power at all: it reached the runtime and
produced the same spectrum as its positive twin"* — still live in the form the
inline check did not cover. The file form now applies the inline rule, including
the log variant's stricter one, so which of the two spellings an author chose
cannot change whether the table is legal.

## The diagnostics name the call the author wrote

Three sites reported a function that is not in the user's source:

- `$dist_normal(s, 0, -1)` was reported as **`$rdist_normal:`**, and the same for
  `uniform`, `exponential`, `poisson`, `chi_square`, `t` and `erlang`. The shared
  validation arm is the right design; only the hardcoded name was wrong.
- `laplace_state_space` is shared by all four `laplace_*` forms and, through
  `lower_zi`, by all four `zi_*` forms, so its new run-time messages have the
  builtin threaded in.

Enhancement-396 fixed this same defect for `noise_table_log`, whose diagnostic had
been hardcoded to `noise_table`. An author greps their source for the function the
compiler named and does not find it.

## Withdrawn from round 63

Seven findings were withdrawn on evidence rather than fixed:

- **`$table_model` extrapolates linearly past both ends** — Enhancement-395's
  documented decision, stated at the site.
- **`2 ** -1 = 0`** — correct IEEE 1364 Table 5-6 integer semantics
  (Enhancement-489).
- **`chi_square`/`t`/`erlang` accept a degenerate dof** — 0 and -1 give
  bit-identical results in both families; self-consistent, no sibling asymmetry.
- **A `parameter` is accepted as an RNG seed** where a literal and an expression
  are refused — measured: the parameter is **not** corrupted (reads 5 before and
  after the draws) and the advance lands in a temporary.
- **`analysis("static")` false at the transient's t=0 row** — latching proves it
  *does* fire during the initial operating point; the printed row is the
  stored-value trap the OSDI analysis matrix warns about.
- **`$finish`/`$stop` inert in an `op`** — they work correctly in a transient
  (the analysis ends at 30.3 ns against a 100 ns baseline);
  `OSDIpendingRequests` acts between accepted points by design, and an `op` has
  no such moment.
- **`laplace_zp` with a pole or zero at the origin** — Enhancement-405 implements
  the LRM's own exception (*"if a root is zero, the term associated with it is
  implemented as `s`, rather than `(1 - s/r)`"*), selected at run time.

## Files

| file | change |
|---|---|
| `openvaf/hir_lower/src/ctx.rs` | `runtime_fatal` — a `$fatal`-shaped abort emitted from lowering, naming the builtin and the offending value |
| `openvaf/hir_lower/src/expr.rs` | `zi_*` sampling period; `laplace_state_space` leading coefficient; `last_crossing` direction; `flicker_noise` exponent; the four integer `$dist_*` clamps; `filter_builtin_name` |
| `openvaf/hir_lower/src/stmt.rs` | `guard_event_direction`, shared by `@(cross)` and `last_crossing` |
| `openvaf/hir_ty/src/validation/body.rs` | `noise_table_log` entries require *positive*; `rng_builtin_name`; the file diagnostic carries the variant |
| `openvaf/hir_ty/src/validation.rs` | `noise_table_file_bad_value` — the inline value rule applied to a data file, and named in the diagnostic |
| `examples/deckdomain_examples/` | new suite |

## Verification

`deckdomain_examples` — **45 checks, both linear solvers**, of which **23 fail on
the shipped binaries**. Full regression **420/420**.

Control cases pinned alongside every fix, all bit-identical to before: the four
`laplace_*` forms against theory (0.000 / -3.010 / -20.043 dB for a 1 kHz
single-pole), `zi_nd` with a legal period, `@(cross)` counts for all three legal
directions, `last_crossing` for each, `noise_table` with a zero frequency,
`noise_table_log` at 1e-300, and a legal `flicker_noise` exponent.
