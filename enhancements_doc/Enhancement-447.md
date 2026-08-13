# Enhancement-447 — the guard that covered one spelling of a bad value

Eight places where a degenerate or invalid input was accepted in silence. What
makes them one enhancement rather than eight unrelated fixes is that **in every
case a working guard already sat a few lines away, covering a different spelling
of the same mistake.** The check existed; it just did not cover the value the
user actually wrote.

Two further candidates were investigated and deliberately **not** changed,
because Enhancement-426 had already decided them the other way — see the end.

## A negative `gmin`

`gmin` is the conductance ngspice adds across every nonlinear junction to keep
the Jacobian well conditioned. A negative one is not a smaller conductance — it
is a negative one, and it silently destroyed the operating point:

```
gmin       op v(nb)              tran[5]
1e-12      6.2944078241e-01      4.0212277534e-03    (default)
-1e-6      6.2948182196e-01      4.0252530105e-03
-1         -1.001001001e-03     -4.025253012e-06     diode drop 0.63 V -> -0.001 V
-1e6       -1.000000001e-09     -4.021227763e-12
```

Every row was `rc=0` with nothing printed, and the error grows smoothly with
magnitude so there is no threshold at which it announces itself.

Meanwhile **every sibling in the same file was already guarded** — `reltol=0`,
`abstol=-1`, `vntol=-1`, `chgtol=-1`, `trtol=-1`, `maxord=0`, `maxord=99` and
`temp=-300` all warn, most of them added by Enhancement-426. `gmin` and
`gshunt` were the two holes. Zero stays legal: it means "no gmin" and is a
documented thing to ask for.

## `scale=0`

```
R1 nb 0 1k              v(nb)=0.5        (normal)
R1 nb 0 0               v(nb)=1.0e-15    Warning: "Value of resistor is too small"
R1 nb 0 1k scale=0      v(nb)=0.0        SILENT   <- resistance became zero
R1 nb 0 1k scale=-1     v(nb)=1.0e+09    only "singular matrix", much later
```

A resistance written as `0` was caught and clamped. The same zero reached through
`scale=0` was silent *and* unclamped — the divider read exactly 0.0 — and a
negative scale surfaced only as a downstream "singular matrix". `scale` multiplies
this instance's own resistance, so a non-positive one is not a small resistor: it
is a dead short or an active element. It now falls back to 1 with a warning.

## `trrandom` with a TYPE that is not a distribution

`trrandom(TYPE TS TD PARAM1 PARAM2)` takes 1 = uniform, 2 = gaussian,
3 = exponential, 4 = poisson. Anything else fell through the generator and left
a flat zero for the whole run:

```
TYPE   rms                  diagnostic
   0   0.0000000000e+00     SILENT   <- dead
   1   5.8442111310e-01     (uniform)
   4   1.0564948676e+00     (poisson)
   5   0.0000000000e+00     SILENT   <- dead
   9   0.0000000000e+00     SILENT   <- dead
  -1   0.0000000000e+00     SILENT   <- dead
```

A typo'd type number silently removed the stimulus from the circuit. Refused
now, on both source types.

## An invalid diode `level`

```
level=1    works
level=2    rc=1  "Diode model level 2 is not supported."
level=3    works
level=99   accepted silently, behaved as level 1
level=-1   accepted silently, behaved as level 1
```

A level the model *knows about but does not implement* was refused loudly, while
a level that is not a level at all was accepted without a word. The check was
right there; it simply tested for one specific value instead of a range.

## `cshunt` set from `.control`

`cshunt` works by adding a capacitor to every voltage node, and that happens once
while the circuit is being set up: `eval_opt()` scans the netlist's own `.option`
cards and publishes `cshunt_value`, which `INPpas4()` consumes. Setting it from a
`.control` block stores a value that nothing then reads.

```
(no option)                     v(b)[10] = 9.9900099900e-01
.options cshunt=1e-6   CARD     v(b)[10] = 6.9209970943e-07   works
option  cshunt=1e-6  .control   v(b)[10] = 9.9900099900e-01   ignored, SILENT
```

The card form is bit-identical to writing the capacitor out by hand. Of nineteen
options tested this was the **only** card-only one — `rshunt`, `gmin`, `temp`,
`tnom`, `reltol`, `trtol`, `method`, `noopiter` and `autostop` all work from
either form. The behaviour is kept (the capacitors genuinely cannot be inserted
after setup) and the silence is not; the notice fires only when no card supplied
the value, so a deck that uses the card correctly stays quiet.

## `show` claimed a source had every waveform

All eight transient waveforms share one `VSRCcoeffs` array, and all eight queries
answered from it unconditionally. A source declared only `sin(0 2 3k)` reported
the coefficients `0 / 2 / 3000` eight times — once under `sin` and once under
each of `pulse`, `exp`, `pwl`, `sffm`, `am`, `trnoise` and `trrandom`.

