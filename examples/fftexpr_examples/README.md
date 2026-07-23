# fftexpr_examples — Enhancement-306

**The Enhancement-241 twin**, in the code path E-241 did not reach.

[E-241](../../enhancements_doc/Enhancement-241.md) fixed an amplitude normalization that
divided by the **zero-padded** transform size instead of the input length — in the `fft`
**command** (`frontend/com_fft.c`). The identical mistake survived in
`maths/cmaths/cmath4.c`, the **vector-expression function** reached by `let F = fft(v)`,
which is a separate implementation of the same computation.

Using E-241's own discriminator — the DC bin — on one signal, 4001 samples padded to 4096:

| path | DC bin (true = 2.0) |
|---|---|
| `fft` **command** | `2.000000` ✓ |
| `let F = fft(s)` | `1.953613` ✗ = 2.0 × 4001/4096 |

## Why this is a contradiction, not a convention

`cx_fft` holds **two** complete implementations (complex-input and real-input), each with
an FFTW branch and a Green's radix-2 branch. In *both*, the FFTW branch already used the
input length while Green's used the padded size:

```
real branch     FFTW: scale = ((double)length)/2.0     Green: ((double)N)/2   <- bug
complex branch  FFTW: scale = (double) fpts            Green: (double) N      <- bug
```

The correct version sat a few lines from the wrong one, in the same function. This build
has `HAVE_LIBFFTW3` undefined, so Green's is the live path.

| oracle | before | after | closed form |
|---|---|---|---|
| real-input, DC bin | 1.953613 | 2.000000 | 2.0 |
| real-input, `ifft(fft(x))` | 2.3e-02 | 1.1e-16 | 0 |
| complex-input, bin 0 | 0.9766780 | 0.9998683 | 0.9998683 |

## The round trip is the independent check

Nothing in this fix touches `ifft`. That `ifft(fft(x))` went from 2.3% error to machine
precision is therefore a **confirmation from a direction the fix did not aim at** — the
pair only inverts when the forward normalization is right.

## Verify

```bash
python3 verify_fftexpr.py
```

Runs under both linear solvers (6 checks), all against closed form. It fails on the
pre-fix binary, so it is a real regression guard.
