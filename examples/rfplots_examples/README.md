# Enhancement-487 — every RF analysis leaves its results in a nutmeg plot

```
python3 verify_rfplots.py
```

17 checks, a few seconds. **7/17** against the pre-fix binary — **10** checks
discriminate.

## What it is

An RF result that is only **printed** is a result you cannot use. It cannot be
plotted, printed again, `wrdata`'d, compared against a reference, or read by a
script — ngspice's entire post-processing model is built on the plot, not on the
terminal.

Six of the eight RF entry points already published. Two did not:

| analysis | before | after |
|---|---|---|
| `.sp` | `sp1 (SP Analysis)` | unchanged |
| `hb` | `hb1 (Harmonic Balance)` | unchanged |
| `.pss` | `pss1` + `qpss1` | unchanged |
| `stb` | `stb1 (Loop gain)` | unchanged |
| `loadpull` | `loadpull1 (Load-pull)` | `pout_dbm`/`gain_db` now typed |
| **`hbosc`** | **nothing** — current plot was its own startup transient | `hbosc1 (Harmonic Balance (oscillator))` |
| **`phasenoise`** | **nothing** — same | `phasenoise1 (Oscillator Phase Noise)` |

## Why it happened

A plain asymmetry. Enhancement-209 gave `HBanalyze` a `struct hbspectrum *out` so
`com_hb` could publish its spectrum as vectors:

```c
extern int HBanalyze(..., int verbose, struct hbspectrum *out);   /* E-134; E-209 out */
extern int HBOSCanalyze(..., int verbose);                        /* E-140 -- no out */
```

`HBOSCanalyze` computes the *same* `(2K+1)*N` two-sided spectrum in the *same*
layout. One signature was extended and its sibling was not, so the driven case
published and the autonomous case printed into the void.

The fix gives `HBOSCanalyze` that parameter and routes both commands through **one
shared publisher** rather than letting `com_hbosc` grow a second copy — the two
had already drifted once.

## The part that is easy to get wrong

`ft_plotabbrev()` matches by **substring**. `"hbosc"` contains `"hb"`, so without
its own entry *ahead* of the `hb` pattern the oscillator spectrum comes out named
`hb1` — indistinguishable from a driven run in the same session. `"phasenoise"`
contains `"noise"` and collides with `.noise` the same way. Both entries are placed
ahead of their shadowing pattern, and `plotorder_examples` — which asserts *"no
EARLIER p_pattern may be a substring of this plot's name"* for every name in the
tree — now knows about them; its `NAMES` table is hand-maintained, so before this
it was passing over the two names vacuously.

Checks [16] and [17] run each shadowing pair **in one session**, which is the only
arrangement where the collision is visible at all.

## What is deliberately left untyped

`gamma_re`, `gamma_im`, `pae`, `eff` and `stb`'s `loopgain` stay `SV_NOTYPE`. They
are dimensionless ratios and `enum simulation_types` has no member for that;
inventing one would be worse than leaving them untyped. Only quantities with a real
type available carry one — `pout_dbm` and `gain_db` are dB (`SV_DB`), `oscfreq`,
`offsetfreq` and `carrierfreq` are frequencies. Checks [8] and [11] hold that line
from both sides.

## Not fixed, and why

`loadpull` leaves its intermediate transients in the session — **61 plots for
`-n 9`, 333 for `-n 21`**, and a realistic 41-point sweep would exceed a thousand.
That buries the results plot and holds every waveform in memory. Discarding plots a
user may want to inspect is a behaviour change on a shipped command, so it is
recorded here rather than made silently.
