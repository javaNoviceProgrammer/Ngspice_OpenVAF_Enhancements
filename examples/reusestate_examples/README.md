# Enhancement-498 — per-run state must be re-armed when the setup is reused

```
python3 verify_reusestate.py
```

34 checks, both linear solvers. 17 of them fail without the fix.

## What was wrong

Enhancement-471 lets `sweep`, `optimize` and `montecarlo -warm` keep a circuit
standing between points: `CKTdoJob` skips `CKTunsetup`/`CKTsetup` and re-runs
only `CKTtemp`. That reasoning was about **topology**, and for topology it is
right. What it missed is that two devices keep **transient run state** on the
instance and seed it in `DEVsetup` — so reuse left that state holding the
*previous* run's values.

### 1. A voltage source stopped scheduling breakpoints

`VSRCbreak_time` is how a source walks its own breakpoint schedule: `VSRCaccept`
arms the next edge only when `CKTtime >= VSRCbreak_time`, and `VSRCsetup` seeds
it to `-1.0` so the first accepted point arms the first edge.

Reused, the instance carried the previous run's break time — a value at or past
that run's TSTOP. At `t = 0` of the next run the test was false, and it stayed
false for the whole run. **A PULSE or PWL source scheduled no breakpoints at
all** and the stepper walked straight over every edge:

| | native timepoints | PWL corners landed on exactly |
|---|---|---|
| before | 81 | **0 of 5** |
| after / `reusesetup=0` / standalone | 103 | **5 of 5** |

This was not a rounding difference. E-471's own comment promises that reuse
"changes nothing a user can see except the time … a few ulp". Measured on a
5-point sweep of an RC driven by a narrow PWL pulse, against a standalone run of
the same circuit:

| R | standalone (and `reusesetup=0`) | with reuse | error |
|---|---|---|---|
| 2 k | 0.24081029 | 0.28041273 | **+16 %** |
| 3 k | 0.17120829 | 0.24705662 | **+44 %** |
| 5 k | 0.11137453 | 0.10074403 | −10 % |

`maximum(v(n))` is a grid-**independent** quantity — this is a different answer,
not a different sampling. Other spacings reached 106 %. Because only a sweep's
*first* point still had a correct schedule, **the same resistance returned two
different answers depending on whether the sweep ran up or down**.

`optimize` inherits it through E-472. Fitting R so that `maximum(v(n)) = 0.20`:

| | objective | fitted R | evaluations |
|---|---|---|---|
| `reusesetup=0` | 9.8e-22 | **2501.777336** (hits 0.2000000003) | 67 |
| with reuse | 1.3e-05 | 2156.690117 (gives 0.2264) | 106 |

Both reported **converged**. The fast path returned a parameter 13 % wrong and
took more evaluations doing it.

### 2. OSDI's `last_crossing` cache

`crossing_time[]` is per-run state too. `osdiaccept.c` states the contract: it
"starts at 0.0 … before any crossing has been observed", and is otherwise left
alone so `V(z)` keeps reporting the *last* crossing per the LRM. Only
`OSDIsetup` seeded it, so a reused point began holding the previous point's
crossing — a 100 kHz sine over 40 µs made `last_crossing(V(in),1)` read `3e-05`
at `t = 0` of points 2…5 instead of `0`. A model asking "has it crossed yet?"
was answered with another run's crossing.

Its sibling operator `absdelay` was already right: `osdiload.c` re-seeds
`delay_hist[k][0]` on `is_init_tran`, the first transient call of each run, not
at setup. That is the pattern; `last_crossing` simply did not follow it.

## The fix

Both are re-armed in the device's `DEVtemperature` method. `CKTtemp` runs once
per job on **both** the reuse and the rebuild path — the reuse branch calls it
explicitly, to re-decide OSDI node collapse — and does **not** run on a
`resume`, because `CKTdoJob`'s reset branch is skipped there. So a new analysis
starts clean and a continued run is left alone.

The fast path itself is untouched: the suite asserts that the setup is still
reused at 4 of the 5 points, so the fix cannot be mistaken for quietly turning
E-471 off.

## Scope

Only transients, and only sources that register breakpoints. `SIN`, `EXP`,
dc-only, a PULSE **current** source (`ISRC` recomputes from `CKTtime` and keeps
no schedule), and every non-transient analysis were unaffected — all are
asserted here as controls. A deck containing any device outside E-471's
fixed-topology list never reused in the first place, so classic decks with a
built-in MOSFET were immune; **linear and OSDI decks were exactly the exposed
case**.

Why the existing suites stayed green: `reusesetup_examples` and
`reuseloops_examples` contain **no PULSE or PWL source** between them. The two
examples that do combine `sweep`, `tran` and a PULSE use `-overlay`, whose
resampling damps the error below their tolerances. Both moved when this was
fixed — `sweepwave_demo`'s `vout_2000[10]` went from `2.441425e-02` to the
correct `2.440859e-02`.

## Not fixed here

Found while building this suite, and left open deliberately: under **KLU**,
`sweep -analysis ac` (and `noise`) with the reuse fast path returns `0.0` for
the reused points and **crashes outright in about one run in ten** (SIGTRAP).
It is non-deterministic — byte-identical decks give different answers run to
run — which points at memory rather than arithmetic. It reproduces on the
shipped Jul-18 binary, is absent with `reusesetup=0`, absent under Sparse, and
absent from a manual `alter` + `ac` loop, so it belongs to the reuse path. It
needs its own investigation; the two controls that would touch it are asserted
under Sparse and reported, not quietly tested around.
