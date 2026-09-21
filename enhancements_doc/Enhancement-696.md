# Enhancement-696: a `slew` rate or a `transition` time the deck fixed outside its domain is named — a zero rate froze the output for the whole run in silence

**Scope:** F6 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_openvaf-r-cli-integers-transition-and-json.md).
openvaf: `hir_lower/src/expr.rs` (`slew_rate_or_warn`, `transition_time_or_warn`;
`lower_slew`, the delay and the rise/fall times of `lower_transition` routed
through [E-651](Enhancement-651.md)'s `project_or_warn`).
`examples/domainwarn_examples/` (eight checks added, 28 per solver). Handbook
[§2.4](../docs/handbook/02-verilog-a-language.md) rows; the compliance document.
**openvaf only.**

**Suites:** [`domainwarn_examples`](../examples/domainwarn_examples/) 28 of 28
per solver, both solvers (6 of the 8 new checks fail on the E-694 binaries);
`rtdomain`, `deckdomain`, `domainrt`, `constfold`, `hunt17diag`, `opargs`,
`lrmfilters`, `transedge` both solvers, unchanged; the compiler workspace tests
green apart from the three pre-existing sourcegen drift failures; full sweep
531 of 531.

## What was wrong

`slew(cmp, pos, neg)` and `transition(cmp, td, tr, tr)` with every argument a
parameter, the defaults `pos = 1e5`, `neg = −1e5`, `tr = 10u`, `td = 0`, a 0/1
comparator stepping at 1 ms and 3 ms:

| card | `slew` rise | `slew` fall | `transition` rise | `ys` at 2.5 ms | any message |
|---|---|---|---|---|---|
| (defaults) | 10 µs | 10 µs | 10 µs | 1.0 | — |
| `pos=0` | never | never | 10 µs | **0.0** | none |
| `pos=-1e5` | 10 µs | 10 µs | 10 µs | 1.0 | none |
| `neg=1e5` | 10 µs | 10 µs | 10 µs | 1.0 | none |
| `neg=0` | 10 µs | never | 10 µs | **1.00569** | none |
| `tr=-10u` | 10 µs | 10 µs | **0** | 1.0 | none |
| `td=-1m` | 10 µs | 10 µs | 10 µs | 1.0 | none |

A zero rate was a zero clamp: `dy/dt` bounded by `[−0, +0]` cannot move, so
`rate=0` on a card held the `slew` output at its initial value for the entire
transient — 0 while its input was 1 for two milliseconds — without a line in the
log; `neg=0` held it at 1 after the fall and, the clamp now one-sided, let the
rise overshoot by 0.6 %. A wrong sign became its magnitude
([E-61](Enhancement-61.md)'s tolerance), a negative time became 0
([E-504](Enhancement-504.md)'s clamp), a negative delay went to the delay
stage as 0 — each a deliberate projection, each in silence. The compiler
refuses the same values as literals ("slew: the maximum positive rate must be
greater than zero, but is 0", "transition: the rise time must not be negative"),
and `absdelay` names the same negative delay from the card at run time
([E-665](Enhancement-665.md)). E-651 set the rule: a value the *deck* fixed
outside a domain is projected *and named* once per accepted point; these three
operators had not been brought under it.

## What changed

**The rates and the times go through `project_or_warn`.** `slew_rate_or_warn`
gives the loop a rate's magnitude, as before, and adds two projections that
never both fire: a finite nonzero value on the wrong side of zero is named and
its magnitude used ("slew: the maximum negative rate is 100000; LRM 4.5.9
requires it negative -- its magnitude is used as the negative limit"); a zero
or NaN magnitude drops the limit in that direction ("slew: the maximum positive
rate is 0; LRM 4.5.9 requires it positive -- there is no positive slew limit"),
the projection onto the domain with the LRM's own reading of "no rate limit",
which is what `transition` already means by a zero time. The one-rate form says
"the rate" and "there is no slew limit", once. `transition_time_or_warn` keeps
E-504's clamp to zero and names it ("transition: the rise time is -1e-05,
negative (LRM 4.5.8 requires a non-negative time); 0 is used"); zero itself is
legal and passes without a word; the delay gets `absdelay`'s projection with
4.5.8's clause. All of it applies to a value the deck fixed (`is_param_derived`);
a run-time quantity is projected the same way in silence, as E-651 reserves for
values that may pass through anything on their way to the solution. The messages
are deferred and repeat-suppressed like every `runtime_warn`.

## Verification

| check | result |
|---|---|
| `pos=0` | the output follows the input (1 at 2.5 ms, 0 at 3.5 ms; was 0 throughout), "the maximum positive rate is 0 … there is no positive slew limit" |
| `pos=-1e5` | magnitude used, "its magnitude is used" |
| `neg=1e5` | "requires it negative -- its magnitude is used as the negative limit" |
| `neg=0` | the fall happens (was held at 1), "there is no negative slew limit" |
| `rate=0` (one-rate form) | "slew: the rate is 0 … there is no slew limit", one line |
| `tr=-1u td=-1m` | instantaneous from 1 ms, three lines: the rise time, the fall time, the delay, each with LRM 4.5.8 and "0 is used" |
| a run-time rate that goes negative (`1e5*(V(p,n) − 2)`) | projected in silence |
| the defaults | 10 µs ramps, no line |
| the E-694 binaries on the suite | 6 of the 8 new checks fail (the two "no word" checks pass there too) |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- A zero *time* for `transition` stays silent: LRM 4.5.8 makes it the
  directive's time or the negligible non-zero transition, not a mistake.
- A wrong-signed rate is still used as its magnitude (E-61) rather than
  refused; the message is new, the projection is not.
- The messages are run-time: a value the model computes from parameters is
  judged when the model runs, once per accepted point, like every E-651
  projection.
