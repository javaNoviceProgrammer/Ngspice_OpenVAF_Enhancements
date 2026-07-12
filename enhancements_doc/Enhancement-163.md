# Enhancement-163 — `.qpss`, `.hbosc`, `.phasenoise` dot-cards

[Enhancement-162](Enhancement-162.md) gave single-tone harmonic balance a `.hb`
dot-card. This completes the harmonic-balance family the same way: the two-tone
quasi-periodic engine and the autonomous-oscillator engine — until now
control-block commands only — get netlist dot-cards, so the whole HB suite has
dot-card parity with the PSS suite.

## What changed

Three more top-level netlist cards now run their analyses straight from the deck:

- **`.qpss <expr> <f1> <f2> [periods] [maxorder]`** — two-tone quasi-periodic
  steady state ([Enhancement-133](Enhancement-133.md)/[136](Enhancement-136.md);
  add the `hb` keyword for the frequency-domain form).
- **`.hbosc <oscnode> <K> [fguess] [tstab]`** — autonomous harmonic balance for an
  oscillator ([Enhancement-140](Enhancement-140.md)); the deck needs a `.ic` to
  start the oscillation.
- **`.phasenoise <fstart> <fstop> [points]`** — oscillator phase noise
  ([Enhancement-140](Enhancement-140.md)); run after `.hbosc`.

`.hbosc` and `.phasenoise` compose in the deck — because the deck→control bridge
preserves order, `.hbosc` runs first (finding the oscillator's periodic steady
state and frequency) and `.phasenoise` then reads it, so a complete oscillator
phase-noise run needs no `.control` block at all:

```
* LC oscillator phase noise, straight from the deck
L1 n 0 1u
C1 n 0 1n
Bnl 0 n I = 2m*V(n) - 5m*V(n)*V(n)*V(n)
R1 n 0 100k
.ic V(n)=0.1
.hbosc n 5 5.0329meg 60u
.phasenoise 1k 10meg 5
.end
```

## How it works

Each card reuses the same one-branch deck→control mechanism as `.hb`
(Enhancement-162) and `.sweep` (Enhancement-146): in `frontend/inp.c` a top-level
`.qpss` / `.hbosc` / `.phasenoise` line is stripped of its leading `.` and appended
to the post-parse control list, executing as the corresponding command once the
circuit is built — inheriting the full E-133/136/140 engines and their solver
independence.

A per-card boundary check (the character after the name must be whitespace or
end-of-line) keeps the cards distinct — in particular `.hbosc` is **not** matched
by the `.hb` branch, since `.hb`'s own boundary check rejects the trailing `osc`.

## Verification

- [`examples/qpss_examples/verify_qpss.py`](../examples/qpss_examples/verify_qpss.py):
  the `.qpss` dot-card produces a two-tone spectrum **bit-for-bit identical** to
  the `qpss` command form, in plain batch mode.
- [`examples/phasenoise_examples/verify_phasenoise.py`](../examples/phasenoise_examples/verify_phasenoise.py):
  `.hbosc` + `.phasenoise` in a deck reproduce the command form's oscillation
  frequency and phase-noise spectrum exactly, with order preserved.

Both under the Sparse and KLU solvers, exactly as the command forms.

## Notes

- Like `.sweep`/`.hb`, a bare command-style dot-card in a deck with no other
  analysis card prints a benign "no simulations run" batch notice even though the
  analysis ran.
- The command forms are unchanged and remain available.

With this, every HB-family analysis — `.hb`, `.qpss`, `.hbosc`, `.phasenoise` —
has a netlist dot-card, matching the PSS family.
