# Enhancement-306 — ngspice: the Enhancement-241 twin in the `fft` expression function

[Enhancement-241](Enhancement-241.md) fixed an amplitude normalization that divided by the
**zero-padded** transform size instead of the number of input samples. It fixed it in the
`fft` **command** (`frontend/com_fft.c`). The identical mistake survived in
`maths/cmaths/cmath4.c` — the **vector-expression function** reached by `let F = fft(v)`,
a separate implementation of the same computation.

Found by continuing the oracle campaign that produced E-241 itself, and located with
E-241's own discriminator: the DC bin.

## The bug

One signal, 4001 samples padded to 4096, DC offset 2.0:

```
fft s        ; the COMMAND        ->  mag(s)[0] = 2.000000     correct
let F = fft(s) ; the FUNCTION     ->  mag(F)[0] = 1.953613     = 2.0 * 4001/4096
```

`X[0]` is the sum of the samples, `D*length` for a DC offset `D`, so dividing by the padded
`N` reads back `D*length/N`. As E-241 put it: *a DC value cannot depend on how many samples
were taken.*

## Why it is a contradiction rather than a convention

`cx_fft` holds **two** complete implementations — one for complex input, one for real — and
each has an FFTW branch and a Green's radix-2 branch. In **both**, the FFTW branch already
used the input length while Green's used the padded size:

```
real branch      FFTW: scale = ((double)length)/2.0     Green: ((double)N)/2   <- wrong
complex branch   FFTW: scale = (double) fpts            Green: (double) N      <- wrong
```

The correct version sat a few lines from the wrong one, inside the same function. That is an
internal contradiction, exactly like `avg` disagreeing with `integ` in
[Enhancement-302](Enhancement-302.md). This build has `HAVE_LIBFFTW3` undefined, so Green's
is the live path — which is why the defect was reachable at all.

## The fix

Both Green branches normalize by the input length, matching their FFTW twins:

| branch | before | after |
|---|---|---|
| real-input | `((double)N)/2` | `((double)length)/2` |
| complex-input | `(double) N` | `(double) length` |

| oracle | before | after | closed form |
|---|---|---|---|
| real-input, DC bin | 1.953613 | **2.000000** | 2.0 |
| real-input, `ifft(fft(x))` | 2.3e-02 | **1.1e-16** | 0 |
| complex-input, bin 0 | 0.9766780 | **0.9998683** | 0.9998683 |

## The round trip is an independent confirmation

Nothing in this change touches `ifft`. That `ifft(fft(x))` went from 2.3% error to machine
precision is therefore evidence arriving from a direction the fix did not aim at: the pair
only inverts when the forward normalization is right. `cx_ifft` was audited and left alone
for exactly this reason — the oracle says it is correct.

## The rest of the audit

Every caller of the Green's radix-2 kernel was checked, not just the one that failed:

| site | verdict |
|---|---|
| `com_fft.c` — `fft` command (2 sites) | `length` — E-241, correct |
| `com_fft.c` — `spec`/PSD (2 sites) | `length*length` — E-241, correct |
| `cmath4.c` — `cx_fft` real-input Green | **fixed here** |
| `cmath4.c` — `cx_fft` complex-input Green | **fixed here** |
| `cmath4.c` — `cx_ifft` | correct (round trip exact) |
| `trannoise/1-f-code.c` | no padding possible — `n_pts` is grown to `2^n_exp` by construction |

`fft` and `ifft` are the only transform functions in the expression table, so there is no
`spec` twin to miss.

## Verification

`examples/fftexpr_examples/verify_fftexpr.py` — 6 checks under both solvers, all against
closed form. It scores **3/6 on the pre-fix binary**, so it is a real regression guard.
E-241's own suite (`fftnorm_examples`) and `ifftreal_examples` pass unchanged.

## Scope of change

`src/maths/cmaths/cmath4.c`, `cx_fft` only.
