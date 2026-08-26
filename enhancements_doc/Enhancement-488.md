# Enhancement-488 — `sweep temp` sweeps the global circuit temperature

**Files:** `src/frontend/com_sweep.c`.

**Suite:** `examples/sweeptemp_examples/` — 20 checks.

## Why

`sweep` resolves a knob three ways: a `.model` parameter, an instance/device
parameter, or a symbolic deck `.param`. The **global** circuit temperature is none
of those. A bare `temp` therefore fell through to the instance/device branch,
`alter temp=…` found no such device, and the sweep ran to completion over a knob
that never moved:

```
sweep: temp (instance/device) over 5 points, analysis 'op'
Warning from checkvalid: vector temp is not available or has zero length.
sweep: warning -- at least one knob's original value could not be read
  ->  five identical points, rc = 0
```

A full set of points and a perfectly plottable **flat curve**. That reads as
*"temperature has no effect on this circuit"* — a wrong conclusion rather than a
missing one, and the user has no reason to doubt it.

The shape is not new to this file. Enhancement-431 removed an unresolved
`-output` drawn as a zero column, and Enhancement-435's own comment in
`com_sweep.c` describes it for subcircuit-local model names:

> *"an unrecognised name falls through to SW_ALTER, `alter` then reports "no such
> parameter" for a MODEL parameter, and the sweep runs on with a knob that never
> moved — producing a full set of points, rc=0, and a perfectly plottable FLAT
> curve."*

`temp` was a third instance, and the one users are most likely to meet: sweeping
temperature is an ordinary thing to want, and every **other** route already
worked — `.option temp=`, `set temp=`, `alter @dev[temp]=`, `sweep @#*[temp]`.

## The oracle is `dc temp`

`.dc temp` has swept the global temperature all along, so it is the reference. On
a divider whose upper leg carries `tc1=0.01` and whose lower leg does not:

```
dc temp    [0.578034682, 0.518134715, 0.469483568, 0.429184549, 0.395256917]
sweep temp [0.578034682, 0.518134715, 0.469483568, 0.429184549, 0.395256917]
```

The suite asserts against `dc temp` directly rather than against a table of
constants, so it tracks ngspice's own answer instead of a snapshot of it.

## Why the obvious implementation does not work

The first attempt did what `.dc temp` does — write `ckt->CKTtemp`, call
`inp_evaluate_temper()`, call `CKTtemp()`. The curve stayed **flat**.

`CKTdoJob` opens with:

```c
ckt->CKTtemp = task->TSKtemp;                          /* cktdojob.c */
```

`.dc` survives that because its entire sweep runs **inside one** `CKTdoJob`
invocation. `sweep` runs a fresh analysis command per point, so the write was
discarded before the next point was ever solved. The **task** is what has to move,
not the circuit.

The knob is therefore applied by issuing `option temp=`, which is how the frontend
already moves it, and which is the same shape as the `alter` / `altermod` this file
uses for every other knob. A useful consequence: the value passes the guarded
`OPT_TEMP` funnel in `cktsopt.c` rather than going around it, so `sweep temp`
inherits Enhancement-426's absolute-zero refusal and Enhancement-440's sanity
check instead of needing a second copy of either.

## Where this deliberately does NOT match `dc temp`

Over a node collapse that **moves with temperature** — an OSDI model that
collapses `d` onto `di` once `$temperature` passes a threshold — `dc temp` is
wrong:

| | 0 °C | 20 °C | 40 °C | 60 °C | 80 °C |
|---|---|---|---|---|---|
| static `op` at each temperature | 0.333333 | 0.333333 | **0.5** | **0.5** | **0.5** |
| `dc temp` | 0.333333 | 0.333333 | **0.0** | **0.0** | **0.0** |
| `sweep temp` | 0.333333 | 0.333333 | **0.5** | **0.5** | **0.5** |

`0.0` is not a physical value for that circuit at any temperature. `.dc` holds one
setup for its whole sweep and never rebuilds when the topology moves — round-24's
finding, still open and **not** addressed here. `sweep` runs a fresh analysis per
point and Enhancement-471's reuse logic rebuilds exactly where the collapse moves
(`setup reused at 3 of 5 points, 1 rebuilt`), so it gets the right answer.

Matching `dc temp` here would have meant copying a defect. Checks [10]–[13] pin
all three series against the static `op`, and [12] asserts that `dc temp`
**disagrees** — so a later pass that "fixes" `sweep temp` into agreement fails the
suite rather than quietly adopting the wrong answer.

## Strictly additive

A deck `.param temp` is tested **first** and still wins. A deck carrying
`.param temp=27` and `R1 in a {temp*40}` sweeps that parameter exactly as before —
reported as `.param`, curve moving. Only a bare `temp` with no such parameter
resolves to the global temperature, so no existing deck changes behaviour.

## Also matched to the oracle

* An unphysical range is refused **up front** and sweeps nothing, as `.dc temp`
  refuses it. Left to the `OPT_TEMP` funnel alone the bad points would be ignored
  one at a time, which is worse than it sounds: the rejected value is dropped but
  the axis still carries it, so `sweep temp lin 3 -600 100` produced a row
  *labelled* −600 °C holding the answer for whatever temperature was in force.
  −25 °C is ordinary and still sweeps.
* The axis carries `SV_TEMP`, the type `dc temp` already gives its own scale, so
  `plot` labels the two alike. Every other sweep axis stays `SV_NOTYPE` — an
  arbitrary knob value has no matching `simulation_types` member and inventing one
  would be worse than leaving it untyped.

## What is NOT fixed

`sweep`'s other unresolvable knobs — a bogus name, a missing device, a missing
parameter — still warn and then sweep flat. Only `temp` is addressed, because only
`temp` names something that exists and has a defined meaning. Making the general
case refuse is a wider behaviour change and is left alone.

## Verification

```
python3 examples/sweeptemp_examples/verify_sweeptemp.py   # 20/20
python3 examples/run_regression.py                        # 402/402
```

**10/20** against the pre-fix binary, so **10 of 20 checks discriminate**. The
controls matter as much: [1] asserts the oracle itself moves (a temperature sweep
that changed nothing would make every comparison vacuous), [14]–[15] hold the
`.param` precedence, and [17]–[18] require the two-knob curves to *move* rather
than merely agree — a flat curve is "identical with reuse on and off" too, and that
is exactly what the broken build produced.
