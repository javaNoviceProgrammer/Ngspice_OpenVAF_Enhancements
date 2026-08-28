# Enhancement-498 — per-run state left stale by the setup-reuse fast path

`sweep`, `optimize` and `montecarlo -warm` keep a circuit standing between
points (Enhancements 471, 472, 473): `CKTdoJob` skips `CKTunsetup`/`CKTsetup`
and re-runs only `CKTtemp`. Two devices keep **transient run state** on the
instance and seed it in `DEVsetup`, so reuse left that state holding the
previous run's values. One of them silently changed transient answers by up to
106 % and made `optimize` return a wrong fit while reporting *converged*.

## Why

E-471 reasoned carefully about **topology** — node collapse is re-decided on
every `CKTtemp`, and reuse is offered only to device types whose topology is
fixed. That reasoning is sound and is not what broke. What was never asked is a
different question: *which state does `DEVsetup` initialise that is not
topology at all?*

For almost every device the answer is "none". For two of them it is a value the
transient run walks forward and expects to find reset at `t = 0`.

## 1. A voltage source stopped scheduling breakpoints entirely

`VSRCbreak_time` is the source's own breakpoint cursor. `VSRCaccept` arms the
next edge only when `CKTtime >= VSRCbreak_time`, and `vsrcset.c` seeds it:

```c
here->VSRCbreak_time = -1.0;        // To set initial breakpoint
```

so the first accepted point of a run arms the first edge. Under reuse that line
never ran again, and the instance carried the previous run's break time — a
value at or past that run's TSTOP. At `t = 0` of the next run the test was
false, and it stayed false for the whole run.

The consequence is not a perturbation. **The source scheduled no breakpoints at
all**, and the stepper walked straight over every edge of a PULSE or PWL
waveform:

| | native timepoints | PWL corners landed on exactly |
|---|---|---|
| before | 81 | **0 of 5** |
| after (= `reusesetup=0` = standalone) | 103 | **5 of 5** |

Measured against a standalone run of the identical circuit, sweeping R across an
RC driven by a narrow PWL pulse:

| R | standalone | with reuse | error |
|---|---|---|---|
| 2 k | 0.24081029 | 0.28041273 | **+16 %** |
| 3 k | 0.17120829 | 0.24705662 | **+44 %** |
| 5 k | 0.11137453 | 0.10074403 | −10 % |

`maximum(v(n))` is grid-**independent**: this is a different answer, not a
different sampling. Other spacings reached 106 %. A 0.3 ppm change of the swept
value was enough — the error does not scale with the parameter step, because
the schedule is either armed or it is not.

Because only a sweep's *first* point still had a correct schedule, the same
resistance returned two different answers depending on the direction of travel:
`R = 1000` gave 0.40217511 sweeping up (correct, it was point 0) and 0.33963131
sweeping down.

`optimize` inherits it through E-472. Fitting R so that `maximum(v(n)) = 0.20`:

| | objective | fitted R | evaluations |
|---|---|---|---|
| `reusesetup=0` | 9.8e-22 | **2501.777336** → 0.2000000003 | 67 |
| with reuse | 1.3e-05 | 2156.690117 → 0.2264 | 106 |

Both printed **converged**. The fast path returned a parameter 13 % wrong and
needed 58 % more evaluations to get there, because a noisy objective misleads
Nelder-Mead.

### What this contradicts

E-471's own escape-hatch comment, `com_sweep.c`:

> Reuse changes nothing a user can see except the time, but it does reuse the
> LU ordering across points … so a solve can land on a different Newton path and
> move a value by a few ulp.

Both halves are wrong for this defect. The magnitude is fourteen orders of
magnitude past "a few ulp", and the stated cause is not the cause: KLU and
Sparse — two entirely different orderings and factorisations — produce
bit-identical deviations. Per the rule that a comment is what separates a
deliberate decision from a defect (Enhancement-475), this was a defect.

## 2. OSDI's `last_crossing` cache

`crossing_time[]` is per-run state as well, and `osdiaccept.c` states its
contract in full: the cache is left unchanged when no new qualifying crossing is
found, so `V(z)` keeps reporting the time of the **last** crossing per the LRM,
and it "starts at 0.0 (set at slot allocation in OSDIsetup) before any crossing
has been observed".

Only `OSDIsetup` seeded it. Under reuse a swept point began holding the previous
point's crossing: a 100 kHz sine over 40 µs made `last_crossing(V(in),1)` read
`3e-05` at `t = 0` of points 2…5 instead of `0`. A model asking "has it crossed
yet?" was answered with a different run's crossing.

Its sibling analog operator was already correct. `absdelay` re-seeds
`delay_hist[k][0]` in `osdiload.c` on `is_init_tran` — the first transient call
of each run — not at setup, and is therefore immune. That is the pattern
`last_crossing` should have followed.

## The fix

Both values are re-armed in the device's `DEVtemperature` method — `VSRCtemp`
and `OSDItemp`. `CKTtemp` is the right hook for exactly the reason the reuse
branch already calls it:

* it runs once per job on **both** paths, reuse and rebuild, so neither path
  can drift from the other;
* it does **not** run on a `resume`, because `CKTdoJob`'s `if (reset)` block is
  skipped there — a continued transient keeps the schedule it was paused with,
  which is what a resume must do.

Setup keeps its own seed; it is now the allocation-time default rather than the
only place the value is ever set.

## What must not move

The fast path is untouched. A fix that simply stopped reusing would make every
correctness check pass while throwing away E-471, so the suite asserts ngspice's
own tally — the setup is still reused at 4 of the 5 points, 0 rebuilt — and that
`reusesetup=0` still reports 0 of 5. The boundary of the change is asserted as
controls: sources that register no breakpoints (`SIN`, `EXP`, dc-only), a PULSE
**current** source (`ISRC` recomputes its edges from `CKTtime` and keeps no
cursor), and `op`/`ac`/`tf`/`noise` are all bit-identical before and after.

## Why the existing suites did not catch it

`reusesetup_examples` and `reuseloops_examples` contain **no PULSE or PWL
source** between them — they exercise `tran 10u 1m`, but only with sources that
were provably unaffected. The two shipped examples that do combine `sweep`,
`tran` and a PULSE both use `-overlay`, whose resampling onto a common grid
damps the error below their tolerances. Both moved when this was fixed:
`sweepwave_demo`'s `vout_2000[10]` went from `2.441425e-02` to the correct
`2.440859e-02`, and `nestedsweep_demo` from `8.646622e-01` to `8.646615e-01`.

## Found here, deliberately not fixed here

Under **KLU**, `sweep -analysis ac` (and `noise`) with the reuse fast path
returns `0.0` for the reused points, and crashes outright in roughly one run in
ten (SIGTRAP). It is non-deterministic: byte-identical decks give different
answers run to run, which points at memory rather than arithmetic. It
reproduces on the shipped Jul-18 binary, is absent with `reusesetup=0`, absent
under Sparse, and absent from a manual `alter` + `ac` loop, so it belongs to the
reuse path — but it is a different defect in a different layer and needs its own
investigation. It is reported in the suite and here rather than quietly tested
around; the two controls that would touch it are asserted under Sparse.

## Verification

`examples/reusestate_examples/` — 34 checks under both linear solvers, **17 of
which fail without the fix**. The strongest assertion available is used
throughout: a swept point must equal a standalone run of the same circuit,
bit for bit.
