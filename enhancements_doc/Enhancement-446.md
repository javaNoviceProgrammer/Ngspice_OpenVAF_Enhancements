# Enhancement-446 — what the netlist wrote, quietly discarded

Six places where something written explicitly in the deck was thrown away or
reinterpreted, with nothing printed. They differ in mechanism but share a shape:
**the value the user typed was not the value the simulator used.**

Three of them come from one root cause worth naming on its own.

## Zero used as the "argument not supplied" sentinel

`vsrcload.c` and `isrcload.c` decided whether an optional waveform argument had
been given by testing `coeffs[n] != 0.0`. A legitimately written **0** is
therefore indistinguishable from an omitted argument.

### An explicit `TD1=0` on an EXP source became the timestep

```
V1 a 0 exp(0 1 0 1m 5m 1m)
```

`TD1 = 0` is the natural way to say "start at t = 0". It was read as *not given*
and replaced by `ckt->CKTstep`, so the whole waveform started one timestep late.
The visible symptom was that every printed row carried the exact analytic value
of the **previous** timepoint, to ten decimal places:

```
      time            ngspice        exact(t)      exact(t_prev)
  9.998000e-04     0.6302026034    0.6320469756    0.6302026034
  1.004800e-03     0.6320469756    0.6338821489    0.6320469756
```

Because the substituted value *is* the timestep, **the answer depended on the
timestep**. On the same deck, changing only `.tran`:

```
.tran  10u 3m    err -3.7e-03
.tran 100u 3m    err -4.0e-02      ~4 % of a 0-to-1 stimulus
```

and writing `TD1` as `1e-30` instead of `0` — a physically meaningless change —
made it exact. It affected the current source identically. SIN, PULSE, PWL and
SFFM were all exact throughout, which is what pinned it to EXP.

The delays are now selected on whether the argument was **supplied**. The time
constants keep a zero guard, because they are divisors and a zero there is not a
value anyone can have meant. Omitted-argument defaults are untouched.

### PULSE `PW=0` and `PER=0` meant different things to V and I sources

The same `!= 0.0` test, applied by `isrcload.c` to `TR`/`TF`/`PW`/`PER` but not
by `vsrcload.c`, made one spec produce two waveforms:

```
                                   @1.5ms   @2.5ms   @3.5ms
V  pulse(0 1  1m 1u 1u 0 4m)      0.00000  0.00000  0.00000   no pulse at all
I  pulse(0 1m 1m 1u 1u 0 4m)      1.00000  1.00000  1.00000   never ends

V  pulse(0 1  1m 1u 1u 1m 0)      1.00000  1.00000  1.00000   repeats
I  pulse(0 1m 1m 1u 1u 1m 0)      1.00000  0.00000  0.00000   single pulse
```

They disagreed in opposite directions on the two cases. Now both read a zero
**pulse width** as the (degenerate) zero-width pulse it asks for, and a zero
**period** as "do not repeat" — a period of zero cannot mean anything else. A
zero rise or fall time still falls back to the timestep, which is the documented
SPICE reading and what the voltage source already did.

Omitted-argument defaults are deliberately left exactly as each source had them,
so no deck that leaves an argument *out* changes meaning.

## A PWL list with an odd token count

A PWL list is time/value pairs, so an odd count leaves one point without a value
— the easiest typo to make in a long list. It was accepted in silence and a
value was invented, differently by each source type:

```
pwl(0 0 1m 1 2m)      on a V source: byte-identical to pwl(0 0 1m 1 2m 0)
                      the stimulus ramps to ZERO at a time never assigned one
pwl(0 0 1m 1m 2m)     on an I source: the stray token is eaten as a VALUE
                      and held for the rest of the run
```

Two different guesses at the same ambiguous input, so it is refused now. The
neighbouring checks already warned about non-increasing and duplicate times;
this was the gap between them.

## A third `.dc` sweep source

`.dc` nests at most two sources. A third specification was neither run nor
refused:

```
.dc V1 0 2 1 V2 0 2 1 V3 0 2 1     ->  9 rows, not 27
```

