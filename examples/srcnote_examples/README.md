# Enhancement-513 — a note about the deck, repeated once per analysis

```
python3 verify_srcnote.py
```

12 checks, both linear solvers. 3 of them fail without the fix.

## What was wrong

User-reported, from a 100-sample Monte Carlo run:

```
Note: v1: dc value used for op instead of transient time=0 value.
Note: v1: dc value used for op instead of transient time=0 value.ran   0%)
Note: v1: dc value used for op instead of transient time=0 value.ran   5%)
```

The note describes a **static property of the deck** — the source has both a DC
value and a transient function whose t=0 value differs — but it is emitted from
`VSRCtemp`, which `CKTdoJob` runs once per **analysis**. A loop command repeated
it per point: 100 samples, 100 notes.

Worse, [E-477](../../enhancements_doc/Enhancement-477.md)'s progress line redraws
with `\r`, so each copy landed on the bar and mangled both — that is the
`...value.ran  47%)` above.

## The fix

Latched per instance (`VSRCdcNoteDone`, same for `ISRC`), using the bitfield idiom
already in those structs. Instances are rebuilt on a re-source, so this is "once
per deck load, and again after a `reset`" for free.

| | before | after |
|---|---|---|
| three `tran` in one run | 3 | **1** |
| 100-sample `montecarlo` | 100 | **1** |
| across a `reset` | — | **2** |
| dc == t=0, or no dc | silent | silent |

**Trade**: an `alter` that later creates or removes the mismatch is not
re-announced.

**Avoiding it entirely**: `V1 in 0 dc 1 PULSE(0 1 ...)` asks for 1 V at the
operating point and 0 V at t=0. Drop the `dc 1` and there is nothing to report.
