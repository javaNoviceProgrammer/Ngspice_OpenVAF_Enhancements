# Enhancement-472 — `optimize` keeps the circuit standing between evaluations

Enhancement-471 stopped `sweep` tearing the circuit down and rebuilding it for
every point. It asked for that in exactly one place, so every other repeated
analysis carried on rebuilding — including `optimize`, which never re-sources
the deck at all for `-param` / `-mparam` knobs, and does not for `-dparam`
either once Enhancement-322's fast path arms. A fit runs hundreds of
evaluations and each one tore down a circuit it had not touched.

It now asks for the same reuse, on the same terms: only when a circuit is
actually standing (any re-source clears the flag), never after an evaluation
whose analysis failed, and never under `-center`, whose inner Monte Carlo resets
per sample.

Everything that makes it safe is Enhancement-471's, unchanged. `CKTdoJob` still
runs `CKTtemp` on a reused analysis, so an OSDI device's node collapse is
re-decided against the snapshot the matrix was built from and any change forces
a genuine rebuild; a built-in device, whose collapse is decided in `DEVsetup`
and cannot be re-checked, still declines the reuse for the whole circuit. The
work here was showing that this holds when the thing moving the collapse is a
**search step** rather than a sweep point.

## The search crosses the collapse

Enhancement-417's `cs_gate` collapses at exactly `rd == 0` — a value a sweep can
step onto deliberately but an optimizer step will never land on. This
enhancement adds `cs_thresh`, which collapses below a *threshold*, so a search
range straddling it moves the topology on its own.

Started at `rd = 600` with the optimum at `rd → 0` on the far side of the
`rth = 100` threshold:

```
optimize: setup reused at 15 of 17 analyses, 1 rebuilt after a node collapse moved
optimize: converged, sum-sq residual = 0 (rms 0) after 17 evaluations
@cgm[rd] = 0.0000000000e+00
```

against, with the reuse off, the identical residual, the identical 17
evaluations and the identical parameter. The rebuild fired, and nothing moved.

## The trajectory question, answered

An optimizer is not a sweep: reusing the matrix ordering can put a solve on a
slightly different Newton path, and a search reads those values back as a cost.
The concern was that the *number of evaluations* could change even where the
optimum does not.

On a well-posed fit it does not — `lm` and `nm` both returned the identical
parameters to 13 digits in the identical evaluation count. The finite-difference
Jacobian is safe by a wide margin: its step is `h = 1e-3` in normalised space
against a perturbation measured at 5e-12 relative, so the derivative error is
~5e-9.

It **can** change on a problem already at its noise floor. A deliberately
degenerate fit — an unreachable target, the search pinned at a bound — converged
in 8 evaluations with the reuse and 17 without, to the same residual to ten
digits, because Levenberg-Marquardt's accept/reject test was comparing two costs
that agree to 1e-12 and its damping `λ` diverged (0.0014 against 5e+03) on the
strength of noise. The optimum is the same; the path to it is not meaningful in
that regime either way.

## Why `montecarlo` is not in this change

Its fast path (Enhancement-346) also leaves the circuit standing between
samples, and would gain as much. It was implemented, measured at 1.29× on a
1200-instance ladder with the yield unchanged, verified to rebuild correctly
when a random draw moved a node collapse — 11 rebuilds in 20 samples, with the
collapse-sensitive yield tracking draw for draw at exactly 50% — and then
**taken back out**.

The reason is a defect underneath it. The fast path can arm while a random
`.param` still has a use it cannot push: a B-source's value is substituted
textually at parse time, so nothing short of a re-source moves it. The
per-sample teardown and rebuild is what accidentally limits the damage today,
and reusing the setup removes that accident.

That defect is **already live, with no reuse involved**. On the shipped binary,
a deck whose random `.param` feeds both a model parameter and a B-source, with a
spec that depends only on that parameter:

| | yield |
|---|---|
| fast path armed | 100% / 0%, **differing between runs of the same deck and seed** |
| fast path cannot arm (re-sources per sample) | 45% |

45% is the right answer — `rv ~ N(100, 60)` against a `0 ≤ v ≤ 100` spec. So the
Monte Carlo fast path can report a yield that is both wrong and unstable, and it
does so today.

Seeding the fast path's closure from the random `.param` names — which is what
makes the equivalent sweep disarm and take the reset path — was tried and did
**not** disarm the deck, so the real fix lies further in, in what pass 2 will
accept as a capture. That is its own change with its own evidence, and until it
lands there is nothing safe here to build on. `montecarlo` is left exactly as it
was, which the suite asserts so it cannot be switched on by accident.

`highsigma` and `wcd` are a different case and are untouched on purpose: they
re-source every sample by design, each redrawing its `.param`s, so there is
never a setup to keep.

## Verification

`examples/reuseloops_examples/verify_reuseloops.py` — **17/17**, both solvers.

The decisive checks are the ones where ngspice's own report says a rebuild fired
*while* the answer is unchanged, which is what distinguishes a working guard
from a test that never exercised it. Under `set ngdebug`:

```
optimize: setup reused at 15 of 17 analyses, 1 rebuilt after a node collapse moved
```

Also checked: an in-place fit keeps every analysis after the first and finds the
identical parameter; a `-dparam` fit that re-sources each evaluation keeps
nothing; a built-in device declines the reuse for the whole circuit — which
nothing but the report can show, since the answer is identical either way;
`-center` keeps nothing; every off-spelling of `reusesetup` really turns it off;
and `montecarlo` neither asks for the reuse nor changes its answer.

Full regression **386/386**, both solvers. ngspice-only.
