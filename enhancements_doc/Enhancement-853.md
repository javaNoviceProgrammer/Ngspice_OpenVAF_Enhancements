# Enhancement-853: `maxord` says when it has no effect, and trap stays at order 2 — Gear's `maxord=6` was the run of `maxord=2` without a word, and trap with `dynorder` or `ordfix` ran on stale coefficients

**Scope:** F9 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

ngspice: `spicelib/analysis/dctran.c`:
- the note at the start of a transient;
- `order_ceiling`, the highest order `dynorder` and `ordfix` may use, which is 2 under trap.

`examples/maxordnote_examples/` (new). **ngspice only.**

**Suites:**
- [`maxordnote_examples`](../examples/maxordnote_examples/): 6 of 6 per solver. On the E-852
  binaries checks [1], [3], [4] and [5] fail; [2] and [6] are controls.
- The full sweep: 560 of 560.

## What was wrong

| options | points | final value |
|---|---|---|
| `method=gear maxord=2` | 3 390 | 5.711600823213e-3 |
| `method=gear maxord=6` | 3 390 | 5.711600823213e-3 |
| `method=gear maxord=6 dynorder` | 2 027 | 5.711291075241e-3, highest order used 6 |

The stock order control only toggles between orders 1 and 2. [Enhancement-128](Enhancement-128.md)'s
`dynorder` and [Enhancement-181](Enhancement-181.md)'s `ordfix` are the ways above 2. `maxord` was
still accepted up to 6 and range-checked, and nothing said it had no effect. In the campaign's
Family D, Gear 2 to Gear 6 gave identical results to the last digit on every network.

The dig found a worse case under trap, which has no order above 2:
- `dynorder` and `ordfix` both took trap's order up to `maxord`.
- `NIcomCof` refuses order 3 for trap with `E_ORDER`, and `dctran` does not check its return.
  The step then ran on the coefficients of the step before.
- Trap with `dynorder` and `maxord=3` took 19 rejected steps, and its result moved by 2e-6.
- Trap with `ordfix=3` ran past 300 s.
- `maxord` also set the length of `dynorder`'s order hold, so it moved a trap run even when the
  order stayed at 2.

## The change

At the start of a transient, a note says when `maxord` is above 2 and has no effect:

```
Note: maxord=6 has no effect without dynorder: the default order control takes Gear to order 2
at most. `.option dynorder` lets the order rise to 6, and `ordfix=6` pins it.
Note: maxord=3 has no effect with method=trap, whose order is 2 at most.
```

The Gear note is not given with `dynorder` or `ordfix`, which do use `maxord`. Like the TEMP
line, neither note is given during an optimizer's runs.

`order_ceiling` is `maxord`, but 2 under trap. It bounds:
- `dynorder`'s available order;
- `dynorder`'s order hold;
- the order `ordfix` pins, and its test for when that order is reached.

Under trap, every `maxord` and every `ordfix` above 2 now gives the run of 2, bit for bit, so the
trap note is true. `CKTmaxOrder` itself is unchanged: the state vectors are allocated and freed by
it.

The default order control does not change, and Gear's results do not change.

## The checks

`maxordnote_examples`:
- **[1]** Gear `maxord=6`: the note names `maxord=6`, `dynorder` and `ordfix`, and the run is
  `maxord=2`'s.
- **[2]** (control) No note for Gear `maxord=2`, Gear `maxord=6 dynorder`, or Gear `ordfix=5`.
- **[3]** Trap `maxord=3`: the trap note.
- **[4]** Trap with `dynorder`: `maxord=3` and `6` give the run of `maxord=2`, with no rejected
  step.
- **[5]** Trap with `ordfix=3` and `6`: the run of `ordfix=2`, bit for bit.
- **[6]** (control) Gear `maxord=6 dynorder` still rises above order 2.
