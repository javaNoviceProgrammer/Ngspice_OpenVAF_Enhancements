# Enhancement-391 — repeated abscissae in a runtime `$table_model`, cubic case

[E-390](Enhancement-390.md) made the runtime array form of `$table_model` agree
with the compile-time forms: it sorts, de-duplicates and honours the cubic
control code. One case was left open and documented — **a repeated abscissa with
cubic interpolation**. This closes it.

## Why it resisted the obvious fix

The compile-time forms de-duplicate by **shortening** the point vector
(`pts.dedup_by`), so the spline is solved over `m` distinct knots. E-390's
runtime de-duplication instead carried the first value forward over each repeat.
That is exactly equivalent for **linear** interpolation — a zero-width segment
whose endpoints are equal contributes nothing — but not for a spline, where the
dead knot still occupies a row of the tridiagonal system and perturbs every
moment in it.

A runtime array cannot shrink. Its length is fixed at compile time; only the
values are unknown.

## What it does instead

The repeats are partitioned to the **end** of the array — a stable 0/1 bubble
network on an "is a repeat" flag that travels with its point — and the trailing
slots take the last distinct knot's coordinates. The live prefix is then exactly
the de-duplicated table, and two things follow that prefix rather than the array:

- the **natural boundary condition** `M = 0` is forced onto the last *live* knot
  and every replica after it, not merely onto the final slot;
- the upper **end tangent** is computed from the last two *live* knots.

A zero-width interval also evaluates to its own knot value rather than a guarded
zero, and is skipped when selecting which segment applies — without that, the
highest qualifying index wins and a dead segment shadows the last live one.

## The mistake worth recording

The end tangent was wrong in the first attempt, and the shape of the failure is
the point. After compaction the last two *slots* are both replicas, so their
spacing is zero; the guarded division then silently turned the extrapolation into
a **clamp**. Every value inside the grid was exact and only the points past its
end were wrong.

Interior agreement is not evidence a spline is right. The bug was visible only
because the check probed `x` beyond the last knot as well as inside it.

## Verification

`examples/vaftabledup_examples` — **20/20 fixed, 12/20 against the E-390
binary**. The eight failures there are precisely the repeated-abscissa cubic
cases; the twelve that already passed are the accept half, so the change lands on
the residual without disturbing what E-390 had already made agree.

Covered: repeats at the start, middle and end; two separate repeats; one abscissa
three times; unsorted *and* repeated; every abscissa equal; a table the body never
fills in (all zeros, so every abscissa repeats); and both clamping and `L`
extrapolation. The accept half re-proves the ordinary strictly-increasing tables,
since compaction runs on every runtime cubic table, and re-proves linear, which
shares the sort.

**Output-preserving: 124/124 corpus `.osdi` byte-identical** against the E-390
compiler. Regression 314/314 → **315/315**.

## Cost

Compaction adds an O(n²) network on top of the existing sort and runs on every
runtime **cubic** table, including those with no repeats. It is bounded by the
same 64-knot cap as the sort, and the linear path is untouched.
