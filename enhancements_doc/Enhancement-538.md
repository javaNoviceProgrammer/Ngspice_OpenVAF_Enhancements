# Enhancement-538: `highsigma -scale` becomes scopeable, and so becomes usable

**Scope:** E-537 gave `highsigma` an effective-sample-size guard that says
when its importance weights have collapsed. That was half an answer — it
diagnosed the failure without offering any way out, because nothing could
name a subset of the variability to inflate. This adds
**`-inflate <param>`**, which restricts inflation (and therefore the weight)
to the parameters the failure actually turns on. On the deck E-537 used to
demonstrate the collapse, the reported P(fail) goes from **3.35e-05 to
0.2967 against a true 0.29670536** — from unusable to essentially exact —
and a scoped run reproduces, bit for bit, the answer from a deck that never
had the extra dimensions at all.

**Suites:** [`examples/mcpolicy_examples/`](../examples/mcpolicy_examples/)
grows from 28 to **33 checks** (both solvers). Full sweep ALL OK. **No
openvaf-r change.**

## Why the old behaviour could not be rescued by arithmetic

Scaled-sigma importance sampling draws from an inflated density and corrects
with a likelihood ratio per inflated dimension. The weight is their
**product**, so its variance grows exponentially with the number of
dimensions — and `-scale` inflated *every* gauss statistical parameter in the
circuit, including ones the metric cannot depend on. With `.option osdimc`
that count is not a modelling choice: a `(* type="instance" *)` mismatch
parameter contributes one dimension **per instance**, so an ordinary deck
arrives in the degenerate regime without anyone asking for it. E-537
measured a true P(fail) of 0.297 reported as 2.5e-11 once twenty
statistically-declared bystander devices joined the product.

That is not a bug in the estimator's algebra — it remains unbiased in
expectation — so there is nothing to correct. The only fix is to stop putting
irrelevant dimensions into the product, which requires a way to say which
ones matter. That is what this enhancement adds.

## The spelling

```
highsigma <N> [-scale <lambda>] [-inflate <param>]... [-seed <s>]
          [-analysis <cmd>] -metric <expr> [-max <hi>] [-min <lo>]
```

`-inflate` is repeatable and takes either a bare parameter name — `rr`,
meaning that parameter wherever it occurs — or the project's ordinary
accessor spelling `@owner[param]`, with `*` allowed as the owner
(`@mm[rr]`, `@*[rr]`). Matching is case-insensitive, like every other name
in this surface. With no `-inflate` the behaviour is exactly what it was:
every gauss statistical parameter inflates, byte for byte, so no existing
deck changes.

The announce line says when a run is scoped, so a log never leaves it
ambiguous which mode produced the numbers:

```
highsigma: 2000 samples, scale (sigma inflation) = 3 on the -inflate
           parameters only, analysis 'op', fail if (v(2)) < 0.487
```

## The weight follows the scope exactly

The correctness requirement is that the importance weight counts **exactly**
the dimensions that were inflated — no more, no fewer. A parameter left out
of scope is drawn at its true sigma and therefore carries no likelihood
ratio at all; including one anyway would bias the estimate, and omitting an
inflated one would too. Both the draw applier and the weight walker consult
the same `osdimc_scale_for()` predicate on the same `(owner, parameter)`
pair, so the two cannot disagree about which value was drawn or how it
should be weighted.

That equivalence is what check [30] pins: the same circuit, once with twenty
bystander devices and `-inflate rr`, once without the bystanders at all,
must produce **identical** numbers — measured `0.29665` both ways. The
bystanders now cost exactly nothing, which is the whole point.

## Saying when the scoping did not work

Two ways a scoped run can quietly measure the wrong thing, both now
reported. A spec that matches **no** statistical parameter in the circuit
inflates nothing, so the run samples the nominal spread while looking like a
scoped result — it now says which specs matched nothing and that nothing was
inflated. And a **malformed** spec (`@bad[`, a name with stray brackets) is
refused before the run rather than silently ignored, so a typo cannot
quietly widen the scope back to everything.

The E-537 collapse note now also points at the remedy, and distinguishes the
two cases: an unscoped run is told to name the parameters that matter, while
a run that is *already* scoped and still degenerate is told to narrow
further — the advice differs, and giving the wrong one wastes a long run.

## Measured

A deck whose metric depends on one parameter, with twenty
statistically-declared bystander devices on a disconnected subcircuit that
cannot affect it. True P(fail) = 0.29670536 by quadrature:

| run | reported P(fail) |
|---|---|
| unscoped, 2000 samples | **3.35e-05** (weights collapsed; flagged) |
| `-inflate rr`, 2000 samples | **0.2967** |
| `-inflate rr`, 8000 samples | 0.28944 ± 0.00715 |
| no bystanders at all, 2000 samples | 0.29665 — identical to the scoped run |

Deliberately unchanged: netlist `.param` Gaussians are inflated wholesale as
they always have been, since `-inflate` names OSDI statistical parameters.
A deck that mixes both and has many netlist Gaussians can still degenerate —
the E-537 effective-sample-size guard reports that, and the netlist side has
its own established idiom (write the `.param`s you want varied). The osdimc
side is where dimensions appear without being asked for, which is why it is
the side that needed naming.
