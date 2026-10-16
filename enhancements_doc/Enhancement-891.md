# Enhancement-891: every `setseed N` starts the same stream — a Monte Carlo repeated after `setseed 1` drew other numbers

**Scope:** F3 of the
[nonlinear correctness campaign of 2026-10-15](../docs/bug_hunts/2026-10-15_ngspice-openvaf-r-nonlinear-correctness-campaign.md).

ngspice: `maths/misc/randnumb.c`. `com_sseed` forgets the seed `checkseed` last applied.

`examples/seedrepeat_examples/` is new. **ngspice only.**

**Suites:**
- [`seedrepeat_examples`](../examples/seedrepeat_examples/): 5 of 5 per solver. On the E-888
  binaries [1] and [3] fail.
- `setseed`, `lhs`, `montecarlo`, `mcfastpath`, `seedac` and the other suites that draw random
  numbers pass.
- The full sweep: 591 of 591.

## What was wrong

The control-language draws go through `checkseed()`: `sgauss`, `sunif`, `rnd`, `poisson` and
`exponential`. `checkseed()` reseeds the generator when `rndseed` differs from the seed it last
applied, which it keeps in a static variable. `setseed` reseeds the generator, sets `rndseed`, and
since [E-374](Enhancement-374.md) refills the transient-noise pools, which draws from the
generator. It never told `checkseed()`. So:
- **After the first `setseed 11`:** the next control-language draw found 11 new to it, reseeded,
  and started from the seed's first state.
- **After a second `setseed 11`:** it found 11 already applied and drew from wherever the pool
  refill had left the generator.

The same `setseed 11` therefore gave two streams:

```
setseed 11
let g = sgauss(vector(3))     -> -0.8159, 0.6548, -0.4705
setseed 11
let g2 = sgauss(vector(3))    -> -1.0678, -1.3123, 1.5295
```

Every later `setseed 11` gave the second stream. `sunif`, `rnd`, `poisson` and `exponential` did
the same. A script that runs `setseed 1`, a Monte Carlo loop, then `setseed 1` and the same loop
got 42.28 and then 62.29.

## The change

`setseed` clears the seed `checkseed()` remembers. Every `setseed N` is now followed by the same
reseed the first one was, and draws the first one's stream:
- **The first `setseed` in a session draws what it always drew.**
- **The draws that never pass through `checkseed()` are untouched.** These are `.param` `agauss`
  and its kin, the Monte Carlo parameter draws, and transient noise. They already started from
  the state `setseed` leaves, and gave the same value after every `setseed`.

## The checks

`seedrepeat_examples`:
- **[1]** After a second `setseed 11`, `sgauss`, `sunif`, `rnd`, `poisson` and `exponential` draw
  what they drew after the first. On E-888 all five differ.
- **[2]** The first `setseed 11` still draws −0.81594714, 0.65480624, −0.47049274.
- **[3]** A Monte Carlo loop of `sgauss` draws repeated after `setseed 1` gives 42.2838 both
  times. E-888 gave 42.2838 and 62.2881.
- **[4]** (control) `setseed 11`, `12`, `11` gives the 11 stream again, and 12 another.
- **[5]** (control) `.param` `agauss` after `setseed 5` and `reset` draws 1063.725 both times.

## Limits

`set rndseed=N` is not `setseed`. Setting the variable to the value it already holds is no change
to `checkseed()`, and the draws continue. Use `setseed` to restart a stream.
