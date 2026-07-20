# Enhancement-241 — `fft`/`spec`: fix the amplitude normalization for non-power-of-2 records

The first **numerical-correctness** find of a correctness-audit campaign (auditing
ngspice analyses against independent analytic and numpy oracles) — a wrong
*number*, not a crash, unlike E-235 – E-240.

## The bug

ngspice's built-in `fft` (and `spec`) command has two code paths in
`frontend/com_fft.c`:

* **FFTW3** (`HAVE_LIBFFTW3`): an exact `length`-point transform,
  `scale = length/2` — correct.
* **Green's radix-2 FFT** (no FFTW3): zero-pads the `length` input samples up to
  the next power of two `N`, then normalized by the **padded** size:

  ```c
  scale = ((double)N)/2;      /* WRONG */
  ```

The single-sided amplitude of a bin is `2·|X|/length` — independent of
zero-padding, which only interpolates the spectrum. Dividing by `N/2` instead of
`length/2` scales every amplitude by `length/N`, so any FFT whose sample count is
not a power of two reads **too small by up to 2×**. A `.tran` essentially never
yields exactly 2ᵏ points, so this bit the common case silently.

The **DC bin** is the unambiguous discriminator — it is always exactly bin 0,
with no window/scalloping ambiguity — yet a signal with DC offset `D` read back
`D·length/N`:

```
v1 1 0 dc 0 sin(2.0 1.0 1000)     ; DC = 2.0
... tran (1025 samples, padded to 2048) ... fft ...
mag(v(1))[0]  ->  1.0009   (= 2.0 * 1025/2048)   instead of 2.0
```

A DC value cannot depend on how many samples were taken. `spec` carries the same
error in its power normalization: `intres = N·N` instead of `length·length`
(the FFTW path already uses `length·length`).

## The fix

Normalize by the actual sample count in the non-FFTW path, matching the FFTW
path:

```c
scale  = ((double)length)/2.0;        /* fft:  was N/2  */
intres = (double)length*(double)length; /* spec: was N*N */
```

The frequency axis was already padding-aware (`freq[i] = i/span · length/N`), so
only the magnitude scale needed the fix. Power-of-2 records (`length == N`) are
unchanged, and FFTW-linked builds were already correct.

## Verification

Against numpy as an independent oracle: after the fix, ngspice's `fft` matches
`numpy.fft.rfft` of the *same* zero-padded record (normalized by `length`)
**bin-by-bin to ~1e-9** across several non-power-of-2 lengths and signals
(DC+tone, single tone, two-tone). The DC bin, the clean discriminator, matches to
machine precision.

`examples/fftnorm_examples/verify_fftnorm.py` (numpy-free, 4 checks): a DC offset
of 2.0 reads 2.0 on a non-power-of-2 record; the same on a maximally-padded record
(1025 → 2048, where the bug halved it to ~1.0); the DC reading is independent of
sample count across four record lengths (padding ~1.02× to ~2×); and the `spec`
PSD tone peak is length-independent.

## Scope

ngspice frontend only — two normalization constants in `frontend/com_fft.c`
(`fft` amplitude, `spec` power) in the non-FFTW code path. No solver, analysis,
device, or compiler change. `fft`/`spec` **amplitudes now change** for
non-power-of-2 records (they become correct); power-of-2 records and FFTW-linked
builds are unchanged. Full regression: 199/199.
