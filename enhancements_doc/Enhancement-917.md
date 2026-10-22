# Enhancement-917: a non-finite step no longer slips past the compiled MOSFET limiter — a chain of 600 or more compiled BSIM4 stages loaded NaN at its far end on the first Newton step and fell into gmin stepping, 73 to 363 iterations; it converges in 9 at every length now

**Scope:** F3 and F4 of the
[options-and-convergence hunt of 2026-09-26](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md).

ngspice:
- `osdi/osdiload.c` (`osdi_lim_moved`: a raw voltage that is not finite has moved).

**ngspice only.**

**Suites:**
- [`chainconv_examples`](../examples/chainconv_examples/) (new): 9 checks per solver, 6 of which fail
  on E-913.
- `osdilimit` 12, `oprobust` 38, `linesearch` 17, `failacct` 9, `warmstart` and `bsrcconv`:
  unchanged.
- The full sweep: 605 of 605.

## What was wrong

The hunt's chain: N common-source stages of the VA-Models BSIM4 4.8, each output driving the next
gate (`nm{k} in{k+1} in{k} 0 0 mos_va w=1u l=100n`, `r{k} vdd in{k+1} 20k`), `vin` 0.6 V, `op`.

| stages | compiled, KLU | compiled, Sparse | built-in, KLU | built-in, Sparse |
|---:|---:|---:|---:|---:|
| 500 | 9 | 9 | 10 | 10 |
| 600 | 73 | 363 | 47 | 145 |
| 1 000 | 184 | 363 | 47 | 145 |
| 3 000 | 93 | 363 | 66 | 360 |

The page called the jump at 600 a Newton path "that passes close to a point where two paths
part". It is an overflow. The first Newton step through hundreds of inverting stages carries the
linearised gain of every stage before it, so the far nodes come back as ±∞. From about 550 stages
on, both kinds of chain see it: the built-in falls to dynamic gmin stepping too, which the page
had not noticed.

The compiled chain had a second fault on top. Every stage past the overflow printed

```
Warning: nm599 (Verilog-A module bsim4va) loaded a value that is not finite: the residual of d is NaN, at d = inf V, g = -inf V, s = 0 V, b = 0 V. ...
```

and Newton could not continue from it. The E-543 limiter had brought vgs and vds back to a finite
step: −∞ became 0.2 V and +∞ became 4 V, through `DEVfetlim` and `DEVlimvds`. But it then asks
whether the limited value moved at all, as

```
|lim − raw| > reltol · max(|lim|, |raw|) + vntol
```

For an infinite raw value that is ∞ > ∞, which is false. The limiter declared the step unmoved,
kept the raw point "exactly", and the device was evaluated at infinite node voltages. The
built-ins compare nothing; they always use the limited value.

## What changed

A raw voltage that is not finite has moved. The limited voltages are written, and the device is
evaluated at them. The BJT and diode branches share the test.

| stages | compiled, KLU | compiled, Sparse | built-in, KLU |
|---:|---:|---:|---:|
| 600 | 9 | 9 | 47 |
| 1 000 | 9 | 9 | 47 |
| 3 000 | 9 | 9 | 66 |
| 10 000 | 9 | 9 | 66 |

The operating point is the one the gmin stepping reached: 3e-16 V apart on every node sampled at
1 000 and 3 000 stages, with `tnom=25` on the card to hold E-914 aside. It is 3.3 µV from the
built-in chain's.

**F4** does not reproduce at E-913. The page counted 21 rejected timepoints on the 1 000-stage
transient against the built-in's 8, and 53 against 16 at 10 000 stages. Re-measured with
full-swing input pulses, the compiled chain rejects about as many as the built-in:

| deck | compiled: iterations / accepted / rejected | built-in |
|---|---:|---:|
| 1 000 stages, `tran 0.5n 20n` | 1 339 / 218 / 26 | 1 213 / 209 / 33 |
| 10 000 stages, `tran 0.5n 60n` | 4 400 / 695 / 91 | 3 919 / 697 / 85 |
| 100 stages, reltol 1e-6, abstol 1e-15, vntol 1e-9 | 21 783 / 4 420 / 2 005 | 18 550 / 4 243 / 1 860 |

The compiled chain takes 5 to 17 % more Newton iterations per run.

| ruled out as the cause | measured |
|---|---|
| counting `DEVfetlim` moves as non-convergence, which the built-in BSIM4 does only for its junctions | unchanged to the iteration |
| the E-889 device convergence test | switched off: ±3 % |

The rest is the two BSIM4 implementations.

## The checks

`chainconv_examples` (new), under both solvers:

| check | what | E-913 |
|---|---|---|
| [1] | 600, 1 000 and 3 000 stages: the operating point in at most 12 iterations, no gmin stepping, nothing non-finite | 73 / 184 / 93 (KLU), 363 (Sparse) |
| [2] | … the built-in BSIM4 chain's point, to 1e-5 V | 1.6 mV: the compiled BSIM4 ran at its 25 °C (E-914) |
| [3] | (reference) the built-in chain of 1 000 stages goes through gmin stepping | passes |
| [4] | the 1 000-stage transient rejects no more than 1.5× the built-in's points | passes |

## Limits

- **The built-in chain** still overflows on its first step past about 550 stages and recovers by
  gmin stepping. That is upstream behaviour and is not changed here.
- **A NaN** from a device's own arithmetic is still a NaN; only an overflowed node voltage is now
  brought back.
