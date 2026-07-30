# Enhancement-374 — `setseed` did not seed transient noise

Found by a correctness campaign over ngspice's command set. Two identical decks
with `setseed 42` produced **different** noise waveforms, while `setseed 42`
followed by `rnd(100)` returned exactly `50.0` both times — so the command itself
worked, just not for the generator transient noise draws from.

---

## The cause

`#define WaGauss` (`ngspice.h`) selects the Wallace normal generator, and `initw()`
in `wallace.c` opened with:

```c
/* initialize the uniform generator */
srand((unsigned int) getpid());
// srand(17);
TausSeed();
```

`initw()` runs at **startup** (`main.c`, `sharedspice.c`) and fills its two pools
from that `getpid()`-derived stream. `GaussWa` then draws from those pools. A later
`setseed` reset `srand` and the Tausworthe state — but nothing refilled pools that
already existed, so the samples kept coming from the process-id stream.

The commented-out `// srand(17)` beside it is a developer's old fixed seed, which
is the same problem from the other direction.

## The fix, in three parts

Moving the seeding alone is not enough; all three are needed.

1. **`initw()` no longer calls `srand()`.** It seeds from whatever state the caller
   has established, so it can never clobber a user seed.
2. **The two startup call sites do the `srand(getpid())` themselves**, so an
   unseeded run stays random per process.
3. **`com_sseed()` calls `destroy_wallace(); initw();`**, so a new seed actually
   rebuilds the pools rather than resetting state nothing reads.

## A trap worth recording

The first version of the `com_sseed` change was guarded with

```c
#if defined(WaGauss) && defined(SIMULATOR)
```

and **`SIMULATOR` is not defined for library sources** like `randnumb.c` — exactly
the situation [Enhancement-367](Enhancement-367.md) documented after finding
`print alle` dead for the same reason. The entire fix compiled out silently, and
`setseed` still did not reproduce. The guard is now on `WaGauss` alone.

That is twice now that this macro has silently disabled working code. It is worth
treating `#ifdef SIMULATOR` in anything outside `main.c`/`ngspice.c`/`sharedspice.c`
as a bug until proven otherwise.

## Verification

`examples/setseed_examples` checks three properties, and the third matters as much
as the first — a fix that pinned one constant sequence would satisfy the first and
be useless:

```
   fixed:        5/5
   pre-fix:      4/5    same seed reproduces the waveform    waveforms differ
```

| property | result |
| --- | --- |
| same seed reproduces the waveform | byte-identical |
| a different seed gives a different waveform | 42 ≠ 99 |
| **no `setseed` still varies run to run** | two unseeded runs differ |
| control: `setseed` still fixes `rnd()` | 50.0 twice |
| the seeded stream is still real noise | 3.5 mV peak-to-peak over 160 points |

The last two are controls that pass on **both** binaries: `rnd()` was never broken,
and the generator must still produce noise rather than a frozen constant.

Regression 297/297.

## Consequence for an earlier document

This falsifies a claim in
[`docs/internals/ngspice_internals/ngspice_transient_noise_analysis.md`](../docs/internals/ngspice_internals/ngspice_transient_noise_analysis.md),
which stated that `setseed` fixes the stream. It did not at the time of writing;
it does now. The note has been corrected to describe both states, and the
seed-averaged statistics in it remain valid — they were means over genuinely
independent runs, which is what the error bars describe.
