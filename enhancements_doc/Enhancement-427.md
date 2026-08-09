# Enhancement-427 — a swept value the device refused, and an event on the last timepoint

Five findings went in. Three were fixed, one was **withdrawn** once it was
measured properly, and one turned out to be a limitation the source code already
documents. The review that sorted them also caught a regression this enhancement
had itself introduced.

## `.dc @inst[param]` applied values the model forbids

With `(*type="instance"*) parameter real r = 1000 from (0:inf)`:

```
dc @n1[r] -2000 -1000 500
    -> THREE data rows at R = -2000, -1500, -1000
       "Parameter r is out of bounds!"  printed four times
       rc = 0
```

Every other route to that parameter refuses the same value: the instance line
aborts, `alter` + a run aborts, the `sweep` command aborts. `.dc @inst[param]`
was the one path that applied it and published the answer.

**The range is not checked where you would look for it.** `OSDIparam` contains
no range check at all — which is why `alter @n1[r]=-5` stores −5 happily and
`print @n1[r]` shows it back. The `from` clause is enforced when the device is
set up again, inside `DEVtemperature` → `OSDItemp` → the model's own
`setup_instance`. `DCTsetInstParam` was `void` and discarded **both** return
values, so the refusal never reached the sweep loop. A fix keyed on `DEVparam`
would have found nothing and changed nothing.

The test is deliberately *"the device refused this value"*, never *"the value
looks wrong"*. A negative resistance is legitimate for a built-in resistor —
`resparam.c` has an explicit branch for one, and E-426 established it — so
`dc @r1[resistance] -2000 -1000 500` still produces its three rows. Nothing in
the fix inspects the value.

The abort exits through the restore path, not by returning where it stands:
leaving the instance holding the rejected value is the E-381/E-382/E-385
state-restoration class of defect.

### The sweep was handing the device one value past `stop`

This is the part that made the first attempt at the fix wrong, and it was found
by an adversarial review of that attempt rather than by testing it.

`.dc` advances the parameter and only *then* tests the stop criterion, so it has
always set one value beyond the end of the sweep — harmless while failures were
ignored. But it means a sweep that legitimately **ends at the edge** of a range
steps one point outside it. With `parameter real k = 0.5 from [0:1]`:

```
dc @n1[k] 0 1 0.25    ->  5 correct rows, and one spurious
                          "Parameter k is out of bounds!"
```

That spurious message predates this enhancement. Refusing refusals without
noticing it would have turned a perfectly valid sweep into a hard error — which
is exactly what the first version of this fix did, measured at rc=1 where it had
been rc=0. The past-stop value is now not applied at all, which also removes the
spurious message. The `TEMP_CODE` arm five lines below has always declined its
own overshoot, with a comment saying why.

## A timer event landing exactly on `tstop` never fired

```
dt = 1e-8, tstop = 1e-6   ->  100 ticks, want 101
```

Independent of the transient step (2e-8, 1e-8, 5e-9, 1e-7 all gave 100), and
`@(final_step)` fires at that same instant — so the timepoint is genuinely
reached and only this comparison rejects it.

`lower_timer` fires on `abstime >= next`, and `next` is built by **repeated
addition**, one `fadd` per fire. After N periods it carries N roundings and sits
a couple of ULP away from the exact `N*period`. When `tstop` is an exact
multiple of the period — the ordinary case — the schedule lands just *past* it.
Reproducing the accumulation in isolation predicts all eight measured cases:

| dt | tstop | accumulated − tstop | last event fires? | measured |
|---|---|---|---|---|
| 1e-8 | 1e-6 | +4.2e-22 | no | 100 |
| 2e-8 | 1e-6 | +6.4e-22 | no | 50 |
| 4e-8 | 1e-6 | +4.2e-22 | no | 25 |
| 3e-8 | 9e-7 | +3.2e-22 | no | 30 |
| 1e-8 | 5e-7 | +3.2e-22 | no | 50 |
| 5e-9 | 1e-6 | −4.4e-21 | yes | 201 ✓ |
| 1e-7 | 1e-6 | 0 | yes | 11 ✓ |
| 1e-9 | 1e-7 | −1.1e-22 | yes | 101 ✓ |

Eight for eight — which is what made it safe to treat as arithmetic rather than
as something structural. That the correct cases outnumbered nothing in
particular is why it looked sporadic.

The comparison now carries a relative tolerance of 1e-12: four orders of
magnitude above the observed drift, and far below any physical timescale (1 ps
early on a 1 s period). It is written as a **multiply**, `next * (1 - 1e-12)`,
rather than `next - eps`, so a one-shot timer that has already fired — where
`next` is `INFINITY` — stays `INFINITY` instead of becoming `INF - INF = NaN`.

This is a compiler change, so a model only gets it when recompiled. That costs
nothing here: **no `.osdi` file is committed anywhere in the repository** — every
suite builds its own from `.va` source at verify time.

