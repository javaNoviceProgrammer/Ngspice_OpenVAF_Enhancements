# Enhancement-191 — `.ac lin 2` / `.sp lin 2` off-by-one fix

A correctness fix found while auditing the data-output path (`wrdata` / `wrsnp` / `save` / rawfile `write`). A ragged-length `wrdata` test wrote an AC vector that came out one point shorter than expected, which traced back not to the writer but to the **AC linear frequency sweep**: `ac lin 2 fstart fstop` (and the `.ac` card, and `.sp lin 2`) produced **one** frequency point instead of two.

## The bug

The AC (`spicelib/analysis/acan.c`) and S-parameter (`spicelib/analysis/span.c`) analyses computed the linear step behind this guard:

```c
case LINEAR:
    if (job->ACnumberSteps - 1 > 1)               /* true only for N >= 3 */
        job->ACfreqDelta = (fstop - fstart) / (job->ACnumberSteps - 1);
    else
        job->ACfreqDelta = 0;                     /* "single point" patch */
```

`numberSteps - 1 > 1` holds only for **N ≥ 3**, so `lin 2` fell into the single-point patch and got `freqDelta = 0`. With a zero step the sweep loop terminates after the first point:

```c
freq += job->ACfreqDelta;
if (job->ACfreqDelta == 0) goto endsweep;
```

so the sweep emitted a single row at `fstart` and silently dropped the `fstop` point. Only exactly **N = 2** was affected: `dec` / `oct` sweeps use a different step formula, and `lin 1`, `lin 3`, `lin 4`, … were all correct. The single-point patch (Richard McRoberts) was meant for `lin 1`; the `- 1 > 1` form over-reached by one and swallowed `lin 2` as well.

## The fix

Restore the intended guard, matching the form the **noise** analysis (`noisean.c`) already used correctly (`if (NnumSteps == 1) delta = 0; else delta = (stop − start)/(N − 1)`):

```c
    if (job->ACnumberSteps > 1)
        job->ACfreqDelta = (fstop - fstart) / (job->ACnumberSteps - 1);
    else
        job->ACfreqDelta = 0;
```

- `N = 1` → `1 > 1` false → `freqDelta = 0` → one point at `fstart` (the genuine single-point case, preserved);
- `N = 2` → `2 > 1` true → `freqDelta = fstop − fstart` → two points at `fstart` and `fstop`;
- `N ≥ 3` → unchanged.

The same one-line change was applied to `span.c` (the `.sp` linear sweep had copied the identical guard). The distortion analysis uses a different `N + 1`-point convention and was not affected; noise was already correct.

## Correctness

The recovered point is a genuine solved point, not a duplicate. `verify_aclin2.py` runs an RC low-pass and checks that **both** `lin 2` endpoints match the exact transfer function `H(jw) = 1/(1 + jwRC)` to < 1e-6, that `lin 1` still yields one point, that `lin N` yields N linearly-spaced points (N = 3, 5, 10), and that `.sp lin 2` yields two points with the analytic series-R S-parameters (S11 = 1/3, S21 = 2/3 for a 50 Ω series R between 50 Ω ports).

The wider output-path audit that surfaced this found the writers themselves clean: Touchstone `wrs2p` / `wrsnp` / `rdsnp` round-trip exactly across RI/MA/DB formats, S/Y/Z parameters (with the correct Rbase normalization), and frequency units including complex angles; `wrdata` handles complex `(re,im)` columns, single-scale, and ragged-length padding; `save` filtering restricts the vector set; and the rawfile `write` / `load` round-trips bit-exact.

## Verification

[`examples/aclin2_examples/verify_aclin2.py`](../examples/aclin2_examples/verify_aclin2.py) — 5 checks under **both** linear solvers (the fix is in the shared analysis setup). A [`aclin2_demo.cir`](../examples/aclin2_examples/) prints the `lin 1` / `lin 2` / `lin 5` frequency lists. Full example regression: 155/155.