The nine values are exactly the two-source grid with V3 pinned at its DC value.
Proven by making V3 dominant — R3 = 1 Ω against R1 = R2 = 1 kΩ — and watching
every value stay in the 1e-3 range, tracking only V1 and V2. A user writing a
three-dimensional corner sweep got a two-dimensional result that looked
complete.

Related and fixed with it: surplus `.ac` arguments were dropped in silence. Any
number of them, numeric or not, produced byte-identical output, while `.tran`
and `.dc` both refused what they could not use.

## The sign of a negative base

```
(-2)**3   ->  +8        (-2)**1  ->  +2
```

The default evaluated `pow(fabs(x), y)`. Odd exponents came out wrong and even
ones coincided, so it was silent on half its inputs — and raising to the first
power did not return the base.

Everything else in the simulator disagreed with it:

| | |
|---|---|
| `pwr(-2,3)` | −8 |
| Verilog-A `pow(-2,3)` inside a model | −8 |
| `**` under `set ngbehavior=lt` | −8 |
| `**` under `set ngbehavior=hs` | −8 |
| `**` by default | **+8** |

Only PSPICE mode agreed, and there `|x|^y` is that dialect's documented `PWR`
convention. Enhancement-399's rule applies directly: an expression must not mean
different things depending on whether the netlist or the model computed it.

For a negative base a real-valued answer exists only when the exponent is an
integer, and it is now returned with its proper sign. When the exponent is not
an integer there *is* no real result, and the historical magnitude is kept
rather than returning NaN — a NaN there poisons the Newton Jacobian, which is
the reasoning Enhancement-256 and Enhancement-440 used for `pwr()` and
`pow(0,-1)`. Positive bases are untouched.

## `@c[capacitance]` folded in `m=`

```
C1 nb 0 1u m=2   ->  @c1[capacitance] = 2e-06     the m-multiplied total
R1 nb 0 1k m=2   ->  @r1[resistance]  = 1000      the written value
```

The same accessor idiom meant two different things depending on device type, so
a script reading a deck back got 2 µF for a capacitor declared as 1 µF. The
capacitor now reports what its instance was given, matching the resistor.

The simulation does not move: `capload.c` applies `m` to the matrix stamps
itself, so this was only ever what the query reported. `m=2` still reads
identically to `2u` and to two 1 µF in parallel.

## One reported defect that was not one

An AM source given a fifth argument emits a constant. That is correct: ngspice's
AM takes `AM(VO VMO VMA FM FC TD PHASEM PHASEC)`, so the fifth argument is the
**carrier frequency**, and `am(1 0 100 1k 0)` sets FC = 0 — making
`sin(2π·0·t) = 0` and leaving the offset VO. Checked against the right argument
order, AM matches its analytic waveform to 1e-12. Nothing was changed.

## Verification

**`examples/argdiscard_examples` — 37/37, both solvers.** Every fix narrows what
is accepted, so each is paired with a control that must not move:

* EXP evaluates at the current timepoint for both source types (worst error
  4.4e-14), and the result no longer depends on the step — errors of 4.4e-14,
  2.2e-14, 2.2e-14 at 5 µs, 50 µs and 100 µs. An **omitted** TD1 still defaults
  to the same waveform as before, and a zero TAU still falls back instead of
  dividing by zero.
* PULSE `PW=0` and `PER=0` now read identically for V and I, and a fully
  specified PULSE is unchanged.
* An odd PWL list is refused on both source types; complete lists still run.
* A third `.dc` source is refused on the command and the card, while one- and
  two-source sweeps still produce their full grids; surplus `.ac` arguments are
  refused while a well-formed `.ac` is untouched.
* `(-2)**3`, `(-2)**1`, `(-2)**5`, `(-2)^3` and `pow(-2,3)` carry their sign;
  `(-2)**2` and `(-2)**4` are unchanged; `pwr(-2,3)` is unchanged; five positive
  base cases including fractional and negative exponents are unchanged; a
  negative base with a fractional exponent stays finite; `pow(0,-1)` is still
  refused.
* `@c1[capacitance]` reports the written value, matching `@r1[resistance]`, and
  the AC response of `m=2` is bit-identical to `2u` and to two 1 µF in parallel.

**Full regression 358/358**, both solvers.
