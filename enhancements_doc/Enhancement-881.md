# Enhancement-881: `xmu` outside [0, 0.5] is refused — xmu=2 turned an answer of 3.757e-7 into −2.53e-7 without a word

**Scope:** D1 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/cktsopt.c`, `CKTsetOpt`: `OPT_XMU` is range-checked. Stock option.

`examples/transopts_examples/` (new, shared with [E-882](Enhancement-882.md) and
[E-883](Enhancement-883.md)). **ngspice only.**

**Suites:**
- [`transopts_examples`](../examples/transopts_examples/): [1] and [2] are this enhancement's,
  7 of 7 per solver. On the E-875 binaries [1] fails; [2] is a control.
- The full sweep: 585 of 585.

## What was wrong

`xmu` weights the trapezoidal rule (0.5) against backward Euler (0). On an RC with an inductor
whose answer at 4 µs is 3.757e-7:
- `.option xmu=-1` gave 2.58e-6;
- `.option xmu=2` gave −2.53e-7.

Neither printed anything. Outside [0, 0.5] the formula is neither method. Every sibling
tolerance has been range-checked since [Enhancement-426](Enhancement-426.md) and
[Enhancement-447](Enhancement-447.md).

## The change

A value outside [0, 0.5] is refused, and the run keeps the value it had:

```
Warning -- Option xmu = 2 must lie in [0, 0.5]; ignored, keeping 0.5
```

Both decks now give 3.757e-7. `xmu=0` and `xmu=0.3` are taken as before.

## The checks

`transopts_examples`:
- **[1]** `xmu=-1` and `xmu=2` are refused with a warning, and the run is the default run.
- **[2]** (control) `xmu=0` and `xmu=0.3` are taken, and move the answer.
