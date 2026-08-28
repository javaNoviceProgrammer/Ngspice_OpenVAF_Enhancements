# Enhancement-501 — aged state across an internal reset, and what the loop commands claim

```
python3 verify_agestate.py
```

30 checks, both linear solvers. 19 of them fail without the fix.

## What was wrong

Round 59 probed the `sweep` / `optimize` / `montecarlo` / `aging` intersection.

### 1. The aged device came back fresh

`aging` ([Enhancement-157](../../enhancements_doc/Enhancement-157.md)) works by
writing an accumulated dose into each device's `age` parameter with `alter`, then
leaving the circuit standing so the analyses that follow see the degraded part.

That dose lives **only in the running circuit** — it has no deck representation.
So every command that re-sources the deck between evaluations threw it away on
the first one and ran the rest of the loop on a fresh circuit, in silence. That is
`wcd`, `highsigma` and `optimize -center`: the three commands whose entire purpose
is to characterise a part were the three that could not characterise an *aged*
one.

On the deck in this suite, a 95-year dose moves the worst-case distance from
**8.66 sigma to 1.81 sigma** — a part that comfortably meets its limit when new
and barely meets it at end of life. Before the fix `wcd` printed 8.66 for both,
with nothing in the output to say which circuit it had measured.

`montecarlo` escaped, but only by accident:
[Enhancement-346](../../enhancements_doc/Enhancement-346.md)'s fast path arms
whenever a random value binds — and says so, *"no per-sample reset"* — which is
the usual case. Its fallback path re-sources like the others.

The dose is now recorded as it is written and replayed after an internal reset.
A `reset` the **user** types drops the record, because that is what `reset` means;
the internal resets are marked as internal, and only those replay.

### 2. `aging` accepted targets it could not age to

`aging`'s own numbers went through a bare `atof()`, and its guard was `t <= 0`:

| command | before | after |
|---|---|---|
| `aging nan` | NaN dose written into every device, *"1 device aged"*, rc = 0 | refused |
| `aging inf` | infinite dose, same | refused |
| `aging abc` | aged to 0 s | refused |
| `aging 1e8 dynamic verbose` | ate `verbose` as the stop time, then blamed `agerate` | names `verbose` |

Every comparison with NaN is false, so `t <= 0` let NaN straight through. This is
the same shape [Enhancement-497](../../enhancements_doc/Enhancement-497.md) fixed
in `setseed` and `disto`.

### 3. A spec bound that is never violated

A spec limit is only ever used in a comparison, so a NaN limit is not a strict
limit — it is *no limit at all*, indistinguishable from omitting the flag. All
four statistical commands took one without a word:

```
montecarlo 20 -analysis op -spec v(n) -min 0.495 -max nan
  yield  : 100.000%  (20 / 20 pass)
```

`-max`, `-min`, `-tol`, `-step` and `-scale` are now parsed the way the rest of
each command's numbers already were. A **negative** bound is still accepted —
it is a perfectly legal limit, and the check that refuses NaN must not refuse it.

### 4. A yield with nothing behind it

A yield is a statement about variation. A deck with no random parameter — or with
one the metric does not depend on — produced 50 identical samples and reported

```
  yield  : 100.000%  (50 / 50 pass)
  95% CI : [92.865%, 100.000%]  (Wilson score)
```

an interval that looks tight precisely because every sample was the same sample.
`montecarlo` now says when no sample differed from any other.

### 5. `optimize` published the score but not the answer

`optimize -center` published `dcenter_yield` and `dcenter_cpk` — what it *scored* —
but never the centred knob value, which is what the command exists to find. A
`-dparam` is a numparam symbol that never becomes a vector, so the shipped
`dcenter_demo.cir` asked for it with `print xc` and printed

```
Warning from checkvalid: vector xc is not available
```

on every run. Each knob's final value is now published as `optimize_<name>`, and
the demo prints `optimize_xc = 5.0022` — the design centre its own comments
predict.

### 6. `aging param` aimed somewhere odd

`aging 1e8 param w` wrote **4.095e8** into a MOSFET's *width* — a transistor
409,500 km across — reported *"1 device aged"*, and exited 0. The parameter name
stays the user's to choose, since models spell their aging state differently, but
`aging` now says so when the dose is aimed at something other than `age` on a
device that *has* an `age`.
