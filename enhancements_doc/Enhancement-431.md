# Enhancement-431 — a `sweep -output` that never resolved was plotted as zero

```
sweep @rs[resistance] 1k 3k 1k -output v(nosuch)
    ->  a full column of 0.0, and a plottable flat line at zero
```

Behind nothing louder than a `checkvalid` warning, easy to lose in a long run —
and the result is not an obvious failure but a clean, believable curve.

## The cause was already written down

`sw_eval_expr()` is documented as returning *"its LAST value … or 0 on failure"*,
and the file already knew what that costs. Enhancement-385 hit exactly this for
the knob-restore path and said so in a comment that is still there:

> `sw_eval_expr()` cannot be used for this: it returns 0.0 on failure, which is
> indistinguishable from a knob that is legitimately zero, and restoring a
> spurious 0 would be worse than not restoring at all.

E-385 solved it for its own case by adding an `*ok` out-param (`sw_read_knob`).
The `-output` path has the same problem and a worse symptom, because the zero is
not used once and discarded — it is recorded, named, and drawn.

So the fix is the same shape: `sw_eval_expr_ok()` reports whether the expression
*resolved*, independently of what it evaluated to. The five other callers —
`optimize` and the metric evaluators — keep the old signature through a thin
wrapper and are untouched.

## Reported per output, not per sweep

Each `-output` carries a tally of the points at which it failed:

* **failed everywhere** — it is a typo, not data. Named in an error, and the
  curve is **not** emitted:

  ```
  Error: sweep -output v(nosuch) never resolved -- no such vector;
         that curve is not recorded.
  ```

* **failed at some points** — a warning with the count, and the curve is still
  emitted, because the points that did resolve are real and dropping them would
  lose data.

* **resolved to zero** — recorded, unremarked. This is the distinction the whole
  change exists for, and it is pinned in the suite with `v(d)-v(d)`, an
  expression that resolves perfectly and is exactly 0.0.

A bad output does not cost the good ones: `-output v(d) -output v(nosuch)
-output i(v1)` records `v(d)` and `i(v1)`, and reports the middle one.

## Verification

* **`examples/sweepguard_examples` — 9/9 new checks.** The refusal, the surviving
  siblings, and both directions of the distinction — a name that does not resolve
  is dropped, a value that is legitimately zero is kept.
* **Full regression 345/345**, both solvers.

## Found by

Answering two questions — *"does `sweep` work with hierarchical parameters, and
does `-output` work with internal nodes?"* Both answers are yes, and checking
them properly meant comparing the recorded numbers against the analytic divider
rather than accepting that a vector appeared. Feeding a deliberately wrong name
to confirm the probe could fail is what produced the column of zeros.

**Noted, not fixed:** `-output` takes only its FIRST token, so
`-output v(a) v(b)` silently records `v(a)` alone; the working syntax is one
`-output` per expression. That is pre-existing — identical before and after this
change — and the usage line's `[-output <expr> ...]` implies otherwise. It wants
its own decision about which of the two is right, so it is recorded here rather
than quietly changed.
