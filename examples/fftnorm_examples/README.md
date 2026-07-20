# `fft`/`spec` amplitude normalization fix (Enhancement-241)

A **numerical-correctness** fix found during a correctness audit (comparing
ngspice analyses against independent analytic and numpy oracles) — the first
wrong-*number* bug of that campaign, after E-235–E-240 (all crashes).

ngspice's built-in `fft` (and `spec`) command, when the binary is **not** linked
against FFTW3, uses a radix-2 FFT that zero-pads the `length` input samples up to
the next power of two `N`. The single-sided amplitude scale was taken from the
**padded** size instead of the true sample count:

```c
scale = ((double)N)/2;      /* com_fft.c — WRONG: N is the zero-padded size */
```

So every FFT whose sample count is not a power of two reported amplitudes too
small by `length/N` — **up to 2×**. A `.tran` almost never produces exactly 2ᵏ
points, so this hit the common case silently. The **DC bin** is the clean
tell: it has no windowing or scalloping ambiguity (always exactly bin 0), yet a
signal with a DC offset of 2.0 read back `2.0·length/N` — e.g. **1.0** for a
1025-sample record (padded to 2048).

The FFTW3 code path already used `length/2` and was correct; E-241 makes the
non-FFTW path match it (`scale = length/2`), and likewise fixes `spec`'s power
normalization (`N·N → length·length`). After the fix, ngspice's `fft` matches
numpy's `rfft` of the same zero-padded record (normalized by `length`)
**bin-by-bin to ~1e-9**, and amplitudes no longer depend on how zero-padding
rounds the record length up. The FFTW-linked build was already correct and is
unaffected; power-of-2 records (where `length == N`) are unchanged.

## Verify

```sh
python3 verify_fftnorm.py
```

Four checks (rectangular window, `set specwindow=none`): a DC offset of 2.0 reads
back as 2.0 on a non-power-of-2 record; the same on a maximally-padded record
(length 1025 → 2048, where the bug halved it to ~1.0); the DC reading is
independent of the sample count across four record lengths; and the `spec` PSD
tone peak is likewise length-independent.
