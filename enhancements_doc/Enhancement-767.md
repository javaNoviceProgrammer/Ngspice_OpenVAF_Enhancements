# Enhancement-767: the `-dparam` optimum is the deck's on the fast path too — on a deck large enough to arm the `.param` fast path, `optimize` fitted the value in place and never wrote it into the deck, so the next `reset` put the circuit back at the initial value; the optimum is written once after the search, as the small-deck path always did

**Scope:** F7 of the 2026-09-29 `optimize` hunt. ngspice only: `frontend/com_optimize.c`
(after the final apply, when the fast path was armed, one `alterparam` per `-dparam` knob
with the optimum; no reset, since the circuit already holds it).

**Suites:** `optimize` 73 of 73 (71 of 73 on the E-766 binary: two of the new section's
four checks; 70 of 73 once E-768's message expectation is in the suite); `optmethods`, `reuseloops`, `loopguard`, `opt100`, `paramfastsweep`,
`mcfastpath`, `agestate`, `mcpolicy`, `dcenter` and `pareto` unchanged; the full sweep
535 of 535.

## What was wrong

A `-dparam` knob is a deck `.param`. On a small deck each evaluation runs `alterparam`
and a re-source, so the stored deck carries every trial value and, at the end, the
optimum. On a deck of 80 weighted devices or more (a primitive counts 1, a compiled
instance 30) E-322's fast path is armed instead: the value is pushed in place, no reset,
and the deck is never touched — and the final "leave the circuit at the optimum"
evaluation went the same way. A chain of 100 resistors into `RL out 0 {rr}`,
`.param rr=1k`, `optimize -dparam rr 1k 100 100k -analysis op -target v(out) 0.9`, then
`reset`, `op`, `listing param`:

| deck | fast path | after the fit | after a user `reset` | `listing param` |
|---|---|---|---|---|
| 100 resistors | armed | v(out) = 0.9 | v(out) = **0.5** | `rr = 1000` |
| 2 resistors | not armed | v(out) = 0.9 | v(out) = 0.9 | `rr` = the optimum |

The fit reported `rr = 9000` and published `optimize_rr`; the circuit held it until the
first reset — the user's, or the internal one of any command that re-sources — and then
the design was the one the user started from, in silence. Which of the two rows a user
got depended on a device count they have no reason to know about.

## What changed

After the final apply, when the fast path was armed, the command runs `alterparam
<name>=<optimum>` once per `-dparam` knob. No reset follows: the circuit already holds
the value in place, and the stored deck now agrees with it. The evaluations themselves
are untouched — the 100-resistor fit still takes its 16 — and the small-deck path is
what it was. After the fix the first row reads 0.9, 0.9 and `rr = 9000`.

## Checks

`examples/optimize_examples/verify_optimize.py` section [21], 4 checks: the chain of 100
arms the fast path and converges to `rr = 9000` in 16 evaluations; after the fit the
output is 0.9 and after a user reset it is still 0.9; `listing param` shows 9000, equal
to `optimize_rr`; a two-resistor deck is as before, the optimum in the listing and the
output after a reset equal to the output after the fit.

## Limits

- This is the `-dparam` kind only. A `-param` or `-mparam` optimum is applied with
  `alter`/`altermod` and is still dropped by a user `reset` (the hunt's O3); E-544's
  journal re-applies it for the sampling commands' internal resets.
- NSGA-II returns a front and leaves no single optimum to write.
- The `sweep` command's own fast path is outside this change.
