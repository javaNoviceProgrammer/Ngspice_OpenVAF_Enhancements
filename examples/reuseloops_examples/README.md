# Enhancement-472 — `optimize` keeps the circuit standing between evaluations

```
python3 verify_reuseloops.py
```

17 checks, both linear solvers.

## What was wrong

Enhancement-471 stopped `sweep` rebuilding the circuit for every point, but
asked for it in one place only. `optimize` never re-sources the deck for
`-param` / `-mparam` knobs — and does not for `-dparam` either once
Enhancement-322's fast path arms — yet it still tore down and rebuilt the
circuit on every evaluation, hundreds of times in a fit.

## What makes it safe

Nothing new. `CKTdoJob` still runs `CKTtemp` on a reused analysis, so an OSDI
device's node collapse is re-decided against the snapshot the matrix was built
from and any change forces a genuine rebuild; a built-in device still declines
the reuse for the whole circuit. The reuse is asked for only when a circuit is
standing that this evaluation did not re-source, never after an analysis that
failed, and never under `-center`.

The work was showing this holds when a **search step** moves the collapse rather
than a sweep point. Enhancement-417's `cs_gate` collapses at exactly `rd == 0`,
which an optimizer step will never land on, so `cs_thresh` collapses below a
*threshold* instead — a search range straddling it moves the topology on its
own:

```
optimize: setup reused at 15 of 17 analyses, 1 rebuilt after a node collapse moved
optimize: converged, sum-sq residual = 0 (rms 0) after 17 evaluations
```

identical residual, evaluation count and parameter to the reuse-off run.

## The trajectory question

Reusing the matrix ordering can put a solve on a slightly different Newton path,
and a search reads those values back as a cost — so the evaluation *count* could
in principle change even where the optimum does not.

On a well-posed fit it does not: `lm` and `nm` both return the identical
parameters to 13 digits in the identical evaluation count, and the
finite-difference Jacobian has a wide margin (step `h = 1e-3` in normalised
space against a 5e-12 perturbation).

It can change on a problem already at its noise floor. A degenerate fit — target
unreachable, search pinned at a bound — took 8 evaluations with the reuse and 17
without, reaching the same residual to ten digits, because LM's accept/reject
test was comparing costs that agree to 1e-12 and its damping diverged on noise.

## Why `montecarlo` was not here

> **Enhancement-473 closed the hole below and then gave `montecarlo` the reuse.**

It was built, measured at 1.29×, verified to rebuild correctly when a draw moved
a node collapse (11 rebuilds in 20 samples, the collapse-sensitive yield
tracking draw for draw), and **taken back out**.

The fast path it would rest on can arm while a random `.param` still has a use
it cannot push — a B-source's value is substituted textually at parse time. That
is already a live defect with no reuse involved: such a deck reports 100% or 0%,
*differing between runs of the same deck and seed*, where re-sourcing every
sample reports the correct 45%. The arming check has to be fixed first.

Checks `[15]`/`[16]` originally asserted `montecarlo` never asks for the reuse;
since Enhancement-473 they assert that it does, and that the yield is unchanged,
so the two commands cannot drift apart. `examples/mcarming_examples` covers it
properly.

`highsigma` and `wcd` re-source every sample by design, so there is never a
setup to keep.
