# `.ac lin 2` / `.sp lin 2` off-by-one fix (Enhancement-191)

A two-point **linear** frequency sweep — `ac lin 2 fstart fstop` (or the `.ac`
card), and likewise `.sp lin 2` — produced **one** frequency point instead of
two. Found while auditing the data-output path (a ragged-length `wrdata` test
turned up an AC vector one point shorter than expected).

## The bug

The AC (`acan.c`) and S-parameter (`span.c`) analyses computed the linear step
size behind this guard:

```c
case LINEAR:
    if (job->ACnumberSteps - 1 > 1)               /* i.e. N >= 3 */
        job->ACfreqDelta = (fstop - fstart) / (job->ACnumberSteps - 1);
    else
        job->ACfreqDelta = 0;                     /* "single point" patch */
```

`numberSteps - 1 > 1` is true only for **N ≥ 3**, so `lin 2` fell into the
single-point patch (`freqDelta = 0`). With a zero step the sweep loop
(`freq += freqDelta; if (freqDelta == 0) goto endsweep;`) stops after the first
point — one row at `fstart`, the `fstop` point silently dropped. `dec` and `oct`
sweeps were unaffected (different step formula), and `lin 1`, `lin 3`, `lin 4`, …
were all correct — only exactly `N = 2` was wrong.

The fix restores the intended guard, matching the form the **noise** analysis
(`noisean.c`) already used correctly:

```c
    if (job->ACnumberSteps > 1)
        job->ACfreqDelta = (fstop - fstart) / (job->ACnumberSteps - 1);
    else
        job->ACfreqDelta = 0;
```

- `N = 1` → `1 > 1` false → `freqDelta = 0` → one point at `fstart` (the genuine
  single-point case is preserved);
- `N = 2` → `2 > 1` true → `freqDelta = fstop − fstart` → two points at `fstart`
  and `fstop`;
- `N ≥ 3` → unchanged.

## Correctness

`verify_aclin2.py` checks that the recovered point is a **genuine solved point**,
not a duplicate: on an RC low-pass, both `lin 2` endpoints match the exact
transfer function `H(jw) = 1/(1 + jwRC)` to < 1e-6. It also confirms `lin 1`
still yields one point, `lin N` yields N linearly-spaced points (N = 3, 5, 10),
and `.sp lin 2` yields two points with the analytic series-R S-parameters
(S11 = 1/3, S21 = 2/3 for a 50 Ω series R between 50 Ω ports).

## Verification

`verify_aclin2.py` — 5 checks, run under **both** linear solvers (Sparse + KLU),
since the fix is in the shared analysis setup: `ac lin 2` gives the two endpoints
matching `1/(1+jwRC)`; `ac lin 1` stays one point; `ac lin N` gives N points;
`sp lin 2` gives the analytic S-parameters. `aclin2_demo.cir` prints the `lin 1`
/ `lin 2` / `lin 5` frequency lists.

## Running

```sh
python3 verify_aclin2.py
ngspice -b aclin2_demo.cir
```
