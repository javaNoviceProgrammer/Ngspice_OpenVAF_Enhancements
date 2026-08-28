# Enhancement-501 — aged state across an internal reset, and what the loop commands claim

Round 59 probed the `sweep` / `optimize` / `montecarlo` / `aging` intersection.
The reuse arithmetic was clean again. What was wrong was the *state* one command
left for the next, and — as in Enhancement-499 — the arguments the commands
accept and the numbers they report afterwards.

## 1. The aged device came back fresh

`aging` (Enhancement-157) works by writing an accumulated dose into each device's
`age` parameter with `alter`, then leaving the circuit standing so the analyses
that follow see the degraded part. The idiom the documentation shows is exactly
that:

```
op
aging 3e9
wcd -metric v(d) -max 0.19 -analysis op
```

The dose lives **only in the running circuit** — it has no deck representation,
because it was never in the deck. So every command that re-sources the deck
between evaluations threw it away on the first one and ran the rest of the loop
on a fresh circuit, in silence. That is `wcd`, `highsigma` and `optimize -center`:
the three commands whose entire purpose is to characterise a part were the three
that could not characterise an *aged* one.

| on a 95-year-aged transistor | before | after |
|---|---|---|
| `wcd` worst-case distance | `beta = 8.6646` (the **fresh** answer) | `beta = 1.8065` |
| `highsigma` failure probability | `3.1451e-02` (fresh) | `9.6201e-01` |
| `optimize -center` | centred the **fresh** circuit | centres the aged one |

The `wcd` row is the whole defect in one line: a part that sits 8.7 sigma inside
its limit when new sits 1.8 sigma inside it at end of life, and the command
reported the first number for the second question with nothing in its output to
say which circuit it had measured.

`montecarlo` escaped, but only by accident. Enhancement-346's fast path arms
whenever a random value binds — and prints *"no per-sample reset"* when it does —
so the usual Monte Carlo never re-sourced at all. Its fallback path re-sources
like the others.

### The fix

`aging` already issues its writes as ordinary `alter` commands. It now records
them as it writes them, and the loop commands replay that record after their
internal `reset`. The record is per-run: `aging` clears it before writing, so a
second `aging` call replaces the first rather than stacking on it, which keeps
Enhancement-157's stated property that a dose is an *absolute* target and calling
it twice is idempotent.

A `reset` the **user** types must still mean "the deck as written" — otherwise
there is no way back to a fresh device short of reloading the file. So the
internal resets are marked as internal (`aging_internal_reset`), `com_rset` drops
the record when it is not, and only the marked ones replay.

## 2. `aging` accepted targets it could not age to

`aging`'s own numbers went through a bare `atof()`, and the guard on the result
was `t_target <= 0`. Every comparison with NaN is false, so NaN walked through it:

| command | before | after |
|---|---|---|
| `aging nan` | NaN dose written into every device, *"1 device aged"*, rc = 0 | refused |
| `aging inf` | infinite dose, same | refused |
| `aging abc` | aged to 0 s | refused |
| `aging 1e8 dynamic nan` | accepted as a stop time | refused |
| `aging 1e8 dynamic verbose` | ate `verbose` as the stop time, then reported an unrecognised `agerate` | names `verbose` |

The guards are now written `!(t > 0.0) || !finite(t)`, which is NaN-correct, and
`dynamic`'s stop time is checked to be a number *before* it is consumed — so the
message names the token the user actually typed. This is the shape
Enhancement-497 fixed in `setseed` and `disto`.

## 3. A spec bound that is never violated

A spec limit is only ever used in a comparison, so a NaN limit is not a strict
limit — it is *no limit at all*, indistinguishable from omitting the flag:

```
montecarlo 20 -analysis op -spec v(n) -min 0.495 -max nan
  yield  : 100.000%  (20 / 20 pass)
  95% CI : [83.887%, 100.000%]  (Wilson score)
```

`montecarlo -spec -max/-min`, `wcd -max/-min/-tol/-step`, `highsigma
-max/-min/-scale` and `optimize -spec -max/-min` are now parsed the way the rest
of each command's numbers already were.

A **negative** bound is still accepted. That matters: `com_optimize.c` already
had a strict real-option reader from Enhancement-499, but it refuses negatives —
correct for `-tol`, wrong for a limit — so the spec bounds got their own reader
that requires finiteness and nothing else.

## 4. A yield with nothing behind it

A yield is a statement about variation. A deck with no random parameter — or with
one the metric does not depend on — produced 50 identical samples and reported

```
  yield  : 100.000%  (50 / 50 pass)
  95% CI : [92.865%, 100.000%]  (Wilson score)
```

The interval looks tight precisely because every sample was the same sample.
Enhancement-495 warns when an individual `agauss(...)` call is degenerate; this is
the whole-run version of the same question, and it catches the cases that are not
about any one call — no random parameter at all, or a random parameter the metric
does not depend on. `montecarlo` now tracks the spread of its spec metrics and
says when no sample differed from any other.

## 5. `optimize` published the score but not the answer

`optimize -center` published `dcenter_yield` and `dcenter_cpk` — what it *scored* —
but never the centred knob value, which is the thing the command exists to find.
A `-dparam` is a numparam symbol that never becomes a vector, so the shipped
`dcenter_demo.cir` asked for it as one:

```
  print xc dcenter_yield dcenter_cpk
  Warning from checkvalid: vector xc is not available
```

on every run, since the example shipped. Each knob's final value is now published
as `optimize_<name>`, and the demo prints `optimize_xc = 5.0022` — the design
centre its own comments predict.

## 6. `aging param` aimed somewhere odd

`aging 1e8 param w` wrote **4.095e8** into a MOSFET's *width* — a transistor
409,500 km across — reported *"1 device aged"*, and exited 0. `aging` selects
devices that *have* the named parameter, and a width qualifies.

The name stays the user's to choose, since models spell their aging state
differently, so this warns and proceeds rather than refusing. But when the very
same device also exposes a plain `age`, choosing a different parameter is far
more likely a slip than an intent, and that is the case it reports.

## Files

| file | change |
|---|---|
| `src/frontend/com_aging.c` | record the doses; NaN-correct guards; `dynamic` stop-time check; `param` plausibility warning |
| `src/frontend/com_aging.h` | `aging_replay()`, `aging_forget_writes()`, `aging_internal_reset` |
| `src/frontend/com_sweep.c` | mark internal resets and replay; `sw_boundarg()` for the spec bounds; no-variation NOTE |
| `src/frontend/com_optimize.c` | mark internal resets and replay; `opt_boundopt()` for the spec bounds; publish `optimize_<name>` |
| `src/frontend/runcoms2.c` | a user `reset` drops the dose record |
| `examples/dcenter_examples/dcenter_demo.cir` | `print optimize_xc` instead of `print xc` |

## Verification

`examples/agestate_examples/verify_agestate.py` — 30 checks under both linear
solvers. 19 fail on the shipped binary.
