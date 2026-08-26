# Enhancement-488 — `sweep temp` sweeps the global circuit temperature

```
python3 verify_sweeptemp.py
```

20 checks, a few seconds. **10/20** against the pre-fix binary — **10** checks
discriminate.

## What it is

`sweep` resolves a knob as a model parameter, an instance/device parameter, or a
deck `.param`. The **global** circuit temperature is none of those, so a bare
`temp` fell through to the instance/device branch, `alter temp=…` found no such
device, and the sweep ran to completion over a knob that never moved:

```
sweep: temp (instance/device) over 5 points, analysis 'op'
Warning from checkvalid: vector temp is not available or has zero length.
sweep: warning -- at least one knob's original value could not be read
  ->  five identical points
```

A full set of points, `rc = 0`, and a perfectly plottable **flat curve** — which
reads as *"temperature has no effect on this circuit"*, a wrong conclusion rather
than a missing one.

This command has had that exact shape removed twice already: E-431 deleted an
unresolved `-output` drawn as a zero column, and E-435's comment in
`com_sweep.c` describes it for subcircuit-local model names. `temp` was a third
instance — and the one users are most likely to hit, because every *other* route
already worked: `.option temp=`, `set temp=`, `alter @dev[temp]=`, and
`sweep @#*[temp]`.

## The oracle

`dc temp` has swept the global temperature all along, so the suite asserts against
it directly rather than against a table of constants:

```
dc temp    [0.578034682, 0.518134715, 0.469483568, 0.429184549, 0.395256917]
sweep temp [0.578034682, 0.518134715, 0.469483568, 0.429184549, 0.395256917]
```

## Why the first attempt failed

Writing `ckt->CKTtemp` directly — what `.dc temp` does — left the curve flat.
`CKTdoJob` opens with:

```c
ckt->CKTtemp = task->TSKtemp;          /* cktdojob.c */
```

`.dc` gets away with it because its whole sweep runs **inside one** `CKTdoJob`.
`sweep` runs a fresh analysis command per point, so the write was discarded before
the next point was solved. The **task** is what has to move.

The knob is therefore applied with `option temp=`, which is how the frontend
already moves it and is the same shape as the `alter`/`altermod` this file uses
for every other knob. That also means the value passes the guarded `OPT_TEMP`
funnel in `cktsopt.c` instead of going around it, so it inherits E-426's
absolute-zero refusal and E-440's sanity check rather than carrying a second copy.

## Where it deliberately does NOT match `dc temp`

Over a node collapse that **moves with temperature**, `dc temp` is wrong:

| | 0 °C | 20 °C | 40 °C | 60 °C | 80 °C |
|---|---|---|---|---|---|
| static `op` (ground truth) | 0.333333 | 0.333333 | **0.5** | **0.5** | **0.5** |
| `dc temp` | 0.333333 | 0.333333 | **0.0** | **0.0** | **0.0** |
| `sweep temp` | 0.333333 | 0.333333 | **0.5** | **0.5** | **0.5** |

`.dc` holds one setup for its whole sweep and never rebuilds — round-24's finding,
still open. `sweep` runs a fresh analysis per point and E-471's logic rebuilds when
the collapse moves (`setup reused at 3 of 5 points, 1 rebuilt`), so it is right.

Checks [10]–[13] pin all three against the static `op`, and [12] asserts that
`dc temp` **disagrees** — so if someone later "fixes" `sweep temp` to match
`dc temp`, this suite fails rather than quietly accepting the wrong answer.

## Strictly additive

A deck `.param temp` is tested **first** and still wins, so a deck that defines and
references its own `temp` parameter sweeps exactly as before (`kind='.param'`,
curve moves). Only a bare `temp` with no such parameter resolves to the global
temperature.

## Not covered here

`sweep`'s other unresolvable knobs — a bogus name, a missing device, a missing
parameter — still warn and then sweep flat. Only `temp` is fixed, because only
`temp` names something that exists.
