# Enhancement-885: the truncation estimate sees the first-order error of `xmu` below 0.5 — xmu=0 ran at trap's points with ten times trap's error

**Scope:** N2 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/cktterr.c`, `terr`: at trap's order 2 with `xmu` other than 0.5, the
first-order term of the local error is estimated as well. Stock behaviour.

`examples/transnotes_examples/` (new, shared with [E-886](Enhancement-886.md),
[E-887](Enhancement-887.md) and [E-888](Enhancement-888.md)). **ngspice only.**

**Suites:**
- [`transnotes_examples`](../examples/transnotes_examples/): [1] to [3] are this enhancement's,
  11 of 11 per solver. On the E-883 binaries [1] and [2] fail; [3] is a control.
- `transopts`, `corenum` and `integmethod` pass.
- The full sweep: 587 of 587.

## What was wrong

`xmu` mixes the trapezoidal rule (0.5) with backward Euler (0). The step is the θ-method

(1 − xmu)·i(n) + xmu·i(n−1) = (q(n) − q(n−1))/h,

whose local error starts at (xmu − ½)·h²·q″. Below 0.5 it is a first-order method. The
truncation estimate kept trap's: its constant on the third divided difference, the h³ term, and a
square root. It sized the steps as if the method were second order, and since the damping lowers
the third difference, it took fewer points than trap.

On an RC with an inductor and a second capacitor, at a 100 ns output step, against a tight
reference:

| xmu | points | rms error (of the range) |
|---|---|---|
| 0.5 (trap) | 177 | 2.76e-3 |
| 0.45 | 165 | 3.70e-3 |
| 0.3 | 153 | 1.13e-2 |
| 0.2 | 150 | 1.71e-2 |
| 0 | 147 | 2.94e-2 |
| `method=gear maxord=1` | 592 | 1.04e-2 |

`xmu=0` is backward Euler, and backward Euler's own control took four times its points. Over the
campaign's Family A, `xmu=0` was 106 times trap's error at the same points (median), and
`xmu=0.2` up to 764 times.

## The change

At trap's order 2 with `xmu` other than 0.5, the step is also limited by the first-order term,
estimated as backward Euler's is: the constant |0.5 − xmu| on the second divided difference, at
the first power. At `xmu=0` that IS backward Euler's estimate. The step is the smaller of the two.
`xmu=0.5` takes the trap path as before.

| xmu | points | rms error |
|---|---|---|
| 0.5 | 177 | 2.76e-3 |
| 0.45 | 196 | 3.59e-3 |
| 0.3 | 313 | 6.86e-3 |
| 0.2 | 426 | 8.13e-3 |
| 0 | 592 | 1.04e-2 — backward Euler's steps |

The error now follows the method's order at the tolerance asked for. A damped trap is still a
first-order method, and costs what one costs.

## The checks

`transnotes_examples`:
- **[1]** `xmu=0` takes backward Euler's steps: the points and the value of `method=gear maxord=1`,
  to rounding. The two are the same method computed two ways, trap's (q(n) − q(n−1))/h and
  Gear's ag0·q(n) + ag1·q(n−1). They agree to the bit on arm64; on x86-64 under Sparse they are
  one point apart in 589, and 4e-12 apart in value.
- **[2]** `xmu=0.2` takes more points than trap, and its error is below 1 % of the range.
- **[3]** (control) `xmu=0.5` is the default run.

## Limits

TR-BDF2's first stage honours `xmu` too ([E-419](Enhancement-419.md)). Its estimate keeps
TR-BDF2's own second-order constant.
