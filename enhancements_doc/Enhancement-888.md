# Enhancement-888: `ordfix` says it runs without truncation control, and a diverging run under it stops — Adams at ordfix=3 ended a stiff network at 3e201 V with exit 0

**Scope:** N6 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice: `spicelib/analysis/dctran.c`: a note at the start of an `ordfix` run, and at each
accepted point of one a node past 1e15 V ends the run.

`examples/transnotes_examples/` (new, shared with [E-885](Enhancement-885.md),
[E-886](Enhancement-886.md) and [E-887](Enhancement-887.md)); `examples/transopts_examples/`
check [5] reads E-882's note by its own text. **ngspice only.**

**Suites:**
- [`transnotes_examples`](../examples/transnotes_examples/): [9] to [11] are this enhancement's,
  11 of 11 per solver. On the E-883 binaries [9] and [10] fail; [11] is a control.
- `transopts` (7 of 7), `corenum`, `integmethod`, `maxordnote` and `dynorder` pass.
- The full sweep: 587 of 587.

## What was wrong

`ordfix` ([Enhancement-181](Enhancement-181.md)) is a verification pin. It fixes the
integration order and accepts every converged step: the step grows to `tmax`, and no truncation
estimate checks it. A run said nothing of this. At an order that is not A-stable, Gear or Adams
at 3 and above, a stiff network grew without bound. One of Family A's networks (seed 1017, nine
nodes, four capacitors, nine resistors) under `method=adams maxord=3 ordfix=3`:
- ended at −3e201 V at its stop time, with exit 0 and no message;
- run ten times longer, reached 5e305 V after 730 529 iterations, still with exit 0.

Over Family A the error reached 5e206 times trap's.

## The change

An `ordfix` run says what it is:

```
Note: ordfix=3 accepts every converged step: the step grows to tmax, and no truncation-error estimate checks it.
Note: order 3 of adams is not A-stable: on a stiff circuit the result can grow without bound at a fixed order. A run whose node passes 1e+15 V stops.
```

The second note is printed only for Gear and Adams pinned at 3 and above.

At each accepted point of an `ordfix` run, a node voltage past 1e15 V, or not a number, ends the
run. This is [E-679](Enhancement-679.md)'s bound for a node held only by gmin:

```
TRAN:  time = 1.26652e-05: the solution is diverging -- node '5' has reached -1.21601e+15 V.
    ordfix=3 accepts every converged step, with no truncation-error control. Run without ordfix, or pin an order that is A-stable (gear or adams at 2 at most).
```

The same network at `gear ordfix=2` runs to the end, at −0.917 V, with the first note only.

`transopts` [5] ([E-882](Enhancement-882.md)) checked that `ordfix=4` at `maxord=4` printed no
`ordfix=` note; it now reads E-882's note by its own text, since this note is printed either way.

## The checks

`transnotes_examples`:
- **[9]** An `ordfix` run says every converged step is accepted with no truncation-error estimate;
  `adams ordfix=3` also says the order is not A-stable, and `gear ordfix=2` does not.
- **[10]** The stiff network at `adams ordfix=3` stops when a node passes 1e15 V.
- **[11]** (control) At `gear ordfix=2` the same network runs to the end.

## Limits

The bound catches a divergence that reaches 1e15 V. A run whose error grows but stays below it,
such as `trbdf2 ordfix=2` 73 % off on one of Family A's networks at a `tmax` too coarse for it,
ends normally: that is what `ordfix` without truncation control does, and the first note says so.
