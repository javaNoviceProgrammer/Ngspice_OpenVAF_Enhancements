# Enhancement-894: an operating point past a megaampere is reported — a diode an ideal source held 4.2 V forward carried 1e45 A without a word

**Scope:** N2 of the
[nonlinear correctness campaign of 2026-10-15](../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

ngspice: `spicelib/analysis/cktop.c`. `CKTop` names the largest branch current past 1e6 A when an
operating point converges.

`examples/nlnotes_examples/` [7] and [8], shared with [E-892](Enhancement-892.md) and
[E-893](Enhancement-893.md). **ngspice only.**

**Suites:**
- [`nlnotes_examples`](../examples/nlnotes_examples/): [7] and [8] are this enhancement's. On the
  E-888 binaries [7] fails; [8] is a control.
- The full sweep: 591 of 591.

## What was wrong

A source that forward-biases a junction with nothing in series leaves nothing to limit the
junction's current. Newton converges anyway, and the operating point is reported. In one of the
campaign's networks, an ideal source held a diode 4.2 V forward and its branch carried 1.05e45 A.
The random networks of the campaign's Family B reached 4e155 A in 93 of 400. None of it was
reported. The circuit is the user's, but it is not one they meant.

## The change

When an operating point converges, `CKTop` looks for the largest branch current past 1e6 A and
names it:

```
Warning: the operating point carries 1.04705e+45 A in v4#branch, past any junction a circuit models:
    a source that forward-biases a junction with nothing in series leaves nothing to limit its current.
```

A megaampere is past any junction a circuit models. The check is in `CKTop`, so it covers every
analysis that starts from an operating point: `op`, `tran`, `ac`, `noise`, `tf`, `pz` and the
first point of `dc`. It reads branch currents, so Verilog-A devices are covered too: the
Verilog-A diode's `limexp` caps the same case at 9.6e15 A, and it is named.

## The checks

`nlnotes_examples`:
- **[7]** The diode an ideal source forward-biases by 4.2 V: the warning names `v4#branch` and
  its 1e45 A. E-888: nothing.
- **[8]** (control) The same diode behind 1 kΩ: no warning.

Across Family B's 400 networks under KLU, built-in and Verilog-A (800 runs):
- **The 174 runs past a megaampere** warn.
- **The 615 other runs** do not.
- **10 runs that carry 1.8 kA to 80 kA** do not, which is the bound by design.
- **One run that carried 1.6e31 A on E-888** no longer does: since [E-889](Enhancement-889.md)
  it converges to its real solution.

## Limits

Between a kiloampere and a megaampere nothing is said. Power circuits carry kiloamperes, and a
bound low enough to catch every forced junction would warn on them.
