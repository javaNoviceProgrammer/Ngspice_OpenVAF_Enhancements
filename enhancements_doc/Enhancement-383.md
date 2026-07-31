# Enhancement-383 — four plot-type entries that could never be reached

`ft_plotabbrev()` returns the **first** entry in `plotabs[]` whose pattern is a
**substring** of the plot's name. [E-367](Enhancement-367.md) registered the plot
types this project added and [E-368](Enhancement-368.md) did the same for the
periodic analyses — both by *adding* entries, and both wrote the rule into the
source:

> ORDER MATTERS: a more specific pattern must precede one that is a substring of it.

E-367 then broke that rule with its own entry. It put `envelope` at the **bottom**
of the table, below `{ "op", "op" }`, and `"envel`**`op`**`e"` contains `op`:

```
envelope: 7 envelope samples over 2e-05 s (fc = 1e+06 Hz, ~20 carrier periods)
Current op1	Envelope Following Analysis (Envelope Following)
```

So `setplot envelope1` failed — the one name the user has to go on — and the plot
took a number out of the operating-point sequence. The entry meant to prevent
exactly this had been shipping, unreachable, since E-367.

## The audit, and three more

The fix is one line, but a one-line ordering mistake that shipped inside the
enhancement that was *fixing this table* is not worth fixing alone. Every plot
name in the tree that reaches `plot_alloc()` — the string literals, the names
`qp_emit_plot()` passes, and the descriptive `analName` strings that arrive via
`plot_alloc(run->type)` — was checked against the table. Three more had the same
shape:

| plot | was named | collided with | the entry |
| --- | --- | --- | --- |
| `envelope` | `op1` | operating-point plots | existed, dead |
| `qpac` | `pac1` | `.pac` | never existed |
| `qpxf` | `pxf1` | `.pxf` | never existed |
| `spectrum` | `sp1` | `.sp` (S-parameters) | existed, dead |

A colliding name is worse than an unnamed one, because it looks right. Two
different analyses in one session both answered to the same abbreviation and the
listing gave nothing to tell them apart:

```
   before                         after
   pac2  QPAC Analysis            qpac1  QPAC Analysis
   pac1  PAC Analysis             pac1   PAC Analysis
```

`qpnoise` was already correct — E-368 had placed it ahead of `pnoise` and `noise`
— which is why only three of the four `qp*` plots were wrong.

## The `spectrum` case is a deliberate behaviour change

`{ "spect", "spect" }` was already in the table, unreachable behind `{ "sp", "sp" }`,
and E-367's source comment recorded the result as an unfixable quirk. It is not a
quirk and it is not unfixable — that entry exists for precisely this purpose. It
now precedes the `sp` entries, so a spectrum plot is `spect1` instead of a second
`sp<N>` indistinguishable from an S-parameter plot.

**This changes the plot name two stock ngspice commands produce**, which the three
other fixes do not. It is intentional. Both `spec` and `fft` set `pl_name` to the
literal `"Spectrum"` (`spec.c`, `com_fft.c`), so both were affected and both are
fixed by the same line. Nothing in this repo depended on the old name, and both
halves of the collision — the spectrum commands and `.sp` — are things this project
relies on heavily.

E-345's example asserts that `fft` name directly, and its expectation was updated
**with** this change rather than worked around — the full regression is what
surfaced it, which is the point of running it before claiming the fix is contained.

**Where the entry had to go is the real constraint.** The noise analysis names its
plot `"Noise SPECTral Density Curves - (V^2 or A^2)/Hz"`, which contains `spect`.
One row too high and every ordinary noise plot would have been renamed `spect<N>`,
breaking `setplot noise1` in decks throughout this repo — a naming fix turned into
a naming regression. It sits below `{ "noise", "noise" }` and above the `sp`
entries, and the accept half pins that.

## One candidate deliberately left alone

`vectors.c`'s `findvec_alle()` calls `plot_alloc("digi")`, which has no entry and
falls through to `"unknown"` — apparently the same defect. It is not. The next
line overwrites the result:

```c
struct plot* pl = plot_alloc("digi");
...
pl->pl_typename = copy("dig1");     /* whatever the table returned is discarded */
```

An entry would be dead on arrival. That path also proved **unreachable from every
invocation tried** — `print alle`, `plot alle`, with event nodes confirmed present
via `eprint` — so adding one would have meant shipping an untested entry that
could never fire, which is the exact defect this enhancement removes. It is left
alone, and the reason is recorded in the table so the next audit does not
"fix" it.

(Separately, that hardcoded `"dig1"` bypasses `plot_unique_typename()`, so two
event plots in one session would share a name. Not touched here: different
mechanism, and unreachable by the same measurements.)

## `loadpull` leaving 17 plots behind is not a defect

Raised alongside this: `loadpull -n 5` leaves 17 `tran` plots, one per grid point.
That is the same established behaviour `sweep` has — a 3-point `sweep` in the
accept half below keeps 334 `op` plots — and [E-367](Enhancement-367.md) already
documents why the numbering runs that high. Consistent across the command family
and pre-existing, so it is reported rather than changed.

## What keeps it fixed

Each of the four defects was a single misplaced line with no runtime test that
could catch it, and **two of them were introduced by the enhancements that were
fixing this same table**. A fifth deck would not have helped; the next entry added
in the wrong place would just have gone unnoticed again.

So the invariant is asserted against the table itself: for every plot name in the
tree that reaches `plot_alloc()`, no earlier pattern may be a substring of it. An
entry added in the wrong place now fails that check without anyone having to think
up a deck that would expose it.

## Verification

`examples/plotorder_examples` — 25 checks.

```
   fixed:     25/25
   pre-fix:   12/25
```

The thirteen pre-fix failures are the defect: five wrong names (`envelope`, `qpac`,
`qpxf`, `spec`, `fft`), five `setplot <name>` selections that find nothing, and
three collision pairs — `[pac2 pac1 …]`, `[sp2 … sp1]`, `[op2 … op1]` — that become
distinct after the fix.

The eleven accept checks pass on **both** binaries, which is the point of having
them: this reorders a table every plot in the program goes through. They pin
`op`, `tran`, `ac`, `noise`, `sp`, `.pac`, `.pxf`, `qpnoise`, and E-367's own
`sweep`, `eye` and `hb`. The `noise` one is the load-bearing check described above.

The twenty-fifth is the ordering invariant. It reads the table rather than the
binary, so it passes pre-fix as well — it is not a discriminator, it is what stops
the next entry going in the wrong place.

Regression 306/306 → 307/307.
