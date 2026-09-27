# Enhancement-745: `pre_snp` refuses a fit that is not the data — a vector fit whose worst element's rms relative error is above 0.1 is refused with the number, the limit and the usual causes, nothing is written, and `-maxerr <x>` raises the limit or `-force` removes it

**Scope:** F5 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md).
`src/frontend/snp2va.c` (the limit and its setters; `snp_fit` refuses above
it and reports the returned fit's own error), `src/frontend/snp2va.h`,
`src/frontend/com_presnp.c` (`-maxerr <x>`, `-force`, the usage, the
accepted-above-default note), `src/frontend/commands.c` (the help text),
`examples/presnp_examples/` (five checks, [E-745]). **ngspice only.** The
fit itself, both emitters and the Python `snp2va.py` are untouched.

**Suites:** [`presnp_examples`](../examples/presnp_examples/) 24 of 24 (19 of
24 on the E-744 binary); `lowrank`, `snpfuzz`, `nport_native`, `touchstone`
unchanged; full sweep 532 of 532.

## What was wrong

The order selection climbs the pole count, keeps the best stable fit and
returns *chosen, else best, else previous*. Its rms relative error — the
worst element's relative rms error over the band — went into the status
line, `2-port, 6 poles, rms rel err 4.25e-01`, and nowhere else: no
threshold, no warning, the model written and used. The hunt's misread files
(F1, F2) were simulated at 6 and 42 percent error with that one line as the
only sign, and a user who does not read it has none. The status line also
reported the best fit's error even when the fit returned was the one before
the knee.

## What changed

A fit whose error is above the limit — 0.1 by default, the worst element's
relative rms error over the fitted band — is refused before anything is
emitted:

```
pre_snp: the fit of _noisy.s2p has an rms relative error of 7.53e-01 (16 poles), above the limit
of 0.1: the model would not be the data -- a noisy or too coarse measurement, a delay-dominated
block a rational fit cannot follow, or a misread file (rdsnp shows what was read); accept it with
-maxerr <x> or -force
```

Neither the `.va`/`.osdi` nor the `.nport` is written. `pre_snp -maxerr <x>`
raises the limit to `x` for that command; `-force` removes it. A fit
accepted that way above the default limit says so on the next line, and the
limit returns to the default after every command, so a later `pre_snp` line
in the same deck is judged as usual. `-maxerr` without a positive number is
refused naming the flag and the default. The status line reports the
returned fit's own error (the previous fit's at a knee), which is the number
the limit is applied to. The usage and the help entry carry the flags.

The limit is on relative rms error, so a filter's stopband — small in
absolute terms — does not fail a fit that follows the passband; the
converter fits Y, whose elements a passive network keeps comparable. The
suite's clean fits sit between 1e-7 and 2e-2 and are untouched.

## Verification

Five checks in `verify_presnp.py`, all through `pre_snp -native` (the limit
sits in the shared fit):

* a file of random S-parameters (seeded, unfittable) is refused: the error
  7.5e-1, the pole count and the limit named, the causes and the flags
  given, no `.nport` written;
* `-maxerr 2` accepts the same fit, writes the `.nport` and says it was
  accepted under `-maxerr` above the default limit;
* `-force` accepts it, saying so;
* `-maxerr abc` and `-maxerr 0` are refused naming the flag and the
  default, nothing written;
* `-maxerr 1e-9` refuses even the clean resonator, so the limit is the
  user's — and every earlier check of the suite ran under the default,
  which touched none of them.

On the E-744 binary the five fail: the random file converts, the flags are
unknown options. `lowrank` (low-rank fits), `snpfuzz` (the E-227 fuzz: a
refusal is a clean outcome there), `nport_native` and `touchstone` are
unchanged.

## What this does not do

* The limit is a single number for the worst element; there is no per-band
  weighting and no passivity criterion (passivity is still checked and
  reported, not enforced). *(Update, E-750: the element's error is now
  relative to the larger of its own size and a thousandth of the largest
  element's, so a negligible element no longer decides; the refusal names
  the order cap when the climb reached it.)*
* The Python `snp2va.py` keeps its `--order` pin and reports its error as
  before.
* A fit that is stable, below the limit and still wrong for the user's
  purpose — a delay-dominated block whose group delay is right and whose
  pulse edges ring — is accepted; the limit measures the frequency-domain
  match over the tabulated band, as E-199's write-up warns.
