# Enhancement-506 — a guard that only ever saw the literal

```
python3 verify_deckdomain.py
```

45 checks, both linear solvers. 23 of them fail without the fix.

## What was wrong

Every value guard in `hir_ty` judges a **constant**. It sees a literal or a
localparam and nothing else, and that is deliberate: a `parameter`'s *default* is
the author's business, which
[Enhancement-426](../../enhancements_doc/Enhancement-426.md) settled and
[Enhancement-479](../../enhancements_doc/Enhancement-479.md) kept when it taught
`const_num` to see a named constant.

But the ordinary way a model is used is that the **deck overrides that
parameter**, and on that route the value reached the runtime with nothing in
between. So a value the compiler calls an outright error was accepted in silence
whenever it arrived the way values actually arrive.

[Enhancement-504](../../enhancements_doc/Enhancement-504.md) closed that for
`transition`, `$bound_step`, the noise power and `idtmod`. Round 63 found it still
open in five more places, and two further faults in the same family.

### Clamp where the domain has a boundary, refuse where it has none

A negative rise time becomes zero, because zero is what `transition` already means
with the argument omitted. An unusable noise power becomes zero, because an
unusable spec should make the source inert rather than the answer wrong.

A sampling period that must be positive, a denominator that must have a leading
term, and an event direction that is one of exactly three values have **no such
nearest legal value**. Substituting one would trade a visibly absurd answer for an
invisibly wrong one, so the run time says what the compiler would have said and
aborts — naming the builtin and the offending number.

When the argument is a constant the condition folds and the branch disappears, so
a conforming model pays nothing.

### 1. `zi_*` sampling period — 1.2e+240, exit code 0

A negative `T` inverts the bilinear map `w = (1 - sT/2)/(1 + sT/2)`, reflecting
every pole across the imaginary axis. The filter ran to **1.2e+240** over 60 ns
with exit code 0 and no diagnostic — the worst of the set, because the number is
absurd and nothing says so. All four `zi_*` forms diverged.

### 2. `laplace_*` leading denominator coefficient

Written as a literal the compiler names the fault exactly. Written as `'{1, d1}`
with `d1` a deck-set parameter it compiled clean, divided by zero building the
state space, and produced six lines of gmin- and source-stepping failure ending in
*"Timestep too small; cause unrecorded"* — a convergence report for a structural
fault the compiler can already describe.

### 3. `@(cross)` and `last_crossing` direction

Dispatched by **sign**, so a deck direction of 7 fired on rising edges and -3 on
falling ones — a plausible count from a spec the compiler calls an outright error
— and NaN made every comparison false, so the event went silently **dead**.

### 4. The integer `$dist_*` family

[Enhancement-505](../../enhancements_doc/Enhancement-505.md) clamped
`rdist_uniform`, `rdist_normal`, `rdist_exponential` and `rdist_poisson`. The
integer siblings sit in the same `match` and did not get them. `hir_ty` validates
the two spellings *together*, so a literal was refused for both and only the deck
route reached the gap:

| call, value from the deck | before | after |
|---|---|---|
| `$dist_exponential(seed, -1)` | deviates in **-10..0** | 0 |
| `$dist_normal(seed, 0, -1)` | the exact **negation** of the correct distribution | 0 |
| `$dist_uniform(seed, 10, 0)` | drew 0..10 from reversed bounds | 10 |

Every sample of `$dist_exponential` was negative, from a distribution whose
support is `[0, inf)`.

### 5. `flicker_noise` — two arguments, one guarded

The power was guarded at compile *and* run time; the **exponent** nowhere. A NaN
exponent made `pwr/f^exp` NaN at every frequency.

Invisible in a way its value-path twin is not: `sqrt(p)` in a `V(o) <+` aborts the
operating point loudly, because a NaN in the matrix cannot converge. A noise
contribution has no such feedback, so it printed `onoise_total = nan` and exited 0.

**Zeroing the power alone does not fix it** — the runtime still evaluates
`0 / f**NaN`, which is NaN. Both arguments are neutralised.

### 6. `noise_table_log` cannot represent a zero

Both variants shared `require_non_negative`, and log-log interpolation takes
`log10` of **both** columns, so zero is exactly the one value that rule admits and
the log form cannot take. `1e-300` works in both columns, which is what makes this
a guard about zero rather than about smallness.

### 7. The noise data **file** form was checked for shape, never for values

A file holding a frequency of **-1** produced output **bit-identical** to the same
file holding **+1**: the sign quietly discarded. That is the defect
[Enhancement-396](../../enhancements_doc/Enhancement-396.md) fixed for an *inline*
table, still live in the form the inline check did not cover.

### The diagnostics name the call the author wrote

`$dist_normal(s, 0, -1)` was reported as `$rdist_normal:` — the shared validation
arm is the right design, only the hardcoded name was wrong — and
`laplace_state_space`, shared by all eight `laplace_*`/`zi_*` forms, gets its
builtin threaded in. Enhancement-396 fixed this same defect for
`noise_table_log`.

## Files

| file | what it holds |
|---|---|
| `zifilt.va` | `zi_nd` whose sampling period comes from the deck |
| `lapfilt.va` | `laplace_nd` whose leading denominator coefficient comes from the deck |
| `crossdir.va`, `lcdir.va` | `@(cross)` and `last_crossing` with a deck direction |
| `flknoise.va` | `flicker_noise` whose exponent can go NaN |
| `distfam.va` | the three integer `$dist_*` draws, selected by a deck parameter |
| `ok_tables.va` | the table forms that must stay legal |
| `bad_*.va` | one refusal case each — these are expected **not** to compile |
| `nt_*.tbl` | noise data files: a negative frequency, a zero frequency, a clean one |

## What is deliberately unchanged

`chi_square`, `t` and `erlang` accept a degenerate dof: measured, 0 and -1 give
bit-identical results in *both* families, so there is no sibling asymmetry to
close. Plain `noise_table` still accepts a zero entry — it interpolates linearly
and zero is a perfectly good frequency there. A run-time value going out of domain
inside a model's own arithmetic remains the model's business, per
[Enhancement-455](../../enhancements_doc/Enhancement-455.md)'s stated convention;
this enhancement guards only the arguments the LRM constrains.