`show` could not be used to find out which waveform a source had, and it
positively asserted seven it did not. A `dc`-only source correctly showed `-` for
all eight, so the code separated "none" from "some" but not *which*.

Only the active waveform answers now. The inactive ones report as empty rather
than as an error, so `show` renders a bare `-` for them — exactly what it already
did for a source with no waveform at all — instead of a column of
`<<NAN, error>>`. The generic `coeffs` query is untouched.

## Three real `.options` keywords called unknown

`savecurrents`, `seed` and `numdgt` were flagged by Enhancement-438's checker.
At least one demonstrably works in the very run that calls it unknown:

```
without savecurrents          @r1[i][5] -> "Error: indexing a scalar (@r1[i])"
.options savecurrents         @r1[i][5] =  5.50805126e-07   (a real waveform)
                              ...and     "Warning: unknown option 'savecurrents'"
```

Enhancement-446 examined this class and downgraded it, because 176 of the 179
`cp_getvar` names are shell variables whose documented setter is `set`. That
reasoning does not cover these three: `savecurrents` has an enhancement of its
own (E-413) and `seed`/`numdgt` are ordinary deck-level `.options` entries. They
are registered the same way E-444 registered `autobus` and E-446 registered the
`.four` controls.

## Two diagnostics that named the wrong thing

`snload`'s help said `"file : Load a snapshot."` while the command has always
required exactly two arguments, so the documented form answered `snload: too few
args.` It sources the netlist and then overlays the saved state, hence both
names; the help says so now.

`pwl(... r=)` on a current source failed with the generic `unknown parameter
(r)`, which reads like a typo. The repeat and delay options are voltage-source
only — ISRC's PWL evaluator is a different, older implementation with no support
for either — so `r` and `td` are declared for the current source purely to refuse
them with a message that names the reason.

**Scope note:** this gives the current source a precise diagnostic, not feature
parity. Porting repeat/delay would mean replacing ISRC's PWL evaluator with the
voltage source's, which is a change to a core load path and belongs in its own
enhancement rather than being folded into a set of guard fixes.

## Three reported defects that were not

**`m=0`.** A negative multiplier is reported and a zero one is not, and zero is
the more drastic — it means zero devices in parallel and removes the instance.
But Enhancement-426 examined exactly this and left it deliberately silent:
`m=0` is the ordinary "disable this instance" idiom, its comment says so at the
site, and its suite asserts the silence. Warning here would fire on decks that
mean precisely what they wrote. Unchanged.

**`@r[resistance]` reporting the nominal value.** The temperature factor and
`scale` are folded into the stored conductance while the nominal resistance is
left untouched, so a `1k tc1=0.001` that behaves as 1073 Ω at 100 °C reports
1000 — and `@c[capacitance]` and `@l[inductance]` both report their effective
value instead, so the three devices genuinely disagree. Enhancement-426 settled
this convention too, and documents `1/@r1[conductance]` as the way to read what
is actually stamped (1200 Ω at 227 °C in its own suite). That is a settled
convention rather than a defect to flip inside a set of guard fixes, so it is
unchanged and both halves are pinned by controls in this suite.

**A misspelled `option method=bogus`** looked like it was silently ignored. It is
not: ngspice prints `setAnalysisParm(options) ci_curOpt: unsupported integration
method`. The message appears at the end of the run with a prefix my probe's
filter did not match, and the pre-Enhancement-447 binary prints it too. Nothing
was changed.

## Verification

**`examples/guardspell_examples` — 54/54, both solvers.** Every fix narrows what
is accepted, so each is paired with a control that must not move — and the two
conventions left alone are pinned as controls too:

* `gmin=-1` and `-1e6` refused *and the operating point unharmed*, while
  `1e-12`, `0` and `1e-3` still work
* `scale=0` and `scale=-1` reported and falling back to 1 rather than shorting,
  while **`m=0` stays silent** (E-426's idiom), a negative multiplier still
  warns, and a plain resistor is silent and unchanged
* trrandom types 1–4 still make noise, 0/5/9/−1 refused on both source types
* diode levels 1 and 3 still work, 99 and −1 refused, level 2 keeps its own
  message
* the cshunt card still works *and stays quiet*, the `.control` form says why,
  and a deck with no cshunt is unaffected
* **`@r1[resistance]` stays the nominal 1000 at 27/100/-50 °C** while
  `1/@r1[conductance]` gives the effective 1000/1073/923 and the circuit uses the
  effective value — E-426's convention, pinned at all three temperatures
* `show` names only the declared waveform for V and I, a `dc`-only source shows
  none, and `@v1[sin]` still returns its coefficients
* the three options are not flagged, a genuinely unknown name still is, and
  `savecurrents` still produces its current waveform
* `snload`'s help names both files; `pwl r=` on a current source says
  voltage-source-only while the voltage source still accepts it and a plain
  current-source pwl is unaffected

**Full regression 359/359**, both solvers — including Enhancement-426's own
suite, which is what caught the two conventions above.