## An integer instance parameter could not be swept, and the refusal lied

```
dc @n1[n] 1 4 1     over `parameter integer n`
    -> "Voltage source, current source, or resistor named "@n1[n]"
        is not in the circuit"
```

Every clause of that sentence is false: the device is in the circuit, and the
parameter is settable — `alter @n1[n]=3` and the instance line both set it. The
cause was an explicit `IF_REAL` test folded into the keyword match, so a
wrong-type hit was indistinguishable from a miss and fell through to the
catch-all that ten distinct causes share.

Integer sweeps now work. A **fractional** one is refused:

```
dc @n1[n] 2 4 0.5
    -> "@n1[n] is an integer parameter -- start, stop and step must be
        whole numbers (got 2 4 0.5)"
```

The accumulator has to stay real — a rounded accumulator with a 0.25 step never
advances, the non-advancing-loop class E-362 and E-426 already had to guard in
this very function. Rounding only at the device boundary would then publish
duplicate operating points under an abscissa that disagrees with the value
applied. Refusing is the honest option, and the census found no deck that wants
one.

## Withdrawn: a negative noise PSD is not a discarded sign

The report was that `white_noise(pw)` silently takes `|pw|`, because `pw = -4e-18`
and `pw = +4e-18` both gave `onoise_spectrum = 1e-06`.

They do — and that is correct. `osdinoise.c` takes the sign *out* of the square
root and reapplies it, because Enhancement-42 implements LRM 4.6.4 coherent
summation: same-named noise sources within one instance are perfectly correlated
and sum as **signed amplitudes**, `|Σ sₖ·√|pwrₖ|·Tₖ|²`. A negative PSD is the
encoding for a contribution that enters that sum with a negative sign.

The measurement that settles it — two sources sharing one name:

```
+P and +P   ->  2.0e-06      amplitudes add
+P and -P   ->  0.0          they CANCEL
-P and -P   ->  2.0e-06      squaring is sign-blind
```

and with two *different* names, 1.414e-06 either way, because uncorrelated
sources add in power and the sign genuinely cannot matter. The original probe
used a lone source, where squaring necessarily erases the sign. **No change.**

## Not fixed: `.ic` on a device-internal node

`.ic v(n1#mid)=0.5` is ignored while a built-in `C1 mid 0 1n ic=0.5` works, which
looks like an OSDI gap. It is not one. `INPpas3` resolves `.ic`/`.nodeset` names
before `CKTsetup()`, which is when *every* device — built-in and OSDI alike —
creates its internal nodes. `inppas3.c`'s own header comment has said so all
along:

> All circuit nodes will have been created by now, (except for internal device
> nodes), so any nodeset or IC nodes which have to be created are flagged with a
> warning.

Measured: a built-in diode's `d1#internal` is rejected identically.

The precise statement is about the **direct-naming route**: `.ic`/`.nodeset`
cannot name a device-internal node — `d1#internal`, `m1#drain`, `q1#collector` —
for any device class, because those nodes do not exist yet when the cards are
read. That is uniform.

What is *not* uniform is what each class offers instead, and it differs in both
directions. Built-ins have two indirect routes: the `ic=` instance parameter on
reactive devices, and `.options copynodesets`, which copies a terminal's
`.nodeset` onto the device's internal nodes (honoured by 31 device setups). An
OSDI model has neither, and expresses the same intent with a parameter plus
`@(initial_step)`. Deferring node resolution until after `CKTsetup` would be an
architectural change with no evidence behind it. Documented and pinned instead,
so the shared limitation is not mistaken for a regression later.

## Verification

* **`examples/sweepparam_examples` — 32/32**, with every boundary pinned from
  both sides: the refusals *and* the legitimate sweeps (real, integer, nested,
  single-point, range-edge, restored-afterwards, and the built-in negative
  resistor that must keep working).
* **Full regression 344/344**, both solvers.
* `cargo test --features llvm18` **210/210**, no snapshot moved.
* The suite's table reader is told how many columns to expect — a reader that
  guesses scores a single-row plot and a three-column sweep table as "no
  output", which is how two round-34 leads were briefly mis-scored.

## Found by

Round 34 of the ngspice+OSDI hunt, then an adversarial scope review run before
the code was finalised. Three notes on method.

**The review caught a regression in the fix, not just in the code.** The
past-stop overshoot was invisible from the finding itself; it only appears when
you ask what a *valid* sweep ending at a range edge does. The first version of
this fix broke exactly that case, and the measurement confirming it took one
deck.

**A root cause can be half right in a way that still matters.** "The `.dc` path
discards an error" was correct; "the error comes from `DEVparam`" was not. The
fix checks both returns and works, but a narrower fix keyed on the named
function would have changed nothing at all.

**The withdrawn finding was a correct feature.** A negative noise PSD looked
like a discarded sign for exactly as long as the probe used one source. The
discriminating experiment — two sources sharing a name — was one line away and
turns 1e-06 into a clean 0.0.
