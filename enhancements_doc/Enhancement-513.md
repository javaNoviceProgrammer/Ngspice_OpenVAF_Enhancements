# Enhancement-513 — a note about the deck, repeated once per analysis

User-reported, from a 100-sample Monte Carlo run:

```
Note: v1: dc value used for op instead of transient time=0 value.
Note: v1: dc value used for op instead of transient time=0 value.ran   0%)
Note: v1: dc value used for op instead of transient time=0 value.ran   5%)
Note: v1: dc value used for op instead of transient time=0 value.ran  13%)
...
```

Two things are wrong there, and the second is the one that matters.

## The note is per-deck; it was emitted per-analysis

It describes a **static property of the deck** — the source carries both a DC
value and a transient function whose t=0 value differs, so the operating point
uses one and the transient starts from the other. But it is emitted from
`VSRCtemp`, which `CKTdoJob` runs **once per analysis**. Any loop command
therefore repeats it per point: 100 samples, 100 notes. Three plain `tran`
commands in one `.control` block printed it three times for the same reason.

## And it corrupted the progress line

[Enhancement-477](Enhancement-477.md)'s loop bar redraws with `\r`. Every copy of
the note landed on that line and mangled both — which is what
`...time=0 value.ran  47%)` is above: the note's tail and the bar's `ran  47%)`
occupying the same row. Two features that are individually correct, producing
corrupt output together.

## The fix

The note is latched per instance — `VSRCdcNoteDone`, and the same for `ISRC` —
following the bitfield idiom already in those structs. Device instances are
rebuilt when the deck is re-sourced, so "once per instance" is exactly "once per
deck load, and again after a `reset`", with no extra bookkeeping and no global
state.

| | before | after |
|---|---|---|
| one `tran` | 1 note | 1 note |
| three `tran` in one run | 3 | **1** |
| 100-sample `montecarlo` | 100 | **1** |
| across a `reset` | — | **2** (said again, correctly) |
| dc == t=0 value | silent | silent |
| no dc value at all | silent | silent |
| current source (`ISRC`) | per analysis | **once** |

## The deliberate trade

If a deck later `alter`s the source so the mismatch appears or disappears, that
change is **not** re-announced. This is an informational note about a deck
property and "once per load" is the normal treatment for those, but it is a trade
rather than a free win, so it is recorded rather than glossed.

## Not a defect, worth knowing

A deck can avoid the note entirely. `V1 in 0 dc 1 PULSE(0 1 ...)` asks for 1 V at
the operating point and 0 V at t=0; that disagreement is exactly what the note
exists to report. Dropping the `dc 1` — `V1 in 0 PULSE(0 1 ...)` — removes it. The
deck that produced the report used `dc 1` deliberately, so that a bare `op`
analysis had a sensible bias.

## Files

| file | change |
|---|---|
| `ngspice-46/src/spicelib/devices/vsrc/vsrcdefs.h` | `VSRCdcNoteDone` flag |
| `ngspice-46/src/spicelib/devices/vsrc/vsrctemp.c` | latch the note |
| `ngspice-46/src/spicelib/devices/isrc/isrcdefs.h` | `ISRCdcNoteDone` flag |
| `ngspice-46/src/spicelib/devices/isrc/isrctemp.c` | latch the note |
| `examples/srcnote_examples/` | new suite |

## Verification

`srcnote_examples` — **12 checks, both linear solvers**, of which **3 fail on the
shipped binaries** (measured: 9/12 pass before the fix, 12/12 after). Checks [7]
and [8] assert that no progress-bar frame carries the note's text and that the bar
still reaches 100%. Full regression **427/427**.
