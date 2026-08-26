# Enhancement-487 — every RF analysis leaves its results in a nutmeg plot

**Files:** `src/spicelib/analysis/dcpss.c`, `src/include/ngspice/cktdefs.h`,
`src/frontend/com_hbosc.c`, `src/frontend/com_hb.c`, `src/frontend/com_hb.h`,
`src/frontend/com_loadpull.c`, `src/frontend/typesdef.c`.

**Suite:** `examples/rfplots_examples/` — 17 checks. `hbosc_examples` and
`plotorder_examples` extended.

## Why

An RF result that is only **printed** is a result you cannot use. It cannot be
plotted, printed again, `wrdata`'d, diffed against a reference, or read by a
script. ngspice's whole post-processing model is built on the plot, not on the
terminal, so a command that prints and stores nothing has produced a number and
thrown it away.

Surveying the eight RF entry points, six already published correctly — `.sp`,
`hb`, `.pss` (two plots), `stb` and `loadpull`. Two did not:

* **`hbosc`** printed its harmonic table and stored nothing, leaving the session
  with **its own startup transient** as the current plot. `hbosc` runs a `tran`
  internally to seed the oscillation, so `setplot` after a successful run showed
  `Current tran1` — the numbers were on screen and nowhere else.
* **`phasenoise`** did exactly the same with its `L(df)` curve.

## The cause: one signature extended, its sibling not

```c
extern int HBanalyze(..., int verbose, struct hbspectrum *out);   /* E-134; E-209 out */
extern int HBOSCanalyze(..., int verbose);                        /* E-140 -- no out */
```

Enhancement-209 added `struct hbspectrum *out` to `HBanalyze` precisely so
`com_hb` could publish the spectrum as nutmeg vectors. `HBOSCanalyze` computes the
**same** `(2K+1)*N` two-sided spectrum in the **same** layout and never got the
parameter, so the driven case published and the autonomous case had nothing to
publish with. This is the same shape Enhancement-486 spent its length on: a
capability one sibling has and the other does not, for no reason beyond which one
was edited.

`HBOSCanalyze` now takes the parameter and hands back the converged spectrum on
the same ownership contract (the caller frees `Vr`/`Vi` after publishing).
`PhaseNoiseAnalyze` gains a matching `struct pnspectrum *out`, collecting the
curve alongside the table it already printed.

## One publisher, not two

`com_hb`'s `hb_publish()` was `static`. The obvious move was to copy it into
`com_hbosc.c`; that is how the two drifted apart in the first place. Instead it is
now `hb_publish_spectrum()`, shared and parameterised by plot name, description and
command name, so the driven and autonomous cases cannot diverge again. `hbosc`
passes one extra flag: it also publishes **`oscfreq`**, because for an autonomous
circuit the oscillation frequency is part of the *answer* rather than an input.

Resulting plots:

| command | plot | vectors |
|---|---|---|
| `hbosc` | `hbosc1 (Harmonic Balance (oscillator))` | `hbfrequency` (scale), one complex vector per node, `oscfreq` |
| `phasenoise` | `phasenoise1 (Oscillator Phase Noise)` | `offsetfreq` (scale), `phasenoise` (dBc/Hz, `SV_DB`), `carrierfreq` |

## The plot NAME, which is where this gets subtle

`ft_plotabbrev()` matches by **substring**:

```c
for (i = 0; i < NUMPLOTTYPES && plotabs[i].p_name; i++)
    if (substring(plotabs[i].p_pattern, buf))
        return (plotabs[i].p_name);
```

`"hbosc"` contains `"hb"`, so with no entry of its own the oscillator spectrum was
abbreviated **`hb1`** — indistinguishable from a driven `hb` run in the same
session. `"phasenoise"` contains `"noise"` and collides with `.noise` identically.
Both now have entries placed *ahead* of the pattern that shadows them, which is the
rule Enhancement-383 wrote into that table: *no EARLIER p_pattern may be a
substring of this plot's name.*

`plotorder_examples` asserts that rule "for every name in the tree that reaches
`plot_alloc()`" — but its `NAMES` table is **hand-maintained**, so it was passing
over these two names vacuously. It now knows about them; mis-ordering the `hbosc`
entry makes it fail with `hbosc->hb (want hbosc)`.

## Types

`loadpull` created every vector `SV_NOTYPE`, including two with a real type
available. `pout_dbm` and `gain_db` are dB quantities and `SV_DB` exists, so they
carry it and `display` names them instead of showing four identical `notype` rows.

`gamma_re`, `gamma_im`, `pae`, `eff` and `stb`'s `loopgain` are **deliberately left
untyped**: they are dimensionless ratios and `enum simulation_types` has no member
for that. Inventing one would be worse than leaving them as they are. Checks [8]
and [11] hold that line from both sides so a later pass does not "fix" it.

## What this does NOT change

`loadpull` leaves its intermediate transients in the session — **61 plots for
`-n 9`, 333 for `-n 21`**; a realistic 41-point sweep would exceed a thousand. That
buries the results plot and holds every waveform in memory. It is a real problem,
but discarding plots a user may want to inspect is a behaviour change on a shipped
command, so it is recorded rather than made silently. `stb`'s phase margin, gain
margin and DC loop gain likewise remain printed-only; they could be stored as
scalar vectors the way `oscfreq` now is.

## Verification

```
python3 examples/rfplots_examples/verify_rfplots.py    # 17/17
python3 examples/hbosc_examples/verify_hbosc.py        # 13/13
python3 examples/plotorder_examples/verify_plotorder.py # 25/25
python3 examples/run_regression.py                     # 401/401
```

`rfplots` scores **7/17** against the pre-fix binary, so **10 of 17 checks
discriminate**; `hbosc` scores 6/13, so 7 discriminate. The controls matter as much
as the fixes: checks [1]–[6] and [8] pass **before and after**, which is the
machine-checked statement that the six analyses which already published were not
disturbed — and check [11] of `hbosc_examples` confirms the driven `hb` still
publishes its own plot through the now-shared publisher.
