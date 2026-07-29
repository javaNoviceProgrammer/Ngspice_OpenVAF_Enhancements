# Enhancement-368 — the periodic small-signal analyses named their plots wrong

[Enhancement-367](Enhancement-367.md) registered eight missing plot types and
claimed the naming was fixed. It was not. The question *"so you checked all plots
for all analyses?"* had an honest answer of **no**, and checking properly found
seven more — four of them **colliding with an unrelated analysis**, which is
worse than being called `unknown`, because the name looks right.

---

## Why E-367's audit could not see them

E-367 found its eight by grepping for **string literals** passed to
`plot_alloc()`. That grep is blind to the path every standard and RF analysis
actually uses:

```c
struct plot *pl = plot_alloc(run->type);       /* outitf.c */
```

where `run->type` is a **runtime** string handed to `beginPlot(analName)` by each
analysis — mostly `ckt->CKTcurJob->JOBname`, and for the periodic family a
descriptive literal passed at the call site. A literal audit of `plot_alloc()`
arguments proves nothing about any of them.

## What was wrong

`ft_plotabbrev()` returns the **first** entry whose pattern is a substring of the
plot name. Each of these names happens to contain a more general pattern, so the
general entry won:

| analysis name | resolved to | should be |
| --- | --- | --- |
| `PXF Analysis` | **`unknown`** — matched nothing at all | `pxf` |
| `PAC Analysis` | `ac` — collides with ordinary AC | `pac` |
| `PSP Analysis` | `sp` — collides with S-parameters | `psp` |
| `PNoise Analysis` | `noise` — collides with ordinary noise | `pnoise` |
| `qpnoise` | `noise` | `qpnoise` |
| `phasenoise` | `noise` | `phasenoise` |
| `Frequency Domain Periodic Steady State Analysis` | `pss` — collides with PSS | `qpss` |

Each now has its own pattern, placed **before** the general one its name
contains.

### Two ordering traps

`"qpnoise"` contains `"pnoise"`, so the `qpnoise` entry must precede the `pnoise`
entry or every QPNoise plot would be abbreviated `pnoise`. And PSS and QPSS are
distinguished *only* by their leading words — `Time Domain Periodic …` versus
`Frequency Domain Periodic …` — so the QPSS pattern has to carry
`frequency domain periodic` rather than just `periodic`, which both share.

## Verification

`examples/periodicnames_examples` drives each analysis from a deck modelled on the
project's own `.pac`/`.pxf`/`.pnoise` examples and reads back what `setplot`
reports.

```
   fixed:        9/9
   pre-fix bin:  4/9   pac      ac2 pss2 pss1        <- collided with AC
                       pxf      unknown2 pss2 pss1   <- unnamed
                       pnoise   noise2 pss2 pss1     <- collided with noise
                       PSS/QPSS pss1 pss2            <- shared a name
```

The four **regression controls** — ordinary `noise`, `ac`, `tran` and `sp` — pass
on *both* binaries. That is what shows the change is targeted: those names are
relied on elsewhere in this repo (`setplot noise1`, `print noise1.onoise_spectrum`
in `noisecorr`, `noisejw`, `stdaudit`, `tempphys`, `physcheck`), and none of them
moved. No deck that runs `pnoise` selects a plot by name, so nothing depended on
the colliding names either.

A trap worth recording, because it produced a confidently wrong clean run while
this was being investigated: the `setplot` listing has a **blank line immediately
after its header**, so a non-greedy regex reaching to the first blank line
captures nothing. An early harness reported *"no plot"* for all 25 analyses and
summarised it as clean. The parser in the committed example matches to the end of
the listing instead and is commented accordingly.

Regression 292/292.

## Scope, stated honestly

`envelope`, `eye` and `loadpull` call `plot_alloc()` with literals and were
registered by E-367, so they are correct **by construction** — but no deck used
here reaches those code paths, so they are not covered by test. `sens` produced
no plot under every invocation tried, which is consistent with the `sens`
breakage already on the open list (*"Internal Error: node allocation in
DEVsetup() during sensitivity analysis"*) and is not a naming problem.

The `print alle` finding recorded in [E-367](Enhancement-367.md) is unchanged and
still open.
