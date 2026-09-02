# `abstolperf_examples` — the cost of the nature-`abstol` path

Pins that LRM 3.6.1's per-node tolerance stamp stays **linear** in circuit size.

```bash
python3 verify_abstolperf.py
```

**4 checks**, both solvers. Against the pre-fix binary the suite scores **3/4** —
the ratio check fails at 3.53x.

## What it guards

[Enhancement-539](../../enhancements_doc/Enhancement-539.md) made a nature's
declared `abstol` reach the convergence test. The first implementation searched
the `CKTnode` list for every (instance, node) pair — O(instances × nodes ×
circuit nodes). It was written believing the path was rare, "only models that
declare custom natures". That is false: `disciplines.vams` declares `abstol` on
the **standard** natures, so it runs for every OSDI node in every deck. On a
17-model photonic deck it cost **4.1 s of a 6.2 s run**, tripling it.

## Why a ratio and not a stopwatch

An absolute time threshold measures the machine, not the algorithm — red on a
slow box, green on a fast one, whichever complexity the code has. Doubling the
circuit separates the two shapes by construction: a linear cost doubles, a
quadratic one quadruples. Measured on this fixture, same deck, same binary, only
the algorithm differing:

| | 8000 → 16000 devices |
|---|---|
| pre-fix (quadratic) | **3.53x** |
| post-fix (linear) | **1.77x – 1.98x** (both solvers) |

`LINEAR_RATIO_MAX = 2.8` sits ~41% clear of the fixed measurement and ~20% below
the broken one. The estimate is the **minimum** of five runs, not the mean — the
run least disturbed by whatever else the machine was doing — and if the baseline
itself exceeds 1.5 s the ratio is reported as un-timeable rather than failed,
since at that point it says more about machine load than about the code.

## Why the other three checks exist

A timing test alone can be passed by **deleting the feature**. So:

- **[2]** asserts the path is genuinely active on this deck — nodes really do
  receive a declared tolerance;
- **[3]** asserts the operating point is still right (a ladder of *n* 1 kΩ
  devices plus a 1 kΩ terminator, driven by 1 V, puts the far node at
  `1/(n+1)`) — a fast wrong answer is not a pass.

The fixture model is deliberately trivial and uses the **standard** `electrical`
discipline, because that is the point: no custom nature is needed to exercise
this path.
